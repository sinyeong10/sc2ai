"""일꾼 수별 미네랄 채취율을 실게임에서 잰다.

    py -X utf8 bridge/measure_income.py --backend bwapi-win --workers 4,6,8,10,12,14,16,18,20,22,24 --window 2000

일꾼 k 기: 시작 4 + (k-4) 생산(인구가 모자라면 파일런을 먼저). 마지막 일꾼이 채취를 시작하고도 settle 프레임을 더 기다린 뒤,
window 프레임 동안의 미네랄 증가량으로 채취율(미네랄/프레임)을 구한다. 그 사이 아무것도 쓰지 않는다.
결과: results/income_by_workers.csv, .md, 원시 관측은 results/income_raw.jsonl.
"""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from env import make_env  # noqa: E402

RESULTS = Path(__file__).resolve().parent / "results"
PROBE_FRAMES = 300  # 프로브 생산 시간(추정). 마지막 일꾼이 채취를 시작하기까지 settle 로 더 기다린다
PYLON_LEAD = 3      # 한도까지 이만큼 남았을 때 파일런을 먼저 넣는다 (파일런 590 ≈ 일꾼 2기 300×2)


def build_sequence(k, first_pylon_at=6):
    """일꾼 k기(시작 4 포함)를 만드는 명령열. 인구 9 → 파일런마다 +8.
    첫 파일런은 일꾼 first_pylon_at 기일 때(6·7·8 중 하나: 초반엔 미네랄 100이 없을 수 있어 비교한다),
    둘째부터는 한도까지 PYLON_LEAD 자리 남았을 때(14/17) 넣는다."""
    seq = []
    workers, cap = 4, 9
    while workers < k:
        need_pylon = k > cap and ((cap == 9 and workers == first_pylon_at) or (cap > 9 and cap - workers <= PYLON_LEAD))
        if need_pylon:
            seq.append(1)
            cap += 8
        seq.append(0)
        workers += 1
    return seq


def measure(env, k, settle, window, raw, first_pylon_at=6):
    seq = build_sequence(k, first_pylon_at)
    obs0 = env.reset(1)  # 목표는 무의미(질럿 안 만듦). 에피소드는 reset 으로 끊는다
    frames = []
    for a in seq:
        o = env.step(a)
        frames.append(o.frame)
        if not o.accepted:
            raise RuntimeError(f"k={k}: 명령 {a} 거부 {o.error}")
    # 마지막 일꾼 완성 + 채취 시작까지 기다린다. 넥서스 큐에 몰린 만큼 더
    pending = min(5, seq.count(0))
    o1 = env.step(8, frames=pending * PROBE_FRAMES + settle)
    m0, f0, w0 = o1.state[0], o1.frame, o1.state[4]
    o2 = env.step(8, frames=window)
    m1, f1, w1 = o2.state[0], o2.frame, o2.state[4]
    rate = (m1 - m0) / (f1 - f0)
    row = {"k": k, "first_pylon_at": first_pylon_at if k > 9 else None, "seq": seq, "cmd_frames": frames, "f0": f0, "m0": m0, "w0": w0, "f1": f1, "m1": m1, "w1": w1,
           "rate": rate, "per_worker": rate / k}
    raw.write(json.dumps(row, ensure_ascii=False) + "\n")
    raw.flush()
    if w0 != k or w1 != k:
        row["note"] = f"일꾼 수 불일치 {w0}/{w1} (기대 {k})"
    return row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", default="bwapi-win")
    ap.add_argument("--workers", default="4-24", help="예: 4-24 또는 4,8,12")
    ap.add_argument("--settle", type=int, default=400)
    ap.add_argument("--window", type=int, default=2000)
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--tag", default="", help="결과 파일 이름 뒤에 붙일 표시 (예: _w6000)")
    args = ap.parse_args()
    if "-" in args.workers:
        lo, hi = args.workers.split("-")
        ks = list(range(int(lo), int(hi) + 1))
    else:
        ks = [int(x) for x in args.workers.split(",")]
    RESULTS.mkdir(exist_ok=True)
    env = make_env(args.backend)
    print("실행기:", env.info, flush=True)
    rows = []
    with open(RESULTS / f"income_raw{args.tag}.jsonl", "a", encoding="utf-8") as raw:
        all_rows = []
        for k in ks:
            variants = [6, 7, 8] if k > 9 else [6]
            best = None
            for fp in variants:
                t0 = time.time()
                row = measure(env, k, args.settle, args.window, raw, fp)
                all_rows.append(row)
                print(f"k={k:>2} 첫파일런@{fp if k > 9 else '-'}: {row['rate']:.4f} 미네랄/프레임, 일꾼당 {row['per_worker']:.4f}  "
                      f"준비 {row['f0'] - args.settle} (프레임 {row['f0']}→{row['f1']}, 미네랄 {row['m0']}→{row['m1']}, {time.time() - t0:.1f}s) "
                      f"{row.get('note', '')}", flush=True)
                if best is None or row["f0"] < best["f0"]:
                    best = row
            rows.append(best)
    env.close()
    # 표
    lines = ["k,pylons,first_pylon_at,cost,t_ready,rate,per_worker,marginal,payback_frames,f0,f1,m0,m1,note"]
    md = ["# 일꾼 수별 채취율 (실게임, Astral Balance UMS, 미네랄 8덩이)", "",
          f"측정 창 {args.window} 프레임, 안정화 {args.settle} 프레임. 한계 수익 = 직전 k 대비 증가분 / 일꾼 증가 수.", "",
          "t_ready = 마지막 일꾼 명령 프레임 + 생산 시간(넥서스 큐 포함) 추정, 회수 = 추가 비용(일꾼 50 + 그 구간 파일런 100) / 한계 수익.", "",
          "| 일꾼 k | 파일런 | 첫 파일런 시점(일꾼) | 누적 비용 | 준비 시점(프레임) | 채취율 (미네랄/프레임) | 일꾼당 | 한계 수익(1기당) | 회수(프레임) | 덩이당 | 비고 |",
          "|---|---|---|---|---|---|---|---|---|---|---|"]
    prev = None
    for row in rows:
        pylons = row["seq"].count(1)
        cost = 50 * row["seq"].count(0) + 100 * pylons
        t_ready = row["f0"] - args.settle  # 측정 시작 = 준비 시점 추정
        marg, payback = "", ""
        if prev and row["k"] > prev["k"]:
            dr = (row["rate"] - prev["rate"]) / (row["k"] - prev["k"])
            marg = f"{dr:.4f}"
            dcost = (cost - prev["cost"]) / (row["k"] - prev["k"])
            payback = f"{dcost / dr:.0f}" if dr > 1e-6 else "∞"
        row["cost"] = cost
        lines.append(f"{row['k']},{pylons},{row.get('first_pylon_at') or ''},{cost},{t_ready},{row['rate']:.5f},{row['per_worker']:.5f},{marg},{payback},{row['f0']},{row['f1']},{row['m0']},{row['m1']},{row.get('note', '')}")
        md.append(f"| {row['k']} | {pylons} | {row.get('first_pylon_at') or '-'} | {cost} | {t_ready} | {row['rate']:.4f} | {row['per_worker']:.4f} | {marg} | {payback} | {row['k'] / 8:.2f} | {row.get('note', '')} |")
        prev = row
    md.append("")
    md.append("## 첫 파일런 시점 비교 (k > 9, 준비 시점 = 측정 시작 - 안정화)")
    md.append("")
    md.append("| 일꾼 k | 첫 파일런 6기 | 7기 | 8기 | 선택 |")
    md.append("|---|---|---|---|---|")
    by_k = {}
    for r in all_rows:
        if r.get("first_pylon_at"):
            by_k.setdefault(r["k"], {})[r["first_pylon_at"]] = r["f0"] - args.settle
    for k in sorted(by_k):
        v = by_k[k]
        pick = min(v, key=v.get)
        md.append(f"| {k} | {v.get(6, '')} | {v.get(7, '')} | {v.get(8, '')} | {pick}기 |")
    (RESULTS / f"income_by_workers{args.tag}.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (RESULTS / f"income_by_workers{args.tag}.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("저장:", RESULTS / f"income_by_workers{args.tag}.md")


if __name__ == "__main__":
    main()
