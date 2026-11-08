"""사람과 함께: 사람이 목표(예 "질럿 3")를 넣으면 현재 게임 상태에서 최적 명령열을 계산해 실행한다.

    py -X utf8 bridge/live_assistant.py --backend bwapi-win [--intent-file bridge/results/intents.txt]

목표 입력 통로 (모두 같은 Intent 로 바뀐다 — 나중에 음성/Dialogflow 같은 의도 인식기를 붙일 자리):
  1. 게임 채팅창: "질럿 3", "zealot 3", "z3", "일꾼 2", "파일런", "게이트 2". 실행기가 text 메시지로 전달한다.
  2. 의도 파일(--intent-file): 한 줄에 JSON 하나를 덧붙이면 읽는다. 예 {"intent":"produce","unit":"zealot","count":3}
     음성 인식기·Dialogflow webhook 은 이 파일(또는 같은 꼴의 JSON)만 쓰면 된다.

처리: 실행기에 라이브 모드로 붙고(게임을 멈추지 않음, 재시작 없음), 목표가 오면 step(8) 로 스냅샷을 받아
sc1_sim.from_snapshot 으로 시뮬레이터를 현재 상태에 맞춘 뒤 빔 탐색으로 명령열을 구해 하나씩 실행한다.
실행 중 새 목표가 오면 남은 목표에 더해 다시 계획한다. 사람은 유닛 조작·전투를 맡고, 생산 명령은 전부 여기서 낸다.
지원 유닛: 질럿(실행기 행동 0~3). 드라군은 실행기에 가스·코어·드라군 행동을 넣은 뒤 ExpSim 으로 붙인다.
"""
import argparse
import dataclasses
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sc1_sim as ss  # noqa: E402
import expansion_estimate as ee  # noqa: E402
from env import make_env  # noqa: E402

ACTION_NAMES = {0: "일꾼", 1: "파일런", 2: "게이트", 3: "질럿", 4: "넥서스", 5: "어시밀레이터", 6: "코어", 7: "드라군",
                10: "성채", 11: "아카이브", 12: "하이템플러", 13: "다크템플러"}
HUD_LETTER = {0: "W", 1: "P", 2: "G", 3: "Z", 4: "N", 5: "A", 6: "C", 7: "D", 10: "I", 11: "R", 12: "T", 13: "K"}
ARMY = ("zealot", "dragoon", "high_templar", "dark_templar")
UNIT_WORDS = {
    "zealot": ("질럿", "zealot", "zeal", "z"),
    "dragoon": ("드라군", "dragoon", "goon", "d"),
    "high_templar": ("템플러", "하이템플러", "templar", "high", "ht", "t"),
    "dark_templar": ("다크", "다크템플러", "dark", "dt", "k"),
    "nexus": ("멀티", "넥서스", "nexus", "expand", "multi", "n"),
    "worker": ("일꾼", "프로브", "probe", "worker", "w", "p"),
    "pylon": ("파일런", "pylon"),
    "gateway": ("게이트", "게이트웨이", "gateway", "gate", "g"),
}


@dataclasses.dataclass
class Intent:
    intent: str                 # "produce" | "status" | "cancel" | "reserve"
    unit: str | None = None     # zealot | dragoon | worker | pylon | gateway
    count: int = 1
    source: str = "text"
    raw: str = ""
    minerals: int = 0           # reserve: 남길 미네랄
    gas: int = 0                # reserve: 남길 가스


def parse_text(text: str) -> Intent | None:
    """채팅 한 줄 → Intent. 단순 규칙. 의도 인식기를 붙이면 이 함수를 대체한다."""
    t = text.strip().lower()
    if not t:
        return None
    if t in ("상태", "status", "/s"):
        return Intent("status", source="text", raw=text)
    if t in ("rebalance", "move", "이전"):
        return Intent("rebalance", source="text", raw=text)
    if t in ("취소", "cancel", "stop"):
        return Intent("cancel", source="text", raw=text)
    m = re.match(r"^(wt|workers|일꾼목표)\s*(\d+)$", t)
    if m:
        return Intent("worker_target", source="text", raw=text, count=int(m.group(2)))
    m = re.match(r"^(r|reserve|keep|예비)\s*m?(\d+)(?:\s*g?(\d+))?$", t)
    if m:
        return Intent("reserve", source="text", raw=text, minerals=int(m.group(2)), gas=int(m.group(3) or 0))
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
    if d.get("intent") == "worker_target":
        return Intent("worker_target", source="file", raw=line, count=int(d.get("count", 0)))
    if d.get("intent") == "reserve":
        return Intent("reserve", source="file", raw=line, minerals=int(d.get("minerals", 0)), gas=int(d.get("gas", 0)))
    if d.get("intent") != "produce":
        return Intent(d.get("intent", "?"), source="file", raw=line)
    return Intent("produce", d.get("unit"), int(d.get("count", 1)), source="file", raw=line)


class IntentFile:
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


class Assistant:
    """명령 큐: 들어온 순서대로 하나씩 처리한다(순차 최적화). "z2" 는 2기를 가장 빨리, 그 2기가 완성된 시점의 상태에서
    다음 명령을 다시 가장 빨리. "z4" 와 "z2, z2" 는 다른 문제다. reserve 는 큐의 그 자리에서 효력을 낸다.
    묶음의 끝 = 명령을 모두 내린 시점(생산에 들어가면 완료). 다음 명령은 그 상태(큐에 든 질럿·짓는 중인 건물 포함)에서 계획한다.
    상태는 로그·채팅 's'·화면 HUD 로 보인다."""

    COST = {0: 50, 1: 100, 2: 150, 3: 100, 4: 400, 5: 100, 6: 200, 7: 125, 10: 150, 11: 150, 12: 50, 13: 125}

    def __init__(self, env, P, beam=800, log=print):
        self.env, self.P, self.beam, self.log = env, P, beam, log
        self.queue: list[Intent] = []        # 아직 시작하지 않은 명령 (produce / reserve)
        self.batch_zealots = 0               # 지금 묶음에서 아직 명령 안 낸 질럿 수
        self.batch_extra = {"worker": 0, "pylon": 0, "gateway": 0, "nexus": 0}
        self.batch_desc = ""                 # 지금 묶음 설명 (HUD 용)
        self.batch_unit = "zealot"           # 지금 묶음의 병력 종류
        self.plan: list[int] = []            # 지금 묶음의 남은 명령
        self.current: str = ""               # 지금 실행 중인 명령 설명
        self.batch_wait_completed = None     # 이 완성 질럿 수에 이르면 묶음 종료 (None 이면 명령을 다 내리면 끝)
        self.batch_buildings: list[str] = []  # 이 묶음이 명령한 건물 유형(실행기 이름). 전부 놓여야 묶음 종료 (실행 보장)
        self.obs = None
        self.issued_builds = {1: [], 2: []}
        self.reserve = {"minerals": 0, "gas": 0}
        self.worker_target = 0               # 일꾼 목표(wt N): 묶음이 없을 때 여유 자원으로 여기까지 일꾼을 뽑는다
        self.worker_target_auto = True       # wt 를 안 쳤으면 기지당 16기(덩이당 2기)를 자동 목표로 쓴다
        self.executor_reserve = False
        self.executor_hud = True
        self.last_hud = None
        self.last_avail = None               # 직전 스냅샷의 '쓸 수 있는' 미네랄 (예비 제외, 예약 건설비 제외)
        self.cmd_since_snapshot = False      # 직전 스냅샷 뒤 어시스턴트가 명령을 냈는가

    # ---- 관측
    def snapshot(self, frames=2):
        self.obs = self.env.step(8, frames=frames)
        ex = self.obs.extra or {}
        if "reserved_minerals" not in ex:
            now = self.obs.frame
            pend_p = max(0, len(self.issued_builds[1]) - (int(ex.get("pylons_ready", 0)) + len(ex.get("pylons_building", []))))
            pend_g = max(0, len(self.issued_builds[2]) - (int(ex.get("gateways_ready", 0)) + len(ex.get("gateways_building", []))))
            ex["pylons_pending_elapsed"] = [now - f for f in self.issued_builds[1][-pend_p:]] if pend_p else []
            ex["gateways_pending_elapsed"] = [now - f for f in self.issued_builds[2][-pend_g:]] if pend_g else []
            ex["reserved_minerals"] = 100 * pend_p + 150 * pend_g
        if "reserve_gas" not in ex:
            ex["reserved_minerals"] = int(ex.get("reserved_minerals", 0)) + self.reserve["minerals"]
        self.obs.extra = ex
        ab = ex.get("abandoned") or []
        if ab:
            self.log(f"[건설 포기] 실행기가 포기: {ab} → 현재 묶음을 다시 계획")
            for b in ab:
                if b in self.batch_buildings:
                    self.batch_buildings.remove(b)
            self._need_replan = True
        # 사람이 예비 자원을 직접 썼는지: 어시스턴트가 명령을 내지 않았는데 쓸 수 있는 미네랄이 줄었으면 예비 해제
        avail = int(self.obs.state[0]) - max(0, int(ex.get("reserved_minerals", 0)) - self.reserve["minerals"])
        if (self.reserve["minerals"] > 0 and not self.cmd_since_snapshot and self.last_avail is not None
                and self.last_avail - avail >= 40):
            self.log(f"[예비 해제] 사람이 자원을 직접 썼다 (쓸 수 있는 미네랄 {self.last_avail} → {avail}). 예비 m{self.reserve['minerals']} g{self.reserve['gas']} 를 0 으로")
            self.reserve = {"minerals": 0, "gas": 0}
            try:
                self.env.set_reserve(0, 0)
            except Exception:
                pass
            self.update_hud()
        self.last_avail = avail
        self.cmd_since_snapshot = False
        return self.obs

    # ---- 입력
    def handle(self, it: Intent):
        if it.intent == "status":
            self.log(self.status_line(full=True))
            return
        if it.intent == "cancel":
            self.queue, self.plan, self.batch_zealots = [], [], 0
            self.batch_wait_completed = None
            self.batch_buildings = []
            self.batch_extra = {k: 0 for k in self.batch_extra}
            self.batch_desc, self.current = "", ""
            self.log("[취소] 큐와 남은 계획을 비웠다 (이미 내린 명령은 그대로)")
            self.update_hud()
            return
        if it.intent == "rebalance":
            try:
                r = self.env.rebalance()
                self.log(f"[이전] 본진 초과 일꾼을 멀티로: {'됨' if r.get('rebalanced') else '멀티 넥서스 없음 또는 미지원'}")
            except Exception as e:
                self.log(f"[이전] 실패: {e}")
            return
        if it.intent == "worker_target":
            self.worker_target = it.count
            self.worker_target_auto = False
            self.log(f"[일꾼 목표] {it.count}기 (묶음이 없을 때 예비 자원을 넘는 여유로 채운다)")
            self.update_hud()
            return
        if it.intent == "reserve":
            self.queue.append(it)
            self.log(f"[큐] 예비 미네랄 {it.minerals} 가스 {it.gas} — 앞의 명령이 끝난 뒤 적용 (큐 {len(self.queue)}개)")
            self.update_hud()
            return
        if it.intent != "produce":
            self.log(f"[무시] 모르는 의도 {it}")
            return
        if it.unit not in ARMY + ("worker", "pylon", "gateway", "nexus"):
            self.log(f"[무시] 모르는 유닛 {it.unit}")
            return
        self.queue.append(it)
        self.log(f"[큐] {it.unit} +{it.count} (출처 {it.source}: {it.raw!r}) (큐 {len(self.queue)}개, 앞 묶음이 끝난 뒤 그 상태에서 계획)")
        self.update_hud()

    def _add_to_batch(self, it: Intent):
        if it.unit in ARMY:
            self.batch_zealots += it.count
            self.batch_unit = it.unit
        else:
            self.batch_extra[it.unit] += it.count
        self.batch_desc = (self.batch_desc + " " if self.batch_desc else "") + f"{it.unit}{it.count}"

    # ---- 큐 진행
    BUILD_TYPE = {1: "Protoss_Pylon", 2: "Protoss_Gateway", 4: "Protoss_Nexus", 5: "Protoss_Assimilator", 6: "Protoss_Cybernetics_Core",
                  10: "Protoss_Citadel_of_Adun", 11: "Protoss_Templar_Archives"}

    def pending_builds(self):
        """이 묶음이 명령했지만 아직 놓이지 않은 건물 (실행기 watches 기준)."""
        if self.obs is None:
            return []
        ws = (self.obs.extra or {}).get("watches")
        if ws is None:
            return []  # 구버전 실행기: 알 수 없으니 기다리지 않는다
        pending = [w["type"] for w in ws]
        return [b for b in self.batch_buildings if b in pending]

    def batch_active(self):
        if self.plan or self.batch_zealots > 0:
            return True
        if self.batch_buildings:
            left = self.pending_builds()
            if left:
                return True  # 건물이 놓일 때까지 묶음 유지 (실행 보장)
            self.batch_buildings = []
        if self.batch_wait_completed is not None:
            done = int((self.obs.extra or {}).get("zealots_completed", 0)) if self.obs is not None else 0
            if done >= self.batch_wait_completed:
                self.log(f"[완료] {self.batch_desc}: 질럿 완성 {done}기 (프레임 {self.obs.frame}) → 다음 명령을 이 상태에서 계획")
                self.batch_wait_completed = None
                return False
            return True
        return False

    def advance(self):
        """묶음이 끝났으면 큐에서 다음 의도 하나를 꺼내 계획한다. 처리할 것이 있으면 True."""
        if self.batch_active():
            return True
        self.batch_desc, self.current = "", ""
        while self.queue:
            it = self.queue.pop(0)
            if it.intent == "reserve":
                self.reserve = {"minerals": it.minerals, "gas": it.gas}
                try:
                    r = self.env.set_reserve(it.minerals, it.gas)
                    self.executor_reserve = r.get("type") == "status"
                except Exception:
                    self.executor_reserve = False
                self.log(f"[예비 적용] 미네랄 {it.minerals}, 가스 {it.gas} ({'실행기' if self.executor_reserve else '어시스턴트 확인'})")
                continue
            self._add_to_batch(it)
            # 묶음의 끝 = 명령을 모두 내린 시점(생산에 들어가면 완료). 완성까지 기다리지 않는다 (사용자 결정 2026-11-08)
            self.batch_wait_completed = None
            self.replan()
            return True
        self.update_hud()
        return False

    def replan(self):
        o = self.snapshot()
        self.plan = []
        for unit, a in (("nexus", 4), ("pylon", 1), ("gateway", 2), ("worker", 0)):
            self.plan += [a] * self.batch_extra[unit]
            self.batch_extra[unit] = 0
        if self.batch_zealots > 0:
            unit = self.batch_unit
            sim = ee.exp_from_snapshot(self.P, o, unit, self.batch_zealots)
            t0 = time.time()
            # 묶음 계획의 일꾼은 기지당 덩이 2배수(16기)까지만. 그 이상의 경제 투자는 wt/w 명령 몫 (사용자 결정 2026-11-08)
            bases = 1 + len(sim.bases_done)
            workers_now = int(o.state[4]) + int((o.extra or {}).get("nexus_queue", 0))
            max_new_workers = max(0, 16 * bases - workers_now)
            top, n = ee.beam_from(sim, unit, self.batch_zealots, self.beam, max_new_gates=2, max_new_workers=max_new_workers)
            if top:
                end, seq = top[0]
                # 시뮬레이터 행동 3(병력) → 실행기 행동 번호
                self.plan += [ee.EXEC_ACTION[unit] if a == 3 else a for a in seq]
                seq = tuple(ee.EXEC_ACTION[unit] if a == 3 else a for a in seq)
                self.log(f"[계획] 프레임 {o.frame} 기준 {self.batch_desc}: 예상 완성 {end} (+{end - o.frame}), "
                         f"명령열 {[ACTION_NAMES[a] for a in seq]} ({n}개 후보, {time.time() - t0:.1f}s)")
            else:
                self.log("[계획 실패] 실행 가능한 명령열을 못 찾았다. 파일런/게이트를 직접 지정해 보라")
                self.batch_zealots = 0
        self.update_hud()

    def run_one(self):
        if getattr(self, "_need_replan", False):
            self._need_replan = False
            self.replan()
        if not self.plan:
            if self.batch_buildings and self.pending_builds():
                self.current = "placing " + ",".join(b.replace("Protoss_", "") for b in self.pending_builds())
                self.update_hud()
                self.snapshot(frames=24)
                self.drain_inputs()
                return False
            if self.batch_wait_completed is not None:
                self.current = "waiting zealots"
                self.update_hud()
                self.snapshot(frames=24)
                self.drain_inputs()
            return False
        a = self.plan[0]
        self.current = ACTION_NAMES.get(a, str(a))
        self.update_hud()
        cost = self.COST.get(a, 0)
        if self.reserve["minerals"] > 0 and not self.executor_reserve:
            while True:
                o = self.snapshot(frames=12)
                reserved = int((o.extra or {}).get("reserved_minerals", 0)) - self.reserve["minerals"]
                if o.state[0] - max(0, reserved) - self.reserve["minerals"] >= cost:
                    break
                if self.drain_inputs(stop_on_control=True):
                    return True
        self.plan.pop(0)
        self.cmd_since_snapshot = True
        o = self.env.step(a)
        self.last_avail = None  # 명령으로 잔량이 바뀌었으니 다음 스냅샷부터 다시 본다
        if not o.accepted:
            err = o.error or ""
            if a in (3, 7, 12, 13):
                self.batch_zealots = max(self.batch_zealots, 1)
            if "maxed" in err or (self.obs is not None and int(self.obs.state[2]) >= 200):  # 사용 인구가 200 일 때만
                # 인구 200: 파일런으로 해결되지 않는다. 이 묶음의 남은 병력 명령은 포기한다
                self.log(f"[거부] {ACTION_NAMES.get(a, a)}: 인구 한도 200. 이 묶음의 남은 명령을 포기한다 (유닛이 줄면 다시 명령)")
                self.plan = [x for x in self.plan if x in (1, 2, 4, 5, 6, 10, 11)]  # 건물만 남긴다
                self.batch_zealots = 0
                self.update_hud()
                return True
            if "supply" in err:
                # 실행기 기준 인구가 꽉 참: 같은 계획을 되풀이하지 말고 파일런을 앞에 끼운 뒤 그 명령을 다시 시도한다
                self.plan = [1, a] + self.plan
                self.log(f"[거부] {ACTION_NAMES.get(a, a)}: {err} → 파일런을 먼저 짓고 다시 시도")
                return True
            self.log(f"[거부] {ACTION_NAMES.get(a, a)}: {err} → 다시 계획")
            self.replan()
            return True
        if a in (3, 7, 12, 13):
            self.batch_zealots -= 1
        if a in self.issued_builds:
            self.issued_builds[a].append(o.frame)
        if a in self.BUILD_TYPE:
            self.batch_buildings.append(self.BUILD_TYPE[a])
        self.log(f"[실행] {ACTION_NAMES.get(a, a)} @프레임 {o.frame} 미네랄 {o.state[0]} 인구 {o.state[2]}/{o.state[3]}")
        self.current = ""
        self.update_hud()
        return True

    def idle_workers(self, during_batch=False):
        """일꾼 목표 채우기. 묶음이 없으면 예비를 넘는 미네랄 50 이상일 때, 묶음 중이면 다음 명령 비용까지 남기고도 50 이 남을 때 한 기."""
        if self.obs is None:
            return False
        ex = self.obs.extra or {}
        if self.worker_target_auto:
            bases = int((ex.get("tech") or {}).get("nexus", {}).get("ready", 1)) or 1
            self.worker_target = 16 * bases
        if self.worker_target <= 0:
            return False
        have = int(self.obs.state[4]) + int(ex.get("nexus_queue", 0))
        if have >= self.worker_target:
            return False
        avail = int(self.obs.state[0]) - max(0, int(ex.get("reserved_minerals", 0)) - self.reserve["minerals"]) - self.reserve["minerals"]
        if during_batch:
            need_next = self.COST.get(self.plan[0], 0) if self.plan else 0
            if avail - need_next < 50 or int(ex.get("nexus_queue", 0)) >= 1:
                return False
            if int(self.obs.state[2]) + 1 > int(self.obs.state[3]):
                return False
            self.cmd_since_snapshot = True
            o = self.env.step(0)
            self.last_avail = None
            if o.accepted:
                self.log(f"[일꾼 보충] {have + 1}/{self.worker_target} @프레임 {o.frame} (묶음 중, 여유분)")
            return True
        if avail < 50 or int(ex.get("nexus_queue", 0)) >= 2:
            return False
        if int(self.obs.state[2]) + 1 > int(self.obs.state[3]):
            # 인구가 꽉 참: 짓는 중·명령된 파일런이 없고 미네랄이 되면 파일런 하나 (3배수까지 가려면 파일런이 더 필요하다)
            coming = len(ex.get("pylons_building", [])) + len(ex.get("pylons_pending_elapsed", []))
            if int(self.obs.state[3]) >= 200:
                return False  # 한도 200: 파일런 무의미
            if coming == 0 and avail >= 100:
                self.cmd_since_snapshot = True
                o = self.env.step(1)
                self.last_avail = None
                if o.accepted:
                    self.issued_builds[1].append(o.frame)
                    self.log(f"[일꾼 목표] 인구 {self.obs.state[2]}/{self.obs.state[3]} 막힘 → 파일런 @프레임 {o.frame}")
                return True
            return False
        self.cmd_since_snapshot = True
        o = self.env.step(0)
        self.last_avail = None
        if o.accepted:
            self.log(f"[일꾼 보충] {have + 1}/{self.worker_target} @프레임 {o.frame} 미네랄 {o.state[0]}")
        return True

    def drain_inputs(self, files=None, stop_on_control=False):
        """쌓인 채팅/파일 입력을 처리한다. stop_on_control: 취소·예비·상태가 오면 True 를 돌려준다."""
        hit = False
        for m in self.env.poll_inbox():
            if m.get("type") == "text":
                it = parse_text(m.get("text", ""))
                if it:
                    self.handle(it)
                    if it.intent in ("cancel", "reserve", "status"):
                        hit = True
        if files:
            for it in files.poll():
                self.handle(it)
        return hit and stop_on_control

    # ---- 상태 표시
    def status_line(self, full=False):
        o = self.obs
        q = ", ".join((f"예비 m{i.minerals} g{i.gas}" if i.intent == "reserve" else f"{i.unit}{i.count}") for i in self.queue) or "-"
        plan = " ".join(ACTION_NAMES.get(a, str(a)) for a in self.plan) or "-"
        wait = f" (완성 대기 {self.batch_wait_completed}기까지)" if self.batch_wait_completed is not None else ""
        head = f"지금: {self.batch_desc or '-'}{wait} / 실행 중: {self.current or '-'} / 남은 명령: {plan} / 대기 큐: {q} / 예비 m{self.reserve['minerals']} g{self.reserve['gas']}"
        if full and o is not None:
            head += (f" / 프레임 {o.frame} 미네랄 {o.state[0]} 가스 {o.extra.get('gas')} 인구 {o.state[2]}/{o.state[3]} 일꾼 {o.state[4]} "
                     f"게이트 {o.extra.get('gateways_ready')} 질럿 완성 {o.extra.get('zealots_completed')}")
            ws = o.extra.get("watches") or []
            if ws:
                head += " / 건설 감시: " + ", ".join(
                    f"{w['type'].replace('Protoss_', '')}(프로브 {w['builder']} @({w.get('x', '?')},{w.get('y', '?')}) → 자리 ({w.get('tx')},{w.get('ty')}), {w['age']}f, 재시도 {w['retries']})" for w in ws)
        return "[상태] " + head

    def update_hud(self):
        if not self.executor_hud:
            return
        q = " > ".join((f"reserve m{i.minerals} g{i.gas}" if i.intent == "reserve" else f"{i.unit}{i.count}") for i in self.queue) or "-"
        plan = " ".join(HUD_LETTER.get(a, "?") for a in self.plan) or "-"
        have = int(self.obs.state[0]) if self.obs is not None else 0
        en = {"일꾼": "worker", "파일런": "pylon", "게이트": "gateway", "질럿": "zealot", "넥서스": "nexus", "어시밀레이터": "assimilator", "코어": "core",
              "드라군": "dragoon", "성채": "citadel", "아카이브": "archives", "하이템플러": "high templar", "다크템플러": "dark templar"}
        now = en.get(self.current, self.current) or "-"   # 게임 폰트는 한글을 못 그린다
        text = (f"AI build: {self.batch_desc or '-'}  now: {now}|"
                f"plan: {plan}|queue: {q}|reserve: m{self.reserve['minerals']} g{self.reserve['gas']} (have m{have})  workers target: {self.worker_target or '-'}")
        if text == self.last_hud:
            return
        try:
            r = self.env.hud(text)
            if r.get("type") != "status":
                self.executor_hud = False
        except Exception:
            self.executor_hud = False
        self.last_hud = text


def make_allowed_from(sim0, target, max_new_gates, max_new_workers):
    """현재 상태 기준 행동 규칙. sc1_sim.make_allowed 는 새 게임(인구 4/9, 건물 없음)을 가정하므로 스냅샷에선 틀린다
    (2026-11-08: 인구 12/33 인데 질럿 3기째부터 파일런을 '필요'로 봐서 파일런·게이트를 헛되이 지었다)."""
    used0 = sim0.supply_used
    cap0 = sim0.cap_base if sim0.cap_base is not None else ss.START_CAP
    gates0 = len(sim0.gate_ready)              # 완성·건설 중·명령됨 모두
    pylons_coming = len(sim0.pylon_done)       # 건설 중·명령됨
    has_pylon = cap0 > ss.START_CAP or pylons_coming > 0

    def allowed(prefix):
        w, p, g, z = prefix.count(0), prefix.count(1), prefix.count(2), prefix.count(3)
        cap = cap0 + 8 * (p + pylons_coming)
        used = used0 + w + 2 * z
        acts = []
        if w < max_new_workers and z == 0:
            acts.append(0)
        if used + 2 * (target - z) + (max_new_workers - w if z == 0 else 0) > cap:
            acts.append(1)
        if (has_pylon or p >= 1) and g < max_new_gates:
            acts.append(2)
        if gates0 + g >= 1 and z < target and used + 2 <= cap:
            acts.append(3)
        return acts
    return allowed


def beam_from(sim0, target, width):
    """sc1_sim.beam_search 와 같은 계층화 빔이지만 주어진 시뮬레이터 상태에서 출발한다."""
    max_new_gates = max(0, max(1, min(6, (target + 1) // 2)) - len(sim0.gate_ready)) + 1
    allowed = make_allowed_from(sim0, target, max_new_gates, 8)
    beam = [(sim0, ())]
    finished = {}
    depth = 0
    while beam and depth < 60:
        cands = []
        for sim, prefix in beam:
            for a in allowed(prefix):
                s2 = sim.copy()
                if s2.step(a) is None:
                    continue
                seq = prefix + (a,)
                if s2.end is not None:
                    if seq not in finished or finished[seq] > s2.end:
                        finished[seq] = s2.end
                else:
                    cands.append((s2.lower_bound(), s2, seq))
        cands.sort(key=lambda c: (c[0], c[2]))
        buckets = {}
        for c in cands:
            buckets.setdefault((c[2].count(0), c[2].count(2)), []).append(c)
        per = max(1, width // max(1, len(buckets)))
        kept = []
        for items in buckets.values():
            kept.extend(items[:per])
        kept.sort(key=lambda c: (c[0], c[2]))
        if len(kept) < width:
            chosen = {id(c[1]) for c in kept}
            kept.extend(c for c in cands if id(c[1]) not in chosen)
        beam = [(s, seq) for _, s, seq in kept[:width]]
        depth += 1
    res = sorted((e, seq) for seq, e in finished.items())
    return res[:5], len(finished)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--backend", default="bwapi-win")
    ap.add_argument("--intent-file", default=None, help="JSON 줄을 덧붙이면 의도로 읽는 파일 (음성 인식기 연동용)")
    ap.add_argument("--beam", type=int, default=800)
    ap.add_argument("--poll-frames", type=int, default=24, help="목표 입력을 확인하는 간격(프레임). 24 ≈ 1초")
    ap.add_argument("--target", type=int, default=0, help="시작하자마자 넣을 질럿 목표")
    ap.add_argument("--opening", default="0,0,0,0,1",
                    help="붙자마자 고정으로 내리는 오프닝. 기본은 실측 최적(일꾼 8기까지 + 8/9 시점 파일런). 비우면 없음")
    args = ap.parse_args()

    P = dict(ss.DEFAULT_PARAMS)
    pp = Path(__file__).resolve().parent / "results" / "sc1_sim_params.json"
    if pp.exists():
        P.update(json.loads(pp.read_text(encoding="utf-8")))
    env = make_env(args.backend)
    print("실행기:", env.info, flush=True)
    o = env.reset(10**6, live=True, restart=False)
    print(f"라이브 모드. 프레임 {o.frame} 미네랄 {o.state[0]} 일꾼 {o.state[4]}. 채팅창에 z3 / d2 / t1 / k2 (질럿·드라군·하이템플러·다크템플러) 처럼 입력하세요.", flush=True)
    asst = Assistant(env, P, beam=args.beam, log=lambda s: print(f"[{time.strftime('%H:%M:%S')}] {s}", flush=True))
    files = IntentFile(args.intent_file)
    opening = [] if args.opening.strip().lower() in ("", "none") else [int(x) for x in args.opening.split(",") if x.strip()]
    if opening and o.frame < 600 and o.state[4] <= 4:
        asst.plan = list(opening)
        asst.log(f"[오프닝] 고정 명령열 {[ACTION_NAMES[a] for a in opening]} 실행 뒤 사용자 명령을 기다린다")
    elif opening:
        asst.log(f"[오프닝] 게임이 이미 진행 중(프레임 {o.frame}, 일꾼 {o.state[4]})이라 오프닝을 건너뛴다")
    if args.target:
        asst.handle(Intent("produce", "zealot", args.target, source="arg"))
    try:
        while True:
            if not asst.batch_active():
                asst.snapshot(frames=args.poll_frames)
            asst.drain_inputs(files)
            if asst.advance():
                asst.idle_workers(during_batch=True)
                asst.run_one()
            else:
                asst.idle_workers()
    except KeyboardInterrupt:
        pass
    finally:
        env.close()


if __name__ == "__main__":
    main()
