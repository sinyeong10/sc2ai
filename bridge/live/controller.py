"""제어 루프. 틱마다: 관측 → 입력 반영 → 편차 검사 → (재)계획 → 발행 → 로그 → HUD. 어디서도 막히지 않는다.

목표 의미(사용자 결정 2026-11-08):
- 큐는 친 순서, 목표 하나 = "지금 상태에서 가장 빨리". 합치지 않는다.
- 완료 판정은 수량: 유닛은 (완성 + 생산 중) 수, 건물은 (완성 + 건설 중 + 명령됨) 수가 목표 시작 시점 기준값 + 요청 수 이상이면 끝.
  사람이 지은 것도 센다 (재계산 뒤 계획에서 사라지므로).
- 예비 자원은 큐의 그 자리에서 효력. 사람이 그 돈을 쓰면 해제.
- 일꾼 목표는 상시 제약(기본 기지당 16). 피격 중 특별 처리 없음.
계획의 명령은 전부 실행기에 비동기 요청으로 보낸다(실행기가 순서대로 조건이 되는 첫 프레임에 실행). 재계획하면 아직 실행
안 된(queued) 요청을 취소하고 새 계획을 보낸다. 이미 나간 건설은 실행기가 끝까지 책임진다.
"""
from __future__ import annotations

import time

from live.intents import ARMY, BUILDINGS, EXEC_ACTION, ACTION_UNIT, HUD_LETTER, Intent, parse_text
from live.planner import Plan, building_count, plan_goal, unit_count

UNIT_KEY = {"nexus": "nexus", "pylon": "pylon", "gateway": "gateway", "assimilator": "assimilator", "core": "core", "citadel": "citadel", "archives": "archives"}
COST = {0: 50, 1: 100, 2: 150, 3: 100, 4: 400, 5: 100, 6: 200, 7: 125, 10: 150, 11: 150, 12: 50, 13: 125}
REPLAN_PERIOD = 600        # 프레임. 주기적 재검증 (사람의 변경·자원 편차를 흡수)
LATE_FRAMES = 300          # 예상보다 이만큼 늦으면 편차


class Goal:
    def __init__(self, intent: Intent, snap):
        self.intent = intent
        self.unit = intent.unit
        self.count = intent.count
        self.baseline = self._measure(snap)
        self.started = int(snap["frame"])
        self.plan: Plan | None = None
        self.planned_at = -1
        self.request_ids: list[int] = []
        self.replans = 0

    def _measure(self, snap):
        if self.unit in ARMY:
            return unit_count(snap, self.unit)
        if self.unit == "worker":
            return unit_count(snap, "probe")
        return building_count(snap, UNIT_KEY[self.unit])

    def progress(self, snap):
        return max(0, self._measure(snap) - self.baseline)

    def remaining(self, snap):
        return max(0, self.count - self.progress(snap))

    def done(self, snap):
        return self.remaining(snap) == 0

    def describe(self):
        return f"{self.unit}{self.count}"


class Controller:
    def __init__(self, client, P, log=print, eventlog=None, beam=800, status_file=None):
        self.client, self.P, self.log, self.ev, self.beam = client, P, log, eventlog, beam
        self.status_file = status_file  # 음성 게이트웨이가 읽어 "지금 뭐 하고 있어?" 에 답하는 상태 파일
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
            if it.intent == "produce" and it.unit not in ARMY + BUILDINGS + ("worker",):
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
        remaining = g.remaining(snap)
        if remaining == 0:
            return
        # 실행 전 요청은 취소하고 새로 보낸다
        n = self.client.cancel()
        plan = plan_goal(self.P, snap, g.unit, remaining, {"beam": self.beam})
        g.plan, g.planned_at, g.replans = plan, int(snap["frame"]), g.replans + (0 if why == "new goal" else 1)
        if self.ev:
            self.ev.write("plan", snap["frame"], goal=g.describe(), remaining=remaining, why=why, actions=plan.actions,
                          expected_frames=plan.expected_frames, end_frame=plan.end_frame, note=plan.reason, seconds=round(plan.seconds, 2), cancelled=n)
        names = [ACTION_UNIT.get(a, a) for a in plan.actions]
        self.log(f"[계획] {g.describe()} 남은 {remaining}: {names} 예상 완료 {plan.end_frame} ({why}, {plan.reason}, {plan.seconds:.1f}s)")
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
        reqs = {r["id"]: r for r in snap.get("requests", [])}
        mine = [reqs[i] for i in g.request_ids if i in reqs]
        failed = [r for r in mine if r["state"] == "failed" and r.get("reason") != "cancelled"]
        if failed:
            why = "; ".join(f"{ACTION_UNIT.get(r['action'], r['action'])}: {r['reason']}" for r in failed)
            self.log(f"[실패] {why} → 재계획")
            if self.ev:
                self.ev.write("deviation", snap["frame"], kind="request_failed", detail=why)
            # 실패 횟수는 라운드(재계획 한 번)당 1회로 센다. 인구 부족은 파일런으로 풀리므로 포기 사유가 아니다
            fc = getattr(g, "fail_counts", {})
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
        # 주기적 재검증과 늦어짐 편차
        late = False
        if g.plan and g.plan.expected_frames:
            for r, exp in zip(mine, g.plan.expected_frames):
                if r["state"] == "queued" and exp is not None and snap["frame"] > exp + LATE_FRAMES:
                    late = True
                    break
        lost = self.prev and (snap["threat"]["lost_buildings"] > self.prev["threat"]["lost_buildings"])
        if lost or late or snap["frame"] - g.planned_at >= REPLAN_PERIOD:
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
        if queued:
            return  # 목표 명령이 기다리는 중엔 끼어들지 않는다
        avail = int(snap["minerals"]) - int(snap["reserved_minerals"]) - 0
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
        rq = " ".join(f"{HUD_LETTER.get(r['action'], '?')}:{r['state'][0]}" for r in reqs) or "-"
        ws = s.get("watches") or []
        wt = ", ".join(f"{w['type'].replace('Protoss_', '')}({w['builder']} @{w.get('x')},{w.get('y')} 재시도 {w['retries']})" for w in ws) or "-"
        return (f"[상태] 목표 {g} / 요청 {rq} / 큐 {q} / 예비 m{self.reserve['minerals']} g{self.reserve['gas']} / 일꾼 목표 {self.worker_target} / "
                f"프레임 {s.get('frame')} 미네랄 {s.get('minerals')} 가스 {s.get('gas')} 인구 {s.get('supply_in_use')}/{s.get('supply_total')} "
                f"일꾼 {(s.get('workers') or {}).get('total')} / 건설 감시 {wt} / 위협 {s.get('threat')}")

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

    def update_hud(self, snap):
        reqs = [r for r in snap.get("requests", []) if r["state"] in ("queued", "issued")]
        plan = " ".join(HUD_LETTER.get(r["action"], "?") + ("*" if r["state"] == "issued" else "") for r in reqs) or "-"
        q = " > ".join((f"reserve m{i.minerals} g{i.gas}" if i.intent == "reserve" else f"{i.unit}{i.count}") for i in self.queue) or "-"
        g = self.goal.describe() if self.goal else "-"
        prog = f" {self.goal.progress(snap)}/{self.goal.count}" if self.goal else ""
        text = (f"goal: {g}{prog}  requests: {plan}|queue: {q}|reserve: m{self.reserve['minerals']} g{self.reserve['gas']}  "
                f"workers {snap['workers']['total']}/{self.worker_target}|threat: {snap['threat']['enemies_near']} near, lost {snap['threat']['lost_units']}u {snap['threat']['lost_buildings']}b")
        if text != self.last_hud:
            self.client.hud(text)
            self.last_hud = text
