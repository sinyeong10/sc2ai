"""백엔드에 무관한 빌드 명령 환경.

AI 쪽 코드는 `make_env(...)`로 환경을 얻고 `reset(target)` / `step(action)`만 부른다.
어떤 게임이 어디서 돌아가는지는 설정(backends.json)으로 바꾼다.

  SimBackend     : offline_rl/build_sim.py 시뮬레이터. 같은 프로세스. 학습·시험용.
  RemoteBackend  : protocol.md의 JSON 줄 프로토콜로 TCP 너머 실행기에 명령.
                   실행기가 시뮬레이터 서버(executor_sim.py)든, BWAPI 1.16.1 DLL이든, OpenBW든,
                   python-sc2 봇이든 같은 코드다.

표준 라이브러리만 사용한다.
"""
from __future__ import annotations

import json
import socket
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "offline_rl"))

PROTOCOL_VERSION = 1
ACTION_NAMES = {0: "worker", 1: "pylon", 2: "gateway", 3: "zealot", 9: "end"}
DEFAULT_PORT = 15800


@dataclass
class Obs:
    frame: int
    iteration: int
    state: list            # [minerals, gas, supply_used, supply_cap, workers, nexus, tech, gateways, zealots, iteration]
    accepted: bool = True
    done: bool = False
    end_frame: int | None = None
    error: str | None = None
    extra: dict = field(default_factory=dict)

    def to_msg(self, msg_id):
        return {"type": "obs", "id": msg_id, "frame": self.frame, "iteration": self.iteration, "state": self.state,
                "accepted": self.accepted, "done": self.done, "end_frame": self.end_frame, "error": self.error,
                "extra": self.extra}

    @classmethod
    def from_msg(cls, m):
        return cls(m["frame"], m["iteration"], list(m["state"]), m.get("accepted", True), m.get("done", False),
                   m.get("end_frame"), m.get("error"), m.get("extra") or {})


class BuildEnv:
    """공통 인터페이스. 백엔드는 이 셋만 구현한다."""
    info: dict = {"backend": "?", "game": "?"}

    def reset(self, target: int, **kw) -> Obs:
        raise NotImplementedError

    def step(self, action: int) -> Obs:
        raise NotImplementedError

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


# --------------------------------------------------------------------------- 시뮬레이터 백엔드
class SimBackend(BuildEnv):
    """build_sim.BuildSim을 환경으로 감싼다. 관측 벡터는 SC2 로그 형식을 따른다."""

    def __init__(self, params=None):
        import build_sim as bs
        self.bs = bs
        if params is None:
            import zealot_n
            params, _ = zealot_n.load_params()
        self.P = params
        self.info = {"backend": "sim", "game": "sc2", "actions": {str(k): v for k, v in ACTION_NAMES.items() if k < 9},
                     "latency_frames": 0, "end_includes_lag": True}
        self.sim = None
        self.prefix: list[int] = []
        self.probe_done: list[float] = []

    def reset(self, target, **kw):
        self.sim = self.bs.BuildSim(self.P, target)
        self.target = target
        self.prefix, self.probe_done = [], []
        return self._obs(0)

    def _obs(self, t, accepted=True, error=None):
        sim, bs = self.sim, self.bs
        done = sim.end is not None
        if done:
            t = max(t, 0)
        gates_ready = sum(1 for c in sim.gate_ready if c <= t)
        pylons_ready = sum(1 for c in sim.pylon_done if c <= t)
        zealots_done = sum(1 for d in sim.zealot_done if d <= t)
        workers = bs.START_WORKERS + sum(1 for d in self.probe_done if d <= t)
        state = [int(sim.minerals_at(t)), 0, sim.used_at(t), sim.cap_at(t), workers, 1, 0,
                 len(sim.gate_ready), zealots_done, t]
        extra = {"gateways_ready": gates_ready, "pylons_ready": pylons_ready,
                 "zealots_in_production": len(sim.zealot_issue) - zealots_done, "prefix": list(self.prefix)}
        return Obs(t, t, state, accepted, done or not accepted, sim.end if done else None, error, extra)

    def step(self, action):
        if self.sim is None:
            raise RuntimeError("reset() 먼저")
        if action == 9:
            return self._obs(max(self.sim.t, 0), accepted=False, error="ended by agent")
        t = self.sim.step(action)
        if t is None:
            return self._obs(max(self.sim.t, 0), accepted=False, error=f"action {action} infeasible")
        self.prefix.append(action)
        if action == 0:
            self.probe_done.append(self.sim.nexus_free)
        return self._obs(t)


# --------------------------------------------------------------------------- 원격 백엔드
class RemoteBackend(BuildEnv):
    """TCP 너머 실행기. 실행기 종류는 hello 응답으로 안다."""

    def __init__(self, host="127.0.0.1", port=DEFAULT_PORT, timeout=60.0, on_wait=None, connect_timeout=10.0):
        self.host, self.port, self.timeout = host, port, timeout
        self.connect_timeout = connect_timeout
        self.on_wait = on_wait or (lambda m: None)
        self.next_id = 0
        self._connect()

    def _connect(self):
        self.sock = socket.create_connection((self.host, self.port), timeout=self.connect_timeout)
        self.sock.settimeout(self.timeout)
        self.rfile = self.sock.makefile("r", encoding="utf-8", newline="\n")
        hello = self._call({"type": "hello", "version": PROTOCOL_VERSION})
        if hello.get("type") != "hello" or hello.get("version") != PROTOCOL_VERSION:
            raise RuntimeError(f"실행기 hello 불일치: {hello}")
        self.info = {k: v for k, v in hello.items() if k not in ("type", "id")}

    def _reconnect(self, deadline):
        """실행기가 게임을 재시작하며 연결을 끊은 경우(모듈 재적재 등) 다시 붙는다. deadline(초)까지 재시도."""
        last = None
        while time.time() < deadline:
            try:
                self.sock.close()
            except OSError:
                pass
            try:
                self._connect()
                return
            except OSError as e:
                last = e
                time.sleep(1.0)
        raise ConnectionError(f"실행기에 다시 붙지 못했다: {last}")

    def _send(self, msg):
        self.sock.sendall((json.dumps(msg, ensure_ascii=False) + "\n").encode("utf-8"))

    def _call(self, msg, msg_id=None):
        if msg_id is None:
            msg_id = self.next_id
            self.next_id += 1
        msg["id"] = msg_id
        self._send(msg)
        while True:
            line = self.rfile.readline()
            if not line:
                raise ConnectionError("실행기가 연결을 끊었다")
            m = json.loads(line)
            if m.get("type") == "wait":
                self.on_wait(m)
                continue
            if m.get("type") == "error":
                if m.get("fatal"):
                    raise RuntimeError(f"실행기 오류: {m.get('message')}")
                return m
            if m.get("id") not in (None, msg_id):
                continue  # 이전 요청의 늦은 응답
            return m

    def reset(self, target, **kw):
        msg_id = self.next_id
        self.next_id += 1
        try:
            m = self._call({"type": "reset", "target": target, **kw}, msg_id=msg_id)
        except (ConnectionError, OSError):
            # 실행기가 게임을 재시작하며 끊었다(예: 모듈을 고정하지 못한 호스트). 다시 붙어 같은 id로 재전송한다
            self._reconnect(time.time() + self.timeout)
            m = self._call({"type": "reset", "target": target, **kw}, msg_id=msg_id)
        if m.get("type") == "error":
            raise RuntimeError(m.get("message"))
        return Obs.from_msg(m)

    def step(self, action, **kw):
        # action 8(대기)은 frames=N 을 함께 보낸다: N 프레임 뒤의 관측을 돌려준다 (측정·대기용)
        m = self._call({"type": "step", "action": int(action), **kw})
        if m.get("type") == "error":
            raise RuntimeError(m.get("message"))
        return Obs.from_msg(m)

    def status(self):
        return self._call({"type": "status"})

    def close(self):
        try:
            self._send({"type": "bye", "id": self.next_id})
        except OSError:
            pass
        try:
            self.sock.close()
        except OSError:
            pass


# --------------------------------------------------------------------------- 설정으로 고르기
def make_env(name="sim", config=None, **override) -> BuildEnv:
    """backends.json의 항목 이름으로 환경을 만든다. 이름이 없으면 name을 backend 종류로 본다."""
    cfg = {}
    candidates = [Path(config)] if config else [ROOT / "bridge" / "backends.json", ROOT / "bridge" / "backends.example.json"]
    for path in candidates:
        if path.exists():
            cfg = json.loads(path.read_text(encoding="utf-8"))
            break
    spec = dict(cfg.get(name) or {"backend": name})
    spec.update(override)
    kind = spec.pop("backend")
    spec.pop("note", None)
    if kind == "sim":
        return SimBackend(**spec)
    if kind == "remote":
        return RemoteBackend(**spec)
    raise ValueError(f"모르는 backend: {kind}")


def run_sequence(env: BuildEnv, target, seq):
    """명령열을 끝까지 실행해 (종료 프레임 또는 None, 관측 목록)을 돌려준다."""
    obs = [env.reset(target)]
    for a in seq:
        o = env.step(a)
        obs.append(o)
        if o.done:
            return o.end_frame, obs
    return None, obs
