"""학습용 이벤트 로그. 게임마다 JSON 줄 파일 하나. 이벤트: observe / intent / plan / request / result / deviation / goal / game_end."""
from __future__ import annotations

import json
import time
from pathlib import Path


class EventLog:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.f = open(self.path, "a", encoding="utf-8")

    def write(self, event: str, frame, **fields):
        rec = {"t": time.time(), "frame": frame, "event": event}
        rec.update(fields)
        self.f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
        self.f.flush()

    def close(self):
        try:
            self.f.close()
        except OSError:
            pass
