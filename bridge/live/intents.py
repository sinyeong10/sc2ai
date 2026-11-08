"""입력 → Intent. 채팅 한 줄(영문 약어)과 JSON 줄(의도 파일: 음성 인식기·Dialogflow 연동 자리)을 같은 꼴로 바꾼다."""
from __future__ import annotations

import dataclasses
import json
import re
from pathlib import Path

UNIT_WORDS = {
    "zealot": ("질럿", "zealot", "zeal", "z"),
    "dragoon": ("드라군", "dragoon", "goon", "d"),
    "high_templar": ("템플러", "하이템플러", "templar", "high", "ht", "t"),
    "dark_templar": ("다크", "다크템플러", "dark", "dt", "k"),
    "worker": ("일꾼", "프로브", "probe", "worker", "w"),
    "pylon": ("파일런", "pylon", "p"),
    "gateway": ("게이트", "게이트웨이", "gateway", "gate", "g"),
    "nexus": ("멀티", "넥서스", "nexus", "expand", "multi", "n"),
    "assimilator": ("가스", "어시밀레이터", "assimilator", "gas", "a"),
    "core": ("코어", "core", "cyber", "c"),
    "citadel": ("성채", "citadel", "i"),
    "forge": ("포지", "forge", "f"),
    "up_weapons": ("공업", "공격업", "weapons", "uw"),
    "up_armor": ("방업", "방어업", "armor", "ua"),
    "up_shields": ("쉴드업", "쉴업", "shields", "us"),
    "archives": ("아카이브", "archives", "arch", "r"),
}
ARMY = ("zealot", "dragoon", "high_templar", "dark_templar")
BUILDINGS = ("pylon", "gateway", "nexus", "assimilator", "core", "citadel", "archives", "forge")
UPGRADES = ("up_weapons", "up_armor", "up_shields")
EXEC_ACTION = {"worker": 0, "pylon": 1, "gateway": 2, "zealot": 3, "nexus": 4, "assimilator": 5, "core": 6, "dragoon": 7,
               "citadel": 10, "archives": 11, "high_templar": 12, "dark_templar": 13, "forge": 14,
               "up_weapons": 15, "up_armor": 16, "up_shields": 17}
ACTION_UNIT = {v: k for k, v in EXEC_ACTION.items()}
HUD_LETTER = {0: "W", 1: "P", 2: "G", 3: "Z", 4: "N", 5: "A", 6: "C", 7: "D", 10: "I", 11: "R", 12: "T", 13: "K",
              14: "F", 15: "+W", 16: "+A", 17: "+S"}


@dataclasses.dataclass
class Intent:
    intent: str                 # produce | reserve | worker_target | status | cancel | rebalance | army | rally | debug
    unit: str | None = None
    count: int = 1
    minerals: int = 0
    gas: int = 0
    source: str = "text"
    raw: str = ""
    args: dict = dataclasses.field(default_factory=dict)  # debug 전용. 반드시 마지막 (위치 인자 순서)


def parse_text(text: str) -> Intent | None:
    t = text.strip().lower()
    if not t:
        return None
    if t in ("상태", "status", "s", "/s"):
        return Intent("status", source="text", raw=text)
    if t in ("취소", "cancel", "stop"):
        return Intent("cancel", source="text", raw=text)
    if t in ("attack", "atk", "공격", "총공격"):
        return Intent("army", source="text", raw=text, args={"op": "attack"})
    m = re.match(r"^(rally|집결|집결지)\s*(here|auto|off|여기|자동|해제|끔)?$", t)
    if m:
        op = {"here": "here", "여기": "here", "auto": "auto", "자동": "auto", "off": "off", "해제": "off", "끔": "off"}.get(m.group(2) or "here")
        return Intent("rally", source="text", raw=text, args={"op": op})
    if t in ("rebalance", "move", "이전"):
        return Intent("rebalance", source="text", raw=text)
    # 예상외 상황 주입(시험): x1 돈 쓰기(게이트 150), x2 짓던 건물 취소, x3 자기 파일런 공격, x4 자기 게이트 공격
    m = re.match(r"^x\s*(\d|spend|cancel|attack|gate)\s*(\d+)?$", t)
    if m:
        k, n = m.group(1), int(m.group(2) or 4)
        if k in ("1", "spend"):
            return Intent("debug", source="text", raw=text, args={"op": "spend", "action": 2})
        if k in ("2", "cancel"):
            return Intent("debug", source="text", raw=text, args={"op": "cancel_building", "unit_type": ""})
        if k in ("3", "attack"):
            return Intent("debug", source="text", raw=text, args={"op": "attack_own", "unit_type": "Protoss_Pylon", "attackers": n})
        if k in ("4", "gate"):
            return Intent("debug", source="text", raw=text, args={"op": "attack_own", "unit_type": "Protoss_Gateway", "attackers": n})
    m = re.match(r"^(wt|workers|일꾼목표)\s*(\d+)$", t)
    if m:
        return Intent("worker_target", count=int(m.group(2)), source="text", raw=text)
    m = re.match(r"^(r|reserve|keep|예비)\s*m?(\d+)(?:\s*g?(\d+))?$", t)
    if m:
        return Intent("reserve", minerals=int(m.group(2)), gas=int(m.group(3) or 0), source="text", raw=text)
    m = re.match(r"^([a-z가-힣]+)\s*(\d+)?$", t) or re.match(r"^(\d+)\s*([a-z가-힣]+)$", t)
    if not m:
        return None
    a, b = m.group(1), m.group(2)
    word, num = (a, b) if not a.isdigit() else (b, a)
    for unit, words in UNIT_WORDS.items():
        if word in words:
            return Intent("produce", unit, int(num) if num else 1, source="text", raw=text)
    return None


def parse_intent_json(line: str) -> Intent | None:
    try:
        d = json.loads(line)
    except json.JSONDecodeError:
        return None
    kind = d.get("intent")
    if kind == "produce":
        return Intent("produce", d.get("unit"), int(d.get("count", 1)), source="file", raw=line)
    if kind == "reserve":
        return Intent("reserve", minerals=int(d.get("minerals", 0)), gas=int(d.get("gas", 0)), source="file", raw=line)
    if kind == "worker_target":
        return Intent("worker_target", count=int(d.get("count", 0)), source="file", raw=line)
    if kind in ("status", "cancel", "rebalance"):
        return Intent(kind, source="file", raw=line)
    if kind == "army":
        return Intent("army", source="file", raw=line, args={"op": d.get("op", "attack")})
    if kind == "rally":
        return Intent("rally", source="file", raw=line, args={"op": d.get("op", "here")})
    if kind == "debug":
        return Intent("debug", source="file", raw=line, args={k: v for k, v in d.items() if k != "intent"})
    return None


class IntentFile:
    """한 줄에 JSON 하나를 덧붙이는 파일. 음성 인식기 등 외부 프로그램의 입력 통로."""

    def __init__(self, path):
        self.path = Path(path) if path else None
        self.pos = self.path.stat().st_size if self.path and self.path.exists() else 0

    def poll(self):
        if not self.path or not self.path.exists():
            return []
        out = []
        with open(self.path, encoding="utf-8") as f:
            f.seek(self.pos)
            for line in f:
                it = parse_intent_json(line.strip()) if line.strip() else None
                if it:
                    out.append(it)
            self.pos = f.tell()
        return out
