"""계획기: (스냅샷, 목표, 제약) → 명령열과 예상 프레임. 상태를 갖지 않는다.

병력 목표는 ExpSim(가스·선행 건물·멀티 포함)을 스냅샷으로 초기화해 계층화 빔으로 푼다.
건물·일꾼 목표는 빠진 선행 건물만 앞에 붙여 그대로 낸다.
일꾼 상한: 묶음 계획의 새 일꾼은 기지당 덩이 2배수(16)까지만 (그 이상은 일꾼 목표가 맡는다).
"""
from __future__ import annotations

import dataclasses
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import expansion_estimate as ee  # noqa: E402
from env import Obs  # noqa: E402
from live.intents import ARMY, BUILDINGS, EXEC_ACTION, UPGRADES  # noqa: E402

PREREQ = {  # 건물 → 완성/건설 중/명령됨 중 하나라도 있어야 하는 선행 건물 (실행기 요구 순서)
    "gateway": ["pylon"], "core": ["gateway"], "citadel": ["core"], "archives": ["citadel"], "assimilator": [], "nexus": [], "pylon": [],
    "forge": ["pylon"],
}
FORGE_FRAMES = 750  # 포지 건설 600 + 프로브 이동 여유 (BW 데이터 + 추정)
UNIT_PREREQ = {"zealot": ["gateway"], "dragoon": ["gateway", "assimilator", "core"], "high_templar": ["gateway", "assimilator", "core", "citadel", "archives"],
               "dark_templar": ["gateway", "assimilator", "core", "citadel", "archives"]}


@dataclasses.dataclass
class Plan:
    actions: list            # 실행기 행동 번호
    expected_frames: list    # 각 명령의 예상 실행 프레임 (모르면 None)
    end_frame: int | None    # 예상 완료 프레임
    reason: str = ""
    seconds: float = 0.0


def building_count(snap, key, include_pending=True):
    b = (snap.get("buildings") or {}).get(key, {})
    n = int(b.get("ready", 0)) + len(b.get("building", []))
    if include_pending:
        n += len(b.get("pending", []))
    return n


def unit_count(snap, unit):
    """만든 수 누계 = 살아 있는 완성 + 생산 중 + 죽은 수. 죽은 수를 더해야 전투 손실을 '덜 만든 것'으로 보고 다시 뽑지 않는다
    (2026-11-08: z3 이 전투 중 손실을 메우느라 끝나지 않았다). 실행기가 dead 를 안 주면 0."""
    u = (snap.get("units") or {}).get(unit, {})
    return int(u.get("done", 0)) + int(u.get("in_production", 0)) + int(u.get("dead", 0))


def snapshot_to_obs(snap) -> Obs:
    """ExpSim.from_snapshot 이 읽는 Obs 꼴로 바꾼다."""
    b = snap.get("buildings") or {}
    bases = snap.get("bases") or []
    nexus_queue = sum(int(x.get("queue", 0)) for x in bases)
    nexus_rem = min([int(x.get("queue_remaining", 0)) for x in bases if x.get("queue", 0)] or [0])
    extra = {
        "gas": snap.get("gas", 0),
        "nexus_queue": nexus_queue, "nexus_remaining": nexus_rem,
        "pylons_building": b.get("pylon", {}).get("building", []), "gateways_building": b.get("gateway", {}).get("building", []),
        "pylons_pending_elapsed": b.get("pylon", {}).get("pending", []), "gateways_pending_elapsed": b.get("gateway", {}).get("pending", []),
        "gate_queue": snap.get("gate_queue", []), "gate_remaining": snap.get("gate_remaining", []),
        "reserved_minerals": snap.get("reserved_minerals", 0), "reserved_gas": snap.get("reserved_gas", 0), "reserve_gas": snap.get("reserve_gas", 0),
        "supply_issued": snap.get("supply_in_use", snap.get("supply_used", 0)),
        "tech": {k: b.get(k, {"ready": 0, "building": [], "pending": []}) for k in ("assimilator", "core", "citadel", "archives", "nexus", "pylon", "gateway")},
        # 기지별 미네랄 덩이 수: 완성 기지 먼저, 짓는 중인 기지는 남은 시간 순 (덩이가 안 보이면 8로 둔다)
        "base_patches": [int(x.get("patches", 0)) or 8 for x in sorted(bases, key=lambda x: (not x.get("done"), x.get("remaining", 0)))],
    }
    return Obs(frame=int(snap["frame"]), iteration=int(snap["frame"]), state=list(snap["state"]), extra=extra)


def plan_goal(P, snap, unit, count, constraints=None) -> Plan:
    """unit: ARMY | BUILDINGS | worker. count: 지금부터 더 만들 수."""
    t0 = time.time()
    c = constraints or {}
    if unit == "worker":
        return Plan([0] * count, [None] * count, None, "worker", time.time() - t0)
    if unit in UPGRADES:
        # 업그레이드: 포지·가스가 없으면 먼저, 2레벨 이상이면 아카이브(성채·코어 체인)도. count = 올릴 레벨 수 (순서대로)
        key = {"up_weapons": "weapons", "up_armor": "armor", "up_shields": "shields"}[unit]
        lvl = int(((snap.get("upgrades") or {}).get(key) or {}).get("level", 0))
        acts = []
        if building_count(snap, "pylon") == 0:
            acts.append(EXEC_ACTION["pylon"])
        ups = snap.get("upgrades") or {}
        running = [int((ups.get(k) or {}).get("remaining", 0)) for k in ("weapons", "armor", "shields") if (ups.get(k) or {}).get("upgrading")]
        forges = building_count(snap, "forge")
        if forges == 0:
            acts.append(EXEC_ACTION["forge"])
        elif not (ups.get(key) or {}).get("upgrading") and len(running) >= forges and min(running) > FORGE_FRAMES:
            # 모든 포지가 다른 업그레이드 중이고 가장 빨리 끝나는 것도 포지 하나 짓는 시간보다 길다 → 포지를 더 지어 병렬로
            acts.append(EXEC_ACTION["forge"])
        if building_count(snap, "assimilator") == 0:
            acts.append(EXEC_ACTION["assimilator"])
        if lvl + count >= 2 and building_count(snap, "archives") == 0:
            for pre in ("gateway", "core", "citadel", "archives"):
                if building_count(snap, pre) == 0:
                    acts.append(EXEC_ACTION[pre])
        acts += [EXEC_ACTION[unit]] * count
        return Plan(acts, [None] * len(acts), None, "upgrade", time.time() - t0)
    if unit in BUILDINGS:
        acts = []
        for pre in PREREQ.get(unit, []):
            if building_count(snap, pre) == 0:
                acts.append(EXEC_ACTION[pre])
        acts += [EXEC_ACTION[unit]] * count
        return Plan(acts, [None] * len(acts), None, "building", time.time() - t0)
    if unit not in ARMY:
        return Plan([], [], None, f"unknown unit {unit}", time.time() - t0)
    obs = snapshot_to_obs(snap)
    sim = ee.exp_from_snapshot(P, obs, unit, count)
    bases = 1 + len(sim.bases_done)
    workers_now = int((snap.get("workers") or {}).get("total", obs.state[4])) + sum(int(x.get("queue", 0)) for x in snap.get("bases") or [])
    max_new_workers = max(0, min(12, 16 * bases - workers_now))
    # 게이트 수에 상한을 두지 않는다(사용자 결정): 최적이면 몇 개든 짓는다. 시뮬레이터가 완료 시각으로 판단한다
    max_new_gates = int(c.get("max_new_gates", 4))
    top, n = ee.beam_from(sim, unit, count, width=int(c.get("beam", 800)), max_new_gates=max_new_gates, max_new_workers=max_new_workers)
    if not top:
        return Plan([], [], None, "no feasible plan", time.time() - t0)
    end, seq = top[0]
    acts = [EXEC_ACTION[unit] if a == 3 else a for a in seq]
    # 예상 실행 프레임: 시뮬레이터를 다시 밟아 얻는다
    sim2 = ee.exp_from_snapshot(P, obs, unit, count)
    frames = []
    for a in seq:
        t = sim2.step(a)
        frames.append(t)
    return Plan(acts, frames, end, f"{n} candidates", time.time() - t0)
