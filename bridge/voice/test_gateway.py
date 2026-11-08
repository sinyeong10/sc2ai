"""게이트웨이 시험: HTTP /text, /intent, TCP 줄, 거부 경로. py -X utf8 bridge/voice/test_gateway.py"""
import json
import socket
import sys
import tempfile
import threading
import time
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gateway import Gateway, make_http_handler, normalize_intent, serve_tcp, Invalid  # noqa: E402

fails = 0


def check(cond, msg):
    global fails
    print(("[OK] " if cond else "[FAIL] ") + msg)
    if not cond:
        fails += 1


def post(url, body, json_body=True):
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if json_body else body.encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json" if json_body else "text/plain"})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))


tmp = Path(tempfile.mkdtemp()) / "intents.txt"
status = tmp.with_name("live_status.json")
status.write_text(json.dumps({"time": time.time(), "frame": 5000, "goal": {"desc": "zealot4", "unit": "zealot", "count": 4, "progress": 2},
                              "queue": [{"intent": "produce", "unit": "nexus", "count": 1}, {"intent": "reserve", "minerals": 200, "gas": 0}],
                              "requests": [{"action": 3, "state": "queued", "reason": "minerals"}, {"action": 3, "state": "queued", "reason": "minerals"}],
                              "reserve": {"minerals": 0, "gas": 0}, "worker_target": 16, "minerals": 120, "gas": 30, "supply_in_use": 40, "supply_total": 49,
                              "workers": 16, "threat": {}}, ensure_ascii=False), encoding="utf-8")
gw = Gateway(tmp, status)
httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_http_handler(gw))
hp = httpd.server_address[1]
threading.Thread(target=httpd.serve_forever, daemon=True).start()
tp = 15899
threading.Thread(target=serve_tcp, args=(gw, "127.0.0.1", tp), daemon=True).start()
time.sleep(0.3)
base = f"http://127.0.0.1:{hp}"

s, r = post(base + "/text", {"text": "질럿 세 기", "final": True})
check(s == 200 and r["intent"] == {"intent": "produce", "unit": "zealot", "count": 3, "text": "질럿 세 기"}, f"/text 질럿 세 기 → {r.get('intent')}")
s, r = post(base + "/text", "드라군 두 기 뽑아", json_body=False)
check(s == 200 and r["intent"]["unit"] == "dragoon" and r["intent"]["count"] == 2, f"/text 평문 → {r.get('intent')}")
s, r = post(base + "/text", {"text": "질럿 세", "final": False})
check(s == 200 and r.get("ignored") == "partial", "부분 인식 결과는 무시")
s, r = post(base + "/intent", {"intent": "produce", "unit": "Zealots", "count": "4.0"})
check(s == 200 and r["intent"]["unit"] == "zealot" and r["intent"]["count"] == 4, f"/intent 표기 정규화 → {r.get('intent')}")
s, r = post(base + "/intent", {"intent": "produce", "unit": "zealot", "count": "NaN"})
check(s == 422 and not r["ok"] and r["say"], f"NaN 거부 → {r.get('error')}")
s, r = post(base + "/text", {"text": "오늘 날씨 어때"})
check(s == 422 and "해석" in r["error"], f"해석 불가 거부 → {r.get('error')}")
s, r = post(base + "/intent", {"intent": "army"})
check(s == 200 and r["intent"] == {"intent": "army", "op": "attack"}, "army 기본 op")

c = socket.create_connection(("127.0.0.1", tp), timeout=5)
f = c.makefile("r", encoding="utf-8")
c.sendall("미네랄 이백 가스 오십 남겨\n".encode("utf-8"))
r1 = json.loads(f.readline())
c.sendall((json.dumps({"intent": "worker_target", "count": 24}) + "\n").encode("utf-8"))
r2 = json.loads(f.readline())
c.close()
check(r1["ok"] and r1["intent"]["minerals"] == 200 and r1["intent"]["gas"] == 50, f"TCP 평문 → {r1.get('intent')}")
check(r2["ok"] and r2["intent"]["count"] == 24, f"TCP JSON → {r2.get('intent')}")

s, r = post(base + "/text", {"text": "지금 명령 뭐 들어갔어"})
check(s == 200 and r["intent"]["intent"] == "status" and "질럿 4 중 2 완료" in r["say"] and "멀티 1" in r["say"], f"상태 질의 → {r.get('say')}")
lines = [json.loads(l) for l in tmp.read_text(encoding="utf-8").splitlines()]
check(len(lines) == 6 and lines[0]["unit"] == "zealot" and lines[-1]["intent"] == "worker_target", f"의도 파일 {len(lines)}줄 (받아들인 것만)")
try:
    normalize_intent({"intent": "produce", "unit": "zealot", "count": 1000})
    check(False, "범위 초과가 통과함")
except Invalid as e:
    check(True, f"범위 검사: {e}")
print(f"\n실패 {fails}")
sys.exit(1 if fails else 0)
