"""라이브 어시스턴트 v2 실행. py -X utf8 bridge/live_run.py --backend bwapi-win [--intent-file ...] [--opening 0,0,0,0,1]

틱(기본 12프레임 ≈ 0.5초)마다 관측 → 입력 → 편차 → 재계획 → 발행 → 로그(bridge/results/live/<시각>.jsonl).
채팅: z3 d2 t1 k2 w2 p g2 n a c i r | r 200 50 | wt 24 | s | cancel | rebalance
"""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sc1_sim as ss  # noqa: E402
from live.client import LiveClient  # noqa: E402
from live.controller import Controller  # noqa: E402
from live.eventlog import EventLog  # noqa: E402
from live.intents import IntentFile, Intent  # noqa: E402

ROOT = Path(__file__).resolve().parent


def load_backends():
    for name in ("backends.json", "backends.example.json"):
        p = ROOT / name
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    return {}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--backend", default="bwapi-win")
    ap.add_argument("--intent-file", default=None)
    ap.add_argument("--tick-frames", type=int, default=12)
    ap.add_argument("--beam", type=int, default=800)
    ap.add_argument("--opening", default="0,0,0,0,1", help="게임 초반(프레임<600, 일꾼 4)이면 고정 오프닝. none 이면 없음")
    args = ap.parse_args()

    P = dict(ss.DEFAULT_PARAMS)
    pp = ROOT / "results" / "sc1_sim_params.json"
    if pp.exists():
        P.update(json.loads(pp.read_text(encoding="utf-8")))
    cfg = load_backends().get(args.backend, {})
    log = lambda s: print(f"[{time.strftime('%H:%M:%S')}] {s}", flush=True)
    # 게임보다 먼저 띄워 두면 포트가 열리는 즉시 붙는다 (0.25초 간격). 첫 일꾼 요청까지의 지연을 없앤다
    announced = False
    while True:
        try:
            client = LiveClient(cfg.get("host", "127.0.0.1"), int(cfg.get("port", 15800)), timeout=float(cfg.get("timeout", 30)))
            break
        except OSError:
            if not announced:
                log("실행기 대기 중 (게임이 뜨면 바로 붙는다)")
                announced = True
            time.sleep(0.25)
    ev = EventLog(ROOT / "results" / "live" / f"{time.strftime('%Y%m%d-%H%M%S')}.jsonl")
    ctrl = Controller(client, P, log=log, eventlog=ev, beam=args.beam)
    files = IntentFile(args.intent_file)
    snap = client.observe()
    log(f"실행기 {client.info.get('backend')} 라이브 v2. 프레임 {snap['frame']} 미네랄 {snap['minerals']} 일꾼 {snap['workers']['total']}")
    if args.opening.lower() != "none" and snap["frame"] < 600 and snap["workers"]["total"] <= 4:
        for a in [int(x) for x in args.opening.split(",") if x.strip()]:
            client.request(a)
        log(f"[오프닝] 고정 명령열 {args.opening} 요청")
    try:
        while True:
            t0 = time.time()
            ctrl.tick(files.poll())
            # 틱 간격: 게임 프레임 기준이 아니라 벽시계로 맞춘다 (보통 속도 ≈ 24프레임/초)
            time.sleep(max(0.0, args.tick_frames / 24.0 - (time.time() - t0)))
    except KeyboardInterrupt:
        pass
    finally:
        ev.write("game_end", ctrl.snap["frame"] if ctrl.snap else -1)
        ev.close()
        client.close()


if __name__ == "__main__":
    main()
