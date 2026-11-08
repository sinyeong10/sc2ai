# Python 에이전트 ↔ StarCraft: Brood War(BWAPI) 연결 방식 조사 초안

- 작성일: 2026-11-08
- 목적: C++ 실행기(BWAPI 모듈) + Python AI(다른 PC 가능) 구조의 빌드오더 RL 프로젝트를 위해, 기존 프로젝트들이 어떻게 게임과 Python을 잇고 있는지 소스 수준으로 확인한다.
- 방법: `git clone --depth 1`로 받은 소스를 읽기만 했다(빌드·실행 안 함). 경로는 각 클론 루트 기준 `경로:줄번호`. 웹 사실은 조회일(2026-11-08) 기준.
- 표기: **[확인]** = 소스/공식 문서에서 직접 읽음. **[추정]** = 읽은 내용에서 유추했고 실행으로 검증하지 않음. **[미확인]** = 찾지 못함.

클론 위치: `<조사 시 임시 클론>\torchcraft`, `dl\torchcraftai`, `dl\sc-docker`, `dl\ualbertabot` (BOSS 포함). 같은 폴더에 다른 조사에서 받아 둔 `dl\bwapi`, `dl\openbw`, `dl\openbw-bwapi`도 일부 참조했다.

---

## 1. TorchCraft (FAIR, 2016–2019)

### 1.1 상태·라이선스 [확인]
- GitHub 저장소는 **2022-07-26 아카이브(읽기 전용)**. `main` 브랜치 마지막 커밋 2019-03-27 (클론 `git log`), GitHub `pushed_at` 2021-08-30. 1.4k stars.
- 라이선스: **BSD 3-clause + 별도 PATENTS 파일**(`torchcraft/LICENSE`, `PATENTS`). Facebook 구 방식의 특허 조항이 붙어 있으므로 재사용 시 PATENTS 문구를 한 번 읽어야 한다.
- 버전: Python 패키지 `torchcraft` 1.4.0 (`setup.py:10`), Lua rockspec 1.4-0.

### 1.2 아키텍처 [확인]
- **서버 = BWAPI AI 모듈(BWEnv.dll / BWEnv.so) 또는 BWAPI 클라이언트 EXE(BWEnvClient)**가 게임 프로세스 안/옆에서 ZeroMQ **REP** 소켓을 열고, 클라이언트(Python/Lua/C++)가 **REQ**로 붙는 요청–응답 패턴. `docs/user/torchcraft.md:5` "The ZMQ server is owned by the StarCraft side... request-reply pattern".
- 전송: ZeroMQ TCP (`zmq_server.cc:103,125` `tcp://*:port`). 포트 기본 11111, 0이면 11111부터 1000개 순차 바인드 시도 (`BWEnv/include/zmq_server.h:25-26`, `zmq_server.cc:97-117`).
- 직렬화: **FlatBuffers 1.7.0** 헤더를 저장소에 동봉 (`BWEnv/fbs/base.h:101-103`), 스키마 `BWEnv/fbs/messages.fbs`. 프로토콜 버전 30 (`zmq_server.h:23`, `client/client.cpp:43`).
- zstd는 **와이어에 쓰지 않는다**. `replayer/zstdstream.h`, `replayer/replayer.cpp`에서만 참조(리플레이 저장용). 단 Python 확장은 `libraries=['zstd','zmq']`로 링크한다(`setup.py:84-86`).
- Python 바인딩: pybind11로 C++ 클라이언트(`client/`, `replayer/`)를 1:1 노출 (`py/*.cpp`, `docs/contributor/code_structure.md`). `pip install pybind11 && pip install .`.

### 1.3 모듈 진입점과 서버 메인 루프 [확인]
- AI 모듈 모드: `BWEnv/src/module.cc:17-24` `onStart()`에서 `Controller`를 새로 만들고 `connect_server()`(ZMQ bind + 클라이언트 핸드셰이크 대기) → `initGame()`. 접속 실패 시 `leaveGame()`. 매 프레임 `onFrame()` → `Controller::onFrame()` (`module.cc:31-33`). `onUnitDestroy`는 사망 ID만 누적 (`module.cc:99-101`).
- 핸드셰이크: `controller.cc:196-232 setupHandshake()`가 `lag_frames = Broodwar->getLatencyFrames()`, 맵 크기(walk tile), 지형 높이/walkable/buildable 비트맵, 시작 위치, 플레이어 목록을 `HandshakeServer`로 보내고 **첫 메시지(보통 설정 명령)를 바로 수신**한다(`:229`).
- **프레임 루프 `controller.cc:712-912 onFrame()`**:
  1. 프레임을 `replayer::Frame`으로 패킹(내 유닛, 적 유닛, 중립, 자원, 총알, 크립) `:754-784`. `combine_frames`가 1보다 크면 이전 프레임과 `combine()`으로 합친다(`:777-783`).
  2. `should_send = combined_frames+1 >= min_combine_frames` (`:738`). 보낼 때는 `StateUpdate`를 만들어 `sendFrame` (`:797-880`).
  3. 보낸 직후 **명령 수신**: `blocking_`이면 `receiveMessage()` 블로킹, 아니면 `max_frame_time_ms_`에서 이미 쓴 시간을 뺀 만큼만 대기(`:891-904`). 시간 내 응답이 없으면 `last_receive_ok=false`로 두고 게임을 진행시키며, 다음 송신 전에 `clearPendingReceive()`(`:1286-1292`)로 REQ/REP 짝을 맞춘다.
  4. 수신된 `Commands`는 `zmq_server.cc:345-376 handleCommands()`가 순회하며 `controller->handleCommand()`를 **그 프레임 안에서 즉시** 호출하고 명령별 상태 바이트(0=성공)를 모아 다음 `StateUpdate.commands_status`로 돌려준다. 프레임당 최대 2500개 명령(`zmq_server.h:24`).
- 클라이언트 EXE 모드(`controller.cc:106-151 loop()`): `BWAPIClient.update()`를 `frameskips`번 돌린 뒤 `onFrame()` (`:121-127`). 게임 종료 후 `leaveGame()`하고 `auto_restart` 설정에 의존(`:144-149`).

### 1.4 명령 집합 [확인] (`include/constants.h:32-81`, 처리 `controller.cc:260-497`)
| 코드 | 이름 | 동작 |
|---|---|---|
| 0 | Quit | `Broodwar->leaveGame()` (`:262-265`) |
| 1 | Restart | `Broodwar->restartGame()`; 주석 "doesn't work in multiplayer". 클라이언트 모드면 게임이 끝났다 다시 시작될 때까지 `update()` 폴링(`:266-280`) |
| 2 | MapHack | `CompleteMapInformation` 플래그(onStart에서만) |
| 3 | RequestImage | 다음 프레임에 화면 이미지 포함 |
| 4 | ExitProcess | 프로세스 종료 플래그 |
| 5 | Noop | 아무것도 안 함(REQ/REP 짝 맞추기용) |
| 6 | SetSpeed | `Broodwar->setLocalSpeed(n)` (`:301-304`) |
| 7 | SetLog | 명령 로그 토글 |
| 8 | SetGui | `Broodwar->setGUI(bool)` (`:309-312`) |
| 9 | **SetFrameskip** | `Broodwar->setFrameSkip(n)`만 호출. 로컬 `frameskips` 갱신은 **주석 처리**됨(`:313-317`) → 송수신 주기와 무관, BWAPI 렌더링 스킵용 [확인]; 실제 의사결정 간격은 11번 |
| 10 | SetCmdOptim | `setCommandOptimizationLevel(0-6)` |
| 11 | **SetCombineFrames** | `min_combine_frames = n` → n프레임마다 1회 송수신 (`:323-326`) |
| 12 | SetMap | bwapi.ini의 map 항목 덮어쓰기 + `Broodwar->setMap()` (`:327`, `:1254-1268`) |
| 13 | SetMulti | auto_menu를 LAN/SINGLE_PLAYER로 ini 덮어쓰기 |
| 14 | SetBlocking | 수신을 블로킹으로 |
| 15 | SetMaxFrameTimeMs | 비블로킹 시 프레임당 최대 대기 ms |
| 16 | **CommandUnit** | 인자 `(unit id, BWAPI UnitCommandType, target id, x, y, extra)`; x,y는 **walk tile** 단위이며 Build/Land/Build_Addon/Place_COP는 TilePosition으로 변환(`:357-364`) → `unit->issueCommand(BWAPI::UnitCommand(...))` (`:387`). 실패 시 `BWAPI_ERROR_MASK | getLastError()` 반환(`:393-394`) |
| 17 | CommandUnitProtected | 같은 타깃을 이미 공격 중이거나 attack frame이면 명령을 **버려서** 재명령으로 인한 공격 취소를 막음(`:397-434`) |
| 18 | CommandUser | 화면 이동/우클릭 등 사용자 입력 |
| 19 | **CommandOpenbw** | `KillUnit(uid)`, `SpawnUnit(player, type, x, y)`; `OPENBW_BWAPI`가 아니면 `OPENBW_NOT_IN_USE` 반환(`:479-492`, `:499-520`) |
| 20-26 | Draw* | 디버그 그리기 |

UnitCommandType 열거는 BWAPI와 동일 순서(`constants.h:108-158`).

### 1.5 메시지 형식 [확인] (`BWEnv/fbs/messages.fbs`)
- `Message{ msg: Any, uid }` 루트. 클라이언트→서버 `HandshakeClient{protocol, map, window_size, window_pos, micro_mode}`, `Commands{[Command{code, args:[int], str}]}` (`:17-21, :30-36, :53-55`).
- 서버→클라이언트 `HandshakeServer{lag_frames, map_size, ground_height_data, walkable_data, buildable_data, map_name, is_replay, player_id, neutral_id, battle_frame_count, start_locations, players}` (`:38-51`), `StateUpdate{data: Frame|FrameDiff, deaths:[int], frame_from_bwapi, battle_frame_count, commands_status:[byte], (이미지 필드)}` (`:62-76`), `PlayerLeft`, `EndGame{data, game_won}` (`:82-85`), `Error`.
- `Frame{ units:[UnitsOfPlayer], actions, resources:[ResourcesOfPlayer], bullets, creep_map, width, height, reward, is_terminal }` (`:207-217`). `Resources{ore, gas, used_psi, total_psi, upgrades, upgrades_level, techs}` (`:117-125`). `Unit`은 id, x, y(walk tile), 체력/실드/에너지, 쿨다운, flags(long 비트마스크), type, pixel 위치/크기, 공격력/사거리, `orders:[Order]`, `command:UnitCommand{frame,type,target...}`(마지막 명령), 속도, `resources`, `buildTechUpgradeType`, `remainingBuildTrainTime`, `remainingUpgradeResearchTime`, `associatedUnit/Count` (`:150-190`).
- **차분 전송**: 첫 송신만 `Frame`, 이후는 `frame_diff(last, prev_sent)`로 `FrameDiff{pids, unitDiffContainers:[UnitDiff{id, var_ids, var_diffs, order_ids, order_diffs,...}], ...}` (`controller.cc:591-612`, `messages.fbs:219-249`). 클라이언트가 복원해 `state.frame`, `state.units`, `state.deaths` 등으로 노출(`py/pystate.cpp:26-70`, `include/state.h`).
- 바이트/프레임, FPS 수치: 저장소 문서와 arXiv 1611.00625(ar5iv 렌더링)에서 **찾지 못함 [미확인]**. 논문 본문은 "entirely synchronous", 상태→featurize→forward→명령의 루프만 설명.

### 1.6 에피소드 재시작 [확인]
- 설정 `config/bwapi.ini`: `auto_menu = SINGLE_PLAYER`, `auto_restart = ON`, `game_type = USE_MAP_SETTINGS`, `map = Maps/BroodWar/micro/m5v5_c_far.scm`, `seed_override`, `speed_override`.
- 방법 1: `Restart` 명령 → `restartGame()` (싱글 플레이어 전용).
- 방법 2: `Quit` → `leaveGame()` → BWAPI `auto_restart`가 새 게임을 시작 → AI 모듈 `onStart()`가 **새 Controller를 만들고 ZMQ를 다시 bind**해 핸드셰이크부터 다시 한다(`module.cc:17-24`, `zmq_server.cc:90-149`). 게임 종료 시 `EndGame` 메시지 후 소켓 close (`controller.cc:614-644`). 예제도 10 전투마다 `set_map` + `quit`으로 맵을 바꾼다(`examples/py/example.py:75-80`).
- 마이크로 모드(`micro_mode`): 한 게임 안에서 맵 트리거가 유닛을 재배치하는 "battle"을 반복. 서버가 아군/적군 유닛이 0이 되면 battle 종료 프레임을 반드시 1회 보내고 다음 battle까지 송신을 멈춘다(`controller.cc:741-751, 906-911`). 클라이언트 state의 `battle_just_ended`, `waiting_for_restart`, `battle_frame_count`.

### 1.7 Windows vs OpenBW, 빌드 [확인]
- Windows: VS 프로젝트 `BWEnv/VisualStudio/BWEnv.vcxproj`(PlatformToolset v141, `:32`), `BWAPI.lib + BWAPIClient.lib` 링크(`:139`), `BWAPI_DIR` 환경변수. 설치 문서는 StarCraft 1.16.1 + BWAPI(Docker 문서는 4.1.2 설치파일, Wine 문서는 4.2.0) + ChaosLauncher 또는 `bwheadless.exe`를 쓴다(`docs/user/starcraft_in_windows.md`, `docker/README.md`, `BWEnv/bin/bwheadless.exe` 동봉). 1.18 이상 미지원 명시.
- OpenBW: `BWEnv/CMakeLists.txt` — `find_package(BWAPI)` 또는 `USE_MINI_OPENBWAPI`(`:18-37`), `BWEnv` 공유 라이브러리(`:60-71`) + `BWEnvClient` 실행파일(`:73-81`). `docs/user/openbw.md:18` "only the shared object will work with OpenBW". 실행은 `OPENBW_ENABLE_UI=0 BWAPI_CONFIG_AI__AI=BWEnv.so BWAPI_CONFIG_AUTO_MENU__* ... BWAPILauncher` (`README.md:67`). MPQ 3개(`Patch_rt.mpq, StarDat.mpq, BrooDat.mpq`) 필요.
- **주의 [확인]**: 상류 `openbw/openbw`는 2026-07-16 커밋 "Remove mini-openbwapi"로 mini-openbwapi를 제거했다. TorchCraft의 `USE_MINI_OPENBWAPI` 경로는 최신 openbw와 맞지 않을 가능성이 크다 [추정].

### 1.8 오늘 재사용 가능한 부분 [추정 포함]
- Python 3: 바인딩은 pybind11 ≥ 2.1 (`py/requirements.txt`, `setup.py:142`)이라 Python 3 자체는 문제없으나, `setup.py:8`이 `distutils`를 import하므로 **Python 3.12+에서는 수정 필요** [추정, distutils 제거는 공식 사항].
- ZeroMQ: libzmq 4+ (`README.md:25`), cppzmq 헤더 동봉. 현재도 그대로 쓸 수 있다.
- FlatBuffers 1.7.0 헤더 동봉. 최신 flatc로 재생성하면 `messages_generated.h`를 다시 만들어야 하며 API 차이가 있을 수 있다 [추정].
- 가장 재사용 가치가 큰 것은 **프로토콜 설계 자체**(핸드셰이크에 정적 맵 정보, 프레임 묶음 송신, 명령 상태 바이트 반환, 차분 전송, 비블로킹 타임아웃)와 `controller.cc`의 BWAPI 명령 매핑. 코드는 BWAPI 4.1/4.2 시대 것이라 4.4.0에 맞춰 컴파일 확인이 필요하다 [추정].

---

## 2. TorchCraftAI / CherryPi (FAIR, 2018–2019)

- 상태: **2022-07-26 아카이브**, 마지막 커밋 2019-07-11. 라이선스 **MIT** (`torchcraftai/LICENSE`). [확인]
- 구조 [확인]: TorchCraft C++ 클라이언트를 감싸 `Player`/`State`/`Module`/UPC 추상화를 제공. "The ability to host several clients in the same process, which amounts to playing several StarCraft games in parallel" (`docs/architecture.md:27`). 서브모듈로 `TorchCraft`, `openbw/openbw`, `openbw/bwapi`를 끌어온다(`.gitmodules`).
- **OpenBW 헤드리스 구동 [확인]**: `src/gameutils/openbwprocess.cpp` — `ForkServer::instance().execute({BWAPILauncher}, env)`로 게임마다 **새 프로세스**를 띄운다(`:189`). 환경변수 `OPENBW_ENABLE_UI=0`, `TORCHCRAFT_FILE_SOCKET=<임시 유닉스 소켓>`, `BWAPI_CONFIG_AUTO_MENU__AUTO_MENU=SINGLE_PLAYER`, `GAME_TYPE=USE_MAP_SETTINGS`, **`AUTO_RESTART=OFF`**, `BWAPI_CONFIG_AI__AI=BWEnv.so`, `RACE` (`:170-186`). 소멸자는 리플레이 저장을 위해 500 ms 유예 후 정리(`:45, :200-217`). 즉 **에피소드 = 프로세스**, TCP 대신 파일 소켓을 쓴다(`TORCHCRAFT_FILE_SOCKET`은 동봉된 TorchCraft 포크가 지원하는 것으로 보임 [추정]). Windows 빌드에서는 "Not implemented"(`:160`).
- 다른 봇과 대전: `VERSION_RACE_NAME.dll` 규칙(374/412/420)으로 Windows DLL 봇을 OpenBW에서 `bwloader.so`로 로드(`:91-123`) [확인].
- **빌드오더 모듈 구조 [확인]**:
  - `src/modules/autobuild.h:54-77` `BuildState{frame, minerals, gas, mineralsPerFramePerGatherer, gasPerFramePerGatherer, usedSupply/maxSupply/inprodSupply, units, upgradesAndTech, production, buildOrder, workers, refineries, autoBuildRefineries, autoBuildHatcheries,...}` — 빌드오더 결정용 **경량 경제 시뮬레이션 상태**. `AutoBuildTask`(`:99-110`)를 상속해 빌드오더를 코드로 쓴다.
  - 구체 빌드 40개: `src/buildorders/*.cpp` (예: `pve4gate.cpp`, `pvp2gatedt.cpp`, `zvtmacro.cpp`), 공통 베이스 `src/buildorders/base.h`(ABBOBase; 적 유닛 수 등 상태 변수).
  - 빌드오더 전환(BOS) 학습: `scripts/bo-switch/`, `src/models/bos/`, 블로그 `website/blog/2018-11-28-build-order-switch-retraining-has-arrived.md`.
- **빌려 쓸 만한 코드 경로 [확인]**:
  - 일꾼 관리: `src/modules/gatherer.h`(GathererModule), `src/modules/gatherer/gathererassignments.{h,cpp}`("Assigns workers to resources for optimal gathering"), `gatherermicro.cpp`, `resourceworkers.{h,cpp}`.
  - 건물 배치: `src/modules/builderhelper.h:27-92` `findBuildLocation(state, seeds, type, upc)`, `canBuildAt`, `checkCreepAt`, `findGeyserForRefinery`; `src/modules/buildingplacer.h:18-38`(휴리스틱 + 선택적 학습 모델 `-bp_model`, 타일 예약); 학습 모델 `src/models/buildingplacer.*`, 튜토리얼 `tutorials/building-placer/`.
  - 생산 실행: `src/modules/builder.*`, `builderc.*`(실제 BWAPI 명령 발행).
- 처리량 수치(게임/초 등): 문서·블로그에서 **찾지 못함 [미확인]**.

---

## 3. sc-docker / scbw (CTU Games & Simulations, SSCAIT)

- 상태: 아카이브 아님, **마지막 커밋 2023-02-25**(basil-ladder PR #91 머지), MIT. 패키지 버전 문자열 `1.0.4-BK` (`scbw/defaults.py:13`). Python ≥ 3.6 (`INSTALL.md:18`). [확인]
- **구동 방식 [확인]**:
  - 이미지 계층 `wine → bwapi → play → java` (`docker/dockerfiles/*.dockerfile`). 베이스 `ubuntu:18.04`, `WINEARCH win32`, `xvfb xauth x11vnc winehq-stable winetricks` 설치(`wine.dockerfile:2,12,62`). StarCraft 1.16.1(ICCUP 배포본), `bwheadless.exe`, 지원 BWAPI.dll들과 토너먼트 모듈(TM) 복사(`bwapi.dockerfile:61-65`).
  - 게임 실행: `docker/scripts/launch_game:5-10` → `winegui bwheadless.exe -l bwapi-data/BWAPI.dll -e StarCraft.exe --installpath ... "$@"`. `winegui`는 `wine explorer /desktop=...,640x480` 래퍼. 헤드리스 인자는 Python이 만든다: `--game NAME --name P --race R --lan` + 호스트는 `--host --map`, 참가자는 `--join` (`scbw/docker_utils.py:278-288`).
  - **플레이어마다 컨테이너 1개**, `sc_net`(172.18.0.0/16) 안에서 LAN(UDP) 게임으로 만난다(`docker_utils.py:29-30, 304-315`). 헤드풀일 때만 `Xvfb :0` + `x11vnc`를 띄운다(`play_common.sh:80-98`, `play_bot.sh:39-41`).
  - 봇 연결: `bot.json`의 `botType` ∈ {AI_MODULE(dll), EXE, JAVA_JNI/JAVA_MIRROR(jar), JYTHON} (`scbw/player.py:48-52`, `USAGE.md:104`). DLL은 bwapi.ini `ai=`에 적어 BWAPI가 로드, EXE/JAR는 게임보다 먼저 `wine`/`win_java32`로 띄워 BWAPIClient로 접속(`play_common.sh:114-161`, `play_bot.sh:42-48`). 게임 시작 후 `run_connect.bat`이 있으면 추가 실행(`:101-112`).
  - 지원 BWAPI: 3.7.4, 3.7.5, 4.1.2, 4.2.0, 4.4.0 — "Version is supported, if we have a functioning tournament module (TM) binary for it" (`scbw/bwapi.py`).
- **결과/리플레이 수집 [확인]**: TM이 `../logs/scores.json`, `frames.csv`, `unit_events.csv`를 쓰도록 환경변수 주입(`docker_utils.py:226-232`). `scores.json` 필드 `is_winner, is_crashed, timed_out, building_score, kill_score, razing_score, unit_score` (`scbw/result.py:11-43`). 리플레이는 `maps/replays/GAME_x_<n>.rep`를 `games/GAME_x/player_<n>.rep`로 이동(`scbw/game.py:172-180`), 요약 `result.json` (`:182-218`). 종료 감지는 컨테이너 안에서 `StarCraft.exe` 프로세스 소멸 또는 리플레이 파일 생성(`play_common.sh:210-233`), 호스트는 컨테이너가 모두 사라질 때까지 폴링하며 하나만 70초 이상 남으면 크래시로 판단(`docker_utils.py:51, 391-404`).
- **게임당 시간 [부분 확인]**: 문서에 "컨테이너 기동 N초" 같은 수치는 없다. `tested_bots.md`의 `game_time` 열이 봇별 46.7–95초 범위인데, 전체 1판의 실시간으로 읽히지만 상대·속도 조건은 적혀 있지 않다 [추정]. 기술보고서 arXiv 1801.02193(ar5iv)도 수치 없음.
- **Python 쪽 제어 가능성**: `scbw`는 컨테이너 오케스트레이션 전용이며 게임 상태 API는 없다 [확인]. 다만 `bot.json`에 `port`를 적으면 컨테이너 포트를 호스트에 공개한다(`player.py:71`, `docker_utils.py:267-272`). 따라서 **TorchCraft BWEnv.dll 같은 프록시 봇을 AI_MODULE로 넣고 11111 포트를 공개하면 호스트/원격 Python이 접속하는 구성이 가능**하다 [추정, 미검증]. `--opt "--net host"`로 LAN을 호스트에 노출하는 사용례도 있다(`USAGE.md:51-54`).
- OS 요구: Docker가 도는 Linux 호스트가 기본. Windows/Mac은 Docker Desktop으로 테스트됨(`README.md:32-36`, `INSTALL.md`). X 가상 프레임버퍼는 이미지 내부 Xvfb이며 헤드리스 모드에서는 띄우지 않는다. 병렬 실행 예: `it.sh`가 `scbw.play --headless ... --timeout_at_frame 86400`을 백그라운드로 여러 개 띄운다.

---

## 4. BWAPI용 Python(및 유사) 브리지 비교

### 4.1 BWAPI 자체 클라이언트 방식 (공유 메모리) [확인, `dl/bwapi` 클론 2026-05-08 기준]
- `bwapi/bwapi/BWAPIClient/Source/Client.cpp:37` `OpenFileMappingA(... "Local\\bwapi_shared_memory_game_list")`, `:75` `Local\\bwapi_shared_memory_<pid>`, `:79` 명명 파이프 `\\.\pipe\bwapi_pipe_<pid>`. 게임 데이터 구조체 `include/BWAPI/Client/GameData.h`에 `latencyFrames`(`:63`), `commandCount`(`:155`), `unitCommandCount`(`:158`). → **같은 머신 전용**. 원격 PC는 별도 프록시가 필요하다.
- OpenBW 상류(`openbw/bwapi`, 마지막 커밋 2021-05-25)의 README는 `BWAPILauncher`와 `.so` 모듈 로드만 설명하고 클라이언트 모드를 언급하지 않는다. JBWAPI의 Linux 가이드는 **`basil-ladder/bwapi`의 `linux-client-support` 브랜치**를 쓰라고 하며(`build_with_openbw.md`), JBWAPI `ClientConnectionPosix.java`는 `shm_open("/bwapi_shared_memory_game_list")`, `"/bwapi_shared_memory_<pid>"`, 유닉스 소켓 `/tmp/bwapi_socket_<pid>`, 프레임 동기화는 1바이트(클라이언트 `1` 전송, 서버 `2` 수신 대기)다. → **OpenBW에서 클라이언트 모드는 포크로만 가능** [추정: 상류 미지원은 README 부재에서 유추].

### 4.2 비교표
| 프로젝트 | 바인딩 방식 | BWAPI 버전 | 언어/버전 | 마지막 활동 | 플랫폼 | 원격 PC | 라이선스 |
|---|---|---|---|---|---|---|---|
| **TorchCraft** (`torchcraft` py) | C++ BWEnv(AI 모듈/클라이언트 EXE) + ZMQ REQ/REP + FlatBuffers, Python은 pybind11 클라이언트 | 문서상 4.1.2/4.2.0, OpenBW | Python 3(pybind11≥2.1; 3.12+는 distutils 수정 필요[추정]) | 2019-03 커밋, 2022-07 아카이브 | Windows(Wine 포함), OpenBW(Linux/mac) | **가능**(TCP) | BSD+PATENTS |
| **pybrood** (neumond) | pybind11, 코드 생성기로 MSVC 프로젝트 생성, `BWAPIClient.lib` 링크 | 4.1.2 (SVN_REV 4708) | Python 3.5 | push 2018-06-16 | Windows 7 32bit; 저자 "Wine에서 injector 실행 실패" | 불가(공유메모리) [추정] | MIT |
| **PyBW** (crass/PyBW, llazzaro/pybw) | SWIG(`.i` 파일에서 추정) 클라이언트 `pybwClient.exe` | 3.7 (llazzaro 쪽은 Beta 3.2) | Python 2.6, VS2008 | 2011-11-30 / 2011-01-22 | Windows | 불가 | 미확인 |
| **cybw** | starcraftai.com 위키에 "Python: CyBW" 항목만 존재, 저장소 **미발견** | – | – | – | – | – | – |
| python-bwapi / bwapi-py / PyBWAPI | 해당 이름의 저장소 **미발견** | – | – | – | – | – | – |
| **JBWAPI** (Java) | 순수 Java, BWAPIClient 메모리맵 파일 직접 읽기 | 4.4.0 | Java | **push 2026-11-07(활성)** | Windows, Linux(OpenBW basil-ladder 포크) | 불가(로컬) | MIT |
| **BWAPI4J** (Java) | Java + C++ 브리지(JNI 호출 최소화) | 4.4.0 | Java | 2019-07-06, v0.8.2b | Windows, OpenBW 네이티브 | 불가 | LGPL-3.0 |
| **bwapi-c / bwapi-rs** | C API로 BWAPI C++를 감싼 `libBWAPIC`; AI 모듈(.so/.dll)로 게임 안에 로드. ctypes/cffi로 Python 바인딩 가능 [추정] | 미기재; v1.0에서 OpenBW 지원 | C / Rust | 2018-07-11; bwapi-rs는 후속 bwapi-xi가 "abandoned"로 기술, bwapi-xi도 2024-01 README만 | OpenBW(Linux), Wine+MinGW | 불가(인프로세스) | 미확인 |

요약: **2026년 현재 살아 있는 것은 JBWAPI(Java, 로컬 공유메모리)뿐**이고, Python 쪽은 전부 2011–2019년에 멈췄다. 원격 PC까지 되는 방식은 TorchCraft처럼 **게임 안의 C++ 모듈이 소켓 서버를 여는 구조**뿐이다.

---

## 5. 프로토콜 설계 교훈

### (a) 명령 발행 ↔ 게임 반영 지연
- TorchCraft [확인]: 핸드셰이크에서 `lag_frames = getLatencyFrames()`를 알려 주고, 명령은 수신 프레임에 즉시 `issueCommand`. 성공/실패는 **다음 StateUpdate의 `commands_status`**로, 실제 적용 여부는 `Unit.command{frame,type,target}`(마지막 명령, `controller.cc:1197-1210`)와 `orders`로 클라이언트가 확인한다. `CommandUnitProtected`는 중복 명령으로 공격이 취소되는 BWAPI 특성을 서버에서 걸러 준다. `SetCmdOptim`으로 BWAPI 명령 최적화 레벨도 조절.
- JBWAPI/BWAPIClient [확인]: 프레임마다 클라이언트가 명령 버퍼를 채우고 1바이트로 "완료"를 알리면 서버가 다음 프레임을 진행 → 지연은 BWAPI latency frames뿐, 통신 지연은 0에 가깝지만 동기 블로킹이다.
- 빌드오더 관점 [추정]: 유닛 단위 명령 대신 "X를 큐에 넣어라"처럼 **의미 단위 명령을 보내고 실행기가 재시도**하게 하면(UAlbertaBot `ProductionManager::manageBuildOrderQueue`의 producer 선택·`predictWorkerMovement`·skip 로직, `ProductionManager.cpp`) 왕복 지연이 결과에 거의 영향을 주지 않는다.

### (b) 조건 대기 중 프레임 스킵
- TorchCraft [확인]: 서버 `set_combine_frames N`이 실제 의사결정 간격(N프레임 묶어 1회 송수신, 사망 ID는 누적). `set_frameskip`은 BWAPI 렌더 스킵만. `set_speed 0` + `set_gui 0`으로 최대 속도. 예제는 추가로 클라이언트에서 `battle_frame_count % 7 == 0`일 때만 명령(`examples/py/example.py:86`). 비블로킹 모드(`set_blocking 0` + `set_max_frame_time_ms`)는 클라이언트가 늦으면 게임을 그냥 진행시킨다 → 실시간 대회용, 학습에는 블로킹이 안전.
- sc-docker [확인]: `--game_speed`(bwapi.ini `speed_override`), `--timeout_at_frame`(TM) 으로 속도/상한만 제어.
- 빌드오더 관점 [추정]: "다음 결정 시점(자원 충족, 건물 완성 등)까지 서버가 알아서 진행하고 그때만 메시지를 보내는" **이벤트 기반 송신**이 TorchCraft의 고정 N프레임 묶음보다 효율적이다. TorchCraft의 `must_send`(battle 종료 시 강제 송신) 패턴이 그 원형이다.

### (c) 에피소드 리셋
- TorchCraft: `restart`(싱글 전용) 또는 `quit`+`auto_restart=ON`, 모듈이 `onStart`마다 ZMQ 재바인드. 맵 변경은 ini 덮어쓰기.
- TorchCraftAI: `AUTO_RESTART=OFF`, **게임마다 BWAPILauncher 프로세스 새로 fork**(ForkServer) + 유닉스 소켓. 가장 깨끗하지만 OpenBW 전용.
- sc-docker: 게임마다 컨테이너 생성/삭제, 종료는 프로세스/리플레이 파일로 감지. 무거움(초 단위 이상 [추정]).
- 결론 [추정]: Windows 실기에서는 TorchCraft 방식(auto_restart), OpenBW에서는 프로세스 단위 리셋이 안정적. 어느 쪽이든 클라이언트는 **`EndGame` 수신 → 재접속/재핸드셰이크**를 상태 머신으로 가져야 한다.

### (d) 직렬화 비용
- TorchCraft: FlatBuffers(zero-copy 파싱), 첫 프레임만 전체·이후 `FrameDiff`(변경된 변수 id/값 쌍), 좌표는 walk tile 정수, 크립맵도 diff, 클라이언트 측 `only_consider_types` 필터. 와이어 압축 없음. 구체적 바이트/프레임·FPS 수치는 **미확인**.
- 공유 메모리(BWAPIClient/JBWAPI): 복사 없음, 동기화 1바이트.
- 빌드오더 관점 [추정]: 필요한 상태는 `frame, minerals, gas, supply used/total, 유닛 타입별 수(완성/진행 중, 남은 시간), 업그레이드`뿐이라 수백 바이트면 충분하다. 유닛별 전체 배열을 보내는 TorchCraft 스키마를 그대로 쓸 필요는 없다.

---

## 6. "빌드오더만 제어 + 일꾼 자동 관리" 선례와 BOSS

### 6.1 UAlbertaBot (MIT, David Churchill) [확인]
- 저장소 `davechurchill/ualbertabot`, `License.md` MIT(2016). README: "not being actively maintained since early 2021", 2020-02부터 VS2019 + **BWAPI 4.4.0** + 클라이언트 EXE 방식, "The bot will only work for the first game played after the .exe is run, so AUTO_RESTART won't work well". 마지막 push 2023-05-19.
- 빌드오더 실행 계층:
  - `UAlbertaBot/Source/BuildOrderQueue.h` — `BuildOrderItem{metaType, priority, blocking, isGasSteal}`, 우선순위 큐.
  - `ProductionManager.{h,cpp}` — `manageBuildOrderQueue()`가 최상위 항목의 producer를 고르고(`getProducer`), 건물이면 일꾼을 미리 이동(`predictWorkerMovement`), 가능하면 `create()`, 아니면 skip. `performBuildOrderSearch()`가 BOSS 결과를 큐로 바꾼다. 교착 감지 `detectBuildOrderDeadlock`.
  - `WorkerManager.h:20-24` — `handleIdleWorkers/handleGasWorkers/handleMoveWorkers/...`로 **일꾼 자동 배치**, `getBuilder(Building&)`, `rebalanceWorkers()`. 설정 `WorkersPerRefinery: 3` (`UAlbertaBot/bin/UAlbertaBot_Config.txt:33`).
  - `BuildingPlacerManager.h:33-45` — `canBuildHere`, `getBuildLocationNear(b, buildDist)`, `reserveTiles/freeTiles`, `getRefineryPosition`.
  - 오프닝은 JSON 설정의 `OpeningBuildOrder` 문자열 배열(예 `Protoss_ZealotRush`, `UAlbertaBot_Config.txt:103`). 이후는 `StrategyManager::getBuildOrderGoal()` 목표를 BOSS로 풀어 이어 간다(`UseBuildOrderSearch: true`, `:71`).
- 이 구조가 "Python이 빌드오더 항목을 밀어 넣고 C++가 생산·일꾼·배치를 알아서 하는" 목표와 가장 가깝다 [추정].

### 6.2 BOSS (Build Order Search System) [확인]
- 정체: Churchill & Buro, "Build Order Optimization in StarCraft", AIIDE 2011. **SC1 빌드 역학의 결정론적 시뮬레이터 + DFBB(depth-first branch & bound) 탐색**. 코드 `ualbertabot/BOSS/source/` (UAlbertaBot과 같은 MIT). SC2용 BOSS는 별도 저장소가 있다는 포크 설명이 있으나 CommandCenter README는 "no automatic build-order planning system"이라고 적어 **미확정**.
- 입력: `GameState`(종족, 미네랄/가스, 완성/진행 중 유닛, 보급) + `BuildOrderSearchGoal`(ActionType별 목표 수/최대 수, `BuildOrderSearchGoal.h:12-13`) + 시간 제한. API `DFBB_BuildOrderSmartSearch::setState/setGoal/addGoal/setTimeLimit/search/getResults` (`DFBB_BuildOrderSmartSearch.h:45-53`), 폴백 `NaiveBuildOrderSearch::solve()`.
- 출력: `BuildOrder`(ActionType 열), `doActions(state)`로 재시뮬레이션, `getCompletionTime(state)`, `isLegalFromState`, `getJSONString` (`BuildOrder.h:19-41`). 결과 구조체에 `solved, solutionFound, timeElapsed, nodesExpanded`.
- 게임 없이 컴파일되도록 설계: BWAPI 게임 기반 생성자는 `_MSC_VER`에서만(`GameState.h:68-72` "we won't be using this if we're compiling to emscripten or linux"). emscripten 웹 빌드(`BOSS/Makefile`, `BOSS/emscripten/BOSS.html`)가 있고 JSON 설정 형식은 `BOSS/emscripten/config.txt`(`States{race, minerals, gas, units[[type,n]]}`, `Build Orders{name:[types]}`, `Experiments`). 단 Makefile이 참조하는 `source/bwapidata/include`가 이 스냅샷에 없어 **그대로는 빌드가 안 될 가능성** [추정].
- **경제 모델 [확인]** (`Constants.h:29-33`, `GameState.cpp`):
  - 수입은 일꾼 수에 **선형**: `MPWPF = 45`, `GPWPF = 70`, `RESOURCE_SCALE = 1000` → 0.045 미네랄/프레임/일꾼, 0.070 가스/프레임/일꾼 (`getMineralsPerFrame = MPWPF * numMineralWorkers`, `GameState.cpp:923-931`). 포화·거리·채광 패치 수 미반영.
  - 시간 전진 `fastForward(toFrame)`: 진행 중 액션이 끝나는 시점마다 수입률을 갱신하며 적분(`:422-472`). `whenCanPerform = max(prereq, minerals, gas, race-specific(저그 라바), supply, worker)` (`:475-515`).
  - 건물은 완성 시각에 **`BUILDING_PLACEMENT = 24*5 = 120` 프레임**(일꾼 이동 여유)을 더함(`UnitData.cpp:166`). 저그 라바 타이머 336.
  - **프로토스**: `doAction`에서 비용 차감 후 `addActionInProgress(action, now+buildTime)`만 수행(`GameState.cpp:377-380`); 일꾼은 묶이지 않음(`whenWorkerReady` 주석 "protoss doesn't tie up a worker to build", `workersRequiredToBuild = 0`, `:288`). 테란은 건설 일꾼 1명을 빼고, 저그는 라바/변태. 보급(파일런)은 `whenSupplyReady`로 일반 처리. 크로노 부스트 같은 가속은 SC1에 없으므로 모델에도 없음.
  - 시작 상태 `setStartingState`: 미네랄 50, 본진 1 + 일꾼 4, 보급 8(저그는 오버로드 추가) (`GameState.cpp:213-230`).
- UAlbertaBot 안에서의 사용: `BOSSManager::update(timeLimit)`가 **프레임마다 최소 5 ms씩 증분 탐색**, `BOSSFrameLimit = 160` 프레임 안에 못 풀면 포기(`BOSSManager.cpp`, `UAlbertaBot_Config.txt:32`). `getStartState()`는 현재 코드에서 BWAPI 상태가 아니라 `setStartingState()`를 쓴다(`BOSSManager.cpp`) — 실게임 상태 반영은 주석 처리된 생성자 쪽 [확인].
- 우리 프로젝트와의 관계 [추정]: BOSS는 "규칙 기반 결정론 시뮬레이터"이고 우리 것은 "로그에서 학습한 시뮬레이터"다. BOSS의 상태 정의(`BuildState`/`GameState` 필드), `whenCanPerform`의 6가지 대기 조건 분해, 120프레임 배치 여유 같은 항목은 SC1용 시뮬레이터의 **피처/검증 기준**으로 바로 쓸 수 있다. Satirist(Steamhammer 저자)는 BOSS 웹 시각화 타이밍이 초반 9풀에서는 Steamhammer와 잘 맞지만 오버풀에서는 덜 맞는다고 적었다(블로그, 수치 없음).

### 6.3 기타 [확인]
- **Steamhammer**: UAlbertaBot 후손, MIT, BWAPI 4.4.0, 최신 6.2.4(2026-10-15, AIIDE 2026판), 소스는 GitHub가 아니라 satirist.org의 zip. BOSS 포함 여부는 페이지에서 확인 못함. 생산 교착 타임아웃 1440프레임 설정 존재(설정 문서).
- **BWEB** (`Cmccrave/BWEB`): BWEM 기반 건물 배치 라이브러리, Blocks/Walls/Stations, MIT, v1.17 커밋 2026-04-22(활성). 초기화 `BWEB::Map::onStart()`, `BWEB::Blocks::findBlocks()`.
- **CommandCenter**(SC1+SC2, Churchill): README "no automatic build-order planning system".

---

## 7. 우리 설계에 대한 시사점 (초안, [추정])
1. **원격 Python이 전제라면 선택지는 하나**: 게임 안 C++ 모듈이 소켓 서버(TorchCraft: ZMQ REQ/REP)를 여는 구조. BWAPIClient 공유메모리 계열은 전부 로컬 전용.
2. **명령 추상화 수준은 TorchCraft보다 높게**: `command_unit`(유닛 단위) 대신 `enqueue(type, priority)`, `cancel`, `set_speed/gui`, `restart` 정도. 실행은 UAlbertaBot `ProductionManager + WorkerManager + BuildingPlacerManager`(MIT) 또는 TorchCraftAI `gatherer/builderhelper`(MIT)를 이식.
3. **상태 메시지는 작게, 이벤트 기반으로**: TorchCraft의 `combine_frames` + `must_send` 패턴을 "결정 지점에서만 송신"으로 바꾸고, `commands_status`처럼 명령별 수락 결과를 반드시 돌려준다. `lag_frames`도 핸드셰이크에 포함.
4. **리셋**: Windows 실기 = `auto_restart=ON` + `onStart` 재바인드(TorchCraft), OpenBW = 프로세스 재생성(TorchCraftAI). 클라이언트는 `EndGame → 재접속` 상태 머신.
5. **검증 기준**: BOSS의 결정론 시뮬레이터(0.045/0.070 수입, 120프레임 배치 여유, 6조건 max)를 SC1 시뮬레이터의 베이스라인·단위 테스트로 활용.

---

## 8. 출처
- TorchCraft 저장소(클론, 2019-03-27 커밋), GitHub 아카이브 고지(2022-07-26), arXiv 1611.00625 (ar5iv 렌더링)
- TorchCraftAI 저장소(클론, 2019-07-11 커밋), GitHub 아카이브 고지
- sc-docker 저장소(클론, 2023-02-25 커밋), arXiv 1801.02193 (ar5iv 렌더링)
- UAlbertaBot/BOSS 저장소(클론, 2022-03-01 커밋; GitHub pushed_at 2023-05-19), AIIDE 2011 논문 페이지(ojs.aaai.org)
- bwapi/bwapi 클론(2026-05-08), openbw/bwapi(2021-05-25), openbw/openbw(2026-08-13, "Remove mini-openbwapi" 2026-07-16) — GitHub Atom 피드
- GitHub 페이지/Atom: neumond/pybrood(2018-06-16), crass/PyBW(2011-11-30), llazzaro/pybw(2011-01-22), JavaBWAPI/JBWAPI(2026-11-07; `Client.java`, `ClientConnectionPosix.java`, `build_with_openbw.md`), OpenBW/BWAPI4J(2019-07-06), RnDome/bwapi-c(2018-07-11), nlinker/bwapi-xi(2024-01-25), Cmccrave/BWEB(2026-04-22)
- satirist.org Steamhammer 페이지(6.2.4, 2026-10-15), BOSS 시각화 블로그 글
- starcraftai.com 위키(CyBW 항목만 존재)
