"""시험용 가짜 실행기. 프로토콜 v2 의미를 파이썬으로 흉내 낸다 (LiveClient 와 같은 메서드).

단순 모델: 미네랄은 일꾼당 0.045/프레임, 가스는 어시밀레이터당 0.21. 유닛은 큐 진입 즉시 done, 건물은 build_delay 프레임 뒤 놓임.
외부에서 상태를 건드려 사람의 행동(건물 짓기, 돈 쓰기, 유닛 손실)을 흉내 낸다.
"""
from __future__ import annotations

COST = {0: (50, 0), 1: (100, 0), 2: (150, 0), 3: (100, 0), 4: (400, 0), 5: (100, 0), 6: (200, 0), 7: (125, 50), 10: (150, 100), 11: (150, 200), 12: (50, 150), 13: (125, 100)}
BKEY = {1: "pylon", 2: "gateway", 4: "nexus", 5: "assimilator", 6: "core", 10: "citadel", 11: "archives"}
UNAME = {0: "probe", 3: "zealot", 7: "dragoon", 12: "high_templar", 13: "dark_templar"}
REQ = {2: ["pylon"], 6: ["gateway"], 10: ["core"], 11: ["citadel"], 3: ["gateway"], 7: ["gateway", "core", "assimilator"], 12: ["archives", "assimilator"], 13: ["archives", "assimilator"]}
SUPPLY = {0: 1, 3: 2, 7: 2, 12: 2, 13: 2}


class FakeExecutor:
    def __init__(self, build_delay=200, fail_actions=None):
        self.frame = 0
        self.minerals, self.gas = 50.0, 0.0
        self.workers = 4
        self.buildings = {k: {"ready": 1 if k == "nexus" else 0, "building": []} for k in BKEY.values()}
        self.units = {k: 0 for k in UNAME.values()}
        self.units["probe"] = 4
        self.supply_used, self.supply_total = 4, 9
        self.requests = []
        self.inbox = []
        self.reserve = (0, 0)
        self.hud_text = ""
        self.lost_buildings = 0
        self.build_delay = build_delay
        self.fail_actions = set(fail_actions or [])
        self.info = {"live_v2": True}

    # ---- 시간
    def advance(self, frames):
        for _ in range(frames):
            self.frame += 1
            self.minerals += 0.045 * self.workers
            self.gas += 0.21 * self.buildings["assimilator"]["ready"]
            for k, b in self.buildings.items():
                still = []
                for done_at in b["building"]:
                    if done_at <= self.frame:
                        b["ready"] += 1
                        if k == "pylon":
                            self.supply_total = min(200, self.supply_total + 8)
                        if k == "nexus":
                            self.supply_total = min(200, self.supply_total + 9)
                    else:
                        still.append(done_at)
                b["building"] = still
            for r in self.requests:
                if r["state"] == "issued" and r["place_at"] <= self.frame:
                    r["state"], r["done_frame"] = "done", self.frame
            self._process()

    def _have(self, key):
        b = self.buildings[key]
        return b["ready"] + len(b["building"]) + sum(1 for r in self.requests if r["state"] == "issued" and BKEY.get(r["action"]) == key)

    def _process(self):
        r = next((x for x in self.requests if x["state"] == "queued"), None)
        if not r:
            return
        a = r["action"]
        if a in self.fail_actions:
            r.update(state="failed", reason="forced failure", done_frame=self.frame)
            return
        for pre in REQ.get(a, []):
            if self.buildings[pre]["ready"] == 0:
                if self._have(pre) == 0:
                    r.update(state="failed", reason=f"requires {pre}", done_frame=self.frame)
                else:
                    r["reason"] = f"{pre} not complete"
                return
        m, g = COST[a]
        reserved = sum(COST[x["action"]][0] for x in self.requests if x["state"] == "issued")
        if self.minerals - reserved - self.reserve[0] < m or self.gas - self.reserve[1] < g:
            r["reason"] = "minerals" if self.minerals - reserved - self.reserve[0] < m else "gas"
            return
        if a in SUPPLY:
            if self.supply_total >= 200 and self.supply_used + SUPPLY[a] > 200:
                r.update(state="failed", reason="supply maxed (200)", done_frame=self.frame)
                return
            if self.supply_used + SUPPLY[a] > self.supply_total:
                coming = len(self.buildings["pylon"]["building"]) + sum(1 for x in self.requests if x["state"] == "issued" and x["action"] == 1)
                if coming == 0:
                    r.update(state="failed", reason="supply impossible (need pylon)", done_frame=self.frame)
                else:
                    r["reason"] = "supply"
                return
        r["issued_frame"] = self.frame
        if a in BKEY:
            r["state"], r["place_at"] = "issued", self.frame + self.build_delay
            self.gas -= g
            self.minerals -= m  # 단순화: 비용을 명령 때 뺀다
            self.buildings[BKEY[a]]["building"].append(self.frame + self.build_delay + 600)
        else:
            self.minerals -= m
            self.gas -= g
            self.supply_used += SUPPLY.get(a, 0)
            self.units[UNAME[a]] += 1
            if a == 0:
                self.workers += 1
            r["state"], r["done_frame"] = "done", self.frame

    # ---- 프로토콜
    def observe(self):
        b = {k: {"ready": v["ready"], "building": [max(0, d - self.frame) for d in v["building"]],
                 "pending": [self.frame - r["issued_frame"] for r in self.requests if r["state"] == "issued" and BKEY.get(r["action"]) == k]}
             for k, v in self.buildings.items()}
        return {"type": "snapshot", "frame": self.frame, "live": True,
                "state": [int(self.minerals), int(self.gas), self.supply_used, self.supply_total, self.workers, 1, 0, b["gateway"]["ready"], self.units["zealot"], self.frame],
                "minerals": int(self.minerals), "gas": int(self.gas),
                "reserved_minerals": self.reserve[0], "reserved_gas": self.reserve[1], "reserve_minerals": self.reserve[0], "reserve_gas": self.reserve[1],
                "supply_used": self.supply_used, "supply_in_use": self.supply_used, "supply_total": self.supply_total,
                "workers": {"total": self.workers, "minerals": self.workers, "gas": 0, "building": 0, "idle": 0},
                "bases": [{"id": 1, "done": True, "remaining": 0, "x": 0, "y": 0, "patches": 8, "workers": self.workers, "queue": 0, "queue_remaining": 0}],
                "buildings": b, "gate_queue": [0] * b["gateway"]["ready"], "gate_remaining": [0] * b["gateway"]["ready"],
                "units": {k: {"done": v, "in_production": 0} for k, v in self.units.items()},
                "requests": [dict(r) for r in self.requests], "watches": [], "abandoned": [],
                "threat": {"enemies_near": 0, "lost_units": 0, "lost_buildings": self.lost_buildings, "last_loss_frame": -1}}

    def request(self, action):
        rid = len(self.requests) + 1
        self.requests.append({"id": rid, "action": action, "state": "queued", "reason": "", "frame_in": self.frame, "issued_frame": -1, "done_frame": -1, "place_at": 0})
        return {"accepted": True, "request_id": rid, "reason": ""}

    def cancel(self, request_id=None):
        n = 0
        for r in self.requests:
            if r["state"] == "queued" and (request_id is None or r["id"] == request_id):
                r.update(state="failed", reason="cancelled", done_frame=self.frame)
                n += 1
        return n

    def set_reserve(self, m, g):
        self.reserve = (m, g)
        return {"type": "status"}

    def hud(self, text):
        self.hud_text = text
        return {"type": "status"}

    def rebalance(self):
        return {"rebalanced": False}

    def poll_inbox(self):
        out, self.inbox = self.inbox, []
        return out

    # ---- 사람 흉내
    def human_builds(self, key):
        self.buildings[key]["ready"] += 1
        if key == "pylon":
            self.supply_total += 8

    def human_spends(self, m):
        self.minerals -= m

    def human_loses_building(self, key):
        if self.buildings[key]["ready"] > 0:
            self.buildings[key]["ready"] -= 1
            self.lost_buildings += 1
