"""명령열 하나를 실행기에 보내 에피소드를 돌리고 관측을 찍는다.

    py -X utf8 bridge/run_episode.py --backend bwapi-win --target 5 --seq 0,0,1,2,2,3,3,3,3,3
    py -X utf8 bridge/run_episode.py --backend sim --target 5 --seq 1,2,2,2,3,3,3,3,3 --repeat 3

행동: 0 일꾼, 1 파일런, 2 게이트, 3 질럿, 9 종료 (bridge/protocol.md).
--repeat 로 같은 명령열을 여러 번 돌려 종료 프레임 분산을 본다(결정론 검증).
"""
import argparse
import dataclasses
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from env import make_env, run_sequence  # noqa: E402

ACTION_NAMES = {0: "일꾼", 1: "파일런", 2: "게이트", 3: "질럿", 9: "종료"}


def fmt_obs(o):
    st = list(getattr(o, "state", []) or [])
    fields = []
    if len(st) >= 10:
        fields.append(f"미네랄 {st[0]:>5}  인구 {st[2]}/{st[3]}  일꾼 {st[4]}  게이트 {st[7]}  질럿 {st[8]}")
    return (f"frame {getattr(o, 'frame', None)!s:>6}  accepted={getattr(o, 'accepted', None)}  "
            f"done={getattr(o, 'done', None)}  " + "  ".join(fields))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--backend", default="sim", help="backends.json 의 이름 (sim, sim-remote, bwapi-win, openbw ...)")
    ap.add_argument("--target", type=int, default=5, help="질럿 목표 수")
    ap.add_argument("--seq", default="0,0,1,2,2,3,3,3,3,3", help="쉼표로 구분한 행동열")
    ap.add_argument("--repeat", type=int, default=1, help="같은 명령열 반복 횟수")
    ap.add_argument("--host", help="backends.json 의 host 를 덮어쓴다")
    ap.add_argument("--port", type=int, help="backends.json 의 port 를 덮어쓴다")
    ap.add_argument("--log", help="관측을 JSON 줄로 적을 파일")
    args = ap.parse_args()

    seq = [int(x) for x in args.seq.split(",") if x.strip()]
    override = {k: v for k, v in (("host", args.host), ("port", args.port)) if v is not None}
    env = make_env(args.backend, **override)
    log = open(args.log, "a", encoding="utf-8") if args.log else None

    ends = []
    for run in range(args.repeat):
        t0 = time.time()
        end, obs = run_sequence(env, args.target, seq)
        wall = time.time() - t0
        print(f"=== run {run + 1}/{args.repeat}  backend={args.backend}  target={args.target}  seq={seq}")
        for a, o in zip([None] + seq, obs):
            name = "reset" if a is None else f"{a} {ACTION_NAMES.get(a, '?')}"
            print(f"  {name:<10} {fmt_obs(o)}")
            if log:
                rec = {"run": run, "action": a, "obs": dataclasses.asdict(o) if dataclasses.is_dataclass(o) else vars(o)}
                log.write(json.dumps(rec, ensure_ascii=False) + "\n")
        print(f"  종료 프레임: {end}   ({wall:.1f}s)")
        ends.append(end)

    if args.repeat > 1:
        vals = [e for e in ends if e is not None]
        print(f"종료 프레임 {ends}")
        if vals:
            print(f"최소 {min(vals)}  최대 {max(vals)}  범위 {max(vals) - min(vals)}")
    if log:
        log.close()
    if hasattr(env, "close"):
        env.close()


if __name__ == "__main__":
    main()
