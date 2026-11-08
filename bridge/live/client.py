"""실행기 v2 클라이언트. 라이브 모드 전용: 어떤 호출도 게임을 멈추지 않는다.

observe()  → 스냅샷 dict (실행기 snapshotJson)
request(a) → {"accepted": bool, "request_id": int, "reason": str}
cancel(request_id=None) → 지운 queued 요청 수
reserve / hud / rebalance / poll_inbox 는 v1 과 같다.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from env import RemoteBackend  # noqa: E402


class LiveClient(RemoteBackend):
    def __init__(self, host="127.0.0.1", port=15800, timeout=30.0):
        super().__init__(host, port, timeout=timeout)
        if not self.info.get("live_v2"):
            raise RuntimeError(f"실행기가 라이브 v2(request/observe)를 지원하지 않는다: {self.info}")
        self.reset(10**6, live=True, restart=False)

    def observe(self) -> dict:
        m = self._call({"type": "observe"})
        if m.get("type") != "snapshot":
            raise RuntimeError(f"observe 응답 이상: {m}")
        return m

    def request(self, action: int) -> dict:
        m = self._call({"type": "request", "action": int(action)})
        return {"accepted": bool(m.get("accepted")), "request_id": m.get("request_id", m.get("id")), "reason": m.get("reason", "")}

    def cancel(self, request_id=None) -> int:
        msg = {"type": "cancel"}
        if request_id is not None:
            msg["request_id"] = int(request_id)
        m = self._call(msg)
        return int(m.get("cancelled", 0))

    def debug(self, op, **args) -> dict:
        """시험용: 사람 행동 흉내 (spend / cancel_building / attack_own)."""
        return self._call({"type": "debug", "op": op, **args})

    def army(self, op="attack") -> dict:
        """전체 병력 명령 (attack: 적 본진으로 공격 이동)."""
        return self._call({"type": "army", "op": op})
