"""실게임 교란 시험: 의도 파일에 명령과 시험용(debug) 동작을 시간차로 넣어 재계획이 도는지 본다.

    py -X utf8 bridge/live/chaos_test.py --intent-file bridge/results/intents.txt

live_run.py 가 같은 의도 파일을 읽고 있어야 한다. 단계(벽시계 기준):
  0s   z4                         질럿 4기 목표
  120s r 200                      예비 200 (앞 목표 뒤 효력)
  180s debug spend gateway        사람이 돈을 씀(게이트 150) → [예비 해제] 기대
  200s d3                         드라군 3 (어시밀·코어 선행)
  330s debug cancel_building core 짓던 코어 취소(손실) → lost_building 재계획 기대
  420s debug attack_own pylon     질럿으로 자기 파일런 공격 → 손실 재계획 기대
  500s t2                         하이템플러 2
"""
import argparse
import json
import time
from pathlib import Path

STEPS = [
    (0, {"intent": "produce", "unit": "zealot", "count": 4}),
    (120, {"intent": "reserve", "minerals": 200, "gas": 0}),
    (180, {"intent": "debug", "op": "spend", "action": 2}),
    (200, {"intent": "produce", "unit": "dragoon", "count": 3}),
    (330, {"intent": "debug", "op": "cancel_building", "unit_type": "Protoss_Cybernetics_Core"}),
    (420, {"intent": "debug", "op": "attack_own", "unit_type": "Protoss_Pylon", "attackers": 4}),
    (500, {"intent": "produce", "unit": "high_templar", "count": 2}),
]


# 전체 점검: 건설 자리·멀티·가스 체인·다크 체인·교란(취소·파괴·지출)·예비·공격
FULL = [
    (20, {"intent": "produce", "unit": "zealot", "count": 4}),
    (120, {"intent": "produce", "unit": "nexus", "count": 1}),
    (150, {"intent": "produce", "unit": "dragoon", "count": 3}),
    (240, {"intent": "debug", "op": "cancel_building", "unit_type": ""}),
    (300, {"intent": "produce", "unit": "dark_templar", "count": 2}),
    (400, {"intent": "debug", "op": "attack_own", "unit_type": "Protoss_Pylon", "attackers": 4}),
    (480, {"intent": "reserve", "minerals": 200, "gas": 0}),
    (490, {"intent": "produce", "unit": "zealot", "count": 2}),
    (540, {"intent": "debug", "op": "spend", "action": 2}),
    (600, {"intent": "army", "op": "attack"}),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--intent-file", default="bridge/results/intents.txt")
    ap.add_argument("--speed", type=float, default=1.0, help="시간 배율 (2 면 두 배 빨리)")
    ap.add_argument("--scenario", choices=["basic", "full"], default="basic")
    args = ap.parse_args()
    steps = FULL if args.scenario == "full" else STEPS
    path = Path(args.intent_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    for at, intent in steps:
        wait = at / args.speed - (time.time() - t0)
        if wait > 0:
            time.sleep(wait)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(intent, ensure_ascii=False) + "\n")
        print(f"[{time.strftime('%H:%M:%S')}] +{at}s {intent}", flush=True)
    print("끝")


if __name__ == "__main__":
    main()
