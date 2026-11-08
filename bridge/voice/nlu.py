"""음성 인식 결과(한국어/영어 문장) → 의도 JSON. 규칙 기반 NLU. Dialogflow 식 의도 스키마와 같은 꼴을 낸다.

의도: produce(unit, count) | reserve(minerals, gas) | worker_target(count) | army(op) | cancel | status | rebalance
예: "질럿 세 기" → {"intent":"produce","unit":"zealot","count":3}
    "미네랄 이백 가스 오십 남겨" → {"intent":"reserve","minerals":200,"gas":50}
    "일꾼 스물넷까지" → {"intent":"worker_target","count":24}
    "총공격" → {"intent":"army","op":"attack"}
STT 가 띄어쓰기를 제멋대로 하므로 공백을 지우고 본다.
"""
from __future__ import annotations

import re

UNIT_KO = [  # (키워드, 유닛) 긴 것 먼저
    ("하이템플러", "high_templar"), ("하이템플", "high_templar"), ("하이 템플러", "high_templar"),
    ("다크템플러", "dark_templar"), ("다크템플", "dark_templar"), ("다크템", "dark_templar"), ("다템", "dark_templar"), ("다크", "dark_templar"),
    ("템플러", "high_templar"), ("템플", "high_templar"),
    ("드라군", "dragoon"), ("드라곤", "dragoon"), ("드래군", "dragoon"), ("드라", "dragoon"),
    ("질럿", "zealot"), ("질롯", "zealot"), ("질럳", "zealot"), ("지럿", "zealot"),
    ("프로브", "worker"), ("일꾼", "worker"), ("일군", "worker"),
    ("파일런", "pylon"), ("파일론", "pylon"), ("파일럿", "pylon"), ("파이런", "pylon"),
    ("게이트웨이", "gateway"), ("게이트", "gateway"), ("관문", "gateway"),
    ("어시밀레이터", "assimilator"), ("어시밀", "assimilator"), ("가스", "assimilator"),
    ("사이버네틱스", "core"), ("사이버", "core"), ("코어", "core"),
    ("템플러아카이브", "archives"), ("아카이브", "archives"), ("아카이브스", "archives"),
    ("아둔의성채", "citadel"), ("아둔", "citadel"), ("성채", "citadel"), ("시타델", "citadel"),
    ("넥서스", "nexus"), ("멀티", "nexus"), ("확장", "nexus"), ("앞마당", "nexus"),
]
UNIT_EN = {"zealot": "zealot", "dragoon": "dragoon", "templar": "high_templar", "dark": "dark_templar", "probe": "worker", "worker": "worker",
           "pylon": "pylon", "gateway": "gateway", "gate": "gateway", "assimilator": "assimilator", "gas": "assimilator", "core": "core",
           "citadel": "citadel", "archives": "archives", "nexus": "nexus", "expand": "nexus"}

NATIVE_TENS = {"열": 10, "스물": 20, "스무": 20, "서른": 30, "마흔": 40, "쉰": 50}
NATIVE_ONES = {"하나": 1, "한": 1, "둘": 2, "두": 2, "셋": 3, "세": 3, "석": 3, "넷": 4, "네": 4, "넉": 4, "다섯": 5, "여섯": 6, "일곱": 7, "여덟": 8, "아홉": 9}
SINO = {"일": 1, "이": 2, "삼": 3, "사": 4, "오": 5, "육": 6, "칠": 7, "팔": 8, "구": 9}
NUM_TOKEN = (r"(?:\d+|스물|스무|서른|마흔|쉰|열|하나|한|둘|두|셋|세|석|넷|네|넉|다섯|여섯|일곱|여덟|아홉|"
             r"(?:[일이삼사오육칠팔구]?백)|(?:[일이삼사오육칠팔구]?천)|(?:[이삼사오육칠팔구]?십)|[일이삼사오육칠팔구])")
NUM_RE = re.compile(NUM_TOKEN + "+")


def parse_number_ko(text: str) -> int | None:
    """한 덩어리의 한국어/숫자 수사 → 정수. '스물넷' 24, '이백오십' 250, '세' 3, '12' 12."""
    s = text.replace(" ", "")
    if not s:
        return None
    if s.isdigit():
        return int(s)
    total, cur = 0, 0
    i = 0
    matched = False
    while i < len(s):
        ch = s[i]
        # 고유어 십 단위
        hit = False
        for k, v in sorted(NATIVE_TENS.items(), key=lambda kv: -len(kv[0])):
            if s.startswith(k, i):
                cur += v; i += len(k); hit = matched = True; break
        if hit:
            continue
        for k, v in sorted(NATIVE_ONES.items(), key=lambda kv: -len(kv[0])):
            if s.startswith(k, i):
                cur += v; i += len(k); hit = matched = True; break
        if hit:
            continue
        if ch == "천":
            total += (cur or 1) * 1000; cur = 0; i += 1; matched = True; continue
        if ch == "백":
            total += (cur or 1) * 100; cur = 0; i += 1; matched = True; continue
        if ch == "십":
            total += (cur or 1) * 10; cur = 0; i += 1; matched = True; continue
        if ch in SINO:
            cur += SINO[ch]; i += 1; matched = True; continue
        if ch.isdigit():
            j = i
            while j < len(s) and s[j].isdigit():
                j += 1
            cur += int(s[i:j]); i = j; matched = True; continue
        return None
    return total + cur if matched else None


def _find_unit(s: str):
    for kw, unit in UNIT_KO:
        k = kw.replace(" ", "")
        idx = s.find(k)
        if idx >= 0:
            return unit, idx, idx + len(k)
    for kw, unit in UNIT_EN.items():
        idx = s.find(kw)
        if idx >= 0:
            return unit, idx, idx + len(kw)
    return None, -1, -1


KEYWORDS_TO_BLANK = [kw.replace(" ", "") for kw, _ in UNIT_KO] + ["미네랄", "가스", "예비", "목표", "까지", "유지", "일꾼", "일군"]


def _blank_keywords(s: str) -> str:
    """수사 추출 전에 단어 속 글자가 수사로 오인되지 않게 키워드 자리를 '#' 로 지운다 ('일꾼'의 '일', '이전'의 '이' 등)."""
    for kw in sorted(set(KEYWORDS_TO_BLANK), key=len, reverse=True):
        s = s.replace(kw, "#" * len(kw))
    return s


def _numbers_with_pos(s: str):
    out = []
    s = _blank_keywords(s)
    for m in NUM_RE.finditer(s):
        v = parse_number_ko(m.group(0))
        if v is not None:
            out.append((m.start(), m.end(), v))
    return out


def parse_utterance(text: str) -> dict | None:
    """문장 하나 → 의도 dict (없으면 None)."""
    raw = text.strip()
    if not raw:
        return None
    s = raw.replace(" ", "").lower()
    # 제어 명령
    if any(k in s for k in ("총공격", "공격", "어택", "attack")):
        return {"intent": "army", "op": "attack", "text": raw}
    if any(k in s for k in ("취소", "캔슬", "cancel", "멈춰", "그만")):
        return {"intent": "cancel", "text": raw}
    if any(k in s for k in ("상태", "status", "현황")):
        return {"intent": "status", "text": raw}
    if any(k in s for k in ("재분배", "리밸런스", "옮겨", "이전해")):
        return {"intent": "rebalance", "text": raw}
    nums = _numbers_with_pos(s)
    # 예비 자원: "미네랄 이백 (가스 오십) 남겨/예비/모아"
    if any(k in s for k in ("예비", "남겨", "남기", "모아", "아껴", "reserve", "keep")):
        minerals = gas = 0
        mi, gi = s.find("미네랄"), s.find("가스")
        for a, b, v in nums:
            # 숫자 바로 앞에 어느 자원 이름이 가까운가
            dm = a - mi if mi >= 0 and mi < a else 10**6
            dg = a - gi if gi >= 0 and gi < a else 10**6
            if dg < dm:
                gas = v
            else:
                minerals = v
        if minerals == 0 and gas == 0 and nums:
            minerals = nums[0][2]
        return {"intent": "reserve", "minerals": minerals, "gas": gas, "text": raw}
    # 일꾼 목표: "일꾼 스물넷까지 / 일꾼 목표 24"
    if ("일꾼" in s or "프로브" in s or "worker" in s) and any(k in s for k in ("까지", "목표", "유지", "맞춰")):
        return {"intent": "worker_target", "count": nums[0][2] if nums else 0, "text": raw}
    # 생산: 유닛 + 수
    unit, a, b = _find_unit(s)
    if unit is None:
        return None
    count = 1
    if nums:
        after = [n for n in nums if n[0] >= b]
        before = [n for n in nums if n[1] <= a]
        pick = after[0] if after else (before[-1] if before else nums[0])
        count = max(1, pick[2])
    return {"intent": "produce", "unit": unit, "count": count, "text": raw}


if __name__ == "__main__":
    import sys
    for t in (sys.argv[1:] or ["질럿 세 기", "드라군 두 기 뽑아", "다크 템플러 하나", "하이템플러 둘", "질럿 열두 기", "파일런", "게이트 두 개",
                               "멀티 해", "가스 지어", "미네랄 이백 남겨", "미네랄 이백 가스 오십 예비", "일꾼 스물넷까지", "총공격", "취소", "상태", "스무 기 질럿"]):
        print(f"{t!r:24} → {parse_utterance(t)}")
