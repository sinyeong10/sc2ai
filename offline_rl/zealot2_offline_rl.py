"""질럿 2기 빌드를 스타2 클라이언트 없이, 기록된 로그만으로 강화학습으로 푼다.

입력 데이터 (모두 실제 게임에서 기록된 것):
  - 2__full_log_2.txt, 2__full_log_3.txt : 319개 명령열 전수 실행 로그 (각 1회)
  - 2__full_log_파일런2.txt              : 파일런을 필요할 때만 짓는 174개 부분집합 로그
  - zelaot/flow-action/semi_sim/2__full_log.txt : 185개 명령열 로그 (헤더 없음)

한 줄 형식: (action, {'state': [minerals, gas, supply_used, supply_cap, workers,
            nexus, tech, gateways, zealots, iteration], 'reward', 'action', 'done'})
state는 그 명령을 내리는 시점의 관측값이다. 마지막 줄 action 9의 iteration이 종료 프레임.

방법:
  1. 로그 -> (상태, 행동, 다음 상태, 소요 프레임) 전이 집합 (경험 모델)
  2. 상태 추상화 3종: counts / counts+minerals / history
  3. 경험 모델 위에서 가치 반복(정확해)과 표 형식 Q-learning(gamma=1, 보상=-소요 프레임)
  4. 학습된 정책의 기대 종료 프레임을 전수 데이터의 최적값과 비교

표준 라이브러리만 사용한다.
"""
from __future__ import annotations

import ast
import csv
import math
import random
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOG_FILES_BY_TARGET = {
    2: [
        ROOT / "2__full_log_2.txt",
        ROOT / "2__full_log_3.txt",
        ROOT / "2__full_log_파일런2.txt",
        ROOT / "zelaot" / "flow-action" / "semi_sim" / "2__full_log.txt",
    ],
    5: [
        ROOT / "zelaot" / "flow-action" / "semi_sim" / "5__full_log.txt",
        ROOT / "zelaot" / "flow-action" / "data_set" / "semi_sim_data" / "5__full_log_1.txt",
        ROOT / "zelaot" / "flow-action" / "data_set" / "semi_sim_data" / "5__full_log_2.txt",
    ],
}
TARGET = 2  # 목표 질럿 수. main()에서 인자로 바꾼다.
OUT_DIR = ROOT / "offline_rl" / "results"
TERMINAL = "T"
ACTION_NAME = {0: "일꾼", 1: "파일런", 2: "게이트", 3: "질럿"}


# --------------------------------------------------------------------------- 데이터
def parse_log(path: Path) -> list[dict]:
    """한 로그 파일을 에피소드 목록으로 바꾼다. 에피소드 = {'actions': [...], 'steps': [(a, state), ...]}"""
    episodes, cur = [], None
    with open(path, encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line:
                if cur and cur["steps"]:
                    episodes.append(cur)
                cur = None
                continue
            if line.startswith("["):
                cur = {"steps": []}
                continue
            if line.startswith("("):
                if cur is None:
                    cur = {"steps": []}
                action, d = ast.literal_eval(line)
                cur["steps"].append((action, list(d["state"])))
    if cur and cur["steps"]:
        episodes.append(cur)

    good = []
    for ep in episodes:
        steps = ep["steps"]
        last_a, last_s = steps[-1]
        if last_a != 9 or last_s[8] != TARGET:  # 목표 질럿 수로 끝나지 않은 기록은 버린다
            continue
        its = [s[9] for _, s in steps]
        if any(b < a for a, b in zip(its, its[1:])) or sum(a == 9 for a, _ in steps) != 1:
            continue  # 프레임이 되돌아가거나 종료가 둘인 기록은 깨진 것으로 본다
        ep["actions"] = tuple(a for a, _ in steps[:-1])
        ep["end_frame"] = last_s[9]
        ep["source"] = path.name
        good.append(ep)
    return good


def load_all() -> list[dict]:
    eps = []
    for p in LOG_FILES_BY_TARGET[TARGET]:
        if p.exists():
            got = parse_log(p)
            print(f"  {p.name}: {len(got)} 에피소드")
            eps.extend(got)
        else:
            print(f"  {p.name}: 없음 (건너뜀)")
    return eps


# --------------------------------------------------------------------------- 상태 추상화
def abs_obs_counts(state, prefix):
    """관측값 기반: supply_used, supply_cap, workers, tech, gateways, zealots.
    건설 명령은 일꾼이 도착해 건물을 놓기 전에 기록되므로 '건설 중' 정보가 빠진다."""
    return (state[2], state[3], state[4], state[6], state[7], state[8])


def abs_cmd_counts(state, prefix):
    """명령 횟수 기반 (저장소 semi_world.py의 상태와 같음): (일꾼, 파일런, 게이트, 질럿) 명령 수."""
    return (prefix.count(0), prefix.count(1), prefix.count(2), prefix.count(3))


def abs_cmd_counts_time(state, prefix):
    """명령 횟수 + 결정 시점 프레임(50 단위)."""
    return abs_cmd_counts(state, prefix) + (state[9] // 50,)


def abs_history(state, prefix):
    """명령열 전체 (트리). 가장 세밀하며 데이터와 1:1."""
    return tuple(prefix)


ABSTRACTIONS = {
    "obs_counts": abs_obs_counts,
    "cmd_counts": abs_cmd_counts,
    "cmd_counts+time": abs_cmd_counts_time,
    "history": abs_history,
}


# --------------------------------------------------------------------------- 경험 모델
INIT_STATE = [0, 0, 12, 15, 12, 1, 0, 0, 0, 0]
MINERAL_COST = {0: 50, 1: 100, 2: 150, 3: 100}


def post_state(state, action):
    """명령이 실행된 직후 기대되는 상태 (저장소 0.makedataset.py와 같은 규칙)."""
    s = list(state)
    s[0] = max(0, s[0] - MINERAL_COST[action])
    if action == 0:
        s[2] += 1
        s[4] += 1
    elif action == 1:
        s[3] += 8
        s[6] = max(s[6], 1)
    elif action == 2:
        s[7] += 1
        s[6] = 2
    elif action == 3:
        s[2] += 2
        s[8] += 1
    return s


def feasible(seq):
    """게임 규칙상 가능한 명령열인지 (파일런 -> 게이트 -> 질럿 선행, 인구수 한도)."""
    w = p = g = z = 0
    for a in seq:
        if a == 2 and p == 0:
            return False
        if a == 3 and g == 0:
            return False
        if a == 0:
            w += 1
        elif a == 1:
            p += 1
        elif a == 2:
            g += 1
        elif a == 3:
            z += 1
        if 12 + w + 2 * z > 15 + 8 * p:
            return False
    return z >= TARGET


def decisions_of(ep):
    """에피소드를 (결정 시점 상태, 행동, 소요 프레임) 열로 바꾼다.

    로그의 k번째 줄은 명령 a_k가 '실행된' 순간 t_k의 관측 x_k다. 결정은 그 직전 명령이
    실행된 순간 t_{k-1}(처음은 0)에, 그 명령의 효과를 반영한 상태에서 내려진다고 본다.
    비용 = t_k - t_{k-1}. 마지막 명령의 비용에는 질럿 2기 완성까지의 대기도 포함한다.
    비용 합 = 종료 프레임."""
    steps = ep["steps"]
    cmds = steps[:-1]
    t_end = steps[-1][1][9]
    out = []
    state, t_prev = list(INIT_STATE), 0
    for k, (a, x) in enumerate(cmds):
        last = k == len(cmds) - 1
        cost = (t_end if last else x[9]) - t_prev
        out.append((state, a, cost))
        state, t_prev = post_state(x, a), x[9]
    return out


class EmpiricalModel:
    """로그에서 뽑은 (s, a) -> [(s', cost)] 표. cost = 다음 결정까지 걸린 프레임."""

    def __init__(self, episodes, abstraction):
        self.trans: dict[tuple, list[tuple]] = defaultdict(list)
        self.start = abstraction(INIT_STATE, [])
        for ep in episodes:
            dec = decisions_of(ep)
            prefix = []
            for k, (s, a, cost) in enumerate(dec):
                s_abs = abstraction(s, prefix)
                prefix.append(a)
                if k == len(dec) - 1:
                    nxt = TERMINAL
                else:
                    nxt = abstraction(dec[k + 1][0], prefix)
                self.trans[(s_abs, a)].append((nxt, cost))
        self.states = {s for (s, _) in self.trans} | {TERMINAL}
        self.actions_of = defaultdict(list)
        for (s, a) in self.trans:
            self.actions_of[s].append(a)
        for s in self.actions_of:
            self.actions_of[s].sort()
        # 통계 캐시 (가치 반복과 정책 평가에서 반복 사용)
        self._mean = {}
        self._dist = {}
        for key, lst in self.trans.items():
            self._mean[key] = statistics.fmean(c for _, c in lst)
            cnt = Counter(n for n, _ in lst)
            tot = sum(cnt.values())
            self._dist[key] = {n: k / tot for n, k in cnt.items()}
        self.nonterminal = [s for s in self.states if s != TERMINAL]

    def available(self, s):
        return self.actions_of.get(s, [])

    def sample(self, s, a, rng):
        return rng.choice(self.trans[(s, a)])

    def mean_cost(self, s, a):
        return self._mean[(s, a)]

    def next_dist(self, s, a):
        return self._dist[(s, a)]


# --------------------------------------------------------------------------- 정확해: 가치 반복
def value_iteration(model: EmpiricalModel, iters=500, tol=1e-6):
    """V(s) = 최소 기대 잔여 프레임. gamma=1, 비용 최소화."""
    V = {s: 0.0 for s in model.states}
    for _ in range(iters):
        delta = 0.0
        for s in model.nonterminal:
            best = math.inf
            for a in model.available(s):
                q = model.mean_cost(s, a) + sum(p * V[n] for n, p in model.next_dist(s, a).items())
                best = min(best, q)
            delta = max(delta, abs(best - V[s]))
            V[s] = best
        if delta < tol:
            break
    policy = {}
    for s in model.states:
        if s == TERMINAL:
            continue
        policy[s] = min(
            model.available(s),
            key=lambda a: model.mean_cost(s, a) + sum(p * V[n] for n, p in model.next_dist(s, a).items()),
        )
    return V, policy


def policy_expected_cost(model: EmpiricalModel, policy, iters=500):
    """주어진 결정적 정책의 기대 종료 프레임 (정책 평가)."""
    V = {s: 0.0 for s in model.states}
    for _ in range(iters):
        delta = 0.0
        for s in model.nonterminal:
            if s not in policy:
                continue
            a = policy[s]
            v = model.mean_cost(s, a) + sum(p * V[n] for n, p in model.next_dist(s, a).items())
            delta = max(delta, abs(v - V[s]))
            V[s] = v
        if delta < 1e-6:
            break
    return V[model.start]


def decode_sequence(model: EmpiricalModel, policy, max_len=20):
    """정책을 따라 가장 흔한 다음 상태를 택하며 명령열을 복원한다."""
    s, seq = model.start, []
    while s != TERMINAL and len(seq) < max_len:
        if s not in policy:
            break
        a = policy[s]
        seq.append(a)
        dist = model.next_dist(s, a)
        s = max(dist, key=dist.get)
    return tuple(seq)


# --------------------------------------------------------------------------- Q-learning
def q_learning(model: EmpiricalModel, episodes, seed, alpha=0.1, eps_start=0.3, eps_end=0.05,
               reward="smdp", eval_every=1000):
    """표 형식 Q-learning. gamma=1.
    reward='smdp'    : 매 명령마다 -소요프레임 (시간을 비용으로)
    reward='terminal': 종료 시 exp(-0.01*(종료프레임-1000)) 만 (저장소의 기존 설계)
    alpha=None       : 상태-행동별 방문 횟수의 역수 1/n. 부트스트랩 목표가 비정상(non-stationary)이라
                       초기의 낙관적 목표가 평균에 오래 남아 고정 학습률보다 느리게 수렴한다 (실험으로 확인).
    불가능한 행동은 데이터에 없으므로 선택지에서 뺀다 (action masking)."""
    rng = random.Random(seed)
    Q = defaultdict(float)
    N = defaultdict(int)
    curve = []

    def greedy(s):
        acts = model.available(s)
        return max(acts, key=lambda a: Q[(s, a)])

    for ep in range(1, episodes + 1):
        eps = max(eps_end, eps_start * (1 - ep / (0.7 * episodes)))
        s, elapsed, done = model.start, 0, False
        while not done:
            acts = model.available(s)
            a = rng.choice(acts) if rng.random() < eps else greedy(s)
            nxt, cost = model.sample(s, a, rng)
            elapsed += cost
            done = nxt == TERMINAL
            if reward == "smdp":
                r = -cost
            else:
                r = math.exp(-0.01 * (elapsed - 1000)) if done else 0.0
            target = r if done else r + max(Q[(nxt, b)] for b in model.available(nxt))
            N[(s, a)] += 1
            lr = alpha if alpha is not None else 1.0 / N[(s, a)]
            Q[(s, a)] += lr * (target - Q[(s, a)])
            s = nxt
        if ep % eval_every == 0 or ep == episodes:
            pol = {st: greedy(st) for st in model.nonterminal}
            curve.append((ep, policy_expected_cost(model, pol)))
    policy = {st: greedy(st) for st in model.nonterminal}
    return Q, policy, curve


# --------------------------------------------------------------------------- 실행
def main():
    import argparse

    global TARGET
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--target", type=int, default=2, choices=sorted(LOG_FILES_BY_TARGET), help="목표 질럿 수")
    ap.add_argument("--episodes", type=int, default=30000, help="Q-learning 에피소드 수")
    ap.add_argument("--seeds", type=int, default=5, help="시드 수")
    ap.add_argument("--eval-every", type=int, default=1000, help="학습 곡선 평가 간격")
    args = ap.parse_args()
    TARGET = args.target

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"데이터 읽기 (목표 질럿 {TARGET}기)")
    episodes = load_all()
    print(f"  합계 {len(episodes)} 에피소드")

    # 전수 데이터 기준 정답
    by_order = defaultdict(list)
    for ep in episodes:
        by_order[ep["actions"]].append(ep["end_frame"])
    order_mean = {o: statistics.fmean(v) for o, v in by_order.items()}
    ranked = sorted(order_mean.items(), key=lambda kv: kv[1])
    best_order, best_frame = ranked[0]
    spreads = [max(v) - min(v) for v in by_order.values() if len(v) >= 2]
    print(f"\n서로 다른 명령열 {len(by_order)}개, 최적 평균 종료 프레임 {best_frame:.1f} : {best_order}")
    print(f"같은 명령열 반복 실행 시 프레임 차이: 중앙값 {statistics.median(spreads):.0f}, 최대 {max(spreads)}")

    lines = []
    lines.append(f"# 질럿 {TARGET}기 빌드 오프라인 강화학습 결과\n")
    lines.append(f"- 사용 에피소드: {len(episodes)}개 (서로 다른 명령열 {len(by_order)}개, 스타2 실행 없음)")
    lines.append(f"- 같은 명령열을 다시 돌렸을 때 종료 프레임 차이: 중앙값 {statistics.median(spreads):.0f}, 최대 {max(spreads)} 프레임")
    lines.append(f"- 전수 데이터 최적 (평균 종료 프레임 기준): **{best_frame:.1f} 프레임**, 명령열 {list(best_order)}\n")
    lines.append("## 상위 10개 명령열 (평균 종료 프레임)\n")
    lines.append("| 순위 | 명령열 | 평균 프레임 | 실행 횟수 |")
    lines.append("|---|---|---|---|")
    for i, (o, m) in enumerate(ranked[:10], 1):
        lines.append(f"| {i} | {list(o)} | {m:.1f} | {len(by_order[o])} |")
    lines.append("")
    lines.append("명령 코드: 0 일꾼, 1 파일런, 2 게이트, 3 질럿\n")

    # 추상화별 실험
    seeds = list(range(args.seeds))
    n_episodes = args.episodes
    lines.append("## 상태 추상화별 결과\n")
    lines.append(f"가치 반복은 경험 모델 위의 정확해, Q-learning은 {len(seeds)}개 시드 평균({n_episodes} 에피소드)이다. "
                 "'기대 프레임'은 경험 모델에서 정책을 평가한 값, '복원 명령열'은 정책을 따라간 명령열과 그 실제 평균 프레임이다.\n")
    lines.append("- obs_counts: 게임 관측값(인구, 일꾼, 테크, 게이트, 질럿 수). 건설 중인 건물이 안 보인다.")
    lines.append("- cmd_counts: 지금까지 내린 명령 횟수 (일꾼, 파일런, 게이트, 질럿). 저장소 semi_world.py와 같은 상태.")
    lines.append("- cmd_counts+time: 위에 결정 시점 프레임(50 단위)을 더한 것.")
    lines.append("- history: 명령열 전체. 상태가 데이터와 1:1이라 추상화 손실이 없다.\n")
    lines.append("| 추상화 | 상태 수 | 가치 반복 기대 프레임 | 가치 반복 복원 명령열 (실제 평균) | Q-learning 기대 프레임 (평균±표준편차) | Q-learning 복원 명령열 (실제 평균) | 최적 대비 격차 |")
    lines.append("|---|---|---|---|---|---|---|")

    curves_out = {}
    for name, fn in ABSTRACTIONS.items():
        model = EmpiricalModel(episodes, fn)
        V, pol_vi = value_iteration(model)
        vi_cost = V[model.start]
        vi_seq = decode_sequence(model, pol_vi)
        vi_real = order_mean.get(vi_seq, float("nan"))

        def fmt_real(v, seq):
            if v == v:
                return f"{v:.1f}"
            return "데이터에 없음, " + ("게임 규칙 위반" if not feasible(seq) else "열거 범위 밖")

        q_costs, q_seqs, curves = [], [], []
        for sd in seeds:
            _, pol_q, curve = q_learning(model, n_episodes, sd, eval_every=args.eval_every)
            q_costs.append(policy_expected_cost(model, pol_q))
            q_seqs.append(decode_sequence(model, pol_q))
            curves.append(curve)
        q_mean, q_std = statistics.fmean(q_costs), statistics.pstdev(q_costs)
        q_seq = Counter(q_seqs).most_common(1)[0][0]
        q_real = order_mean.get(q_seq, float("nan"))
        gap = q_real - best_frame
        curves_out[name] = curves

        gap_s = f"+{gap:.1f}" if gap == gap else "측정 불가"
        print(f"\n[{name}] 상태 {len(model.states)}개")
        print(f"  가치 반복: 기대 {vi_cost:.1f}, 복원 {list(vi_seq)} (실제 {fmt_real(vi_real, vi_seq)})")
        print(f"  Q-learning: 기대 {q_mean:.1f}±{q_std:.1f}, 복원 {list(q_seq)} (실제 {fmt_real(q_real, q_seq)}), 최적 대비 {gap_s}")
        lines.append(f"| {name} | {len(model.states)} | {vi_cost:.1f} | {list(vi_seq)} ({fmt_real(vi_real, vi_seq)}) | "
                     f"{q_mean:.1f} ± {q_std:.1f} | {list(q_seq)} ({fmt_real(q_real, q_seq)}) | {gap_s} |")

    # 보상·학습률 설계 비교 (history 추상화)
    lines.append(f"\n## 보상·학습률 설계 비교 (history 추상화, {len(seeds)}개 시드)\n")
    lines.append("| 설정 | Q-learning 기대 프레임 | 최적 도달 시드 수 |")
    lines.append("|---|---|---|")
    model_h = EmpiricalModel(episodes, abs_history)
    opt_h = value_iteration(model_h)[0][model_h.start]
    configs = [
        ("매 명령 -소요프레임, 학습률 0.1 고정", dict(reward="smdp", alpha=0.1)),
        ("매 명령 -소요프레임, 학습률 1/n", dict(reward="smdp", alpha=None)),
        ("종료 시 exp(-0.01(T-1000)) 만, 학습률 0.1 고정", dict(reward="terminal", alpha=0.1)),
        ("종료 시 exp(-0.01(T-1000)) 만, 학습률 1/n", dict(reward="terminal", alpha=None)),
    ]
    for label, kw in configs:
        costs, hits = [], 0
        for sd in seeds:
            _, pol_q, _ = q_learning(model_h, n_episodes, sd, eval_every=n_episodes, **kw)
            c = policy_expected_cost(model_h, pol_q)
            costs.append(c)
            hits += abs(c - opt_h) < 0.5
        lines.append(f"| {label} | {statistics.fmean(costs):.1f} ± {statistics.pstdev(costs):.1f} | {hits}/{len(seeds)} |")
        print(f"{label}: {statistics.fmean(costs):.1f} ± {statistics.pstdev(costs):.1f}, 최적 도달 {hits}/{len(seeds)}")

    # 학습 곡선 저장
    with open(OUT_DIR / f"learning_curve_zealot{TARGET}.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["abstraction", "seed", "episode", "expected_end_frame"])
        for name, curves in curves_out.items():
            for sd, curve in zip(seeds, curves):
                for ep, c in curve:
                    w.writerow([name, sd, ep, f"{c:.2f}"])

    lines.append("\n## 학습 곡선 (Q-learning, 시드 평균 기대 프레임)\n")
    lines.append("| 에피소드 | " + " | ".join(ABSTRACTIONS) + " |")
    lines.append("|---|" + "---|" * len(ABSTRACTIONS))
    n_points = len(next(iter(curves_out.values()))[0])
    for i in range(n_points):
        if i % max(1, n_points // 10) and i != n_points - 1:
            continue
        ep = curves_out["history"][0][i][0]
        vals = [statistics.fmean(curves[sd][i][1] for sd in range(len(seeds))) for curves in curves_out.values()]
        lines.append(f"| {ep} | " + " | ".join(f"{v:.1f}" for v in vals) + " |")
    lines.append(f"\n원본 수치: `offline_rl/results/learning_curve_zealot{TARGET}.csv`\n")

    out_md = OUT_DIR / f"zealot{TARGET}_results.md"
    with open(out_md, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"\n결과 저장: {out_md}")


if __name__ == "__main__":
    main()
