"""가짜 실행기로 제어 루프 시험. py -X utf8 bridge/live/test_controller.py

시나리오: (1) z2 → 완료, (2) r 150 뒤 z1 은 예비 유지, (3) 요청 실패(강제) → 재계획, (4) 사람이 성채를 지으면 목표 완료,
(5) 건물 손실 → 재계획, (6) 사람이 돈을 쓰면 예비 해제, (7) 일꾼 목표 자동 보충.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import sc1_sim as ss  # noqa: E402
from live.controller import Controller  # noqa: E402
from live.fake_executor import FakeExecutor  # noqa: E402
from live.intents import parse_text  # noqa: E402

P = dict(ss.DEFAULT_PARAMS)
fails = 0


def check(cond, msg):
    global fails
    print(("[OK] " if cond else "[FAIL] ") + msg)
    if not cond:
        fails += 1


def run(ctrl, ex, ticks, intents_at=None):
    intents_at = intents_at or {}
    for i in range(ticks):
        its = [parse_text(t) for t in intents_at.get(i, [])]
        ctrl.tick(its)
        ex.advance(12)


# (1)(2)(7)
ex = FakeExecutor(build_delay=60)
ex.workers, ex.minerals = 12, 400
ex.buildings["pylon"]["ready"] = 2; ex.supply_total = 25
ex.buildings["gateway"]["ready"] = 1
logs = []
ctrl = Controller(ex, P, log=lambda s: logs.append(s) or print(s), beam=300)
run(ctrl, ex, 150, {0: ["z2", "r 150", "z1"]})
check(ex.units["zealot"] >= 3, f"질럿 3기 생산됨 ({ex.units['zealot']})")
check(ex.reserve == (150, 0), f"예비 150 적용 ({ex.reserve})")
check(ex.workers > 12, f"일꾼 목표 자동 보충 ({ex.workers})")
check(any("[완료] zealot2" in s for s in logs) and any("[완료] zealot1" in s for s in logs), "두 묶음이 순서대로 완료")

# (3) 강제 실패 → 재계획 (게이트 요청만 실패하게)
ex = FakeExecutor(build_delay=60, fail_actions={2})
ex.workers, ex.minerals = 12, 500
ex.buildings["pylon"]["ready"] = 2; ex.supply_total = 25
logs = []
ctrl = Controller(ex, P, log=lambda s: logs.append(s) or print(s), beam=300)
run(ctrl, ex, 12, {0: ["z1"]})
check(any("[실패]" in s for s in logs) and any("재계획" in s for s in logs), "요청 실패가 재계획을 일으킴")

# (4) 사람이 성채를 지으면 목표 완료
ex = FakeExecutor(build_delay=60)
ex.workers, ex.minerals, ex.gas = 14, 600, 300
ex.buildings["pylon"]["ready"] = 2; ex.supply_total = 25
ex.buildings["gateway"]["ready"] = 1; ex.buildings["core"]["ready"] = 1; ex.buildings["assimilator"]["ready"] = 1
logs = []
ctrl = Controller(ex, P, log=lambda s: logs.append(s) or print(s), beam=300)
ctrl.tick([parse_text("i")])        # 성채 1 목표
ex.human_builds("citadel")           # 사람이 먼저 지음
ex.cancel()                          # (실행기 쪽 요청은 아직 queued 였다고 가정)
ctrl.tick([]); ex.advance(12); ctrl.tick([])
check(any("[완료] citadel1" in s for s in logs), "사람이 지은 성채로 목표 완료")

# (5) 건물 손실 → 재계획
ex = FakeExecutor(build_delay=60)
ex.workers, ex.minerals = 12, 120
ex.buildings["pylon"]["ready"] = 2; ex.supply_total = 25
ex.buildings["gateway"]["ready"] = 2
logs = []
ctrl = Controller(ex, P, log=lambda s: logs.append(s) or print(s), beam=300)
ctrl.tick([parse_text("z6")]); ex.advance(12)
ex.human_loses_building("gateway")
ctrl.tick([]); ex.advance(12); ctrl.tick([])
check(any("lost_building" in s for s in logs), "건물 손실이 재계획을 일으킴")

# (6) 사람이 돈을 쓰면 예비 해제
ex = FakeExecutor(build_delay=60)
ex.workers, ex.minerals = 12, 500
ex.buildings["pylon"]["ready"] = 2; ex.supply_total = 25
logs = []
ctrl = Controller(ex, P, log=lambda s: logs.append(s) or print(s), beam=300)
ctrl.tick([parse_text("r 200")]); ex.advance(12); ctrl.tick([]); ex.advance(12); ctrl.tick([])
ex.human_spends(300)
ctrl.tick([])
check(ex.reserve == (0, 0) and any("[예비 해제]" in s for s in logs), f"사람 소비로 예비 해제 ({ex.reserve})")

print(f"\n실패 {fails}")
sys.exit(1 if fails else 0)
