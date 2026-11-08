"""브리지 왕복 시험: SimBackend(직접)와 RemoteBackend(TCP → executor_sim)가 같은 결과를 내는지.

실행: python -X utf8 bridge/test_bridge.py
"""
from __future__ import annotations

import json
import socket
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from env import PROTOCOL_VERSION, RemoteBackend, SimBackend, make_env, run_sequence  # noqa: E402
import executor_sim  # noqa: E402

SEQS = {2: [1, 2, 2, 0, 0, 0, 0, 2, 3, 3], 5: [1, 2, 2, 2, 0, 3, 3, 3, 3, 3]}
EXPECT = {2: 581, 5: 722}


def start_server():
    bound = {}
    ev = threading.Event()

    def ready(b):
        bound["addr"] = b
        ev.set()

    th = threading.Thread(target=executor_sim.serve, args=(SimBackend, "127.0.0.1", 0),
                          kwargs={"log": lambda *a: None, "ready": ready}, daemon=True)
    th.start()
    ev.wait(5)
    return bound["addr"]


def main():
    fails = 0
    host, port = start_server()

    # 1. 직접 vs 원격, 같은 명령열 → 같은 종료 프레임·관측
    for target, seq in SEQS.items():
        with SimBackend() as direct, RemoteBackend(host, port) as remote:
            e1, o1 = run_sequence(direct, target, seq)
            e2, o2 = run_sequence(remote, target, seq)
        same = e1 == e2 == EXPECT[target] and [o.state for o in o1] == [o.state for o in o2]
        fails += not same
        print(f"[{'OK' if same else 'FAIL'}] N={target} 직접 {e1} 원격 {e2} (기대 {EXPECT[target]}), 관측 {len(o2)}개, 실행기 {remote.info['backend']}")

    # 2. 불가능한 명령 → accepted False, done True
    with RemoteBackend(host, port) as remote:
        remote.reset(2)
        o = remote.step(3)  # 게이트 없이 질럿
        ok = (not o.accepted) and o.done and o.error
        fails += not ok
        print(f"[{'OK' if ok else 'FAIL'}] 불가능한 명령: accepted={o.accepted} done={o.done} error={o.error}")

    # 3. 같은 id 재전송 → 명령이 두 번 실행되지 않고 같은 응답
    s = socket.create_connection((host, port))
    f = s.makefile("r", encoding="utf-8")

    def call(msg):
        s.sendall((json.dumps(msg) + "\n").encode())
        return json.loads(f.readline())

    call({"type": "hello", "version": PROTOCOL_VERSION, "id": 0})
    call({"type": "reset", "target": 2, "id": 1})
    a = call({"type": "step", "action": 1, "id": 2})
    b = call({"type": "step", "action": 1, "id": 2})
    c = call({"type": "step", "action": 2, "id": 3})
    ok = a == b and c["extra"]["prefix"] == [1, 2]
    fails += not ok
    print(f"[{'OK' if ok else 'FAIL'}] 재전송: 같은 응답 {a == b}, 접두사 {c['extra']['prefix']}")
    s.close()

    # 4. make_env 설정 경로
    env = make_env("sim")
    e, _ = run_sequence(env, 2, SEQS[2])
    ok = e == 581
    fails += not ok
    print(f"[{'OK' if ok else 'FAIL'}] make_env('sim') → {e}")

    print("실패", fails)
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
