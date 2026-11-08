"""질럿 N기 최단 생산 명령열을 스타1 실게임에서 찾는다 (N=2..20).

    py -X utf8 bridge/solve_sc1.py --targets 2-20 --backend bwapi-win

흐름 (N 마다):
  1. 시뮬레이터(bridge/sc1_sim.py)를 지금까지의 실게임 데이터로 다시 적합한다.
  2. 시뮬레이터에서 빔 탐색(+작은 N 은 전수)으로 후보 상위 K 개를 뽑는다.
  3. 후보를 실게임에서 돌린다. 결정론이므로 이미 돌린 명령열은 데이터셋에서 읽는다.
  4. 실게임 최선의 이웃(교환·추가·제거)을 시뮬레이터로 걸러 실게임에서 몇 라운드 돌린다(국소 탐색).
  5. N 의 결과를 results/sc1_solutions.json + .md 에 바로 적는다.
모든 에피소드는 results/sc1_dataset.jsonl 에 남는다(명령열·실행 프레임·관측·종료 프레임).

게임이 죽거나 연결이 끊기면 포트가 다시 열릴 때까지 기다렸다가 이어서 한다(게임은 사람이 Start 로 띄운다).
"""
import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sc1_sim as ss  # noqa: E402
from dataset import Dataset  # noqa: E402
from env import make_env  # noqa: E402

ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
DLL_PATH = Path(r"C:\sin\StarCraft\bwapi-data\AI\BuildExecutor.dll")


def log(msg, fh=None):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    if fh:
        fh.write(line + "\n")
        fh.flush()


def executor_id():
    if DLL_PATH.exists():
        return hashlib.sha256(DLL_PATH.read_bytes()).hexdigest()[:12]
    return "unknown"


class RealRunner:
    """실게임 실행 + 데이터셋 캐시 + 재접속."""

    def __init__(self, backend, ds: Dataset, logfh, wait_max=3600):
        self.backend = backend
        self.ds = ds
        self.logfh = logfh
        self.wait_max = wait_max
        self.env = None
        self.episodes_run = 0

    def _connect(self):
        t0 = time.time()
        while True:
            try:
                self.env = make_env(self.backend)
                log(f"실행기 연결: {self.env.info}", self.logfh)
                return
            except OSError as e:
                if time.time() - t0 > self.wait_max:
                    raise
                if int(time.time() - t0) % 60 < 5:
                    log(f"실행기 대기 중({e.__class__.__name__}). 게임이 떠 있는지 확인(Chaoslauncher Start)", self.logfh)
                time.sleep(5)

    def run(self, target, seq):
        """(end_frame|None, cached) 를 돌려준다."""
        row = self.ds.get(target, seq)
        if row is not None:
            return row["end_frame"], True
        for attempt in range(5):
            if self.env is None:
                self._connect()
            try:
                t0 = time.time()
                obs = [self.env.reset(target)]
                for a in seq:
                    o = self.env.step(a)
                    obs.append(o)
                    if o.done or not o.accepted:
                        break
                last = obs[-1]
                end = last.end_frame if (last.done and last.accepted) else None
                steps = [{"action": None, "frame": obs[0].frame, "state": obs[0].state, "accepted": True}]
                for a, o in zip(seq, obs[1:]):
                    steps.append({"action": a, "frame": o.frame, "state": o.state, "accepted": o.accepted})
                self.ds.add(target, seq, end, steps, wall=round(time.time() - t0, 1))
                self.episodes_run += 1
                return end, False
            except (OSError, RuntimeError) as e:
                log(f"에피소드 실패({e}). 재접속 {attempt + 1}/5", self.logfh)
                try:
                    self.env.close()
                except Exception:
                    pass
                self.env = None
                time.sleep(3)
        raise RuntimeError("실게임 실행을 반복해서 실패했다")


def refit(ds, P_prev, logfh):
    data = ds.episodes()
    if not data:
        return dict(ss.DEFAULT_PARAMS), float("nan")
    P, err = ss.fit(data, P0=P_prev)
    err2, by_a = ss.loss(P, data, per_action=True)
    detail = " ".join(f"{k}:{sum(abs(x) for x in v) / len(v):.0f}" for k, v in sorted(by_a.items(), key=lambda kv: str(kv[0])))
    log(f"시뮬레이터 적합: 에피소드 {len(data)}개, 평균 절대 오차 {err:.1f} 프레임 (행동별 {detail})", logfh)
    return P, err


def calibration_sequences():
    """0단계: 시뮬레이터 초기 적합용 다양한 짧은 명령열 (N=2~4)."""
    seqs = []
    for w in (0, 1, 2, 4):
        seqs.append([0] * w + [1, 2, 3, 3])
        seqs.append([0] * w + [1, 2, 2, 3, 3, 3])
        seqs.append([0] * w + [1, 2, 3, 3, 3, 3])
    seqs.append([1, 2, 3, 1, 3, 3, 3])
    seqs.append([0, 0, 0, 0, 0, 0, 1, 2, 2, 3, 3, 3, 3])
    seqs.append([0, 1, 0, 2, 0, 3, 3, 3])
    seqs.append([1, 0, 0, 2, 2, 2, 3, 3, 3, 3])
    seqs.append([0, 0, 1, 2, 2, 3, 3, 3, 3, 3])
    return seqs


def solve_target(target, P, runner, logfh, args):
    t_start = time.time()
    ep0 = runner.episodes_run
    max_gates = max(1, min(args.max_gates, (target + 1) // 2))
    # 1) 시뮬레이터 후보
    top, nfin = ss.beam_search(P, target, width=args.beam, max_gates=max_gates, max_workers=args.max_workers,
                               topk=args.topk)
    if target <= args.exhaustive_upto:
        ex, cnt = ss.exhaustive(P, target, max_gates, args.max_workers)
        log(f"N={target}: 전수 {cnt}개 (최선 {ex[0][0] if ex else None}) vs 빔 {nfin}개 (최선 {top[0][0] if top else None})", logfh)
        seen = {s for _, s in top}
        for e, s in ex[:args.topk]:
            if s not in seen:
                top.append((e, s))
    # 같은 예측·같은 구성(일꾼/파일런/게이트 수)의 변형은 하나만 두어 후보를 다양하게 한다
    seen_groups, diverse, rest = set(), [], []
    for e, s in top:
        key = (e, s.count(0), s.count(1), s.count(2))
        (diverse if key not in seen_groups else rest).append((e, s))
        seen_groups.add(key)
    top = (diverse + rest)[:args.topk]
    log(f"N={target}: 시뮬레이터 후보 {len(top)}개, 예측 최선 {top[0][0] if top else None} {list(top[0][1]) if top else None}", logfh)
    # 2) 실게임 평가
    evaluated = {}  # seq tuple -> end
    for pred, seq in top:
        end, cached = runner.run(target, list(seq))
        evaluated[tuple(seq)] = end
        log(f"  후보 예측 {pred:>6} → 실게임 {end!s:>6} {'(캐시)' if cached else ''} {list(seq)}", logfh)
    best_seq, best_end = min(((s, e) for s, e in evaluated.items() if e is not None), key=lambda x: x[1], default=(None, None))
    # 3) 국소 탐색
    for rnd in range(args.local_rounds):
        if best_seq is None:
            break
        nb = ss.neighbors(best_seq, target, args.max_workers, max_gates)
        scored = []
        for s in nb:
            if tuple(s) in evaluated:
                continue
            _, pend = ss.simulate(s, P, target)
            if pend is not None:
                scored.append((pend, tuple(s)))
        scored.sort()
        picks = [s for _, s in scored[:args.local_k]]
        if not picks:
            break
        improved = False
        for s in picks:
            end, cached = runner.run(target, list(s))
            evaluated[s] = end
            if end is not None and end < best_end:
                best_seq, best_end, improved = s, end, True
        log(f"  국소 탐색 {rnd + 1}: 이웃 {len(picks)}개 → 최선 {best_end} {list(best_seq)}{' (개선)' if improved else ''}", logfh)
        if not improved:
            break
    n_ep = runner.episodes_run - ep0
    rec = {"target": target, "best_seq": list(best_seq) if best_seq else None, "best_end": best_end,
           "sim_pred_best": top[0][0] if top else None, "sim_best_seq": list(top[0][1]) if top else None,
           "episodes_new": n_ep, "episodes_evaluated": len(evaluated),
           "candidates": sorted(([e, list(s)] for s, e in evaluated.items() if e is not None), key=lambda x: x[0])[:30],
           "params": P, "wall": round(time.time() - t_start, 1)}
    log(f"N={target} 결과: 종료 {best_end} 명령열 {rec['best_seq']} (실게임 새 에피소드 {n_ep}개, {rec['wall']}s)", logfh)
    return rec


def write_results(records, path_json, path_md):
    path_json.write_text(json.dumps(records, ensure_ascii=False, indent=1), encoding="utf-8")
    lines = ["# 스타1 질럿 N기 최단 생산 (실게임, 1.16.1 + BWAPI 4.4.0, UMS 맵, seed 12345)", "",
             "행동: 0 일꾼, 1 파일런, 2 게이트, 3 질럿. 종료 = N기째 질럿 완성 프레임. 모든 에피소드는 `sc1_dataset.jsonl`.", "",
             "| N | 종료 프레임 | 명령열 | 일꾼/파일런/게이트 | 시뮬 예측(최선) | 실게임 평가 수 |", "|---|---|---|---|---|---|"]
    for r in records:
        s = r["best_seq"] or []
        lines.append(f"| {r['target']} | {r['best_end']} | `{','.join(map(str, s))}` | {s.count(0)}/{s.count(1)}/{s.count(2)} | "
                     f"{r['sim_pred_best']} | {r['episodes_evaluated']} |")
    path_md.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--targets", default="2-20")
    ap.add_argument("--backend", default="bwapi-win")
    ap.add_argument("--map", default="(2)Astral Balance UMS.scm")
    ap.add_argument("--seed", type=int, default=12345)
    ap.add_argument("--beam", type=int, default=3000)
    ap.add_argument("--topk", type=int, default=12)
    ap.add_argument("--max-gates", type=int, default=6)
    ap.add_argument("--max-workers", type=int, default=20, help="추가 일꾼 상한(시작 4 제외). 기본 20 = 덩이당 3기")
    ap.add_argument("--exhaustive-upto", type=int, default=6)
    ap.add_argument("--local-rounds", type=int, default=3)
    ap.add_argument("--local-k", type=int, default=10)
    ap.add_argument("--skip-calibration", action="store_true")
    ap.add_argument("--dataset", default=str(RESULTS / "sc1_dataset.jsonl"))
    ap.add_argument("--tag", default="")
    args = ap.parse_args()

    if "-" in args.targets:
        a, b = args.targets.split("-")
        targets = list(range(int(a), int(b) + 1))
    else:
        targets = [int(x) for x in args.targets.split(",")]

    RESULTS.mkdir(exist_ok=True)
    logfh = open(RESULTS / f"solve_sc1{args.tag}.log", "a", encoding="utf-8")
    ctx = {"map": args.map, "seed": args.seed, "executor": executor_id()}
    ds = Dataset(args.dataset, context=ctx)
    log(f"데이터셋 {args.dataset}: {len(ds)}행, 문맥 {ctx}", logfh)
    runner = RealRunner(args.backend, ds, logfh)

    if not args.skip_calibration:
        for seq in calibration_sequences():
            # 시뮬레이터가 실행 불가(인구·자원이 영원히 안 됨)로 보는 명령열은 실게임에 보내지 않는다
            _, pend = ss.simulate(seq, ss.DEFAULT_PARAMS, seq.count(3))
            if pend is None:
                log(f"보정 {seq} 건너뜀: 시뮬레이터에서 실행 불가", logfh)
                continue
            end, cached = runner.run(seq.count(3), seq)
            log(f"보정 {seq} → {end} {'(캐시)' if cached else ''}", logfh)

    P, _ = refit(ds, None, logfh)
    path_json = RESULTS / f"sc1_solutions{args.tag}.json"
    path_md = RESULTS / f"sc1_solutions{args.tag}.md"
    records = json.loads(path_json.read_text(encoding="utf-8")) if path_json.exists() else []
    done = {r["target"] for r in records}
    for target in targets:
        if target in done:
            log(f"N={target} 이미 있음, 건너뜀", logfh)
            continue
        rec = solve_target(target, P, runner, logfh, args)
        records.append(rec)
        records.sort(key=lambda r: r["target"])
        write_results(records, path_json, path_md)
        P, _ = refit(ds, P, logfh)
    (RESULTS / "sc1_sim_params.json").write_text(json.dumps(P, indent=1), encoding="utf-8")
    log(f"끝. 실게임 새 에피소드 {runner.episodes_run}개, 데이터셋 {len(ds)}행", logfh)


if __name__ == "__main__":
    main()
