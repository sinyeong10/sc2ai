"""음성 명령 게이트웨이. 다른 보드(회사 STT)가 보낸 인식 결과를 받아 의도로 바꾸고 제어 루프의 의도 파일에 넣는다.

    py -X utf8 bridge/voice/gateway.py --intent-file bridge/results/intents.txt [--http-port 15810] [--tcp-port 15811]

받는 통로 둘 (아무거나):
  HTTP  POST /text    {"text": "질럿 세 기", "final": true}  또는 text/plain 본문     → NLU → 의도
        POST /intent  {"intent": "produce", "unit": "zealot", "count": 3}            → 검증·정규화만
        GET  /health
  TCP   한 줄 = JSON({"text":..} 또는 의도) 또는 날 문장. 응답도 한 줄 JSON.
응답: {"ok": true, "intent": {...}, "say": "질럿 3기"}  |  {"ok": false, "error": "...", "say": "잘못된 명령이에요"}
  "say" 는 보드가 TTS 로 읽어 주라고 주는 짧은 문장이다(실패도 들리게).

경계에서 검증·정규화(볼트 [[외부-JSON-명령-검증과-정규화]] 따름): 스키마는 INTENT_SCHEMA 한 곳, 숫자는 float→유한성→범위→int,
표기 변형(단수/복수, 대소문자)은 여기서 통일, 실패는 조용히 버리지 않고 응답과 로그로 남긴다. final 이 아닌(부분) 인식 결과는 무시한다.
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from nlu import parse_utterance  # noqa: E402

LOG = logging.getLogger("voice.gateway")

UNITS = ("zealot", "dragoon", "high_templar", "dark_templar", "worker", "pylon", "gateway", "nexus", "assimilator", "core", "citadel", "archives")
UNIT_ALIASES = {"zealots": "zealot", "dragoons": "dragoon", "templar": "high_templar", "ht": "high_templar", "dt": "dark_templar", "probe": "worker",
                "probes": "worker", "workers": "worker", "gate": "gateway", "gateways": "gateway", "pylons": "pylon", "gas": "assimilator",
                "expand": "nexus", "multi": "nexus", "cyber": "core", "cybernetics": "core"}
# 스키마: 의도 → {필드: (타입, 최소, 최대, 기본)}
INTENT_SCHEMA = {
    "produce": {"unit": ("unit", None, None, None), "count": ("int", 1, 100, 1)},
    "reserve": {"minerals": ("int", 0, 10000, 0), "gas": ("int", 0, 10000, 0)},
    "worker_target": {"count": ("int", 0, 200, 0)},
    "army": {"op": ("enum", ("attack",), None, "attack")},
    "cancel": {}, "status": {}, "rebalance": {},
}
SAY_UNIT = {"zealot": "질럿", "dragoon": "드라군", "high_templar": "하이템플러", "dark_templar": "다크템플러", "worker": "일꾼", "pylon": "파일런",
            "gateway": "게이트", "nexus": "멀티", "assimilator": "가스", "core": "코어", "citadel": "성채", "archives": "아카이브"}


class Invalid(ValueError):
    pass


def _int_field(v, lo, hi, name):
    try:
        f = float(v)
    except (TypeError, ValueError):
        raise Invalid(f"{name}: 숫자가 아님 ({v!r})")
    if not math.isfinite(f):
        raise Invalid(f"{name}: 유한한 수가 아님 ({v!r})")
    n = int(f)
    if lo is not None and n < lo:
        raise Invalid(f"{name}: {lo} 미만 ({n})")
    if hi is not None and n > hi:
        raise Invalid(f"{name}: {hi} 초과 ({n})")
    return n


def normalize_intent(d: dict) -> dict:
    """외부 의도 JSON → 내부 의도. 틀리면 Invalid. 상태 없음(단위 시험 쉬움)."""
    if not isinstance(d, dict):
        raise Invalid("JSON 객체가 아님")
    kind = str(d.get("intent", "")).strip().lower()
    if kind not in INTENT_SCHEMA:
        raise Invalid(f"모르는 의도 {kind!r}")
    out = {"intent": kind}
    for field, (typ, lo, hi, default) in INTENT_SCHEMA[kind].items():
        v = d.get(field, default)
        if typ == "int":
            out[field] = _int_field(v, lo, hi, field)
        elif typ == "unit":
            u = str(v or "").strip().lower().replace(" ", "_")
            u = UNIT_ALIASES.get(u, u)
            if u not in UNITS:
                raise Invalid(f"모르는 유닛 {v!r}")
            out[field] = u
        elif typ == "enum":
            e = str(v or default).strip().lower()
            if e not in lo:
                raise Invalid(f"{field}: {e!r} 는 {lo} 중 하나여야 함")
            out[field] = e
    if "text" in d:
        out["text"] = str(d["text"])[:200]
    return out


def say_for(intent: dict) -> str:
    k = intent["intent"]
    if k == "produce":
        return f"{SAY_UNIT.get(intent['unit'], intent['unit'])} {intent['count']}"
    if k == "reserve":
        return f"미네랄 {intent['minerals']} 가스 {intent['gas']} 예비"
    if k == "worker_target":
        return f"일꾼 {intent['count']}까지"
    return {"army": "총공격", "cancel": "취소", "status": "상태", "rebalance": "일꾼 이전"}.get(k, k)


ACTION_SAY = {0: "일꾼", 1: "파일런", 2: "게이트", 3: "질럿", 4: "멀티", 5: "가스", 6: "코어", 7: "드라군", 10: "성채", 11: "아카이브", 12: "하이템플러", 13: "다크템플러"}


def status_sentence(st, stale_after=5.0) -> str:
    """제어 루프 상태 파일 → TTS 용 한 문장. 들어간 명령만 읽는다(자원·인구는 읽지 않는다, 사용자 결정)."""
    if not st:
        return "제어 루프 상태를 알 수 없어요"
    if time.time() - float(st.get("time", 0)) > stale_after:
        return "제어 루프가 응답하지 않아요"
    items = []
    g = st.get("goal")
    if g:
        items.append(f"{SAY_UNIT.get(g['unit'], g['unit'])} {g['count']} 진행 중 {g['progress']} 완료")
    for i in st.get("queue") or []:
        items.append(f"예비 미네랄 {i['minerals']}" if i["intent"] == "reserve" else f"{SAY_UNIT.get(i['unit'], i['unit'])} {i['count']}")
    if not items:
        return "들어간 명령 없음"
    return "들어간 명령 " + ", ".join(items)


class Gateway:
    def __init__(self, intent_file: Path, status_file=None):
        self.status_file = Path(status_file) if status_file else None
        self.intent_file = Path(intent_file)
        self.intent_file.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        self.count_ok = self.count_bad = 0

    def handle(self, payload) -> dict:
        """payload: dict(JSON) 또는 str(날 문장). 응답 dict."""
        try:
            if isinstance(payload, str):
                d = {"text": payload}
            elif isinstance(payload, dict):
                d = payload
            else:
                raise Invalid("본문 형식")
            if "intent" in d:
                intent = normalize_intent(d)
            else:
                text = str(d.get("text", "")).strip()
                if not text:
                    raise Invalid("text 없음")
                if d.get("final") is False:
                    return {"ok": True, "ignored": "partial"}
                parsed = parse_utterance(text)
                if parsed is None:
                    raise Invalid(f"명령으로 해석되지 않음: {text!r}")
                intent = normalize_intent(parsed)
            if intent["intent"] == "status":
                # 질의: 의도 파일에 넣지 않고 제어 루프의 상태 파일을 읽어 문장으로 답한다
                st = None
                if self.status_file and self.status_file.exists():
                    try:
                        st = json.loads(self.status_file.read_text(encoding="utf-8"))
                    except (OSError, json.JSONDecodeError):
                        st = None
                sent = status_sentence(st)
                LOG.info("상태 질의 → %s", sent)
                return {"ok": True, "intent": intent, "say": sent, "status": st}
            line = json.dumps(intent, ensure_ascii=False)
            with self.lock, open(self.intent_file, "a", encoding="utf-8") as f:
                f.write(line + "\n")
            self.count_ok += 1
            LOG.info("의도 %s", line)
            return {"ok": True, "intent": intent, "say": say_for(intent)}
        except Invalid as e:
            self.count_bad += 1
            LOG.warning("거부 %s (%r)", e, payload)
            return {"ok": False, "error": str(e), "say": "잘못된 명령이에요"}


def make_http_handler(gw: Gateway):
    class H(BaseHTTPRequestHandler):
        def _send(self, code, body):
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path == "/health":
                self._send(200, {"ok": True, "accepted": gw.count_ok, "rejected": gw.count_bad})
            else:
                self._send(404, {"ok": False, "error": "GET /health 만"})

        def do_POST(self):
            n = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(n).decode("utf-8", errors="replace")
            ctype = self.headers.get("Content-Type", "")
            if self.path not in ("/text", "/intent"):
                return self._send(404, {"ok": False, "error": "POST /text 또는 /intent"})
            if "json" in ctype:
                try:
                    payload = json.loads(raw)
                except json.JSONDecodeError as e:
                    return self._send(400, {"ok": False, "error": f"JSON 오류: {e}", "say": "잘못된 명령이에요"})
            else:
                payload = raw
            if self.path == "/intent" and not isinstance(payload, dict):
                return self._send(400, {"ok": False, "error": "/intent 는 JSON 객체"})
            res = gw.handle(payload)
            self._send(200 if res.get("ok") else 422, res)

        def log_message(self, fmt, *args):
            LOG.debug("http %s", fmt % args)
    return H


def serve_tcp(gw: Gateway, host, port):
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((host, port))
    srv.listen(4)
    LOG.info("TCP %s:%d", host, port)

    def client(conn, addr):
        LOG.info("TCP 연결 %s", addr)
        with conn, conn.makefile("r", encoding="utf-8", errors="replace", newline="\n") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line) if line.startswith("{") else line
                except json.JSONDecodeError:
                    payload = line
                res = gw.handle(payload)
                try:
                    conn.sendall((json.dumps(res, ensure_ascii=False) + "\n").encode("utf-8"))
                except OSError:
                    break
        LOG.info("TCP 종료 %s", addr)

    while True:
        conn, addr = srv.accept()
        threading.Thread(target=client, args=(conn, addr), daemon=True).start()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--intent-file", default=str(Path(__file__).resolve().parent.parent / "results" / "intents.txt"))
    ap.add_argument("--host", default="0.0.0.0", help="다른 보드에서 붙으려면 0.0.0.0")
    ap.add_argument("--http-port", type=int, default=15810)
    ap.add_argument("--tcp-port", type=int, default=15811)
    ap.add_argument("--log", default=str(Path(__file__).resolve().parent.parent / "results" / "voice_gateway.log"))
    ap.add_argument("--status-file", default=str(Path(__file__).resolve().parent.parent / "results" / "live_status.json"), help="제어 루프가 쓰는 상태 파일")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler(args.log, encoding="utf-8")])
    gw = Gateway(Path(args.intent_file), Path(args.status_file))
    threading.Thread(target=serve_tcp, args=(gw, args.host, args.tcp_port), daemon=True).start()
    httpd = ThreadingHTTPServer((args.host, args.http_port), make_http_handler(gw))
    LOG.info("HTTP %s:%d  의도 파일 %s", args.host, args.http_port, args.intent_file)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
