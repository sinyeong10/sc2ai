"""bwapi.ini 프로필 전환: 실험용(lab, 상대 AI 없는 UMS 맵) ↔ 라이브용(live, 멜리 맵 + 블리자드 컴퓨터 상대, 사람과 함께).

    py -X utf8 bridge/tools/set_mode.py lab
    py -X utf8 bridge/tools/set_mode.py live --enemy Terran

게임은 시작할 때 bwapi.ini 를 읽으므로 바꾼 뒤 Chaoslauncher 로 다시 띄운다. 원본 기본값은 bwapi.ini.default 에서 읽어
키 이름을 보존한다. 라이브는 창 모드·사운드 켬, 실험용은 사운드 끔. 시드는 둘 다 고정(12345).
"""
import argparse
import re
from pathlib import Path

GAME = Path(r"C:\sin\StarCraft")
INI = GAME / "bwapi-data" / "bwapi.ini"
DEFAULT = GAME / "bwapi-data" / "bwapi.ini.default"

PROFILES = {
    "lab": {
        "map": "maps/sc2ai/(2)Astral Balance UMS.scm", "game_type": "USE_MAP_SETTINGS",
        "race": "Protoss", "enemy_race": "Terran", "sound": "OFF",
    },
    "live": {
        "map": "maps/BroodWar/(2)Astral Balance.scm", "game_type": "MELEE",
        "race": "Protoss", "enemy_race": "Terran", "sound": "ON",
    },
}
COMMON = {
    "ai": "bwapi-data/AI/BuildExecutor.dll", "ai_dbg": "bwapi-data/AI/BuildExecutor.dll",
    "auto_menu": "SINGLE_PLAYER", "auto_restart": "ON", "enemy_count": "1", "save_replay": "",
    "holiday": "OFF", "windowed": "ON", "seed_override": "12345",
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=list(PROFILES))
    ap.add_argument("--enemy", default=None, help="상대 종족: Terran | Protoss | Zerg | Random")
    ap.add_argument("--map", default=None, help="맵 경로(게임 폴더 기준)")
    args = ap.parse_args()
    values = dict(COMMON)
    values.update(PROFILES[args.mode])
    if args.enemy:
        values["enemy_race"] = args.enemy
    if args.map:
        values["map"] = args.map
    src = DEFAULT if DEFAULT.exists() else INI
    out, done = [], set()
    for line in src.read_text(encoding="utf-8", errors="replace").splitlines():
        m = re.match(r"^;?\s*(\w+)\s*=", line)
        key = m.group(1) if m else None
        if key in values and key not in done and (not line.startswith(";") or key == "seed_override"):
            line = f"{key} = {values[key]}"
            done.add(key)
        out.append(line)
    missing = set(values) - done
    if missing:
        raise SystemExit(f"키를 못 찾았다: {missing}")
    header = f"; 프로필 [{args.mode}] (bridge/tools/set_mode.py 가 bwapi.ini.default 에서 생성)\n"
    INI.write_text(header + "\n".join(out) + "\n", encoding="utf-8")
    print(f"{INI} ← {args.mode}: " + ", ".join(f"{k}={values[k]}" for k in ("map", "game_type", "enemy_race", "sound", "windowed")))


if __name__ == "__main__":
    main()
