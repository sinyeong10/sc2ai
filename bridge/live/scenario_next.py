"""조건 기반 실게임 시험: 로그를 보며 앞 단계가 끝난 뒤 다음 교란을 넣는다(시간 고정이 아니라).

    py -X utf8 bridge/live/scenario_next.py --log bridge/results/live_run17.log --intent-file bridge/results/intents.txt

단계 (게임 시작 때 오프닝 + 드라군 10 은 제어 루프가 자동으로 넣는다):
  1. 연결 60초 뒤: n(멀티), r 200(예비), z2, r 0, uw, us → 넥서스 위치, 예비 적용, 포지·공업·쉴드업
  2. "[예비 적용]" 이 뜨면 5초 뒤: 사람 흉내 지출  → "[예비 해제]" 가 뜨는지 (오탐이 아니라 진짜 소비)
  3. 그 뒤: 질럿·드라군 6기로 자기 파일런 공격     → 파괴 뒤 재계획
  4. 파괴(lost_building) 뒤: d2                    → 전력 끊긴 게이트를 피하거나 파일런을 먼저 짓는지
  5. 그 뒤 30초: attack
각 단계의 대기는 최대 15분. 시간이 넘으면 그 단계를 건너뛰고 기록한다.
"""
import argparse
import json
import time
from pathlib import Path


def tail_lines(path: Path, pos: int):
    if not path.exists():
        return [], pos
    with open(path, encoding="utf-8", errors="replace") as f:
        f.seek(pos)
        data = f.read()
        return data.splitlines(), f.tell()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", required=True)
    ap.add_argument("--intent-file", default="bridge/results/intents.txt")
    ap.add_argument("--max-wait", type=int, default=900)
    args = ap.parse_args()
    log, intents = Path(args.log), Path(args.intent_file)
    pos = log.stat().st_size if log.exists() else 0

    def put(*items):
        with open(intents, "a", encoding="utf-8") as f:
            for it in items:
                f.write(json.dumps(it, ensure_ascii=False) + "\n")
        print(f"[{time.strftime('%H:%M:%S')}] 넣음 {items}", flush=True)

    def wait_for(pattern, label):
        nonlocal pos
        t0 = time.time()
        while time.time() - t0 < args.max_wait:
            lines, pos = tail_lines(log, pos)
            for ln in lines:
                if pattern in ln:
                    print(f"[{time.strftime('%H:%M:%S')}] 확인 {label}: {ln.strip()[:160]}", flush=True)
                    return True
            time.sleep(1)
        print(f"[{time.strftime('%H:%M:%S')}] 시간 초과 {label}", flush=True)
        return False

    wait_for("라이브 v2", "게임 연결")
    time.sleep(60)
    put({"intent": "produce", "unit": "nexus", "count": 1}, {"intent": "reserve", "minerals": 200, "gas": 0},
        {"intent": "produce", "unit": "zealot", "count": 2}, {"intent": "reserve", "minerals": 0, "gas": 0},
        {"intent": "produce", "unit": "up_weapons", "count": 1}, {"intent": "produce", "unit": "up_shields", "count": 1})
    if wait_for("[예비 적용]", "예비 적용"):
        time.sleep(5)
        put({"intent": "debug", "op": "spend", "action": 2})
        wait_for("[예비 해제]", "예비 해제")
    put({"intent": "debug", "op": "attack_own", "unit_type": "Protoss_Pylon", "attackers": 6})
    if wait_for("lost_building", "파일런 파괴 재계획"):
        put({"intent": "produce", "unit": "dragoon", "count": 2})
        wait_for("[완료] dragoon2", "파괴 뒤 드라군 2")
    time.sleep(30)
    put({"intent": "army", "op": "attack"})
    print("끝", flush=True)


if __name__ == "__main__":
    main()
