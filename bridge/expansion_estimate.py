"""멀티(둘째 넥서스)가 이득이 되는 병력 수를 시뮬레이터로 추정한다 (질럿 또는 드라군).

    py -X utf8 bridge/expansion_estimate.py --unit zealot  --targets 5,10,20,30,40
    py -X utf8 bridge/expansion_estimate.py --unit dragoon --targets 5,10,15,20,30 --worker-mult 2
    py -X utf8 bridge/expansion_estimate.py --unit dragoon --targets 5,10,15,20,30 --worker-mult 3

행동: 0 일꾼, 1 파일런, 2 게이트, 3 병력(질럿/드라군), 4 넥서스, 5 어시밀레이터, 6 사이버네틱스 코어.
가정(실측이 없는 값은 BW 데이터 상수 + 이동 시간 추정):
  - 넥서스 400 미네랄, 명령→완성 2200 프레임(건설 1800 + 앞마당 이동). 완성 시 인구 +9, 프로브 큐 추가, 미네랄 덩이 8·간헐천 1 추가.
  - 미네랄 수입은 기지 수 b 에 따라 구간 용량이 8b: 처음 8b 기 0.046, 다음 8b 기 0.026, 그 뒤 0.021 (실측 income_by_workers.md).
  - 어시밀레이터 100 미네랄, 명령→완성 700 프레임(건설 600 + 이동). 완성 시 미네랄 일꾼 3기가 가스로 옮겨 기지당 가스 0.21/프레임
    (3기 ≈ 300가스/분, 1분 ≈ 1430프레임). 기지당 간헐천 1개 = 어시밀레이터 1개.
  - 코어 200 미네랄, 명령→완성 1050 프레임(건설 900 + 이동), 완성된 게이트 필요.
  - 드라군 125 미네랄 50 가스, 인구 2, 750 프레임, 코어 필요. 질럿 100 미네랄, 600 프레임.
  - 일꾼 상한 = 기지당 8덩이 × worker_mult (2 또는 3). 일꾼 재배치는 즉시·최적.
실행기에는 넥서스·가스·코어·드라군 행동이 아직 없다. 추정이 의미 있으면 그때 구현한다.
"""
import argparse
import heapq
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sc1_sim as ss  # noqa: E402

UNITS = {
    "zealot": {"min": 100, "gas": 0, "frames": 600, "core": False, "archives": False},
    "dragoon": {"min": 125, "gas": 50, "frames": 750, "core": True, "archives": False},
    "high_templar": {"min": 50, "gas": 150, "frames": 750, "core": True, "archives": True},
    "dark_templar": {"min": 125, "gas": 100, "frames": 750, "core": True, "archives": True},
}
# (미네랄, 가스, 명령→완성 프레임). 건설 시간(BW 데이터) + 이동 150 추정. 성채 60s=900, 아카이브 60s=900
EXTRA = {"nexus": (400, 0, 2200), "assim": (100, 0, 700), "core": (200, 0, 1050), "citadel": (150, 100, 1050), "archives": (150, 200, 1050)}
EXEC_ACTION = {"zealot": 3, "dragoon": 7, "high_templar": 12, "dark_templar": 13}  # 실행기 행동 번호
GAS_PER_BASE = 0.21
GAS_WORKERS = 3


class ExpSim(ss.SC1Sim):
    __slots__ = ("bases_done", "nexus_frees", "unit", "gas_spent", "gas_events", "assim_done", "core_done", "citadel_done", "archives_done",
                 "patch_counts")

    def __init__(self, P, target, unit="zealot"):
        super().__init__(P, target)
        self.unit = UNITS[unit]
        self.events = [(P["start_delay"], ss.START_WORKERS, 0), (0, 0, 1)]
        self.bases_done: list[int] = []
        self.nexus_frees = [0]
        self.gas_spent = 0.0
        self.gas_events: list[tuple[int, float]] = []
        self.assim_done: list[int] = []
        self.core_done = None
        self.citadel_done = None
        self.archives_done = None
        self.patch_counts = None  # 기지별 미네랄 덩이 수(완성 순). None 이면 기지당 8

    # ---- 미네랄
    def _rate_b(self, n, b):
        """미네랄 수입: 기지 b 개의 실제 덩이 수 합 c 로 구간을 나눈다 (덩이당 1기 0.044, 2기째 0.024, 3기째 0.019, 실측).
        멀티의 덩이가 적으면(고갈·작은 멀티) 그만큼 용량이 줄어든다."""
        P = self.P
        pc = self.patch_counts or []
        c = sum((pc[i] if i < len(pc) else ss.MINERAL_FIELD) for i in range(max(1, b)))
        return (P["income"] * min(n, c) + P["income_add"] * max(0, min(n, 2 * c) - c) + P["income_over"] * max(0, n - 2 * c))

    def minerals_at(self, t):
        ev = sorted(self.events)
        m = ss.START_MINERALS - self.spent
        n, b, prev = 0, 0, None
        for te, dw, db in ev:
            if te >= t:
                break
            if prev is not None:
                m += self._rate_b(n, b) * (te - prev)
            n += dw
            b += db
            prev = te
        if prev is not None and t > prev:
            m += self._rate_b(n, b) * (t - prev)
        return m

    def rate_at(self, t):
        n = sum(dw for te, dw, _ in self.events if te <= t)
        b = sum(db for te, _, db in self.events if te <= t)
        return self._rate_b(n, b)

    # ---- 가스
    def gas_at(self, t):
        g = -self.gas_spent
        for te, r in self.gas_events:
            if te < t:
                g += r * (t - te)
        return g

    def gas_rate_at(self, t):
        return sum(r for te, r in self.gas_events if te <= t)

    def earliest_afford(self, cost, t, gas=0):
        for _ in range(10000):
            m = self.minerals_at(t)
            g = self.gas_at(t) if gas else 0
            if m >= cost - 1e-9 and g >= gas - 1e-9:
                return t
            nxts = [te for te, _, _ in self.events if te > t] + [te for te, _ in self.gas_events if te > t]
            nxt = min(nxts, default=None)
            need = 0
            if m < cost:
                rt = self.rate_at(t)
                if rt <= 0:
                    if nxt is None:
                        return None
                    t = nxt
                    continue
                need = max(need, math.ceil((cost - m) / rt - 1e-9))
            if gas and g < gas:
                gr = self.gas_rate_at(t)
                if gr <= 0:
                    if nxt is None:
                        return None
                    t = nxt
                    continue
                need = max(need, math.ceil((gas - g) / gr - 1e-9))
            if nxt is None or t + need <= nxt:
                return t + need
            t = nxt
        return None

    def cap_at(self, t):
        base = ss.START_CAP if self.cap_base is None else self.cap_base
        return base + 8 * sum(1 for c in self.pylon_done if c <= t) + 9 * sum(1 for c in self.bases_done if c <= t)

    def supply_time(self, need, t):
        if self.supply_used + need <= self.cap_at(t):
            return t
        for c in sorted(self.pylon_done + self.bases_done):
            if c >= t and self.supply_used + need <= self.cap_at(c):
                return c
        return None

    def _builder_pause(self, t):
        d = self.P["builder_pause"]
        if d > 0:
            self.events.append((t, -1, 0))
            self.events.append((t + d, 1, 0))

    def _afford_with_supply(self, cost, need_supply, t, gas=0):
        for _ in range(60):
            t2 = self.earliest_afford(cost, t, gas)
            if t2 is None:
                return None
            if need_supply:
                t3 = self.supply_time(need_supply, t2)
                if t3 is None:
                    return None
                if t3 != t2:
                    t = t3
                    continue
            return t2
        return None

    def step(self, a):
        P = self.P
        t = self.t + 1
        if a == 4:  # 넥서스
            cost, _, dur = EXTRA["nexus"]
            t = self.earliest_afford(cost, t)
            if t is None or (self.end is not None and t > self.end):
                return None
            self.spent += cost
            done = t + dur
            self.bases_done.append(done)
            self.nexus_frees.append(done)
            self.events.append((done, 0, 1))
            self._builder_pause(t)
        elif a == 5:  # 어시밀레이터 (완성된 넥서스마다 하나)
            cost, _, dur = EXTRA["assim"]
            bases_ready = [0] + self.bases_done
            if len(self.assim_done) >= len(bases_ready):
                return None
            t = max(t, sorted(bases_ready)[len(self.assim_done)])
            t = self.earliest_afford(cost, t)
            if t is None or (self.end is not None and t > self.end):
                return None
            self.spent += cost
            done = t + dur
            self.assim_done.append(done)
            self.gas_events.append((done, GAS_PER_BASE))
            self.events.append((done, -GAS_WORKERS, 0))  # 미네랄 일꾼 3기가 가스로
            self._builder_pause(t)
        elif a == 6:  # 코어
            cost, _, dur = EXTRA["core"]
            if self.core_done is not None or not self.gate_ready:
                return None
            t = max(t, min(self.gate_ready))
            t = self.earliest_afford(cost, t)
            if t is None or (self.end is not None and t > self.end):
                return None
            self.spent += cost
            self.core_done = t + dur
            self._builder_pause(t)
        elif a == 10:  # 아둔의 성채 (코어 완성 필요)
            cost, gas, dur = EXTRA["citadel"]
            if self.citadel_done is not None or self.core_done is None or (gas and not self.assim_done):
                return None
            t = max(t, self.core_done)
            t = self.earliest_afford(cost, t, gas)
            if t is None or (self.end is not None and t > self.end):
                return None
            self.spent += cost
            self.gas_spent += gas
            self.citadel_done = t + dur
            self._builder_pause(t)
        elif a == 11:  # 템플러 아카이브 (성채 완성 필요)
            cost, gas, dur = EXTRA["archives"]
            if self.archives_done is not None or self.citadel_done is None:
                return None
            t = max(t, self.citadel_done)
            t = self.earliest_afford(cost, t, gas)
            if t is None or (self.end is not None and t > self.end):
                return None
            self.spent += cost
            self.gas_spent += gas
            self.archives_done = t + dur
            self._builder_pause(t)
        elif a == 0:
            cost = ss.COST[0]
            t = self._afford_with_supply(cost, 1, t)
            if t is None or (self.end is not None and t > self.end):
                return None
            self.spent += cost
            i = min(range(len(self.nexus_frees)), key=lambda k: max(t, self.nexus_frees[k]))
            start = max(t, self.nexus_frees[i])
            done = start + P["probe"]
            self.nexus_frees[i] = done
            self.events.append((done + P["mine_delay"], 1, 0))
            self.supply_used += 1
        elif a == 3:  # 병력
            u = self.unit
            if not self.gate_ready:
                return None
            t = max(t, min(self.gate_ready))
            if u["core"]:
                if self.core_done is None:
                    return None
                t = max(t, self.core_done)
            if u.get("archives"):
                if self.archives_done is None:
                    return None
                t = max(t, self.archives_done)
            if u["gas"] and not self.assim_done:
                return None
            t = self._afford_with_supply(u["min"], 2, t, u["gas"])
            if t is None or (self.end is not None and t > self.end):
                return None
            self.spent += u["min"]
            self.gas_spent += u["gas"]
            # 짓는 중 포함, 생산을 가장 먼저 시작할 수 있는 게이트 (실행기 pickGateway 와 같음)
            g = min(range(len(self.gate_ready)), key=lambda i: (max(float(t), self.gate_busy[i]), i))
            if self.gate_ready[g] > t:
                t = self.gate_ready[g]
            start = max(float(t), self.gate_busy[g])
            done = start + u["frames"]
            self.gate_busy[g] = done
            self.gate_queue[g].append(done)
            self.zealot_done.append(done)
            self.supply_used += 2
            if len(self.zealot_done) >= self.target:
                self.end = int(math.ceil(sorted(self.zealot_done)[self.target - 1])) + P["end_lag"]
        else:
            return super().step(a)
        self.t = t
        self.times.append(t)
        return t

    def lower_bound(self):
        r = self.target - len(self.zealot_done)
        if r <= 0:
            return self.end
        t = max(self.t, 0)
        u = self.unit
        busy = sorted(self.gate_busy) if self.gate_busy else [float(t + self.P["gate"])]
        busy = [max(b, float(t)) for b in busy]
        heapq.heapify(busy)
        last = t
        for _ in range(r):
            b = heapq.heappop(busy)
            last = b + u["frames"]
            heapq.heappush(busy, last)
        need = r * u["min"] - self.minerals_at(t)
        rate = self.rate_at(t)
        lb = max(last, t + (need / rate if rate > 0 and need > 0 else 0) + u["frames"])
        if u["gas"]:
            gneed = r * u["gas"] - self.gas_at(t)
            gr = self.gas_rate_at(t) or GAS_PER_BASE
            lb = max(lb, t + (gneed / gr if gneed > 0 else 0) + u["frames"])
        return lb

    def copy(self):
        o = ExpSim.__new__(ExpSim)
        o.P, o.target, o.unit = self.P, self.target, self.unit
        o.events = list(self.events)
        o.spent, o.supply_used = self.spent, self.supply_used
        o.pylon_done, o.gate_ready = list(self.pylon_done), list(self.gate_ready)
        o.gate_busy, o.gate_queue = list(self.gate_busy), [list(q) for q in self.gate_queue]
        o.nexus_free = self.nexus_free
        o.zealot_done = list(self.zealot_done)
        o.t, o.end, o.times = self.t, self.end, list(self.times)
        o.bases_done, o.nexus_frees = list(self.bases_done), list(self.nexus_frees)
        o.gas_spent, o.gas_events = self.gas_spent, list(self.gas_events)
        o.assim_done, o.core_done = list(self.assim_done), self.core_done
        o.citadel_done, o.archives_done = self.citadel_done, self.archives_done
        o.patch_counts = self.patch_counts
        o.cap_base = self.cap_base
        o.has_pylon = self.has_pylon
        return o


def make_allowed(target, unit, max_gates, worker_mult, allow_nexus, max_nexus=1):
    u = UNITS[unit]

    def allowed(prefix):
        w, p, g, z, x, s, c = (prefix.count(a) for a in (0, 1, 2, 3, 4, 5, 6))
        bases = 1 + x
        cap = ss.START_CAP + 8 * p + 9 * x
        used = ss.START_WORKERS + w + 2 * z
        acts = []
        if z == 0 and ss.START_WORKERS + w < ss.MINERAL_FIELD * worker_mult * bases + GAS_WORKERS * s:
            acts.append(0)
        if p == 0 or used + 2 * (target - z) + (ss.MINERAL_FIELD * worker_mult * bases - ss.START_WORKERS - w if z == 0 else 0) > cap:
            acts.append(1)
        if p >= 1 and g < max_gates:
            acts.append(2)
        if (g >= 1 and z < target and used + 2 <= cap and (not u["core"] or c >= 1) and (not u["gas"] or s >= 1)
                and (not u.get("archives") or prefix.count(11) >= 1)):
            acts.append(3)
        if allow_nexus and x < max_nexus and z == 0:
            acts.append(4)
        if u["gas"] and s < bases and g >= 1:
            acts.append(5)
        if u["core"] and c == 0 and g >= 1:
            acts.append(6)
        ci, ar = prefix.count(10), prefix.count(11)
        if u.get("archives"):
            if ci == 0 and c >= 1:
                acts.append(10)
            if ar == 0 and ci >= 1:
                acts.append(11)
        return acts
    return allowed


def beam(P, target, unit, allow_nexus, width, max_gates, worker_mult, topk=3):
    allowed = make_allowed(target, unit, max_gates, worker_mult, allow_nexus)
    frontier = [(ExpSim(P, target, unit), ())]
    finished = {}
    depth = 0
    while frontier and depth < 140:
        cands = []
        for sim, prefix in frontier:
            for a in allowed(prefix):
                s2 = sim.copy()
                if s2.step(a) is None:
                    continue
                seq = prefix + (a,)
                if s2.end is not None:
                    if seq not in finished or finished[seq] > s2.end:
                        finished[seq] = s2.end
                else:
                    cands.append((s2.lower_bound(), s2, seq))
        cands.sort(key=lambda c: (c[0], c[2]))
        frontier = stratified(cands, width)
        depth += 1
    _c = {0: 50, 1: 100, 2: 150, 3: 100, 4: 400, 5: 100, 6: 200, 7: 125, 10: 150, 11: 150, 12: 50, 13: 125}
    res = [(e, seq) for e, _, _, seq in sorted((e, sum(_c.get(a, 0) for a in seq), len(seq), seq) for seq, e in finished.items())]
    return res[:topk]


def stratified(cands, width):
    """하한만으로 자르면 일꾼이 많은(수입이 커서 하한이 낮은) 접두사가 빔을 독차지해 일꾼이 적은 해를 놓친다.
    (일꾼, 넥서스, 어시밀, 게이트) 구성 버킷마다 상위 몇 개씩 고르게 남긴다."""
    buckets = {}
    for lb, s, seq in cands:
        key = (seq.count(0), seq.count(4), seq.count(5), seq.count(2))
        buckets.setdefault(key, []).append((lb, s, seq))
    per = max(1, width // max(1, len(buckets)))
    kept = []
    for key, items in buckets.items():
        kept.extend(items[:per])
    kept.sort(key=lambda c: (c[0], c[2]))
    if len(kept) < width:  # 남는 자리는 전체 순위로 채운다
        chosen = {id(c[1]) for c in kept}
        for c in cands:
            if len(kept) >= width:
                break
            if id(c[1]) not in chosen:
                kept.append(c)
    return [(s, seq) for _, s, seq in kept[:width]]


def exp_from_snapshot(P, obs, unit, target):
    """실행기 관측(extra 에 스냅샷·tech)에서 ExpSim 을 현재 상태로 초기화한다. target = 지금부터 더 만들 unit 수."""
    ex = obs.extra or {}
    t0 = int(obs.frame)
    st = obs.state
    minerals, used, cap, workers = int(st[0]), int(st[2]), int(st[3]), int(st[4])
    tech = ex.get("tech") or {}
    sim = ExpSim(P, target, unit)
    sim.t = t0 - 1
    reserved_m = int(ex.get("reserved_minerals", 0))
    sim.spent = ss.START_MINERALS - (minerals - reserved_m)
    sim.gas_spent = -(int(ex.get("gas", 0)) - int(ex.get("reserved_gas", 0)))
    assim = tech.get("assimilator", {"ready": 0, "building": [], "pending": []})
    gas_workers = GAS_WORKERS * int(assim.get("ready", 0))
    sim.events = [(t0, max(0, workers - gas_workers), 0), (0, 0, 1)]
    sim.gas_events = [(t0, GAS_PER_BASE * int(assim.get("ready", 0)))] if assim.get("ready") else []
    sim.assim_done = [t0] * int(assim.get("ready", 0))
    for r in assim.get("building", []):
        sim.assim_done.append(t0 + r)
        sim.gas_events.append((t0 + r, GAS_PER_BASE))
        sim.events.append((t0 + r, -GAS_WORKERS, 0))
    for e in assim.get("pending", []):
        done = t0 + max(30, EXTRA["assim"][2] - int(e))
        sim.assim_done.append(done)
        sim.gas_events.append((done, GAS_PER_BASE))
        sim.events.append((done, -GAS_WORKERS, 0))
    nq, nr = int(ex.get("nexus_queue", 0)), int(ex.get("nexus_remaining", 0))
    sim.nexus_frees = [t0]
    for i in range(nq):
        done = t0 + nr + i * P["probe"]
        sim.nexus_frees[0] = done
        sim.events.append((done + P["mine_delay"], 1, 0))
    sim.supply_used = max(used, int(ex.get("supply_issued", used))) + nq  # 실행기는 큐의 유닛까지 센다
    sim.cap_base = cap
    sim.has_pylon = cap > ss.START_CAP or int((tech.get("pylon") or {}).get("ready", 0)) > 0
    sim.pylon_done = [t0 + r for r in ex.get("pylons_building", [])]
    for e in ex.get("pylons_pending_elapsed", []):
        sim.pylon_done.append(t0 + max(30, P["pylon"] - int(e)))
    for q, r in zip(ex.get("gate_queue", []), ex.get("gate_remaining", [])):
        sim.gate_ready.append(t0)
        busy = float(t0 + r + max(0, q - 1) * 600) if q > 0 else float(t0)
        sim.gate_busy.append(busy)
        sim.gate_queue.append([busy] if q > 0 else [])
    for r in list(ex.get("gateways_building", [])) + [max(30, P["gate"] - int(e)) for e in ex.get("gateways_pending_elapsed", [])]:
        sim.gate_ready.append(t0 + r)
        sim.gate_busy.append(float(t0 + r))
        sim.gate_queue.append([])
    def tech_done(key):
        d = tech.get(key, {"ready": 0, "building": [], "pending": []})
        if int(d.get("ready", 0)) > 0:
            return t0
        if d.get("building"):
            return t0 + min(d["building"])
        if d.get("pending"):
            return t0 + max(30, EXTRA[key][2] - min(int(e) for e in d["pending"]))
        return None
    sim.core_done, sim.citadel_done, sim.archives_done = tech_done("core"), tech_done("citadel"), tech_done("archives")
    if ex.get("base_patches"):
        sim.patch_counts = [int(x) for x in ex["base_patches"]]
    # 기지: 넥서스 완성 수(본진 포함)와 짓는 중·명령된 것
    nx = tech.get("nexus", {"ready": 1, "building": [], "pending": []})
    extra_ready = max(0, int(nx.get("ready", 1)) - 1)
    for _ in range(extra_ready):
        sim.events.append((t0, 0, 1))
        sim.bases_done.append(t0)
        sim.nexus_frees.append(t0)
    for r in list(nx.get("building", [])) + [max(30, EXTRA["nexus"][2] - int(e)) for e in nx.get("pending", [])]:
        sim.events.append((t0 + r, 0, 1))
        sim.bases_done.append(t0 + r)
        sim.nexus_frees.append(t0 + r)
    return sim


def make_allowed_from(sim0, unit, target, max_new_gates=2, max_new_workers=8):
    """스냅샷 상태 기준 행동 규칙 (새 게임 가정인 make_allowed 와 다르다)."""
    u = UNITS[unit]
    used0, cap0 = sim0.supply_used, (sim0.cap_base if sim0.cap_base is not None else ss.START_CAP)
    gates0, pylons_coming = len(sim0.gate_ready), len(sim0.pylon_done)
    has_pylon = cap0 > ss.START_CAP or pylons_coming > 0
    has_assim, has_core = len(sim0.assim_done) > 0, sim0.core_done is not None
    has_citadel, has_archives = sim0.citadel_done is not None, sim0.archives_done is not None

    def allowed(prefix):
        w, p, g, z = (prefix.count(a) for a in (0, 1, 2, 3))
        s5, c6, ci, ar = (prefix.count(a) for a in (5, 6, 10, 11))
        cap = cap0 + 8 * (p + pylons_coming)
        used = used0 + w + 2 * z
        acts = []
        if w < max_new_workers and z == 0:
            acts.append(0)
        if cap < 200 and used + 2 * (target - z) + (max_new_workers - w if z == 0 else 0) > cap:
            acts.append(1)  # 한도 200 은 게임 최대: 그 이상 파일런은 무의미
        if (has_pylon or p >= 1) and g < max_new_gates:
            acts.append(2)
        gate_ok = gates0 + g >= 1
        assim_ok = (not u["gas"]) or has_assim or s5 >= 1
        core_ok = (not u["core"]) or has_core or c6 >= 1
        arch_ok = (not u.get("archives")) or has_archives or ar >= 1
        if gate_ok and z < target and used + 2 <= cap and assim_ok and core_ok and arch_ok:
            acts.append(3)
        if u["gas"] and not has_assim and s5 == 0:
            acts.append(5)
        if u["core"] and not has_core and c6 == 0 and gate_ok and (has_pylon or p >= 1):
            acts.append(6)
        if u.get("archives"):
            if not has_citadel and ci == 0 and (has_core or c6 >= 1):
                acts.append(10)
            if not has_archives and ar == 0 and (has_citadel or ci >= 1):
                acts.append(11)
        return acts
    return allowed


def beam_from(sim0, unit, target, width=800, max_new_gates=2, max_new_workers=8, topk=5):
    """주어진 ExpSim 상태에서 출발하는 계층화 빔."""
    allowed = make_allowed_from(sim0, unit, target, max_new_gates, max_new_workers)
    frontier = [(sim0, ())]
    finished = {}
    depth = 0
    while frontier and depth < 80:
        cands = []
        for sim, prefix in frontier:
            for a in allowed(prefix):
                s2 = sim.copy()
                if s2.step(a) is None:
                    continue
                seq = prefix + (a,)
                if s2.end is not None:
                    if seq not in finished or finished[seq] > s2.end:
                        finished[seq] = s2.end
                else:
                    cands.append((s2.lower_bound(), s2, seq))
        cands.sort(key=lambda c: (c[0], c[2]))
        frontier = stratified(cands, width)
        depth += 1
    _c = {0: 50, 1: 100, 2: 150, 3: 100, 4: 400, 5: 100, 6: 200, 7: 125, 10: 150, 11: 150, 12: 50, 13: 125}
    res = [(e, seq) for e, _, _, seq in sorted((e, sum(_c.get(a, 0) for a in seq), len(seq), seq) for seq, e in finished.items())]
    return res[:topk], len(finished)


def describe(seq):
    nx = seq.index(4) if 4 in seq else None
    return (f"일꾼 {seq.count(0)} 게이트 {seq.count(2)} 파일런 {seq.count(1)} 가스 {seq.count(5)} "
            f"넥서스 {'없음' if nx is None else f'{nx + 1}번째 명령'}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--unit", choices=list(UNITS), default="dragoon")
    ap.add_argument("--targets", default="5,10,15,20,30")
    ap.add_argument("--beam", type=int, default=1200)
    ap.add_argument("--worker-mult", type=int, default=2, help="기지당 덩이 수의 배수 (2 또는 3)")
    ap.add_argument("--max-gates", type=int, default=8)
    args = ap.parse_args()
    P = dict(ss.DEFAULT_PARAMS)
    u = UNITS[args.unit]
    print(f"유닛 {args.unit}: {u['min']}m/{u['gas']}g, {u['frames']}프레임. 일꾼 상한 기지당 8×{args.worker_mult}. "
          f"넥서스 {EXTRA['nexus']}, 어시밀 {EXTRA['assim']}, 코어 {EXTRA['core']}, 가스 {GAS_PER_BASE}/프레임/기지")
    print(f"{'N':>3} | {'멀티 없음':>8} | {'멀티 허용':>8} | 차이 | 구성(멀티 허용)")
    for n in [int(x) for x in args.targets.split(",")]:
        mg = max(1, min(args.max_gates, (n + 1) // 2))
        r0 = beam(P, n, args.unit, False, args.beam, mg, args.worker_mult)
        r1 = beam(P, n, args.unit, True, args.beam, mg, args.worker_mult)
        e0, s0 = r0[0]
        e1, s1 = r1[0]
        print(f"{n:>3} | {e0:>8} | {e1:>8} | {e1 - e0:+5d} | {describe(s1)}   [멀티 없음: {describe(s0)}]", flush=True)
        if 4 in s1:
            print(f"      멀티 명령열: {list(s1)}")


if __name__ == "__main__":
    main()
