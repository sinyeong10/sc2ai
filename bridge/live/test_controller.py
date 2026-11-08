"""가짜 실행기로 제어 루프 시험. py -X utf8 bridge/live/test_controller.py

시나리오: (1) z2 → 완료, (2) r 150 뒤 z1 은 예비 유지, (3) 요청 실패(강제) → 재계획, (4) 사람이 성채를 지으면 목표 완료,
(5) 건물 손실 → 재계획, (6) 사람이 돈을 쓰면 예비 해제, (7) 일꾼 목표 자동 보충,
(8) 건물은 놓여야 완료이고 명령된 건물은 다시 계획하지 않음, (9) 제어 루프 재시작 뒤 상태 복원(중복 없음),
(10) 다른 게임의 상태는 복원하지 않음, (11) 건물 목표는 주기·늦어짐 재계획 없음, (12) 집결지 명령, (13) 재보정 상수 적용.
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

# (8) 건물은 놓여야 완료. 일꾼이 가는 중(pending)이면 아직이고, 그동안 같은 건물을 또 계획하지 않는다
ex = FakeExecutor(build_delay=120)
ex.workers, ex.minerals = 12, 400
ex.buildings["pylon"]["ready"] = 2; ex.supply_total = 25
logs = []
ctrl = Controller(ex, P, log=lambda s: logs.append(s) or print(s), beam=300)
ctrl.tick([parse_text("p1")]); ex.advance(12)
ctrl.tick([]); ex.advance(12)
pend = [r for r in ex.requests if r["action"] == 1 and r["state"] == "issued"]
check(len(pend) == 1 and not any("[완료] pylon1" in s for s in logs), f"명령만 나간 파일런은 완료가 아님 (issued {len(pend)})")
for _ in range(12):
    ctrl.tick([]); ex.advance(12)
n_pylon_req = sum(1 for r in ex.requests if r["action"] == 1 and r.get("reason") != "cancelled")
check(any("[완료] pylon1" in s for s in logs) and n_pylon_req == 1, f"놓인 뒤 완료, 파일런 요청 1개 ({n_pylon_req})")

# (9) 제어 루프 재시작 뒤 상태 복원: 큐·목표 기준값·예비를 이어 받고 중복 생산하지 않는다
import os, tempfile  # noqa: E402
tmpdir = tempfile.mkdtemp()
state = os.path.join(tmpdir, "state.json")
ex = FakeExecutor(build_delay=60)
ex.workers, ex.minerals = 12, 160
ex.buildings["pylon"]["ready"] = 2; ex.supply_total = 25
ex.buildings["gateway"]["ready"] = 1
logs = []
ctrl = Controller(ex, P, log=lambda s: logs.append(s) or print(s), beam=300, state_file=state)
run(ctrl, ex, 3, {0: ["z2", "r 100", "z1", "wt 14"]})
z_before = ex.units["zealot"]
ctrl2 = Controller(ex, P, log=lambda s: logs.append(s) or print(s), beam=300, state_file=state)
ctrl2.snap = ex.observe()
ok = ctrl2.restore_state(ctrl2.snap)
check(ok and ctrl2.goal is not None and ctrl2.goal.describe() == "zealot2" and len(ctrl2.queue) == 2 and ctrl2.worker_target == 14
      and not ctrl2.worker_target_auto, f"복원: 목표 {ctrl2.goal.describe() if ctrl2.goal else '-'}, 큐 {len(ctrl2.queue)}, 일꾼 목표 {ctrl2.worker_target}")
check(ctrl2.goal.baseline == ctrl.goal.baseline, f"복원: 기준값 유지 ({ctrl2.goal.baseline})")
run(ctrl2, ex, 200)
check(z_before >= 1 and ex.units["zealot"] == 3, f"복원 뒤 질럿 합계 3 (복원 전 {z_before}, 끝 {ex.units['zealot']})")
check(ex.reserve == (100, 0), f"복원 뒤 예비 적용 ({ex.reserve})")
check(any("restored" in s for s in logs), "복원 뒤 지금 상태에서 다시 계획")

# (10) 다른 게임(game_id 다름)의 상태는 복원하지 않는다
ex_new = FakeExecutor(build_delay=60, game_id="fake-2")
ctrl3 = Controller(ex_new, P, log=lambda s: None, beam=300, state_file=state)
check(not ctrl3.restore_state(ex_new.observe()), "다른 게임의 상태는 복원 안 함")

# (11) 건물 목표: 돈이 모자라 오래 기다려도 주기·늦어짐 재계획으로 요청을 취소·재요청하지 않는다
ex = FakeExecutor(build_delay=60)
ex.workers, ex.minerals = 1, 0
ex.buildings["pylon"]["ready"] = 2; ex.supply_total = 25
logs = []
ctrl = Controller(ex, P, log=lambda s: logs.append(s) or print(s), beam=300)
ctrl.worker_target_auto, ctrl.worker_target = False, 0
run(ctrl, ex, 150, {0: ["g3"]})
check(not any(("periodic" in s or "late" in s) for s in logs if "[계획]" in s), "건물 목표: 주기·늦어짐 재계획 없음")
check(sum(1 for s in logs if "[계획]" in s) == 1, f"건물 목표: 계획 1번 ({sum(1 for s in logs if '[계획]' in s)})")

# (12) 집결지 명령
ex = FakeExecutor(build_delay=60)
logs = []
ctrl = Controller(ex, P, log=lambda s: logs.append(s) or print(s), beam=300)
ctrl.tick([parse_text("rally")]); ctrl.tick([parse_text("rally off")])
check(ex.rally_mode == "off" and any("[집결지] here" in s for s in logs), f"집결지 명령 ({ex.rally_mode})")

# (13) 재보정 상수 적용
import json  # noqa: E402
import expansion_estimate as ee  # noqa: E402
from live import planner, refit  # noqa: E402
pp = os.path.join(tmpdir, "params.json")
with open(pp, "w", encoding="utf-8") as f:
    json.dump({"P": {"gate": 1077}, "EXTRA": {"core": 999}, "FORGE_FRAMES": 700, "GAS_PER_BASE": 0.2}, f)
keep = (dict(ee.EXTRA), planner.FORGE_FRAMES, ee.GAS_PER_BASE)
P2 = dict(P)
ch = refit.apply_params(pp, P2)
check(P2["gate"] == 1077 and ee.EXTRA["core"][2] == 999 and planner.FORGE_FRAMES == 700 and ee.GAS_PER_BASE == 0.2 and len(ch) == 4,
      f"재보정 상수 적용 ({ch})")
ee.EXTRA.clear(); ee.EXTRA.update(keep[0]); planner.FORGE_FRAMES, ee.GAS_PER_BASE = keep[1], keep[2]

print(f"\n실패 {fails}")
sys.exit(1 if fails else 0)
