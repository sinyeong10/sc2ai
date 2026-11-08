"""시뮬레이터를 실행기로 내놓는 서버. protocol.md v1.

용도:
  1. 다른 PC의 AI가 RemoteBackend로 붙어 학습하는 경로를 게임 없이 끝까지 시험한다.
  2. C++ 실행기(bridge/cpp)를 만들 때 따라야 할 참조 구현이다. 메시지 처리 순서가 같다.

실행:  python -X utf8 bridge/executor_sim.py --host 0.0.0.0 --port 15800
표준 라이브러리만 사용한다.
"""
from __future__ import annotations

import argparse
import json
import socket
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from env import PROTOCOL_VERSION, DEFAULT_PORT, BuildEnv, SimBackend  # noqa: E402


class LineConn:
    def __init__(self, sock):
        self.sock = sock
        self.rfile = sock.makefile("r", encoding="utf-8", newline="\n")

    def recv(self):
        line = self.rfile.readline()
        if not line:
            return None
        try:
            return json.loads(line)
        except json.JSONDecodeError as e:
            return {"type": "_bad", "message": str(e)}

    def send(self, msg):
        self.sock.sendall((json.dumps(msg, ensure_ascii=False) + "\n").encode("utf-8"))


def serve_connection(conn: LineConn, env: BuildEnv, log=print):
    """연결 하나를 끝까지 처리한다. 동기식 환경(step이 바로 돌아오는 것)용."""
    last = {}  # id -> 마지막 응답 (같은 id 재전송 시 다시 보냄)
    while True:
        m = conn.recv()
        if m is None:
            return
        t, mid = m.get("type"), m.get("id")
        if t == "_bad":
            conn.send({"type": "error", "id": mid, "message": f"JSON 오류: {m['message']}", "fatal": False})
            continue
        if mid in last and t in ("step", "reset"):
            conn.send(last[mid])
            continue
        if t == "hello":
            if m.get("version") != PROTOCOL_VERSION:
                conn.send({"type": "error", "id": mid, "message": f"version {PROTOCOL_VERSION} 필요", "fatal": True})
                return
            conn.send({"type": "hello", "id": mid, "version": PROTOCOL_VERSION, **env.info})
        elif t == "reset":
            try:
                obs = env.reset(int(m["target"]), **{k: v for k, v in m.items() if k in ("seed", "speed")})
                last[mid] = obs.to_msg(mid)
            except Exception as e:  # noqa: BLE001
                last[mid] = {"type": "error", "id": mid, "message": f"reset 실패: {e}", "fatal": False}
            conn.send(last[mid])
        elif t == "step":
            try:
                obs = env.step(int(m["action"]))
                last[mid] = obs.to_msg(mid)
            except Exception as e:  # noqa: BLE001
                last[mid] = {"type": "error", "id": mid, "message": f"step 실패: {e}", "fatal": False}
            conn.send(last[mid])
        elif t == "stop":
            # 시뮬레이터는 step 안에서 모두 끝나므로 중단할 진행이 없다. 다음 reset을 기다린다.
            conn.send({"type": "status", "id": mid, **env.info, "stopped": True})
        elif t == "status":
            conn.send({"type": "status", "id": mid, **env.info, "time": time.time()})
        elif t == "bye":
            return
        else:
            conn.send({"type": "error", "id": mid, "message": f"모르는 type {t}", "fatal": False})


def serve(env_factory, host="0.0.0.0", port=DEFAULT_PORT, log=print, ready=None, once=False):
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((host, port))
    srv.listen(4)
    bound = srv.getsockname()
    log(f"실행기(sim) 대기: {bound[0]}:{bound[1]}")
    if ready is not None:
        ready(bound)
    try:
        while True:
            s, addr = srv.accept()
            log(f"연결: {addr}")
            env = env_factory()

            def worker(s=s, addr=addr, env=env):
                try:
                    serve_connection(LineConn(s), env, log)
                finally:
                    env.close()
                    s.close()
                    log(f"종료: {addr}")

            if once:
                worker()
                return
            threading.Thread(target=worker, daemon=True).start()
    finally:
        srv.close()


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = ap.parse_args()
    serve(SimBackend, args.host, args.port)


if __name__ == "__main__":
    main()
