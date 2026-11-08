"""제어 루프. 틱마다: 관측 → 입력 반영 → 편차 검사 → (재)계획 → 발행 → 로그 → HUD. 어디서도 막히지 않는다.

목표 의미(사용자 결정 2026-11-08):
- 큐는 친 순서, 목표 하나 = "지금 상태에서 가장 빨리". 합치지 않는다.
- 완료 판정은 수량: 유닛은 (완성 + 생산 중 + 죽은) 수, 건물은 (완성 + 건설 중) = '놓인' 수가 목표 시작 시점 기준값 + 요청 수
  이상이면 끝. 명령만 나가고 아직 안 놓인 건물은 완료가 아니다(사용자 규칙 "건물은 배치"). 다만 계획할 때는 명령된 건물을
  이미 있는 것으로 보고 다시 짓지 않는다. 기준값은 명령된 것까지 센다(목표 시작 때 이미 오던 건물은 이 목표 몫이 아니다).
  사람이 지은 것도 센다 (재계산 뒤 계획에서 사라지므로).
- 재계획: 요청 실패, 건물 손실, 낸 요청이 다 끝났는데 몫이 남음. 병력·일꾼 목표는 주기(600프레임)·늦어짐도 본다.
  건물·업그레이드 목표는 주기·늦어짐으로 재계획하지 않는다(실행기가 순서대로 처리 중인 요청을 괜히 취소·재요청했다).
- 상태(큐·현재 목표 기준값·예비·일꾼 목표)는 틱마다 파일에 저장하고, 제어 루프를 다시 켜면 같은 게임일 때 이어 받는다.
- 예비 자원은 큐의 그 자리에서 효력. 사람이 그 돈을 쓰면 해제.
- 일꾼 목표는 상시 제약(기본 기지당 16). 피격 중 특별 처리 없음.
계획의 명령은 전부 실행기에 비동기 요청으로 보낸다(실행기가 순서대로 조건이 되는 첫 프레임에 실행). 재계획하면 아직 실행
안 된(queued) 요청을 취소하고 새 계획을 보낸다. 이미 나간 건설은 실행기가 끝까지 책임진다.
"""
from __future__ import annotations

import dataclasses
import json
import os
import time

from live.intents import ARMY, BUILDINGS, UPGRADES, EXEC_ACTION, ACTION_UNIT, HUD_LETTER, Intent, parse_text
from live.planner import Plan, building_count, plan_goal, unit_count

UNIT_KEY = {"nexus": "nexus", "pylon": "pylon", "gateway": "gateway", "assimilator": "assimilator", "core": "core", "citadel": "citadel",
            "archives": "archives", "forge": "forge"}
UPGRADE_KEY = {"up_weapons": "weapons", "up_armor": "armor", "up_shields": "shields"}
COST = {0: 50, 1: 100, 2: 150, 3: 100, 4: 400, 5: 100, 6: 200, 7: 125, 10: 150, 11: 150, 12: 50, 13: 125, 14: 150, 15: 100, 16: 100, 17: 150}
REPLAN_PERIOD = 600        # 프레임. 주기적 재검증 (사람의 변경·자원 편차를 흡수)
LATE_FRAMES = 300          # 예상보다 이만큼 늦으면 편차
HORIZON = 8                # 큰 병력 목표는 이만큼씩 나눠 계획한다 (질럿 50기를 한 번에 풀면 계산이 20초 걸려 재계획 고리가 생겼다)


def rle(tokens, sep=" ", fmt="{n}{t}"):
    """연속으로 같은 항목을 묶는다: Z Z Z Z Z P → 5Z P (가시성)."""
    out, prev, n = [], None, 0
    for t in list(tokens) + [None]:
        if t == prev:
            n += 1
            continue
        if prev is not None:
            out.append(fmt.format(n=n, t=prev) if n > 1 else str(prev))
        prev, n = t, 1
    return sep.join(out)


class Goal:
    def __init__(self, intent: Intent, snap):
        self.intent = intent
        self.unit = intent.unit
        self.count = intent.count
        self.baseline = self._measure(snap, committed=True)
        self.started = int(snap["frame"])
        self.plan: Plan | None = None
        self.planned_at = -1
        self.request_ids: list[int] = []
        self.replans = 0
        self.chunk_base, self.chunk = 0, 0
        self.held = False
        self.fail_counts: dict[int, int] = {}
        self.needs_plan = False

    def _measure(self, snap, committed=False):
        """놓인(배치) 기준 수. committed=True 면 명령됐지만 아직 안 놓인 건물(pending)도 센다. 유닛·업그레이드는 둘이 같다."""
        if self.unit in UPGRADES:
            u = ((snap.get("upgrades") or {}).get(UPGRADE_KEY[self.unit]) or {})
            return int(u.get("level", 0)) + (1 if u.get("upgrading") else 0)  # 시작하면 완료(유닛의 큐 진입과 같은 기준)
        if self.unit in ARMY:
            return unit_count(snap, self.unit)
        if self.unit == "worker":
            return unit_count(snap, "probe")
        return building_count(snap, UNIT_KEY[self.unit], include_pending=committed)

    def progress(self, snap):
        """완료 판정·표시용: 건물은 놓인 것만."""
        return max(0, self._measure(snap) - self.baseline)

    def committed(self, snap):
        """계획용: 명령된 건물까지. 이미 일꾼이 가는 건물을 다시 계획하지 않는다."""
        return max(0, self._measure(snap, committed=True) - self.baseline)

    def to_plan(self, snap):
        return max(0, self.count - self.committed(snap))

    def remaining(self, snap):
        return max(0, self.count - self.progress(snap))

    def done(self, snap):
        return self.remaining(snap) == 0

    def describe(self):
        return f"{self.unit}{self.count}"

    def to_dict(self):
        return {"intent": dataclasses.asdict(self.intent), "baseline": self.baseline, "started": self.started, "replans": self.replans,
                "held": self.held, "fail_counts": {str(k): v for k, v in self.fail_counts.items()}}

    @classmethod
    def from_dict(cls, d):
        g = cls.__new__(cls)
        g.intent = Intent(**d["intent"])
        g.unit, g.count = g.intent.unit, g.intent.count
        g.baseline, g.started, g.replans = int(d["baseline"]), int(d["started"]), int(d.get("replans", 0))
        g.plan, g.planned_at, g.request_ids = None, -1, []
        g.chunk_base, g.chunk = 0, 0
        g.held = bool(d.get("held", False))
        g.fail_counts = {int(k): int(v) for k, v in (d.get("fail_counts") or {}).items()}
        g.needs_plan = True  # 복원 뒤 첫 틱에 지금 상태에서 다시 계획한다 (이전 제어 루프의 queued 요청은 취소된다)
        return g


class Controller:
    def __init__(self, client, P, log=print, eventlog=None, beam=800, status_file=None, state_file=None):
        self.client, self.P, self.log, self.ev, self.beam = client, P, log, eventlog, beam
        self.status_file = status_file  # 음성 게이트웨이가 읽어 "지금 뭐 하고 있어?" 에 답하는 상태 파일
        self.state_file = state_file    # 제어 루프 재시작 때 이어 받을 상태 (큐·목표·예비·일꾼 목표)
        self.last_state_key = None
        self.queue: list[Intent] = []
        self.goal: Goal | None = None
        self.reserve = {"minerals": 0, "gas": 0}
        self.worker_target = 0
        self.worker_target_auto = True
        self.snap = None
        self.prev = None
        self.last_hud = None
        self.last_avail = None
        self.sent_since_obs = False
        self.worker_request_pending = None

    # ---------------- 틱
    def tick(self, intents=()):
        snap = self.client.observe()
        self.prev, self.snap = self.snap, snap
        if self.ev:
            self.ev.write("observe", snap["frame"], snapshot=snap)
        for m in self.client.poll_inbox():
            if m.get("type") == "text":
                it = parse_text(m.get("text", ""))
                if it:
                    self.handle(it)
        for it in intents:
            self.handle(it)
        self.check_reserve_spent(snap)
        if self.goal is None:
            self.start_next_goal(snap)
        if self.goal is not None:
            self.drive_goal(snap)
        self.maintain_supply(snap)
        self.fill_workers(snap)
        self.update_hud(snap)
        self.write_status(snap)
        self.save_state(snap)
        self.sent_since_obs = False

    # ---------------- 입력
    def handle(self, it: Intent):
        f = self.snap["frame"] if self.snap else -1
        if self.ev:
            self.ev.write("intent", f, intent=it.__dict__)
        if it.intent == "status":
            self.log(self.status_line())
        elif it.intent == "cancel":
            n = self.client.cancel()
            self.queue.clear()
            self.goal = None
            self.log(f"[취소] 큐 비움, 실행 전 요청 {n}개 취소 (이미 나간 건설은 실행기가 마무리)")
        elif it.intent == "rebalance":
            r = self.client.rebalance()
            self.log(f"[이전] 멀티로 일꾼 이전: {'됨' if r.get('rebalanced') else '멀티 없음'}")
        elif it.intent == "rally":
            r = self.client.rally(it.args.get("op", "here"))
            where = f"({r.get('x')},{r.get('y')})" if r.get("x", -1) >= 0 else ""
            self.log(f"[집결지] {it.args.get('op', 'here')} → 모드 {r.get('mode')} {where}")
        elif it.intent == "army":
            r = self.client.army(it.args.get("op", "attack"))
            self.log(f"[전체 공격] 병력 {r.get('units', 0)}기 공격 이동")
        elif it.intent == "debug":
            r = self.client.debug(it.args.get("op", ""), **{k: v for k, v in it.args.items() if k != "op"})
            self.log(f"[시험] {it.args} → {r.get('debug')}")
        elif it.intent == "worker_target":
            self.worker_target, self.worker_target_auto = it.count, False
            self.log(f"[일꾼 목표] {it.count}기")
        elif it.intent in ("produce", "reserve"):
            if it.intent == "produce" and it.unit not in ARMY + BUILDINGS + UPGRADES + ("worker",):
                self.log(f"[무시] 모르는 유닛 {it.unit}")
                return
            self.queue.append(it)
            desc = f"예비 m{it.minerals} g{it.gas}" if it.intent == "reserve" else f"{it.unit} +{it.count}"
            self.log(f"[큐] {desc} (출처 {it.source}: {it.raw!r}) → 큐 {len(self.queue)}개")
        else:
            self.log(f"[무시] {it}")

    # ---------------- 목표
    def start_next_goal(self, snap):
        while self.queue:
            it = self.queue.pop(0)
            if it.intent == "reserve":
                self.reserve = {"minerals": it.minerals, "gas": it.gas}
                self.client.set_reserve(it.minerals, it.gas)
                self.log(f"[예비 적용] 미네랄 {it.minerals}, 가스 {it.gas}")
                continue
            self.goal = Goal(it, snap)
            if self.ev:
                self.ev.write("goal", snap["frame"], goal=self.goal.describe(), baseline=self.goal.baseline)
            self.replan(snap, "new goal")
            return

    def replan(self, snap, why):
        g = self.goal
        g.needs_plan = False
        remaining = g.to_plan(snap)  # 명령된(아직 안 놓인) 건물은 이미 있는 것으로 본다
        if remaining == 0:
            return
        # 실행 전 요청은 취소하고 새로 보낸다
        n = self.client.cancel()
        chunk = min(remaining, HORIZON) if g.unit in ARMY else remaining
        plan = plan_goal(self.P, snap, g.unit, chunk, {"beam": self.beam})
        g.chunk_base = g.committed(snap)
        g.chunk = chunk
        g.plan, g.planned_at, g.replans = plan, int(snap["frame"]), g.replans + (0 if why == "new goal" else 1)
        if self.ev:
            self.ev.write("plan", snap["frame"], goal=g.describe(), remaining=remaining, why=why, actions=plan.actions,
                          expected_frames=plan.expected_frames, end_frame=plan.end_frame, note=plan.reason, seconds=round(plan.seconds, 2), cancelled=n)
        names = rle([ACTION_UNIT.get(a, a) for a in plan.actions], sep=", ", fmt="{t}×{n}")
        part = f" (이번 {chunk}기)" if chunk < remaining else ""
        self.log(f"[계획] {g.describe()} 남은 {remaining}{part}: {names} 예상 완료 {plan.end_frame} ({why}, {plan.reason}, {plan.seconds:.1f}s)")
        if not plan.actions:
            self.log(f"[목표 실패] {g.describe()}: {plan.reason}. 다음 목표로")
            self.goal = None
            return
        g.request_ids = []
        for a in plan.actions:
            ack = self.client.request(a)
            if self.ev:
                self.ev.write("request", snap["frame"], action=a, accepted=ack["accepted"], request_id=ack["request_id"], reason=ack["reason"])
            if ack["accepted"]:
                g.request_ids.append(ack["request_id"])
            else:
                self.log(f"[요청 거부] {ACTION_UNIT.get(a, a)}: {ack['reason']}")
        self.sent_since_obs = True

    def drive_goal(self, snap):
        g = self.goal
        if g.done(snap):
            self.log(f"[완료] {g.describe()} (프레임 {snap['frame']}, 재계획 {g.replans}회)")
            if self.ev:
                self.ev.write("goal_done", snap["frame"], goal=g.describe(), replans=g.replans)
            n = self.client.cancel()  # 사람이 대신 지어 남은 요청이 있으면 지운다
            self.goal = None
            self.start_next_goal(snap)
            return
        if g.needs_plan:
            self.replan(snap, "restored")
            return
        reqs = {r["id"]: r for r in snap.get("requests", [])}
        mine = [reqs[i] for i in g.request_ids if i in reqs]
        # 업그레이드가 포지 사용 중(이전 레벨·다른 업그레이드)이라 기다리면 실행기 큐를 막지 않도록 빼 둔다
        if g.unit in UPGRADES:
            ups = snap.get("upgrades") or {}
            running = sum(1 for k in ("weapons", "armor", "shields") if (ups.get(k) or {}).get("upgrading"))
            forge_coming = building_count(snap, "forge") > building_count(snap, "forge", include_pending=False) or                 len((snap["buildings"].get("forge") or {}).get("building", [])) > 0
            blocked = [r for r in mine if r["state"] == "queued" and any(k in r.get("reason", "") for k in ("upgrading", "busy"))]
            if blocked and not forge_coming:
                self.client.cancel()
                g.request_ids = []
                g.held = True
                return
            if g.held:
                if running >= building_count(snap, "forge", include_pending=False) and not forge_coming:
                    return  # 아직 모든 포지가 바쁨: 기다린다
                g.held = False
                self.replan(snap, "forge free")
                return
        failed = [r for r in mine if r["state"] == "failed" and r.get("reason") != "cancelled"]
        if failed:
            why = "; ".join(f"{ACTION_UNIT.get(r['action'], r['action'])}: {r['reason']}" for r in failed)
            self.log(f"[실패] {why} → 재계획")
            if self.ev:
                self.ev.write("deviation", snap["frame"], kind="request_failed", detail=why)
            # 실패 횟수는 라운드(재계획 한 번)당 1회로 센다. 인구 부족은 파일런으로 풀리므로 포기 사유가 아니다
            PSI = (2, 6, 10, 11)  # 게이트·코어·성채·아카이브: 파일런 전력 범위가 필요
            space = [r for r in failed if (r["action"] in PSI and ("no powered space" in r["reason"] or "no build tile" in r["reason"]
                                                                    or "refused repeatedly" in r["reason"]))
                     or "unpowered" in r["reason"] or "Unit_Busy" in r["reason"]]
            if space and int(snap["supply_total"]) < 200 or space and building_count(snap, "pylon") > 0:
                b = snap["buildings"]["pylon"]
                coming = len(b.get("building", [])) + len(b.get("pending", []))
                if coming == 0:
                    self.log(f"[자리 부족] {ACTION_UNIT.get(space[0]['action'])}: 전력 범위에 자리 없음 → 파일런을 먼저 짓고 다시 계획")
                    self.client.cancel()
                    ack = self.client.request(1)
                    if self.ev:
                        self.ev.write("deviation", snap["frame"], kind="no_powered_space", detail=why)
                    self.replan(snap, "no powered space")
                    return
            fc = g.fail_counts
            for a in {r["action"] for r in failed if "supply impossible" not in r["reason"]}:
                fc[a] = fc.get(a, 0) + 1
            g.fail_counts = fc
            if any(("maxed" in r["reason"]) for r in failed) or any(v >= 3 for v in fc.values()):
                reason = "인구 한도 200" if any("maxed" in r["reason"] for r in failed) else f"같은 명령 3회 실패 ({why})"
                self.log(f"[목표 포기] {g.describe()}: {reason}")
                if self.ev:
                    self.ev.write("goal_failed", snap["frame"], goal=g.describe(), reason=reason)
                self.client.cancel()
                self.goal = None
                return
            self.replan(snap, "request failed")
            return
        # 낸 요청이 모두 끝났는데(실행됨·실패) 계획할 몫이 남았으면 지금 상태에서 다시 계획한다.
        # 병력: 나눠 계획한 다음 몫. 건물·업그레이드: 놓인 건물이 부서졌거나 명령된 건물이 사라진 경우(주기 재계획 대신 이것으로 잡는다)
        if all(r["state"] in ("done", "failed") for r in mine) and g.to_plan(snap) > 0 and snap["frame"] - g.planned_at >= 24:
            self.replan(snap, "next chunk" if g.unit in ARMY else "not placed")
            return
        # 주기적 재검증과 늦어짐 편차는 병력·일꾼 목표만. 예상 프레임은 계획 계산에 걸린 시간만큼 밀어서 본다
        timed = g.unit in ARMY or g.unit == "worker"
        late = False
        if timed and g.plan and g.plan.expected_frames:
            shift = int(g.plan.seconds * 24) + 24
            for r, exp in zip(mine, g.plan.expected_frames):
                if r["state"] == "queued" and exp is not None and snap["frame"] > exp + shift + LATE_FRAMES:
                    late = True
                    break
        lost = self.prev and (snap["threat"]["lost_buildings"] > self.prev["threat"]["lost_buildings"])
        if lost or late or (timed and snap["frame"] - g.planned_at >= REPLAN_PERIOD):
            kind = "lost_building" if lost else ("late" if late else "periodic")
            if self.ev:
                self.ev.write("deviation", snap["frame"], kind=kind)
            self.replan(snap, kind)

    # ---------------- 상시 제약
    def check_reserve_spent(self, snap):
        avail = int(snap["minerals"]) - (int(snap["reserved_minerals"]) - int(snap.get("reserve_minerals", 0)))
        # 우리 요청이 이번 관측 사이에 실행돼 쓴 돈은 사람의 소비가 아니다
        spent = 0
        counted = getattr(self, "_counted_reqs", set())
        for r in snap.get("requests", []):
            if r["state"] in ("issued", "done") and r["id"] not in counted and r.get("reason") != "cancelled":
                spent += COST.get(r["action"], 0)
                counted.add(r["id"])
        self._counted_reqs = counted
        if (self.reserve["minerals"] > 0 and self.last_avail is not None and self.last_avail - avail - spent >= 40):
            self.log(f"[예비 해제] 사람이 자원을 썼다 ({self.last_avail} → {avail})")
            self.reserve = {"minerals": 0, "gas": 0}
            self.client.set_reserve(0, 0)
        self.last_avail = avail

    def maintain_supply(self, snap):
        """목표가 있을 때만(사용자 결정): 인구가 한도에 닿거나 넘으면 파일런을 하나 요청한다. 목표가 없으면 손대지 않는다. 한도 200 제외."""
        if self.goal is None:
            return
        total, in_use = int(snap["supply_total"]), int(snap["supply_in_use"])
        if total >= 200 or in_use + 2 <= total:
            return
        b = snap["buildings"]["pylon"]
        coming = len(b.get("building", [])) + len(b.get("pending", [])) + sum(1 for r in snap.get("requests", []) if r["state"] == "queued" and r["action"] == 1)
        if coming:
            return
        avail = int(snap["minerals"]) - int(snap["reserved_minerals"])
        if avail < 100:
            return
        ack = self.client.request(1)
        if ack["accepted"]:
            self.sent_since_obs = True
            self.log(f"[인구 유지] {in_use}/{total} → 파일런 요청")
            if self.ev:
                self.ev.write("request", snap["frame"], action=1, accepted=True, request_id=ack["request_id"], reason="supply maintenance")

    def fill_workers(self, snap):
        w = snap.get("workers") or {}
        bases = snap.get("bases") or []
        ready_bases = sum(1 for b in bases if b.get("done")) or 1
        if self.worker_target_auto:
            self.worker_target = 16 * ready_bases
        if self.worker_target <= 0:
            return
        have = int(w.get("total", 0)) + sum(int(b.get("queue", 0)) for b in bases)
        if have >= self.worker_target:
            return
        queued = [r for r in snap.get("requests", []) if r["state"] == "queued"]
        # 목표 명령이 '돈'을 기다리는 중이면 끼어들지 않는다(그 돈을 뺏지 않게). 건물·포지 완성 등 다른 것을 기다리면
        # 그 명령의 비용을 남기고 여유가 있을 때만 보충한다 (2026-11-08: 쉴드업이 포지를 기다리는 동안 일꾼 보충이 멈췄다)
        if any(r.get("reason", "") in ("", "minerals", "gas", "supply") for r in queued):
            return
        held = sum(COST.get(r["action"], 0) for r in queued)
        avail = int(snap["minerals"]) - int(snap["reserved_minerals"]) - held
        if avail < 50 or sum(int(b.get("queue", 0)) for b in bases) >= 2 * ready_bases:
            return
        if int(snap["supply_in_use"]) + 1 > int(snap["supply_total"]):
            if int(snap["supply_total"]) >= 200 or building_count(snap, "pylon") > building_count(snap, "pylon", include_pending=False) or len((snap["buildings"]["pylon"]).get("building", [])):
                return
            if avail >= 100:
                self.client.request(1)
                self.log("[일꾼 목표] 인구 막힘 → 파일런")
                self.sent_since_obs = True
            return
        ack = self.client.request(0)
        if ack["accepted"]:
            self.sent_since_obs = True
            self.log(f"[일꾼 보충] {have + 1}/{self.worker_target}")

    # ---------------- 표시
    def status_line(self):
        s = self.snap or {}
        q = ", ".join((f"예비 m{i.minerals} g{i.gas}" if i.intent == "reserve" else f"{i.unit}{i.count}") for i in self.queue) or "-"
        g = self.goal.describe() if self.goal else "-"
        reqs = [r for r in s.get("requests", []) if r["state"] in ("queued", "issued")]
        rq = rle(f"{HUD_LETTER.get(r['action'], '?')}:{r['state'][0]}" for r in reqs) or "-"
        ws = s.get("watches") or []
        wt = ", ".join(f"{w['type'].replace('Protoss_', '')}({w['builder']} @{w.get('x')},{w.get('y')} 재시도 {w['retries']})" for w in ws) or "-"
        return (f"[상태] 목표 {g} / 요청 {rq} / 큐 {q} / 예비 m{self.reserve['minerals']} g{self.reserve['gas']} / 일꾼 목표 {self.worker_target} / "
                f"프레임 {s.get('frame')} 미네랄 {s.get('minerals')} 가스 {s.get('gas')} 인구 {s.get('supply_in_use')}/{s.get('supply_total')} "
                f"일꾼 {(s.get('workers') or {}).get('total')} / 건설 감시 {wt} / 집결지 {(s.get('rally') or {}).get('mode', '-')} / 위협 {s.get('threat')}")

    # ---------------- 상태 저장·복원
    def state_dict(self, snap):
        return {"version": 1, "game_id": snap.get("game_id"), "frame": int(snap["frame"]), "saved_at": time.time(),
                "queue": [dataclasses.asdict(i) for i in self.queue],
                "goal": self.goal.to_dict() if self.goal else None,
                "reserve": dict(self.reserve), "worker_target": self.worker_target, "worker_target_auto": self.worker_target_auto}

    def save_state(self, snap):
        """틱마다 부르지만 내용(프레임 제외)이 바뀌었거나 240프레임이 지났을 때만 쓴다."""
        if not self.state_file:
            return
        st = self.state_dict(snap)
        key = json.dumps({k: v for k, v in st.items() if k not in ("frame", "saved_at")}, sort_keys=True, ensure_ascii=False)
        if key == self.last_state_key and st["frame"] - getattr(self, "last_state_frame", -10 ** 9) < 240:
            return
        tmp = str(self.state_file) + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(st, f, ensure_ascii=False)
            os.replace(tmp, self.state_file)
            self.last_state_key, self.last_state_frame = key, st["frame"]
        except OSError:
            pass

    MAX_RESTORE_GAP = 2400  # 게임 식별자가 없을 때(이전 실행기·가짜 실행기): 저장 뒤 이 프레임 안에서만 같은 게임으로 본다

    def restore_state(self, snap) -> bool:
        """같은 게임이면 저장한 큐·목표·예비·일꾼 목표를 이어 받는다. 게임 판정: game_id 가 둘 다 있으면 같아야 하고,
        없으면 저장 프레임 ≤ 지금 프레임 ≤ 저장 프레임 + MAX_RESTORE_GAP."""
        if not self.state_file or not os.path.exists(self.state_file):
            return False
        try:
            with open(self.state_file, encoding="utf-8") as f:
                st = json.load(f)
        except (OSError, ValueError):
            return False
        if st.get("version") != 1:
            return False
        gid_now, gid_saved = snap.get("game_id"), st.get("game_id")
        f_now, f_saved = int(snap["frame"]), int(st.get("frame", -1))
        if gid_now and gid_saved:
            same = gid_now == gid_saved and f_now >= f_saved
        else:
            same = f_saved <= f_now <= f_saved + self.MAX_RESTORE_GAP
        if not same:
            return False
        self.queue = [Intent(**d) for d in st.get("queue", [])]
        self.goal = Goal.from_dict(st["goal"]) if st.get("goal") else None
        self.reserve = {"minerals": int(st["reserve"]["minerals"]), "gas": int(st["reserve"]["gas"])}
        self.worker_target, self.worker_target_auto = int(st.get("worker_target", 0)), bool(st.get("worker_target_auto", True))
        if self.reserve["minerals"] or self.reserve["gas"]:
            self.client.set_reserve(self.reserve["minerals"], self.reserve["gas"])
        if self.ev:
            self.ev.write("restore", f_now, saved_frame=f_saved, state=st)
        g = self.goal.describe() if self.goal else "-"
        self.log(f"[복원] 프레임 {f_saved} 저장분: 목표 {g} (기준값 {self.goal.baseline if self.goal else '-'}), 큐 {len(self.queue)}개, "
                 f"예비 m{self.reserve['minerals']} g{self.reserve['gas']}, 일꾼 목표 {self.worker_target}{'(자동)' if self.worker_target_auto else ''}")
        return True

    def write_status(self, snap):
        if not self.status_file:
            return
        import json, os, time as _t
        reqs = [r for r in snap.get("requests", []) if r["state"] in ("queued", "issued")]
        st = {"time": _t.time(), "frame": snap["frame"],
              "goal": {"desc": self.goal.describe(), "unit": self.goal.unit, "count": self.goal.count, "progress": self.goal.progress(snap)} if self.goal else None,
              "queue": [({"intent": "reserve", "minerals": i.minerals, "gas": i.gas} if i.intent == "reserve" else {"intent": "produce", "unit": i.unit, "count": i.count}) for i in self.queue],
              "requests": [{"action": r["action"], "state": r["state"], "reason": r.get("reason", "")} for r in reqs],
              "reserve": self.reserve, "worker_target": self.worker_target,
              "minerals": snap["minerals"], "gas": snap["gas"], "supply_in_use": snap["supply_in_use"], "supply_total": snap["supply_total"],
              "workers": snap["workers"]["total"], "threat": snap["threat"]}
        tmp = str(self.status_file) + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(st, f, ensure_ascii=False)
            os.replace(tmp, self.status_file)
        except OSError:
            pass

    @staticmethod
    def upgrade_lines(snap):
        """업그레이드 상태: 진행 중이면 '다음 레벨 남은 초', 아니면 현재 레벨 (예: 'weapons L1 52s', 'shields L0')."""
        out = []
        for key, short in (("weapons", "W"), ("armor", "A"), ("shields", "S")):
            u = (snap.get("upgrades") or {}).get(key) or {}
            lvl = int(u.get("level", 0))
            if u.get("upgrading"):
                out.append(f"+{short} L{lvl + 1} {int(u.get('remaining', 0)) // 24}s")
            elif lvl:
                out.append(f"+{short} L{lvl}")
        return out

    def update_hud(self, snap):
        reqs = [r for r in snap.get("requests", []) if r["state"] in ("queued", "issued")]
        plan = rle(HUD_LETTER.get(r["action"], "?") + ("*" if r["state"] == "issued" else "") for r in reqs) or "-"
        q = " > ".join((f"reserve m{i.minerals} g{i.gas}" if i.intent == "reserve" else f"{i.unit}{i.count}") for i in self.queue) or "-"
        g = self.goal.describe() if self.goal else "-"
        prog = f" {self.goal.progress(snap)}/{self.goal.count}" if self.goal else ""
        text = (f"goal: {g}{prog}  requests: {plan}|queue: {q}|reserve: m{self.reserve['minerals']} g{self.reserve['gas']}  "
                f"workers {snap['workers']['total']}/{self.worker_target}|threat: {snap['threat']['enemies_near']} near, lost {snap['threat']['lost_units']}u {snap['threat']['lost_buildings']}b")
        ups = self.upgrade_lines(snap)
        if ups:
            text += "|upgrades: " + "  ".join(ups)
        if text != self.last_hud:
            self.client.hud(text)
            self.last_hud = text
        # 우측 하단 진행률: 현재 목표의 진행 수와 예상 남은 시간
        if self.goal:
            g = self.goal
            frac = min(1.0, g.progress(snap) / max(1, g.count))
            eta = ""
            if g.plan and g.plan.end_frame:
                eta = f"  ETA {max(0, int((g.plan.end_frame - snap['frame']) / 24))}s"
            ptext = f"{g.describe()}  {g.progress(snap)}/{g.count}{eta}  (queue {len(self.queue)})"
            permille = int(frac * 1000)
        else:
            ptext, permille = (f"idle  (queue {len(self.queue)})", -1)
        ups = self.upgrade_lines(snap)
        running = [u for u in ups if u.endswith("s")]
        if running:
            ptext += "  |  " + " ".join(running)
        if (ptext, permille) != getattr(self, "last_progress", None):
            try:
                self.client.progress(ptext, permille)
            except Exception:
                pass
            self.last_progress = (ptext, permille)
