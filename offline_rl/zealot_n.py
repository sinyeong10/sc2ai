"""질럿 N기 문제를 질럿 2 로그로 학습한 시뮬레이터 위에서 푼다.

N마다:
  1. 전수 평가: 열거 규칙(1.backtrack-all-action.py, 목표만 N으로) 안의 모든 명령열을
     시뮬레이터로 평가해 최적을 구한다 (정답).
  2. Q-learning (history 상태): 시뮬레이터를 환경으로 학습해 1의 답을 찾는지 본다.
  3. Q-learning (compact 상태): 시뮬레이터 내부 상태를 버킷으로 묶은 Markov 근사 상태.
     history보다 상태가 적어도 같은 답을 찾는지 본다 (작업-노트 9절 3번).
  4. 로그가 있는 N(2, 5)은 실제 종료 프레임과 비교한다.

시뮬레이터 매개변수는 results/sim_params.csv(질럿 2 로그로 적합)를 읽는다. 없으면 다시 적합한다.
표준 라이브러리만 사용한다.
"""
from __future__ import annotations

import csv
import math
import random
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_sim as bs  # noqa: E402
import zealot2_offline_rl as base  # noqa: E402

OUT_DIR = bs.OUT_DIR


def load_params():
    path = OUT_DIR / "sim_params.csv"
    P = dict(bs.DEFAULT_PARAMS)
    if path.exists():
        with open(path, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                k, v = row["param"], row["value"]
                P[k] = int(v) if k in bs.INT_PARAMS else float(v)
        return P, False
    eps2 = bs.load(2)
    P, _ = bs.fit(bs.episode_targets(eps2), 2, verbose=False)
    return P, True


# --------------------------------------------------------------------------- 행동 규칙 (목표 N, 게이트 상한 G)
def make_allowed(max_gates):
    def allowed(prefix, target):
        w, p, g, z = prefix.count(0), prefix.count(1), prefix.count(2), prefix.count(3)
        acts = []
        if z == 0 and bs.START_WORKERS + w < min(bs.START_CAP + p * 8 - 2 * z, bs.MINERAL_FIELD * 2):
            acts.append(0)
        if p == 0 or bs.START_WORKERS + w + 2 * z + 1 + 2 * g + 1 > bs.START_CAP + p * 8:
            acts.append(1)
        if p >= 1 and g < max_gates:
            acts.append(2)
        if g >= 1 and bs.START_CAP + p * 8 - (bs.START_WORKERS + w) - z * 2 >= 2:
            acts.append(3)
        return acts
    return allowed


# --------------------------------------------------------------------------- compact 상태
def compact_state(sim: bs.BuildSim, prefix, target, t_bucket=20, m_bucket=50):
    """시뮬레이터 내부 상태를 버킷으로 묶는다. 남은 질럿 수를 넣어 목표(N)를 조건으로 삼는다."""
    t = max(sim.t, 0)
    w, p, g, z = prefix.count(0), prefix.count(1), prefix.count(2), prefix.count(3)
    pylons_ready = sum(1 for c in sim.pylon_done if c <= t)
    gates_ready = sum(1 for c in sim.gate_ready if c <= t)
    zealots_started = sum(1 for s in sim.zealot_start if s <= t)
    minerals = int(sim.minerals_at(t)) // m_bucket
    return (target - z, w, p - pylons_ready, pylons_ready, g - gates_ready, gates_ready,
            z - zealots_started, minerals, t // t_bucket)


def q_learning(P, target, episodes, seed, allowed, state_fn=None, alpha=0.1, eps_start=0.3, eps_end=0.05,
               eval_every=10000, max_len=24):
    """시뮬레이터 위 표 형식 Q-learning. state_fn=None이면 history 상태."""
    rng = random.Random(seed)
    Q = defaultdict(float)
    curve = []

    def state_of(sim, prefix):
        return tuple(prefix) if state_fn is None else state_fn(sim, prefix, target)

    def run_episode(eps_greedy):
        sim = bs.BuildSim(P, target)
        prefix, traj = [], []
        while True:
            acts = allowed(prefix, target)
            s = state_of(sim, prefix)
            if not acts or len(prefix) >= max_len:
                return None, traj
            a = rng.choice(acts) if rng.random() < eps_greedy else max(acts, key=lambda b: Q[(s, b)])
            t_prev = max(sim.t, 0)
            t = sim.step(a)
            prefix.append(a)
            if t is None:
                traj.append((s, a, -1000, None, None))
                return None, traj
            if sim.end is not None:
                traj.append((s, a, -(sim.end - t_prev), None, None))
                return sim.end, traj
            nxt = state_of(sim, prefix)
            traj.append((s, a, -(t - t_prev), nxt, allowed(prefix, target)))

    for ep in range(1, episodes + 1):
        e = max(eps_end, eps_start * (1 - ep / (0.7 * episodes)))
        _, traj = run_episode(e)
        for s, a, r, nxt, nacts in traj:
            tv = r if nxt is None else r + (max(Q[(nxt, b)] for b in nacts) if nacts else -1000)
            Q[(s, a)] += alpha * (tv - Q[(s, a)])
        if ep % eval_every == 0 or ep == episodes:
            end_g, traj_g = run_episode(0.0)
            curve.append((ep, end_g if end_g is not None else float("nan")))
    end_g, traj_g = run_episode(0.0)
    seq = tuple(a for _, a, _, _, _ in traj_g)
    return end_g, seq, curve, len({s for s, _ in Q})


# --------------------------------------------------------------------------- 실행
def main():
    import argparse

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--targets", type=str, default="2,3,4,5,6,7,8", help="질럿 수 목록")
    ap.add_argument("--max-gates", type=int, default=3)
    ap.add_argument("--episodes", type=int, default=300000)
    ap.add_argument("--seeds", type=int, default=3)
    ap.add_argument("--eval-every", type=int, default=20000)
    ap.add_argument("--count-only", action="store_true", help="명령열 개수만 센다")
    ap.add_argument("--tag", type=str, default="", help="결과 파일 이름 뒤에 붙일 표시")
    args = ap.parse_args()
    targets = [int(x) for x in args.targets.split(",")]
    allowed = make_allowed(args.max_gates)
    P, refit = load_params()
    print("매개변수:", "다시 적합" if refit else "results/sim_params.csv", {k: P[k] for k in bs.FIT_PARAMS})

    logs, val = {}, {}
    for n in (2, 5):
        if n in targets:
            eps = bs.load(n)
            by = defaultdict(list)
            for ep in eps:
                by[ep["actions"]].append(ep["end_frame"])
            logs[n] = {o: statistics.fmean(v) for o, v in by.items()}
            val[n] = bs.validate(P, eps, n)

    lines = [f"# 질럿 N기 문제 (시뮬레이터: 질럿 2 로그로 적합, 게이트 최대 {args.max_gates}개)\n",
             "명령 코드: 0 일꾼, 1 파일런, 2 게이트, 3 질럿. 프레임 단위는 iteration(약 5.5 게임 루프).\n",
             "## N별 전수 최적 (시뮬레이터)\n",
             "| N | 명령열 수 | 전수 평가 시간 | 최적 명령열 | 예측 프레임 | 로그 실제 (해당 N) | 로그 최적 |",
             "|---|---|---|---|---|---|---|"]
    exhaustive = {}
    for n in targets:
        t0 = time.time()
        res, cnt = bs.exhaustive_sim(P, n, allowed=allowed, max_len=30)
        dt = time.time() - t0
        best_e, best_o = res[0]
        exhaustive[n] = (res, cnt)
        act = logs.get(n, {}).get(best_o)
        log_best = min(logs[n].items(), key=lambda kv: kv[1]) if n in logs else None
        act_s = "-" if n not in logs else ("로그에 없음" if act is None else f"{act:.1f}")
        lb_s = "-" if log_best is None else f"{list(log_best[0])} {log_best[1]:.1f}"
        print(f"N={n}: 명령열 {cnt}개 ({dt:.0f}초), 최적 {list(best_o)} 예측 {best_e}, 로그 {act_s}, 로그 최적 {lb_s}")
        lines.append(f"| {n} | {cnt} | {dt:.0f}초 | {list(best_o)} | {best_e} | {act_s} | {lb_s} |")
        if n in logs:
            v = val[n]
            lines.append("")
            lines.append(f"N={n} 로그에 있는 명령열 {v['n']}개만 평가: MAE {v['mae']:.1f}, 순위 상관 {v['spearman']:.3f}, "
                         f"로그 최적 {list(v['best_true'][0])} {v['best_true'][1]:.1f}의 예측 {v['best_true'][2]} (예측 {v['pred_rank_of_true_best']}위), "
                         f"로그 안 예측 최적 {list(v['best_pred'][0])} {v['best_pred'][1]} → 실제 {v['best_pred'][2]:.1f} (실제 {v['true_rank_of_pred_best']}위). "
                         + ("질럿 2 로그의 열거 규칙은 위 표의 규칙(질럿 5용)과 달라 전수 최적 명령열이 로그에 없을 수 있다." if n == 2 else ""))
            # 시뮬레이터 상위 5개의 실제 순위
            true_rank = sorted(logs[n], key=logs[n].get)
            lines.append("")
            lines.append(f"N={n} 시뮬레이터 상위 5개의 실제 순위: " + ", ".join(
                f"{list(o)} 예측 {e} 실제 {logs[n].get(o, float('nan')):.1f} ({true_rank.index(o) + 1 if o in logs[n] else '없음'}위)"
                for e, o in res[:5]))
            lines.append("")
            lines.append("| N | 명령열 수 | 전수 평가 시간 | 최적 명령열 | 예측 프레임 | 로그 실제 (해당 N) | 로그 최적 |")
            lines.append("|---|---|---|---|---|---|---|")
    if args.count_only:
        print("\n".join(lines))
        return

    lines.append("\n## N별 Q-learning (시뮬레이터 환경)\n")
    lines.append(f"{args.seeds}개 시드, {args.episodes} 에피소드, 보상 −소요 프레임, γ=1, 학습률 0.1, 열거 규칙으로 행동 마스킹. "
                 "history = 명령열 상태. compact = (남은 질럿, 일꾼 명령 수, 건설 중 파일런, 완성 파일런, 건설 중 게이트, "
                 "완성 게이트, 대기 중 질럿, 미네랄//50, 시각//20).\n")
    lines.append("| N | 전수 최적 | 상태 | 상태 수 | 학습 정책 명령열 | 예측 프레임 | 최적 도달 시드 | 처음 최적 도달 에피소드 (시드별) | 시드당 시간 |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    curves_out = []
    for n in targets:
        best_e = exhaustive[n][0][0][0]
        for sname, sfn in (("history", None), ("compact", compact_state)):
            seqs, ends, nstates, firsts, times = [], [], [], [], []
            for sd in range(args.seeds):
                t0 = time.time()
                end_g, seq, curve, ns = q_learning(P, n, args.episodes, sd, allowed, state_fn=sfn, eval_every=args.eval_every)
                times.append(time.time() - t0)
                seqs.append(seq)
                ends.append(end_g)
                nstates.append(ns)
                first = next((ep for ep, c in curve if c == c and c <= best_e), None)
                firsts.append(first)
                curves_out.append((n, sname, sd, curve))
            hits = sum(1 for e in ends if e is not None and e <= best_e)
            from collections import Counter
            seq_c = Counter(seqs).most_common(1)[0][0]
            end_c = Counter(ends).most_common(1)[0][0]
            print(f"N={n} {sname}: 정책 {list(seq_c)} 예측 {end_c}, 최적 도달 {hits}/{args.seeds}, 상태 {statistics.fmean(nstates):.0f}, "
                  f"처음 도달 {firsts}, {statistics.fmean(times):.0f}초/시드")
            lines.append(f"| {n} | {best_e} | {sname} | {statistics.fmean(nstates):.0f} | {list(seq_c)} | {end_c} | {hits}/{args.seeds} | "
                         f"{', '.join('-' if f is None else str(f) for f in firsts)} | {statistics.fmean(times):.0f}초 |")

    with open(OUT_DIR / f"zealot_n_curves{args.tag}.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["target", "state", "seed", "episode", "greedy_end_frame"])
        for n, sname, sd, curve in curves_out:
            for ep, c in curve:
                w.writerow([n, sname, sd, ep, c])
    out = OUT_DIR / f"zealot_n_results{args.tag}.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("저장:", out)


if __name__ == "__main__":
    main()
