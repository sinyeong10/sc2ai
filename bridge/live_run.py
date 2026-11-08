"""라이브 어시스턴트 v2 실행. py -X utf8 bridge/live_run.py --backend bwapi-win [--intent-file ...] [--opening 0,0,0,0,1]

틱(기본 12프레임 ≈ 0.5초)마다 관측 → 입력 → 편차 → 재계획 → 발행 → 로그(bridge/results/live/<시각>.jsonl).
채팅: z3 d2 t1 k2 w2 p g2 n a c i r f uw ua us | r 200 50 | wt 24 | s | cancel | rebalance | attack | rally [auto|off]

제어 루프를 다시 켜도 같은 게임이면 큐·현재 목표·예비·일꾼 목표를 이어 받는다(--state-file). 이어 받으면 오프닝·시작 목표는 넣지 않는다.
게임이 끝날 때마다 최근 로그로 계획기 상수를 재보정해(--refit-last) 다음 게임 시작 때 적용한다(--live-params).
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
from live import refit  # noqa: E402

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
    ap.add_argument("--status-file", default=str(ROOT / "results" / "live_status.json"), help="음성 게이트웨이가 읽는 상태 파일")
    ap.add_argument("--start-goals", default="dragoon:10",
                    help="새 게임 시작 때 오프닝 뒤 큐에 넣을 목표. 예 dragoon:10,zealot:4. none 이면 없음 (적 첫 공격 전 대비)")
    ap.add_argument("--state-file", default=str(ROOT / "results" / "live_state.json"), help="제어 루프 상태 저장·복원. none 이면 안 함")
    ap.add_argument("--live-params", default=str(ROOT / "results" / "live_params.json"), help="재보정 상수. none 이면 기본값")
    ap.add_argument("--refit-last", type=int, default=40, help="게임이 끝날 때 최근 N개 로그로 재보정. 0 이면 안 함")
    args = ap.parse_args()

    P = dict(ss.DEFAULT_PARAMS)
    pp = ROOT / "results" / "sc1_sim_params.json"
    if pp.exists():
        P.update(json.loads(pp.read_text(encoding="utf-8")))
    cfg = load_backends().get(args.backend, {})
    log = lambda s: print(f"[{time.strftime('%H:%M:%S')}] {s}", flush=True)
    files = IntentFile(args.intent_file)
    # 게임이 끝나도 종료하지 않는다: 게임 프로세스가 내려가면(연결 끊김) 다시 기다리고, 같은 프로세스에서 새 게임이 시작되면
    # (프레임이 되돌아감 / 실행기가 라이브 모드가 아님) 라이브 모드를 다시 켠다. 사람이 게임만 다시 띄우면 바로 이어진다.
    try:
        while True:
            reason = run_session(args, cfg, P, files, log)
            log(f"[세션 종료] {reason} → 다음 게임을 기다린다")
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass


def run_session(args, cfg, P, files, log):
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
    if args.live_params.lower() != "none":
        changes = refit.apply_params(args.live_params, P)
        if changes:
            log(f"[재보정 적용] {', '.join(changes)}")
    state_file = None if args.state_file.lower() == "none" else args.state_file
    ctrl = Controller(client, P, log=log, eventlog=ev, beam=args.beam, status_file=args.status_file, state_file=state_file)
    reason = "?"
    try:
        snap = client.observe()
        log(f"실행기 {client.info.get('backend')} 라이브 v2. 프레임 {snap['frame']} 미네랄 {snap['minerals']} 일꾼 {snap['workers']['total']}"
            f" 게임 {snap.get('game_id', '?')}")
        ctrl.snap = snap
        restored = ctrl.restore_state(snap)
        if not restored and args.opening.lower() != "none" and snap["frame"] < 600 and snap["workers"]["total"] <= 4:
            for a in [int(x) for x in args.opening.split(",") if x.strip()]:
                client.request(a)
            log(f"[오프닝] 고정 명령열 {args.opening} 요청")
        if not restored and args.start_goals.lower() != "none" and snap["frame"] < 600 and snap["workers"]["total"] <= 4:
            for item in args.start_goals.split(","):
                if ":" in item:
                    unit, n = item.split(":")
                    ctrl.handle(Intent("produce", unit.strip(), int(n), source="start", raw=item.strip()))
        last_frame = snap["frame"]
        while True:
            t0 = time.time()
            ctrl.tick(files.poll())
            f = ctrl.snap["frame"]
            if f + 100 < last_frame or not ctrl.snap.get("live", True):
                reason = f"새 게임 감지 (프레임 {last_frame} → {f})"
                break
            last_frame = f
            # 틱 간격: 게임 프레임 기준이 아니라 벽시계로 맞춘다 (보통 속도 ≈ 24프레임/초)
            time.sleep(max(0.0, args.tick_frames / 24.0 - (time.time() - t0)))
    except (OSError, ConnectionError, RuntimeError, KeyError) as e:
        reason = f"연결 끊김 ({e.__class__.__name__}: {e})"
    finally:
        ev.write("game_end", ctrl.snap["frame"] if ctrl.snap else -1, reason=reason)
        ev.close()
        try:
            client.close()
        except Exception:
            pass
    if args.refit_last > 0 and args.live_params.lower() != "none":
        try:
            new, _ = refit.run(refit.recent_logs(str(ROOT / "results" / "live" / "*.jsonl"), args.refit_last),
                               ROOT / "results" / "live_refit.md", args.live_params, write=True, verbose=False)
            log(f"[재보정] 최근 로그 {args.refit_last}개 → {args.live_params}: {json.dumps(new, ensure_ascii=False)}")
        except Exception as e:  # 재보정 실패가 다음 게임을 막으면 안 된다
            log(f"[재보정 실패] {e.__class__.__name__}: {e}")
    return reason

if __name__ == "__main__":
    main()
