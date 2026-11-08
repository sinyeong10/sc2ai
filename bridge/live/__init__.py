"""라이브(사람과 함께) 빌드 어시스턴트 v2. 설계: docs/스타1-라이브-빌드-재설계.md

client.py     실행기 v2 클라이언트 (observe / request / cancel, 비동기)
intents.py    채팅·파일 입력 → Intent
planner.py    (스냅샷, 목표, 제약) → 명령열·예상 프레임 (순수 함수)
controller.py 틱 루프: 관측 → 편차 → 재계획 → 발행 → 로그
eventlog.py   학습용 JSON 줄 이벤트 로그
fake_executor.py 시험용 가짜 실행기 (프로토콜 v2 의미를 파이썬으로 흉내)
"""
