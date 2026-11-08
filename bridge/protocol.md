# 빌드 명령 프로토콜 v1 (AI ↔ 실행기)

AI(Python, 학습 PC)와 실행기(게임을 돌리는 프로세스)를 분리하기 위한 계약이다. 실행기가
무엇이든(시뮬레이터, python-sc2 봇, BWAPI 1.16.1 DLL, OpenBW, Docker 안의 스타1) AI 쪽은
같은 메시지를 보낸다. 기존 `socket_order`의 pickle 파일 교환을 대체한다.

## 전송

- TCP, 한 연결에 한 에피소드 열(여러 에피소드 가능). 메시지는 **UTF-8 JSON 한 줄**(`\n` 종료).
- 실행기가 서버(bind), AI가 클라이언트(connect). 게임 PC 방화벽에서 포트 하나만 열면 된다.
- 인증 없음. LAN 또는 SSH 터널 안에서만 쓴다. 인터넷에 직접 노출하지 않는다.
- 모든 요청에 `id`(정수, 단조 증가)를 넣고 응답은 같은 `id`를 돌려준다. 같은 `id`의 `step`이
  다시 오면 실행기는 명령을 두 번 내리지 않고 마지막 응답을 다시 보낸다(재전송 안전).

## 메시지

### AI → 실행기

| type | 필드 | 뜻 |
|---|---|---|
| `hello` | `version`(=1) | 연결 직후 1회. 버전이 다르면 실행기가 `error` 후 끊는다 |
| `reset` | `target`(목표 유닛 수), `seed`(선택), `speed`(선택, 0=최고속) | 새 에피소드. 게임을 (재)시작하고 첫 관측을 돌려준다 |
| `step` | `action`(정수) | 명령 1개. **명령이 게임에 실제로 내려진 순간**까지 막힌다(blocking) |
| `step` | `action`=8, `frames`(정수) | 대기. `frames` 프레임 뒤의 관측을 돌려준다. 명령열 기록에 넣지 않는다(측정·대기용). 실행기가 지원하면 `hello.actions`에 `"8":"wait"` |
| `reset` | `target`, `live`=true | **라이브 모드**(사람과 함께). 게임을 재시작하지도 멈추지도 않고 기본 속도·화면 켬. `target`은 게임 시작부터 센 절대 질럿 수. 사람의 채팅은 실행기가 `{"type":"text","frame":..,"text":..}`로 먼저 보낸다(id 없음). 관측 `extra`에 스냅샷(`nexus_queue/remaining`, `pylons_building`, `gateways_building`, `gate_queue/remaining`, `zealots_completed`, `gas`)이 실린다 |
| `stop` | | 현재 에피소드 중단(게임은 유지) |
| `status` | | 진단. 실행기 종류, 현재 프레임, 대기 중 명령 |
| `bye` | | 연결 종료 |

행동 번호는 저장소 전체와 같다. 0 일꾼, 1 보급 건물(파일런), 2 생산 건물(게이트웨이), 3 전투 유닛(질럿), 9 종료.
확장 시 번호를 재사용하지 않고 추가한다(예: 4 가스, 5 사이버네틱스 코어, 6 드라군). `hello` 응답의
`actions`에 실행기가 지원하는 번호와 이름을 싣는다.

### 실행기 → AI

| type | 필드 | 뜻 |
|---|---|---|
| `hello` | `version`, `backend`, `game`, `actions`, `latency_frames` | `backend`: `sim`, `sc2-python`, `bwapi-1.16.1`, `openbw`, … `game`: `sc2` 또는 `bw` |
| `obs` | 아래 | `reset`/`step`의 응답 |
| `wait` | `id`, `frame`, `reason` | `step` 대기 중 N프레임마다 보내는 생존 신호. AI는 이것으로 "오래 걸림"과 "멈춤"을 구분한다 |
| `error` | `id`, `message`, `fatal` | 프로토콜 오류, 게임 다운 등. `fatal`이면 연결을 끊는다 |

`obs` 필드:

```json
{"type":"obs","id":7,"frame":1234,"iteration":224,
 "state":[minerals,gas,supply_used,supply_cap,workers,nexus,tech,gateways,zealots,iteration],
 "accepted":true,"done":false,"end_frame":null,"error":null,
 "extra":{"gateways_ready":2,"pylons_ready":1,"zealots_in_production":1}}
```

- `state`는 기존 로그(`2__full_log_*.txt`)와 같은 10칸 벡터라 `offline_rl/`의 파서와 호환된다.
  스타1에서는 `iteration = frame`(SC2 봇의 1 iteration ≈ 5.5 게임 루프와 다름), `tech`는
  사이버네틱스 코어 수(없으면 0), `supply_*`는 스타1 내부 단위(×2)를 2로 나눠 SC2와 같은 단위로 보낸다.
- `accepted=false`: 명령을 끝내 내릴 수 없었다(선행 건물 없음, 인구 한도 초과, 건설 위치 K회 실패 등).
  `error`에 이유. 저장소의 기존 설계대로 그 에피소드는 `done=true`로 끝난다.
- `done=true`이고 `end_frame`이 있으면 목표 달성. `end_frame`은 **목표 수째 유닛이 완성된 프레임**이다.
  SC2 로그의 종료 프레임은 봇의 다음 iteration에 기록돼 `end_lag`(약 12)가 있었다. 실행기가 완성 이벤트에서
  바로 적으면 그 지연이 없으므로 두 환경을 비교할 때 이 차이를 뺀다.

## 실행 의미 (실행기가 지켜야 할 것)

1. `step(a)`는 `a`를 **큐에 넣지 않는다**. 실행기는 매 프레임 "지금 내릴 수 있는가"를 보고, 가능한 첫 프레임에
   내린 뒤 그 프레임의 관측을 돌려준다. 그래서 한 번에 대기 중 명령은 최대 1개다. SC2 봇의 `finish_action`과
   같은 의미이고, 로그 한 줄 = 명령 실행 시점 관측이라는 규약이 유지된다.
2. 내릴 수 있는 조건(프로토스 기준): 자원 ≥ 비용, 인구 여유(일꾼 1, 질럿 2), 선행 건물 완성(게이트웨이는 완성된
   파일런과 전력, 질럿은 완성된 게이트웨이), 건설 위치 확보, 건설할 일꾼 확보.
3. 실행기 안의 **자동 기능**(일꾼 채취 배분, 건설 위치, 건설 일꾼 선택, 게이트 배정)은 명령의 일부가 아니라
   환경의 일부다. 상태 공간을 줄이기 위한 의도적 설계다(readme). 어떤 규칙을 쓰는지 `hello`의 `backend`와
   실행기 문서에 적어 두고, 바꾸면 로그와 시뮬레이터 적합값이 달라진다는 것을 안다.
4. 대기 중에는 `wait`를 보낸다(기본 200프레임마다). AI 쪽 기본 timeout은 60초다.
5. `reset`은 이전 에피소드가 끝나지 않았어도 받는다(중단 후 재시작).
6. **프레임 블로킹.** 에피소드 중 대기 명령이 없으면 실행기는 다음 메시지가 올 때까지 게임 프레임을 진행하지
   않는다. AI의 생각 시간과 네트워크 지연이 게임 시간에 섞이면 같은 명령열이 다른 결과를 내므로, 결정론 가정
   (readme, 작업 노트 3절)을 지키기 위한 필수 조건이다. 시뮬레이터는 저절로 만족하고, BWAPI 모듈은 `onFrame`
   안에서 메시지를 기다리는 것으로 구현한다(BWAPIClient 모드가 매 프레임 클라이언트 응답을 기다리는 것과 같은 효과).
7. **마지막 명령의 응답.** 목표 수째 유닛 명령이 내려지면 실행기는 그 유닛이 완성될 때까지 응답을 미루고
   `done=true, end_frame`과 함께 돌려준다. 그래서 AI는 `done`만 보면 되고, 시뮬레이터 백엔드와 의미가 같다.
   그 사이에도 `wait`는 온다.
8. 목표 달성 뒤 들어온 `step`은 `accepted=false, done=true, error="episode already finished"`다.

## 예시 (한 에피소드)

```
> {"type":"hello","version":1,"id":0}
< {"type":"hello","version":1,"backend":"sim","game":"sc2","actions":{"0":"worker","1":"pylon","2":"gateway","3":"zealot"},"latency_frames":0}
> {"type":"reset","target":2,"id":1}
< {"type":"obs","id":1,"frame":0,"iteration":0,"state":[50,0,12,15,12,1,0,0,0,0],"accepted":true,"done":false,"end_frame":null,"error":null,"extra":{}}
> {"type":"step","action":1,"id":2}
< {"type":"obs","id":2,"frame":45,...,"accepted":true,"done":false,...}
...
> {"type":"step","action":3,"id":9}
< {"type":"obs","id":9,"frame":430,...,"accepted":true,"done":true,"end_frame":581,...}
```

## 버전 규칙

필드를 더하는 것은 같은 버전에서 허용한다(수신 쪽은 모르는 필드를 무시). 필드의 뜻이나 행동 번호의 뜻을
바꾸면 `version`을 올린다.

## 라이브 v2 (사람과 함께, 비동기) — 2026-11-08

`hello.live_v2 = true` 인 실행기에서, `reset(live=true)` 뒤에 쓴다. 어떤 메시지도 게임을 멈추지 않는다. 실험 모드(`step`)와 섞지 않는다.

| 보냄 | 응답 | 뜻 |
|---|---|---|
| `{"type":"request","id":N,"action":a}` | `{"type":"ack","id":N,"request_id":N,"accepted":bool,"reason":..}` | 비동기 요청. 실행기가 순서대로 조건이 되는 첫 프레임에 실행한다. 수명: `queued` → `issued`(건물: 놓일 때까지) → `done` \| `failed`(사유) |
| `{"type":"observe","id":N}` | `{"type":"snapshot", ...}` | 완전한 스냅샷. 자원·예약분, 인구(게임값·큐 포함값·한도), 일꾼 분류, 기지, 건물별(완성·건설 중 남은 시간·명령됨 경과), 게이트 큐, 병력 수(완성·생산 중), 요청 목록(상태·사유), 건설 감시, 포기 목록, 위협(근처 적·손실) |
| `{"type":"cancel","id":N[,"request_id":R]}` | `{"type":"status","cancelled":n}` | 아직 실행 전(`queued`)인 요청만 지운다. 이미 나간 건설은 실행기가 끝까지 책임진다 |
| `{"type":"reserve",...}`, `hud`, `rebalance` | `status` | v1 과 같음 |

행동 번호: 0 일꾼, 1 파일런, 2 게이트, 3 질럿, 4 넥서스(앞마당), 5 어시밀레이터, 6 코어, 7 드라군, 10 성채, 11 아카이브, 12 하이템플러, 13 다크템플러.
실행기 자동 규칙: 인구는 매번 게임값 + 큐 대기분으로 계산(누적 변수 없음), 건설은 실패 프로브 제외·자리 재탐색으로 24프레임 간격 최대 200회 재발행,
배치는 2칸 통로를 남기고 자원 길을 피함, 일꾼 분배는 가스 3·기지당 덩이 2배수 → 3배수. 클라이언트: `bridge/live/`.
