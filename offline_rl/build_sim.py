"""질럿 2 로그로 빌드 시뮬레이터(비용 모델)를 학습하고, 질럿 5 로그로 검증한다.

왜 시뮬레이터인가:
  표 형식 Q-learning은 데이터에 있는 상태만 값을 가진다. 질럿 5 문제의 상태(게이트 3개,
  질럿 3~5기)는 질럿 2 데이터에 한 번도 나오지 않으므로 어떤 상태 추상화를 써도 표가
  비어 있다. 질럿 2 → 질럿 5로 옮길 수 있는 것은 "명령이 얼마나 걸리는가"의 규칙이다.
  그래서 봇(incredibot-sct.py)의 실행 규칙을 그대로 옮긴 결정론적 시뮬레이터를 만들고,
  수치(채취율, 생산 시간, 시간 증폭 등)는 질럿 2 로그에 맞춰 학습한다(모델 기반 RL의 모델 학습).

학습(질럿 2)  : 매개변수 좌표 하강법. 손실 = 명령 실행 시각과 종료 프레임의 평균 절대 오차.
검증(질럿 5)  : 4,805개 명령열의 종료 프레임을 예측해 실제와 비교. 질럿 5 로그는 적합에 쓰지 않는다.
정책 학습     : 시뮬레이터를 환경으로 Q-learning(질럿 5 목표). 결과 명령열의 실제 프레임을 질럿 5 로그에서 찾는다.

표준 라이브러리만 사용한다.
"""
from __future__ import annotations

import csv
import math
import random
import statistics
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import zealot2_offline_rl as base  # noqa: E402

ROOT = base.ROOT
OUT_DIR = base.OUT_DIR
MINERAL_COST = base.MINERAL_COST
START_MINERALS = 50
START_WORKERS = 12
START_CAP = 15

# 로그 관찰에서 잡은 초기값. 단위는 모두 iteration(봇 on_step 호출 횟수).
DEFAULT_PARAMS = {
    "income": 0.16,        # 처음 12명 일꾼 1명당 채취율 (미네랄/iteration)
    "income_add": 0.12,    # 13~16번째 일꾼 1명당 채취율
    "income_over": 0.07,   # 포화(sat명) 초과 일꾼의 채취율
    "sat": 16,             # 미네랄 8덩이 x 2
    "start_delay": 16,     # 게임 시작 후 첫 채취 수입까지
    "probe": 70,           # 일꾼 생산 시간
    "mine_delay": 2,       # 새 일꾼이 채취를 시작하기까지
    "pylon": 115,          # 파일런 명령 -> 완성 (일꾼 이동 포함)
    "gate": 227,           # 게이트 명령 -> 완성
    "zealot": 150,         # 질럿 생산 시간
    "chrono_len": 111,     # 시간 증폭 지속 시간 (게이트의 작업 속도 1.5배 창)
    "chrono_regen": 273,   # 넥서스 에너지 50 회복 시간
    "builder_pause": 0,    # 건설 일꾼이 채취를 쉬는 시간
    "end_lag": 1,          # 마지막 질럿 완성 -> 봇이 종료를 기록하기까지
}
INT_PARAMS = {"start_delay", "probe", "mine_delay", "pylon", "gate", "zealot", "chrono_len",
              "chrono_regen", "builder_pause", "end_lag", "sat"}
FIT_PARAMS = ["income", "start_delay", "probe", "pylon", "gate", "zealot", "chrono_len",
              "chrono_regen", "builder_pause", "mine_delay", "end_lag", "income_add", "income_over"]


# --------------------------------------------------------------------------- 시뮬레이터
class BuildSim:
    """봇의 명령 실행 규칙을 옮긴 결정론적 시뮬레이터.

    규칙(incredibot-sct.py):
      일꾼   : 미네랄 50, 인구 여유 1. 넥서스 큐에 순차 생산.
      파일런 : 미네랄 100. 완성되면 인구 한도 +8.
      게이트 : 미네랄 150, 완성된 파일런 필요.
      질럿   : 미네랄 100, 인구 여유 2, 완성된 게이트 필요. 가장 먼저 비는 게이트부터 배정
               (봇의 '생산 재분배'와 같음, _schedule 참고). 비어 있는 게이트에 들어가면 에너지가 있을 때 시간 증폭.
               시간 증폭은 게이트에 chrono_len 동안 걸리는 1.5배 창이라 다음 질럿에도 남은 만큼 적용된다.
      인구수 : 일꾼은 명령 즉시 인구를 차지한다(로그: 일꾼 3기 명령 뒤 4기째가 파일런 완성을 기다림).
               질럿은 생산이 시작돼야 인구를 차지한다(로그: 게이트 1개에 질럿 3기 명령 뒤 supply_used=16).
      종료   : 목표 수째 질럿 완성 시각 + end_lag.
    명령은 직전 명령 다음 iteration부터 조건을 만족하는 첫 iteration에 실행된다.
    """

    __slots__ = ("P", "target", "events", "spent", "supply_used", "pylon_done", "gate_ready",
                 "nexus_free", "zealot_issue", "zealot_start", "zealot_done", "t", "end", "times")

    def __init__(self, P, target):
        self.P = P
        self.target = target
        self.events = [(P["start_delay"], START_WORKERS)]  # (시각, 채취 일꾼 증감)
        self.spent = 0.0
        self.supply_used = START_WORKERS
        self.pylon_done: list[int] = []
        self.gate_ready: list[int] = []
        self.nexus_free = 0
        self.zealot_issue: list[int] = []    # 질럿 명령 시각
        self.zealot_start: list[float] = []  # 생산 시작 시각 (스케줄 결과)
        self.zealot_done: list[float] = []
        self.t = -1          # 직전 명령 실행 시각
        self.end = None      # 종료 프레임 (목표 달성 시)
        self.times: list[int] = []

    # ---- 자원
    def _rate(self, n):
        P = self.P
        return (P["income"] * min(n, START_WORKERS)
                + P["income_add"] * max(0, min(n, P["sat"]) - START_WORKERS)
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

    def earliest_afford(self, cost, t):
        ev = sorted(self.events)
        while True:
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

    def cap_at(self, t):
        return START_CAP + 8 * sum(1 for c in self.pylon_done if c <= t)

    def used_at(self, t):
        return self.supply_used + 2 * sum(1 for s in self.zealot_start if s <= t)

    def supply_time(self, need, t):
        """인구 여유가 need 이상 되는 첫 시각 (>= t). 불가능하면 None."""
        if self.used_at(t) + need <= self.cap_at(t):
            return t
        for c in sorted(self.pylon_done):
            if c >= t and self.used_at(c) + need <= self.cap_at(c):
                return c
        return None

    # ---- 질럿 스케줄
    def _schedule(self):
        """질럿 명령 시각과 게이트 완성 시각으로 생산 시작·완료 시각을 다시 계산한다.

        봇의 규칙: 질럿은 명령 시점에 완성돼 있던 첫 게이트(sg0)의 큐에 들어가고, 다른 게이트가
        비면 큐의 마지막 질럿을 그리로 옮긴다. 옮겨 들어간 질럿과 비어 있는 게이트에 바로 들어간
        질럿은 에너지가 있으면 시간 증폭을 받는다. 같은 게이트에서 앞 질럿이 끝나 자동으로
        시작하는 질럿은 받지 않는다. 결과는 '가장 먼저 비는 게이트부터 차례로 배정'과 같다."""
        P = self.P
        Z, C, regen = P["zealot"], P["chrono_len"], P["chrono_regen"]
        busy = [float(r) for r in self.gate_ready]
        boost = [0.0] * len(busy)
        uses = 0
        starts, dones = [], []
        for issue in self.zealot_issue:
            ready = [i for i, r in enumerate(self.gate_ready) if r <= issue]
            sg0 = min(ready, key=lambda i: self.gate_ready[i])
            g = min(range(len(busy)), key=lambda i: (busy[i], i))
            start = max(issue, busy[g])
            auto = g == sg0 and busy[g] > issue  # 같은 게이트 큐에서 자동 시작
            energy = 50 + 50 * start / regen - 50 * uses
            if not auto and energy >= 50 - 1e-9:
                uses += 1
                boost[g] = start + C
            b = max(0.0, boost[g] - start)
            done = start + Z / 1.5 if 1.5 * b >= Z else start + Z - 0.5 * b
            busy[g] = done
            starts.append(start)
            dones.append(done)
        self.zealot_start, self.zealot_done = starts, dones
        if len(dones) >= self.target:
            self.end = math.ceil(sorted(dones)[self.target - 1]) + P["end_lag"]

    # ---- 명령
    def step(self, a):
        """명령 a를 실행하고 실행 시각을 돌려준다. 실행 불가능하면 None."""
        P = self.P
        cost = MINERAL_COST[a]
        t = self.t + 1
        if a == 2:
            if not self.pylon_done:
                return None
            t = max(t, min(self.pylon_done))
        if a == 3:
            if not self.gate_ready:
                return None
            t = max(t, min(self.gate_ready))  # 완성된 게이트가 하나라도 있어야 한다
        need_supply = {0: 1, 3: 2}.get(a, 0)
        for _ in range(50):
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
        if self.end is not None and t > self.end:
            return None  # 목표 달성 뒤에 실행될 명령
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
            self._builder_pause(t)
            if self.zealot_issue:
                self._schedule()
        elif a == 3:
            self.zealot_issue.append(t)
            self._schedule()
        self.t = t
        self.times.append(t)
        return t

    def _builder_pause(self, t):
        d = self.P["builder_pause"]
        if d > 0:
            self.events.append((t, -1))
            self.events.append((t + d, 1))

    def copy(self):
        o = BuildSim.__new__(BuildSim)
        o.P, o.target = self.P, self.target
        o.events = list(self.events)
        o.spent, o.supply_used = self.spent, self.supply_used
        o.pylon_done, o.gate_ready = list(self.pylon_done), list(self.gate_ready)
        o.nexus_free = self.nexus_free
        o.zealot_issue, o.zealot_start, o.zealot_done = list(self.zealot_issue), list(self.zealot_start), list(self.zealot_done)
        o.t, o.end, o.times = self.t, self.end, list(self.times)
        return o


def simulate(seq, P, target):
    """명령열을 실행해 (명령 실행 시각 목록, 종료 프레임)을 돌려준다. 종료 전 실행 불가면 end=None."""
    sim = BuildSim(P, target)
    for a in seq:
        if sim.step(a) is None:
            break
    return sim.times, sim.end


# --------------------------------------------------------------------------- 학습 (질럿 2)
def load(target):
    base.TARGET = target
    eps = []
    for p in base.LOG_FILES_BY_TARGET[target]:
        if p.exists():
            eps.extend(base.parse_log(p))
    return eps


def episode_targets(eps):
    """에피소드 -> (명령열, 로그 실행 시각 목록, 종료 프레임)"""
    out = []
    for ep in eps:
        times = [s[9] for _, s in ep["steps"][:-1]]
        out.append((ep["actions"], times, ep["end_frame"]))
    return out


def loss(P, data, target, per_action=False):
    """명령 실행 시각 + 종료 프레임의 평균 절대 오차. 실행 실패는 큰 벌점."""
    tot, n = 0.0, 0
    by_a = defaultdict(list)
    for seq, times, end in data:
        pred, pend = simulate(seq, P, target)
        if pend is None or len(pred) != len(times):
            tot += 1000
            n += 1
            continue
        for a, p, q in zip(seq, pred, times):
            tot += abs(p - q)
            n += 1
            by_a[a].append(p - q)
        tot += abs(pend - end)
        n += 1
        by_a["end"].append(pend - end)
    return (tot / n, by_a) if per_action else tot / n


def fit(data, target, P0=None, verbose=True):
    """좌표 하강법. 각 매개변수를 한 칸씩 움직여 손실이 줄면 받아들인다."""
    P = dict(P0 or DEFAULT_PARAMS)
    best = loss(P, data, target)
    steps = {k: (8 if k in INT_PARAMS else 0.004) for k in FIT_PARAMS}
    if verbose:
        print(f"  초기 손실 {best:.2f}")
    for rnd in range(40):
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
                v = loss(cand, data, target)
                if v < best - 1e-9:
                    P, best, improved = cand, v, True
                    break
        if not improved:
            # 보폭을 줄인다
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
            print(f"  round {rnd + 1}: 손실 {best:.2f}  " + ", ".join(
                f"{k}={P[k]:.3f}" if k not in INT_PARAMS else f"{k}={P[k]}" for k in FIT_PARAMS))
    return P, best


# --------------------------------------------------------------------------- 검증 (질럿 5)
def rank_corr(xs, ys):
    """스피어만 순위 상관."""
    def ranks(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and v[order[j + 1]] == v[order[i]]:
                j += 1
            for k in range(i, j + 1):
                r[order[k]] = (i + j) / 2 + 1
            i = j + 1
        return r
    rx, ry = ranks(xs), ranks(ys)
    mx, my = statistics.fmean(rx), statistics.fmean(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = math.sqrt(sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry))
    return num / den if den else float("nan")


def validate(P, eps, target):
    """명령열별 실제 평균 종료 프레임과 예측을 비교한다."""
    by_order = defaultdict(list)
    for ep in eps:
        by_order[ep["actions"]].append(ep["end_frame"])
    actual = {o: statistics.fmean(v) for o, v in by_order.items()}
    pred, fail = {}, []
    for o in actual:
        _, e = simulate(o, P, target)
        if e is None:
            fail.append(o)
        else:
            pred[o] = e
    orders = list(pred)
    errs = [pred[o] - actual[o] for o in orders]
    abs_errs = [abs(e) for e in errs]
    res = {
        "n": len(actual),
        "fail": len(fail),
        "mae": statistics.fmean(abs_errs),
        "bias": statistics.fmean(errs),
        "max": max(abs_errs),
        "within10": sum(e <= 10 for e in abs_errs) / len(abs_errs),
        "within20": sum(e <= 20 for e in abs_errs) / len(abs_errs),
        "spearman": rank_corr([pred[o] for o in orders], [actual[o] for o in orders]),
    }
    true_rank = sorted(orders, key=actual.get)
    pred_rank = sorted(orders, key=pred.get)
    res["top10_overlap"] = len(set(true_rank[:10]) & set(pred_rank[:10]))
    res["best_true"] = (true_rank[0], actual[true_rank[0]], pred[true_rank[0]])
    res["best_pred"] = (pred_rank[0], pred[pred_rank[0]], actual[pred_rank[0]])
    res["pred_rank_of_true_best"] = pred_rank.index(true_rank[0]) + 1
    res["true_rank_of_pred_best"] = true_rank.index(pred_rank[0]) + 1
    res["worst"] = sorted(orders, key=lambda o: -abs(pred[o] - actual[o]))[:5]
    res["pred"], res["actual"] = pred, actual
    return res


# --------------------------------------------------------------------------- 시뮬레이터 위 강화학습 (질럿 5)
MINERAL_FIELD = 8


def allowed_actions(prefix, target):
    """저장소 1.backtrack-all-action.py의 열거 규칙. 로그에 있는 명령열 공간과 같다."""
    w, p, g, z = prefix.count(0), prefix.count(1), prefix.count(2), prefix.count(3)
    acts = []
    if z == 0 and START_WORKERS + w < min(START_CAP + p * 8 - 2 * z, MINERAL_FIELD * 2):
        acts.append(0)
    if p == 0 or START_WORKERS + w + 2 * z + 1 + 2 * g + 1 > START_CAP + p * 8:
        acts.append(1)
    if p >= 1 and g < 3:
        acts.append(2)
    if g >= 1 and START_CAP + p * 8 - (START_WORKERS + w) - z * 2 >= 2:
        acts.append(3)
    return acts


def q_learning_sim(P, target, episodes, seed, alpha=0.1, eps_start=0.3, eps_end=0.05,
                   eval_every=10000, max_len=16, allowed=allowed_actions):
    """시뮬레이터를 환경으로 하는 표 형식 Q-learning. 상태 = 명령열(history), gamma=1,
    보상 = -(다음 명령 실행까지 걸린 프레임), 마지막 명령은 종료까지. 행동은 열거 규칙으로 가린다."""
    rng = random.Random(seed)
    Q = defaultdict(float)
    curve = []
    best_seen = (math.inf, None)

    def run_episode(eps_greedy):
        sim = BuildSim(P, target)
        prefix = []
        trajectory = []
        while True:
            acts = allowed(prefix, target)
            if not acts or len(prefix) >= max_len:
                return None, trajectory
            s = tuple(prefix)
            if rng.random() < eps_greedy:
                a = rng.choice(acts)
            else:
                a = max(acts, key=lambda b: Q[(s, b)])
            t_prev = max(sim.t, 0)
            t = sim.step(a)
            prefix.append(a)
            if t is None:
                trajectory.append((s, a, -1000, None))
                return None, trajectory
            if sim.end is not None:
                trajectory.append((s, a, -(sim.end - t_prev), None))
                return sim.end, trajectory
            trajectory.append((s, a, -(t - t_prev), tuple(prefix)))

    for ep in range(1, episodes + 1):
        e = max(eps_end, eps_start * (1 - ep / (0.7 * episodes)))
        end, traj = run_episode(e)
        if end is not None and end < best_seen[0]:
            best_seen = (end, tuple(a for _, a, _, _ in traj))
        for s, a, r, nxt in traj:
            if nxt is None:
                target_v = r
            else:
                acts = allowed(list(nxt), target)
                target_v = r + (max(Q[(nxt, b)] for b in acts) if acts else -1000)
            Q[(s, a)] += alpha * (target_v - Q[(s, a)])
        if ep % eval_every == 0 or ep == episodes:
            end_g, traj_g = run_episode(0.0)
            curve.append((ep, end_g if end_g is not None else float("nan"),
                          tuple(a for _, a, _, _ in traj_g)))
    end_g, traj_g = run_episode(0.0)
    return (end_g, tuple(a for _, a, _, _ in traj_g)), best_seen, curve, len(Q)


def exhaustive_sim(P, target, allowed=allowed_actions, max_len=16):
    """열거 규칙 안의 모든 명령열을 시뮬레이터로 평가한다 (접두사 공유 DFS). 최적 10개와 개수."""
    results = []
    count = 0

    def dfs(sim, prefix):
        nonlocal count
        for a in allowed(prefix, target):
            s2 = sim.copy()
            if s2.step(a) is None:
                continue
            prefix.append(a)
            if s2.end is not None:
                count += 1
                results.append((s2.end, tuple(prefix)))
            elif len(prefix) < max_len:
                dfs(s2, prefix)
            prefix.pop()

    dfs(BuildSim(P, target), [])
    results.sort()
    return results, count


# --------------------------------------------------------------------------- 실행
def main():
    import argparse

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--episodes", type=int, default=300000, help="시뮬레이터 Q-learning 에피소드 수")
    ap.add_argument("--seeds", type=int, default=3)
    ap.add_argument("--eval-every", type=int, default=20000)
    ap.add_argument("--no-exhaustive", action="store_true", help="시뮬레이터 전수 평가 생략")
    args = ap.parse_args()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    lines = ["# 질럿 2 로그로 학습한 빌드 시뮬레이터와 질럿 5 검증\n"]

    # 1. 학습
    print("질럿 2 로그 읽기")
    eps2 = load(2)
    data2 = episode_targets(eps2)
    print(f"  {len(eps2)} 에피소드, 명령 {sum(len(t) for _, t, _ in data2)}개")
    t0 = time.time()
    print("매개변수 적합 (질럿 2만 사용)")
    P, l2 = fit(data2, 2)
    print(f"  적합 완료 {time.time() - t0:.0f}초, 학습 손실 {l2:.2f}")
    l2, by_a2 = loss(P, data2, 2, per_action=True)

    lines.append("## 1. 학습: 질럿 2 로그 → 시뮬레이터 매개변수\n")
    lines.append(f"- 학습 데이터: 질럿 2 에피소드 {len(eps2)}개 (명령 {sum(len(t) for _, t, _ in data2)}개). 질럿 5 로그는 쓰지 않았다.")
    lines.append(f"- 손실(명령 실행 시각·종료 프레임 평균 절대 오차): **{l2:.2f} iteration**\n")
    lines.append("| 매개변수 | 값 | 뜻 |")
    lines.append("|---|---|---|")
    desc = {
        "income": "처음 12명 일꾼 1명당 채취율 (미네랄/iteration)", "income_add": "13~16번째 일꾼 1명당 채취율", "income_over": "16명 초과 일꾼의 채취율",
        "start_delay": "첫 수입까지 지연", "probe": "일꾼 생산 시간", "mine_delay": "새 일꾼 채취 시작 지연",
        "pylon": "파일런 명령→완성", "gate": "게이트 명령→완성", "zealot": "질럿 생산",
        "chrono_len": "시간 증폭 지속 시간(1.5배 창)", "chrono_regen": "에너지 50 회복", "builder_pause": "건설 일꾼 채취 중단",
        "end_lag": "마지막 질럿 완성→종료 기록",
    }
    for k in FIT_PARAMS:
        v = P[k] if k in INT_PARAMS else f"{P[k]:.4f}"
        lines.append(f"| {k} | {v} | {desc[k]} |")
    lines.append("\n명령 종류별 잔차(예측 − 실제, iteration):\n")
    lines.append("| 명령 | 개수 | 평균 | 절대 평균 | 최대 |")
    lines.append("|---|---|---|---|---|")
    for k in [0, 1, 2, 3, "end"]:
        v = by_a2[k]
        nm = base.ACTION_NAME.get(k, "종료")
        lines.append(f"| {nm} | {len(v)} | {statistics.fmean(v):+.1f} | {statistics.fmean(abs(x) for x in v):.1f} | {max(abs(x) for x in v)} |")
        print(f"  {nm}: n={len(v)} 평균 {statistics.fmean(v):+.1f} 절대 {statistics.fmean(abs(x) for x in v):.1f} 최대 {max(abs(x) for x in v)}")

    # 질럿 2 자체 검증 (적합 데이터)
    v2 = validate(P, eps2, 2)
    lines.append(f"\n질럿 2 명령열 {v2['n']}개 종료 프레임: MAE {v2['mae']:.1f}, 순위 상관 {v2['spearman']:.3f}, "
                 f"실제 최적 {list(v2['best_true'][0])} {v2['best_true'][1]:.1f} → 예측 {v2['best_true'][2]}, "
                 f"예측 최적 {list(v2['best_pred'][0])} {v2['best_pred'][1]} (실제 {v2['best_pred'][2]:.1f}, 실제 순위 {v2['true_rank_of_pred_best']})\n")

    # 2. 검증
    print("\n질럿 5 로그 읽기 (검증 전용)")
    eps5 = load(5)
    v5 = validate(P, eps5, 5)
    print(f"  명령열 {v5['n']}개, 실패 {v5['fail']}, MAE {v5['mae']:.1f}, 편향 {v5['bias']:+.1f}, 최대 {v5['max']}, "
          f"10 이내 {v5['within10']:.0%}, 20 이내 {v5['within20']:.0%}, 순위 상관 {v5['spearman']:.3f}")
    print(f"  실제 최적 {list(v5['best_true'][0])} {v5['best_true'][1]:.1f} → 예측 {v5['best_true'][2]} (예측 순위 {v5['pred_rank_of_true_best']})")
    print(f"  예측 최적 {list(v5['best_pred'][0])} {v5['best_pred'][1]} → 실제 {v5['best_pred'][2]:.1f} (실제 순위 {v5['true_rank_of_pred_best']})")
    lines.append("## 2. 검증: 질럿 5 로그 (학습에 쓰지 않음)\n")
    lines.append(f"- 서로 다른 명령열 {v5['n']}개 (에피소드 {len(eps5)}개), 시뮬레이터 실행 실패 {v5['fail']}개")
    lines.append(f"- 종료 프레임 예측 오차: MAE **{v5['mae']:.1f}**, 편향 {v5['bias']:+.1f}, 최대 {v5['max']}, "
                 f"오차 10 이내 {v5['within10']:.0%}, 20 이내 {v5['within20']:.0%}")
    lines.append(f"- 순위 상관(스피어만) **{v5['spearman']:.3f}**, 실제 상위 10개와 예측 상위 10개 겹침 {v5['top10_overlap']}/10")
    lines.append(f"- 실제 최적 {list(v5['best_true'][0])}: 실제 {v5['best_true'][1]:.1f}, 예측 {v5['best_true'][2]}, 예측 순위 {v5['pred_rank_of_true_best']}위")
    lines.append(f"- 예측 최적 {list(v5['best_pred'][0])}: 예측 {v5['best_pred'][1]}, 실제 {v5['best_pred'][2]:.1f}, 실제 순위 {v5['true_rank_of_pred_best']}위\n")
    lines.append("예측 오차가 큰 명령열 5개:\n")
    lines.append("| 명령열 | 실제 | 예측 | 오차 |")
    lines.append("|---|---|---|---|")
    for o in v5["worst"]:
        lines.append(f"| {list(o)} | {v5['actual'][o]:.1f} | {v5['pred'][o]} | {v5['pred'][o] - v5['actual'][o]:+.1f} |")
    # 질럿 5 잔차를 명령별로
    data5 = episode_targets(eps5)
    l5, by_a5 = loss(P, data5, 5, per_action=True)
    lines.append(f"\n질럿 5 명령 실행 시각 잔차 (평균 절대 오차 {l5:.2f}):\n")
    lines.append("| 명령 | 개수 | 평균 | 절대 평균 | 최대 |")
    lines.append("|---|---|---|---|---|")
    for k in [0, 1, 2, 3, "end"]:
        v = by_a5[k]
        nm = base.ACTION_NAME.get(k, "종료")
        lines.append(f"| {nm} | {len(v)} | {statistics.fmean(v):+.1f} | {statistics.fmean(abs(x) for x in v):.1f} | {max(abs(x) for x in v)} |")
    with open(OUT_DIR / "sim_pred_zealot5.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["order", "actual_mean", "predicted", "error"])
        for o in sorted(v5["actual"], key=v5["actual"].get):
            p = v5["pred"].get(o)
            w.writerow([" ".join(map(str, o)), f"{v5['actual'][o]:.1f}", p, "" if p is None else f"{p - v5['actual'][o]:+.1f}"])

    # 3. 시뮬레이터 위 계획/학습
    lines.append("\n## 3. 시뮬레이터 위에서 질럿 5 정책 학습\n")
    if not args.no_exhaustive:
        t0 = time.time()
        res, cnt = exhaustive_sim(P, 5)
        print(f"\n시뮬레이터 전수 평가: 명령열 {cnt}개, {time.time() - t0:.0f}초")
        lines.append(f"열거 규칙 안의 명령열 {cnt}개를 시뮬레이터로 모두 평가했다 ({time.time() - t0:.0f}초). 상위 10개:\n")
        lines.append("| 순위 | 명령열 | 예측 프레임 | 실제 (질럿 5 로그) |")
        lines.append("|---|---|---|---|")
        for i, (e, o) in enumerate(res[:10], 1):
            act = v5["actual"].get(o)
            lines.append(f"| {i} | {list(o)} | {e} | {'로그에 없음' if act is None else f'{act:.1f}'} |")
            print(f"  {i}. {list(o)} 예측 {e} 실제 {act}")
        lines.append("")

    print("\n시뮬레이터 Q-learning (질럿 5)")
    lines.append(f"Q-learning: 상태 = 명령열, 행동 마스킹 = 열거 규칙, 보상 = -소요 프레임, gamma=1, {args.seeds}개 시드, {args.episodes} 에피소드.\n")
    lines.append("| 시드 | 학습 정책 명령열 | 예측 프레임 | 실제 (질럿 5 로그) | 상태 수 |")
    lines.append("|---|---|---|---|---|")
    curves_all = []
    for sd in range(args.seeds):
        t0 = time.time()
        (end_g, seq_g), best_seen, curve, nq = q_learning_sim(P, 5, args.episodes, sd, eval_every=args.eval_every)
        act = v5["actual"].get(seq_g)
        print(f"  시드 {sd}: 정책 {list(seq_g)} 예측 {end_g} 실제 {act} (탐색 중 최선 {best_seen[0]} {list(best_seen[1]) if best_seen[1] else None}), "
              f"Q 항목 {nq}, {time.time() - t0:.0f}초")
        lines.append(f"| {sd} | {list(seq_g)} | {end_g} | {'로그에 없음' if act is None else f'{act:.1f}'} | {nq} |")
        curves_all.append(curve)
    lines.append("\n학습 곡선 (탐욕 정책의 예측 프레임):\n")
    lines.append("| 에피소드 | " + " | ".join(f"시드 {sd}" for sd in range(args.seeds)) + " |")
    lines.append("|---|" + "---|" * args.seeds)
    for i in range(len(curves_all[0])):
        lines.append(f"| {curves_all[0][i][0]} | " + " | ".join(f"{c[i][1]:.0f}" for c in curves_all) + " |")

    out = OUT_DIR / "sim_transfer_results.md"
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    with open(OUT_DIR / "sim_params.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["param", "value"])
        for k, v in P.items():
            w.writerow([k, v])
    print(f"\n결과 저장: {out}")


if __name__ == "__main__":
    main()
