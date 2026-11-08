"""스타1(1.16.1 + bridge/cpp 실행기) 빌드 시뮬레이터, 적합, 탐색.

offline_rl/build_sim.py(SC2) 와 같은 분해이지만 상수와 규칙이 스타1·실행기에 맞다.
  시작: 미네랄 50, 프로브 4, 인구 4/9. 시간 단위 프레임.
  비용: 일꾼 50, 파일런 100, 게이트 150, 질럿 100. 실행기가 건설 비용을 명령 때 예약하므로 명령 시점 차감으로 본다.
  일꾼: 넥서스 큐 순차 생산(probe 프레임), 완성 뒤 mine_delay 지나 채취.
  파일런: 명령 → 완성 pylon 프레임(일꾼 이동 포함). 완성 시 인구 +8. 건설 일꾼은 builder_pause 동안 채취를 쉰다.
  게이트: 완성된 파일런 필요. 명령 → 완성 gate 프레임.
  질럿: 명령 시점에 완성된 게이트 중 큐가 짧고 남은 시간이 적은 것(실행기 pickGateway). 재분배 없음. zealot 프레임.
  인구: 일꾼·질럿 모두 명령 시점에 차지(실행기가 supplyUsed() 로 판정).
  종료: 목표 수째 질럿 완성 프레임(onUnitComplete) + end_lag.
명령은 직전 명령 다음 프레임부터 조건을 만족하는 첫 프레임에 실행된다(실행기 A5).

표준 라이브러리만 사용한다.
"""
from __future__ import annotations

import math
from collections import defaultdict

START_MINERALS = 50
START_WORKERS = 4
START_CAP = 9
MINERAL_FIELD = 8          # Astral Balance 본진 미네랄 덩이 수 (chk_inspect 로 확인)
COST = {0: 50, 1: 100, 2: 150, 3: 100}
SUPPLY = {0: 1, 1: 0, 2: 0, 3: 2}

# 초기값: 2026-11-08 실게임 N=5 궤적(bridge/results/results_sc1_ums10.jsonl)과 BOSS 상수에서 잡음. 적합으로 갱신한다.
DEFAULT_PARAMS = {
    # 수입 상수는 2026-11-08 실측(bridge/results/income_by_workers.md, 일꾼 4~24기, 첫 파일런 6/7/8 비교)에서 고정한다.
    # 1~8기(덩이당 1): 일꾼당 0.046, 9~16기: 한계 0.026, 17~24기: 한계 0.021 (미네랄/프레임). 적합 대상이 아니다.
    "income": 0.046,
    "income_add": 0.026,
    "income_over": 0.021,
    "sat": 16,
    "start_delay": 40,     # 시작 후 첫 수입까지
    "probe": 302,          # 실측: 일꾼 명령 간격 302프레임(넥서스 큐 제한)
    "mine_delay": 30,
    "pylon": 590,          # 명령 → 완성 (이동 포함)
    "gate": 1045,
    "zealot": 600,
    "builder_pause": 250,
    "end_lag": 0,
}
INT_PARAMS = {"sat", "start_delay", "probe", "mine_delay", "pylon", "gate", "zealot", "builder_pause", "end_lag"}
FIT_PARAMS = ["start_delay", "probe", "mine_delay", "pylon", "gate", "zealot", "builder_pause", "end_lag"]  # 수입 3개는 실측 고정


class SC1Sim:
    __slots__ = ("P", "target", "events", "spent", "supply_used", "pylon_done", "gate_ready", "gate_busy", "gate_queue",
                 "nexus_free", "zealot_done", "t", "end", "times")

    def __init__(self, P, target):
        self.P = P
        self.target = target
        self.events = [(P["start_delay"], START_WORKERS)]
        self.spent = 0.0
        self.supply_used = START_WORKERS
        self.pylon_done: list[int] = []
        self.gate_ready: list[int] = []
        self.gate_busy: list[float] = []     # 게이트별 마지막 질럿 완료 시각
        self.gate_queue: list[list[float]] = []  # 게이트별 질럿 완료 시각들
        self.nexus_free = 0
        self.zealot_done: list[float] = []
        self.t = -1
        self.end = None
        self.times: list[int] = []

    # ---- 자원
    def _rate(self, n):
        P = self.P
        return (P["income"] * min(n, MINERAL_FIELD)
                + P["income_add"] * max(0, min(n, P["sat"]) - MINERAL_FIELD)
                + P["income_over"] * max(0, n - P["sat"]))

    def minerals_at(self, t):
        ev = sorted(self.events)
        m = START_MINERALS - self.spent
        n, prev = 0, None
        for te, d in ev:
            if te >= t:
                break
            if prev is not None:
                m += self._rate(n) * (te - prev)
            n += d
            prev = te
        if prev is not None and t > prev:
            m += self._rate(n) * (t - prev)
        return m

    def rate_at(self, t):
        return self._rate(sum(d for te, d in self.events if te <= t))

    def earliest_afford(self, cost, t):
        ev = sorted(self.events)
        for _ in range(10000):
            m = self.minerals_at(t)
            if m >= cost - 1e-9:
                return t
            n = sum(d for te, d in ev if te <= t)
            nxt = min((te for te, _ in ev if te > t), default=None)
            rt = self._rate(n)
            if rt <= 0:
                if nxt is None:
                    return None
                t = nxt
                continue
            need = math.ceil((cost - m) / rt - 1e-9)
            if nxt is None or t + need <= nxt:
                return t + need
            t = nxt
        return None

    def cap_at(self, t):
        return START_CAP + 8 * sum(1 for c in self.pylon_done if c <= t)

    def supply_time(self, need, t):
        if self.supply_used + need <= self.cap_at(t):
            return t
        for c in sorted(self.pylon_done):
            if c >= t and self.supply_used + need <= self.cap_at(c):
                return c
        return None

    # ---- 명령
    def step(self, a):
        """명령 a 를 실행하고 실행 프레임을 돌려준다. 종료 전 실행 불가면 None."""
        P = self.P
        cost = COST[a]
        t = self.t + 1
        if a == 2:
            if not self.pylon_done:
                return None
            t = max(t, min(self.pylon_done))
        if a == 3:
            if not self.gate_ready:
                return None
            t = max(t, min(self.gate_ready))
        need_supply = SUPPLY[a]
        for _ in range(60):
            t2 = self.earliest_afford(cost, t)
            if t2 is None:
                return None
            if need_supply:
                t3 = self.supply_time(need_supply, t2)
                if t3 is None:
                    return None
                if t3 != t2:
                    t = t3
                    continue
            t = t2
            break
        else:
            return None
        if self.end is not None and t > self.end:
            return None
        self.spent += cost
        if a == 0:
            start = max(t, self.nexus_free)
            done = start + P["probe"]
            self.nexus_free = done
            self.events.append((done + P["mine_delay"], 1))
            self.supply_used += 1
        elif a == 1:
            self.pylon_done.append(t + P["pylon"])
            self._builder_pause(t)
        elif a == 2:
            self.gate_ready.append(t + P["gate"])
            self.gate_busy.append(float(t + P["gate"]))
            self.gate_queue.append([])
            self._builder_pause(t)
        elif a == 3:
            ready = [i for i, r in enumerate(self.gate_ready) if r <= t]
            # 실행기 pickGateway: 큐 길이(미완료 질럿 수) 짧은 것, 같으면 남은 시간 적은 것, 같으면 먼저 생긴 것
            g = min(ready, key=lambda i: (sum(1 for d in self.gate_queue[i] if d > t), max(0.0, self.gate_busy[i] - t), i))
            start = max(float(t), self.gate_busy[g])
            done = start + P["zealot"]
            self.gate_busy[g] = done
            self.gate_queue[g].append(done)
            self.zealot_done.append(done)
            self.supply_used += 2
            if len(self.zealot_done) >= self.target:
                self.end = int(math.ceil(sorted(self.zealot_done)[self.target - 1])) + P["end_lag"]
        self.t = t
        self.times.append(t)
        return t

    def _builder_pause(self, t):
        d = self.P["builder_pause"]
        if d > 0:
            self.events.append((t, -1))
            self.events.append((t + d, 1))

    def copy(self):
        o = SC1Sim.__new__(SC1Sim)
        o.P, o.target = self.P, self.target
        o.events = list(self.events)
        o.spent, o.supply_used = self.spent, self.supply_used
        o.pylon_done, o.gate_ready = list(self.pylon_done), list(self.gate_ready)
        o.gate_busy, o.gate_queue = list(self.gate_busy), [list(q) for q in self.gate_queue]
        o.nexus_free = self.nexus_free
        o.zealot_done = list(self.zealot_done)
        o.t, o.end, o.times = self.t, self.end, list(self.times)
        return o

    # ---- 탐색용 낙관적 하한: 남은 질럿을 지금 게이트로 자원 제약 없이 만들 때의 완료 시각과, 미네랄 수입 제약 중 큰 쪽
    def lower_bound(self):
        r = self.target - len(self.zealot_done)
        if r <= 0:
            return self.end
        t = max(self.t, 0)
        P = self.P
        busy = sorted(self.gate_busy) if self.gate_busy else [float(t + P["gate"])]
        busy = [max(b, float(t)) for b in busy]
        import heapq
        heapq.heapify(busy)
        last = t
        for _ in range(r):
            b = heapq.heappop(busy)
            last = b + P["zealot"]
            heapq.heappush(busy, last)
        need = r * COST[3] - self.minerals_at(t)
        rate = self.rate_at(t)
        lb_min = t + (need / rate if rate > 0 and need > 0 else 0) + P["zealot"]
        return max(last, lb_min)


def simulate(seq, P, target):
    sim = SC1Sim(P, target)
    for a in seq:
        if sim.step(a) is None:
            break
    return sim.times, sim.end


# --------------------------------------------------------------------------- 적합
def loss(P, data, per_action=False):
    """data: [(target, seq, 실행 프레임 목록, end)]. 평균 절대 오차. 실행 실패는 큰 벌점."""
    tot, n = 0.0, 0
    by_a = defaultdict(list)
    for target, seq, times, end in data:
        pred, pend = simulate(seq, P, target)
        if pend is None or len(pred) != len(times):
            tot += 2000
            n += 1
            continue
        for a, p, q in zip(seq, pred, times):
            tot += abs(p - q)
            n += 1
            by_a[a].append(p - q)
        tot += 2 * abs(pend - end)
        n += 1
        by_a["end"].append(pend - end)
    return (tot / max(n, 1), by_a) if per_action else tot / max(n, 1)


def fit(data, P0=None, verbose=False, rounds=60):
    """좌표 하강법(build_sim.fit 과 같음). 매개변수를 한 칸씩 움직여 손실이 줄면 받는다."""
    P = dict(P0 or DEFAULT_PARAMS)
    if not data:
        return P, float("nan")
    best = loss(P, data)
    steps = {k: (16 if k in INT_PARAMS else 0.004) for k in FIT_PARAMS}
    for rnd in range(rounds):
        improved = False
        for k in FIT_PARAMS:
            st = steps[k]
            for d in (st, -st):
                cand = dict(P)
                cand[k] = cand[k] + d
                if k in INT_PARAMS:
                    cand[k] = int(round(cand[k]))
                if cand[k] < 0 or (k == "income" and cand[k] <= 0):
                    continue
                v = loss(cand, data)
                if v < best - 1e-9:
                    P, best, improved = cand, v, True
                    break
        if not improved:
            shrunk = False
            for k in FIT_PARAMS:
                if k in INT_PARAMS and steps[k] > 1:
                    steps[k] = max(1, steps[k] // 2)
                    shrunk = True
                elif k not in INT_PARAMS and steps[k] > 0.0005:
                    steps[k] /= 2
                    shrunk = True
            if not shrunk:
                break
        if verbose:
            print(f"  round {rnd + 1}: 손실 {best:.2f}")
    return P, best


# --------------------------------------------------------------------------- 탐색
def make_allowed(target, max_gates, max_workers, workers_before_zealots=True):
    """열거 규칙. offline_rl/zealot_n.make_allowed 와 같은 꼴, 스타1 상수."""
    def allowed(prefix):
        w, p, g, z = prefix.count(0), prefix.count(1), prefix.count(2), prefix.count(3)
        cap = START_CAP + 8 * p
        used = START_WORKERS + w + 2 * z
        acts = []
        if w < max_workers and (z == 0 or not workers_before_zealots) and START_WORKERS + w < MINERAL_FIELD * 3:  # 덩이당 3기까지 허용. 효율은 데이터(income_add/over 적합)가 정한다
            acts.append(0)
        # 파일런: 아직 없거나, 남은 생산(일꾼·질럿)에 인구가 모자랄 수 있을 때
        if p == 0 or used + 2 * (target - z) + (max_workers - w if z == 0 else 0) > cap:
            acts.append(1)
        if p >= 1 and g < max_gates:
            acts.append(2)
        if g >= 1 and z < target and used + 2 <= cap:
            acts.append(3)
        return acts
    return allowed


def beam_search(P, target, width=2000, max_gates=None, max_workers=12, topk=20, workers_before_zealots=True):
    """빔 탐색. 접두사를 하한(lower_bound)으로 줄 세워 width 개만 남긴다. 완성 명령열 상위 topk 반환."""
    if max_gates is None:
        max_gates = max(1, min(8, (target + 1) // 2))
    allowed = make_allowed(target, max_gates, max_workers, workers_before_zealots)
    beam = [(SC1Sim(P, target), ())]
    finished = {}
    depth = 0
    while beam and depth < 80:
        cands = []
        for sim, prefix in beam:
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
        beam = [(s, seq) for _, s, seq in cands[:width]]
        depth += 1
    res = sorted((e, seq) for seq, e in finished.items())
    return res[:topk], len(finished)


def exhaustive(P, target, max_gates, max_workers, max_len=40, workers_before_zealots=True, limit=2_000_000):
    """작은 N 검증용 전수 탐색(분기 한정). (상위 목록, 완성 개수)"""
    allowed = make_allowed(target, max_gates, max_workers, workers_before_zealots)
    results = []
    count = 0
    best = [math.inf]

    def dfs(sim, prefix):
        nonlocal count
        if count > limit:
            return
        for a in allowed(prefix):
            s2 = sim.copy()
            if s2.step(a) is None:
                continue
            prefix.append(a)
            if s2.end is not None:
                count += 1
                results.append((s2.end, tuple(prefix)))
                best[0] = min(best[0], s2.end)
            elif len(prefix) < max_len and s2.lower_bound() <= best[0]:
                dfs(s2, prefix)
            prefix.pop()

    dfs(SC1Sim(P, target), [])
    results.sort()
    return results, count


def neighbors(seq, target, max_workers=12, max_gates=8):
    """실게임 국소 탐색용 이웃: 인접 교환, 일꾼 추가/제거, 게이트 추가/제거, 파일런 추가/제거."""
    seq = list(seq)
    out = set()
    for i in range(len(seq) - 1):
        if seq[i] != seq[i + 1]:
            s = seq[:]
            s[i], s[i + 1] = s[i + 1], s[i]
            out.add(tuple(s))
    for a, cap in ((0, max_workers), (2, max_gates), (1, 8)):
        idxs = [i for i, x in enumerate(seq) if x == a]
        if idxs:
            for i in idxs:
                s = seq[:i] + seq[i + 1:]
                out.add(tuple(s))
        if len(idxs) < cap:
            first_z = next((i for i, x in enumerate(seq) if x == 3), len(seq))
            positions = range(0, (first_z + 1 if a == 0 else len(seq) + 1))
            for i in positions:
                s = seq[:i] + [a] + seq[i:]
                out.add(tuple(s))
    out.discard(tuple(seq))
    return [list(s) for s in out if s.count(3) == target]


if __name__ == "__main__":
    import sys
    seq = [int(x) for x in (sys.argv[1] if len(sys.argv) > 1 else "0,0,1,2,2,3,3,3,3,3").split(",")]
    target = seq.count(3)
    times, end = simulate(seq, DEFAULT_PARAMS, target)
    print("times", times, "end", end)
    top, n = beam_search(DEFAULT_PARAMS, target, width=500)
    print(f"beam: {n}개 완성, 상위 5:")
    for e, s in top[:5]:
        print("  ", e, s)
