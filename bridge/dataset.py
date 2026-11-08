"""실게임 에피소드 데이터셋. JSON 줄, 추가만 한다.

실게임은 결정론이라(같은 맵·시드·실행기·목표·명령열 → 같은 결과) 한 번 돌린 명령열은 다시 돌리지 않고 여기서 읽는다.
행 하나 = 에피소드 하나:
  {"key": ..., "context": {"map":..., "seed":..., "executor":...}, "target": N, "seq": [...],
   "end_frame": int|null, "steps": [{"action": a, "frame": f, "state": [...10칸], "accepted": bool}, ...],
   "wall": 초, "time": ISO8601}
steps[0] 은 reset 관측(action null). 명령이 거부되면(accepted false) 그 뒤는 없고 end_frame 은 null.
"""
import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DEFAULT_PATH = ROOT / "results" / "sc1_dataset.jsonl"


def make_key(context, target, seq):
    c = context or {}
    return f"{c.get('map', '?')}|{c.get('seed', '?')}|{c.get('executor', '?')}|{target}|" + ",".join(map(str, seq))


class Dataset:
    def __init__(self, path=DEFAULT_PATH, context=None):
        self.path = Path(path)
        self.context = dict(context or {})
        self.rows = []
        self.index = {}
        if self.path.exists():
            with open(self.path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    row = json.loads(line)
                    self.rows.append(row)
                    self.index[row["key"]] = row

    def get(self, target, seq):
        return self.index.get(make_key(self.context, target, seq))

    def add(self, target, seq, end_frame, steps, wall=None, extra=None):
        row = {"key": make_key(self.context, target, seq), "context": dict(self.context), "target": int(target),
               "seq": [int(a) for a in seq], "end_frame": end_frame, "steps": steps, "wall": wall,
               "time": time.strftime("%Y-%m-%dT%H:%M:%S")}
        if extra:
            row["extra"] = extra
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        self.rows.append(row)
        self.index[row["key"]] = row
        return row

    def episodes(self, target=None, context_only=True):
        """시뮬레이터 적합용: [(target, seq, 명령 실행 프레임 목록, end_frame)]. 거부된 에피소드는 뺀다."""
        out = []
        for r in self.rows:
            if context_only and r["context"] != self.context:
                continue
            if target is not None and r["target"] != target:
                continue
            if r["end_frame"] is None:
                continue
            times = [s["frame"] for s in r["steps"][1:] if s.get("accepted", True)]
            if len(times) != len(r["seq"]):
                continue
            out.append((r["target"], tuple(r["seq"]), times, r["end_frame"]))
        return out

    def __len__(self):
        return len(self.rows)
