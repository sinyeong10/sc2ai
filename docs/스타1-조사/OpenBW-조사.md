# OpenBW 조사 초안: 리눅스/ARM 헤드리스 브루드워 실행기 후보

- 작성일: 2026-11-08
- 목적: 빌드오더 최적화 RL에서 "파이썬 에이전트(다른 PC) → C++ 실행기 → 브루드워 엔진" 구조의 엔진 후보로 OpenBW를 평가
- 조사 방법: 소스 클론(얕은 클론) 분석 + 공식 README/이슈/문서 확인. 코드는 읽기만 했고 빌드·실행하지 않음.
- 클론 위치와 커밋
  - `dl/openbw` = OpenBW/openbw master, 최신 커밋 `4b046d5` (2026-08-13, tscmoo, "Read/set invincible flag on map units.")
  - `dl/openbw-bwapi` = OpenBW/bwapi develop-openbw, 최신 커밋 `48124ba` (2020-06-11, "Merge pull request #14 ... static-build")
  - 아래 `파일:줄` 표기는 각 클론 루트 기준. `openbw/`는 엔진, `bwapi/`는 BWAPI 포크.
- 표기: **[확인]** = 소스나 공식 문서에서 직접 확인, **[추정]** = 확인한 사실에서 유도한 판단, **[2차]** = 제3자 글·이슈 댓글 등 간접 근거

---

## 0. 한 줄 결론

OpenBW는 브루드워 엔진을 C++14로 재구현한 헤더 전용 라이브러리이고, BWAPI 4.2.0 포크를 통해 리눅스에서 그래픽 없이 봇을 돌릴 수 있다 **[확인]**. 헤드리스 모드에서는 프레임 제한이 전혀 없고(엔진이 CPU가 허락하는 만큼 돈다) **[확인]**, 상태 스냅샷·난수 시드 설정 API까지 있어 **[확인]** 짧은 에피소드를 수천 번 반복하는 용도에 구조적으로 잘 맞는다. 다만 (1) 엔진 저장소에 라이선스 파일이 없고 **[확인]**, (2) BWAPI 포크는 2020년 이후 멈춰 있으며 **[확인]**, (3) BWAPI 클라이언트(공유 메모리) 모드가 막혀 있어 봇은 반드시 `.so` 모듈로 써야 하고 **[확인]**, (4) ARM 빌드 사례는 찾지 못했다 **[확인: 근거 없음]**. 정식 처리량 수치는 어디에도 없어 직접 벤치마크가 필요하다.

---

## 1. OpenBW가 무엇인가

### 1.1 정체 **[확인]**

- 브루드워(1.16.1 기준) 게임 로직을 처음부터 다시 쓴 재구현체. 블리자드 바이너리를 쓰지 않는다. 저장소는 거의 전부 헤더 파일이며 핵심은 `openbw/bwgame.h` (22,396줄, 약 800KB). 그 외 `actions.h`(플레이어 명령 처리), `sync.h`(록스텝 네트워크/동기화), `replay.h`·`replay_saver.h`, `data_loading.h`(MPQ 읽기), `ui/`(SDL2 UI, 선택 사항), `deps/asio`(네트워크용 Boost.Asio 독립판).
- C++14 요구 (`openbw/ui/CMakeLists.txt:3`, `bwapi/CMakeLists.txt:7`).
- 엔진 자체 README는 한 줄이고 "빌드·사용법은 OpenBW/bwapi를 보라"고만 적혀 있다 (`openbw/README.md`).
- 제3자 설명 **[2차]**: "Inside Brood War" 해설 페이지는 OpenBW를 "고정소수점 연산·RNG·명령 로직을 원본과 비트 단위로 맞춘 역공학 재구현"이라고 소개하며 주 저자를 Vegard Mella(tscmoo)로 적는다. 리플레이 호환이 그 근거라고 설명한다.
- 자체 컴퓨터 AI(AI 스크립트)는 없다. README가 "OpenBW has no built-in computer player, so in single player games the opponent does not perform any actions"라고 명시 **[확인]**. 소스에서도 게임 시작 시 `controller_computer` 슬롯을 `controller_occupied`로 바꿔 버린다 (`openbw/sync.h:692-695`). 중립 유닛이 공격하는 상황은 `error("... computer player behavior which is not supported yet :(")`로 예외를 던진다 (`openbw/bwgame.h:7618`) → 크리터/중립 유닛이 공격받아 반격하는 맵에서는 게임이 중단될 수 있다 **[추정]**.

### 1.2 필요한 게임 데이터 **[확인]**

- `data_loading.h:1319-1326`에서 `OPENBW_MPQ_PATH` 디렉터리 아래 세 파일을 **이 이름 그대로** `fopen`한다: `Patch_rt.mpq`, `BrooDat.mpq`, `StarDat.mpq` (`openbw/data_loading.h:1322-1324`, `openbw/data_loading.h:233`).
  - 리눅스는 파일명 대소문자를 구분하므로 1.16.1 설치본의 `patch_rt.mpq`/`STARDAT.MPQ` 같은 표기면 심볼릭 링크나 이름 변경이 필요하다 **[추정: 코드에 대소문자 무시 처리 없음, 리눅스 FS 특성]**. BWAPI 포크 README는 `Stardat.mpq, Broodat.mpq`라고 적어 소스와도 표기가 다르다.
- 어떤 버전의 MPQ인가
  - 포크 README: "copied from StarCraft: BroodWar 1.16.1 or 1.18" **[확인]**.
  - TorchCraftAI 리눅스 설치 문서: "MPQs from newer versions (like 1.18 or 1.2 (Remastered)) are not supported yet" → 1.16.1을 Wine으로 설치해 MPQ를 뽑으라고 안내 **[확인, 2018~2022 문서]**.
  - 리마스터(1.21+)는 CASC 포맷으로 재포장되어 `StarDat.mpq`/`BrooDat.mpq` 자체가 없다 **[2차: 블리자드 포럼 글]**. 소스에 CASC 처리 코드는 전혀 없다 (grep `casc|remastered|1.18` 결과 0건) **[확인]**.
  - 결론: 실무적으로 **1.16.1의 세 MPQ**가 안전한 선택이다. 1.18 MPQ는 README와 TorchCraftAI 문서가 서로 모순되므로 직접 시험해야 한다.
- MPQ 자체는 블리자드 저작물이므로 배포할 수 없고, 각 실행 머신에 별도 복사해야 한다. 소형 ARM 보드에도 마찬가지 **[추정: 법적 상식]**.

### 1.3 라이선스 **[확인]**

- **엔진(OpenBW/openbw)에는 LICENSE 파일이 없다.** `openbw/` 루트에 라이선스 파일 없음, 소스 내 라이선스 문구도 `deps/asio`(Boost Software License)뿐. GitHub 이슈 #17 "Add a LICENSE.md"가 2018-02-26부터 열려 있고, 2026-04-02에도 유지관리자 확인을 요청하는 댓글이 달렸으나 tscmoo의 답변은 없다.
  - 법적으로는 "공개된 소스이지만 명시적 허락 없음" 상태. 사내 연구용 빌드는 현실적 위험이 낮지만, 재배포·제품화·논문 코드 공개 시에는 문제가 된다 **[추정]**.
- **BWAPI 포크(OpenBW/bwapi)는 LGPL-3.0** (`bwapi/LICENSE`, `bwapi/LICENSE.md`; GitHub 표기도 LGPL-3.0).
- 질문의 "GPL?"에 대한 답: GPL이 아니라 **미지정(엔진) + LGPL-3.0(BWAPI 포크)**.

### 1.4 유지관리 상태 **[확인, 2026-11-08 GitHub 기준]**

| 저장소 | 최신 커밋 | 비고 |
|---|---|---|
| OpenBW/openbw | 2026-08-13 | 2019-04 → 2024-12 사이 공백, 2024-12부터 tscmoo가 desync·크래시 수정 재개 ("Fix various desyncs/bugs" 2024-12-05, "Fix desync in can_place_building" 2026-06-20, "Fix crashes in give_unit_to and pathfinding" 2026-07-15, "Remove mini-openbwapi" 2026-07-16). 별 266, 열린 이슈 17, 열린 PR 8 |
| OpenBW/bwapi | 2020-06-11 | 그 뒤 커밋 없음. 이슈 탭 비활성(0건), 열린 PR 9. 별 89 |

- 사실상 1인 프로젝트(tscmoo). 이슈에 대한 유지관리자 응답이 드물다 (#17, #27 모두 무응답).
- 포크 README 스스로 "development version, breaking changes can occur at any time"라고 경고.

### 1.5 알려진 문제 **[확인]**

- **리플레이 desync**: 이슈 #14(2018), #22(2018), #27(2019, Windows VS2017; 2021년 리눅스 Steamhammer 자가대전에서도 재현 보고), #28(2019) 모두 열린 상태. 증상은 "봇 게임은 정상 종료되는데 OpenBW가 저장한 리플레이가 원본 클라이언트/OpenBW 뷰어에서 desync". 2024~2026 커밋이 desync를 다수 고쳤지만 이슈는 닫히지 않았다.
  - RL 관점: 리플레이 재생 정확도 문제이지 라이브 시뮬레이션 자체의 결정론 문제는 아니다. 다만 "원본 게임과 비트 단위로 동일한가"는 보장이 아니라 목표로 봐야 한다 **[추정]**.
- 잘못된 맵에서 멈춤(#21), "fixme unknown flag" 오류(#19, 소스 `openbw/bwgame.h:17209`), 특정 리플레이 로드 실패(#7, #13, #16).
- 미구현/미지원(`bwapi/BUGS.txt`): `unitCountsDead, allUnitsLost, ... killCount` 등 점수 계열 함수, 수리 비용·환불 자원, **`restartGame()` 동작 안 함**.
- `bwgame.h`에 `fixme`/`error("...fixme")` 62곳. 예: `drop_carried_items: fixme`(2214), `cloak fixme`(16825), `fixme rescue passive`(17202). 이들은 `error()`이므로 해당 경로에 들어가면 예외로 종료된다 **[추정: error()는 예외 던짐, `bwapi/OpenBWData/BW/BWData.cpp:44` 참고]**.
- 사운드: UI를 켜도 `OPENBW_NO_SDL_MIXER`, `OPENBW_NO_SDL_IMAGE`가 정의되어 빌드된다 (`openbw/ui/CMakeLists.txt:14-15`) → 소리 없음. 헤드리스엔 무관.
- 안개(fog): 시야 계산은 엔진에 구현되어 있고(`bwgame.h`에 visibility 관련 참조 120곳) BWAPI 포크가 `isVisible` 등을 매핑한다 **[확인: 구현 존재]**. 정확도는 별도 검증 필요.
- 경로 탐색: 엔진에 구현되어 있고 2026-07 커밋이 크래시를 고쳤다. 원본과의 일치 여부는 리플레이 호환으로 간접 검증될 뿐이다 **[추정]**.
- 멀티플레이는 1v1만, 탑 vs 바텀 문의(#30, 2021)는 답 없음.
- Windows 특이: `OPENBW_LAN_MODE`는 TCP만 지원.

---

## 2. 헤드리스/UI 모드, 속도, 병렬 실행

### 2.1 헤드리스 **[확인]**

- 빌드 시점: CMake 옵션 `OPENBW_ENABLE_UI` (기본 OFF, `bwapi/bwapi/OpenBWData/CMakeLists.txt:2`). 끄면 SDL2를 아예 찾지 않고 `openbw_ui` 타깃도 만들지 않는다 (`bwapi/bwapi/OpenBWData/CMakeLists.txt:13-16`). 즉 **기본 빌드가 곧 헤드리스 빌드**다.
- 실행 시점(UI를 포함해 빌드했을 때): 환경 변수 `OPENBW_ENABLE_UI`의 기본값이 `"1"`이고 `0/OFF/NO/FALSE/N`이면 UI 비활성 (`bwapi/bwapi/OpenBWData/BW/BWData.cpp:810-819`). 봇 코드에서 `Broodwar->setGUI(false)`를 호출해도 같은 효과 (`BWData.cpp:1486-1490`, `bwapi/bwapi/BWAPI/Source/BWAPI/GameDrawing.cpp:197-203`).
- `ui/`에는 "창을 만들지 않고 메모리 버퍼에만 그리는" 플래그도 있다(2018-01-30 커밋 "ui: add some flags to allow drawing without creating a window"). 화면 픽셀을 관측으로 쓰고 싶을 때 `Game::drawGameScreen(x, y, w, h)`가 RGBA 버퍼를 돌려준다 (`BWData.cpp:876-883`, 이슈 #18에서 tscmoo가 "No real guarantees about speed or stability"라고 단서) **[확인]**.

### 2.2 속도 제어 **[확인]**

- 프레임 페이싱(sleep)은 **UI 객체가 있을 때만** 실행된다. `openbwapi_impl::next_frame()`에서 `if (ui) { ...; std::this_thread::sleep_for(...) }` 블록 안에만 지연 코드가 있다 (`BWData.cpp:850-873`). 따라서 헤드리스에서는 프레임 제한이 없고 엔진 업데이트 + BWAPI 업데이트 비용만큼 빠르게 돈다.
- 속도 표: `game_speeds_frame_times = {167, 111, 83, 67, 56, 48, 42}` ms (`BWData.cpp:336`), 기본은 마지막 값(Fastest, 42ms ≈ 23.8 fps). `OPENBW_GAME_SPEED` 환경 변수로 ms/프레임을 덮어쓸 수 있으나 역시 UI 모드에서만 의미 있다 (`BWData.cpp:801-805`, `865`).
- BWAPI `setLocalSpeed(n)`은 이 표를 통째로 n으로 바꾸는 구현 (`bwapi/bwapi/BWAPI/Source/BWAPI/GameImpl.cpp:639-658` → `BWData.cpp:1121-1124`). 헤드리스에서는 호출해도 무해하지만 효과도 없다.
- `setFrameSkip`은 OpenBWData 쪽이 **빈 함수** (`BWData.cpp:1131-1134`). `setGUI(false)`가 내부적으로 `setFrameSkip(9999999)`를 부르지만 (`GameDrawing.cpp:203`) 결국 아무 일도 안 한다.
- `Game::Latency()`는 0을 반환하고 (`BWData.cpp:1033-1036`) 싱글플레이는 `sync_server_noop`로 동작한다 (`BWData.cpp:467`). 멀티(1v1)에서는 `sync_st.latency = 3` (`BWData.cpp:518`), 기본 구조체 값은 2 (`openbw/sync.h:25`). 명령은 latency 프레임 뒤에 적용되므로 BWAPI 봇이 평소 겪는 지연 프레임 개념은 유지된다.

### 2.3 처리량 수치 **[확인: 공개 수치 없음]**

- GitHub 이슈, TorchCraft/TorchCraftAI 문서, sc-docker 보고서 어디에도 OpenBW 헤드리스 fps·게임/시간 수치가 없다. TL.net 소개 스레드에 "리눅스 툴체인이 Windows VM보다 확실히 빠를 것"이라는 개발자 답변이 있다는 검색 요약만 있고(원문 페이지는 403으로 직접 확인 못 함) **[2차]**, 이슈 #18에서 N00byEdge가 "1998년 게임의 최적화된 헤드리스 빌드이니 pysc2보다 빠를 것"이라고 한 추정뿐이다.
- 추정 근거 **[추정]**: 1프레임 비용 = 엔진 `next_frame` (유닛 최대 1700개, `bwgame.h:299`) + BWAPI `update()`(모든 유닛 데이터를 BWAPI 구조체로 복사하는 기존 BWAPI 오버헤드). 빌드오더 초반(유닛 수십 개)이라면 프레임당 수십 µs~수백 µs 수준이 자연스럽지만, **반드시 직접 측정**해야 한다. 측정 방법: `TestAIModule` 대신 아무것도 안 하는 모듈을 `.so`로 올리고 `onFrame`에서 프레임 카운트/시간 기록.

### 2.4 여러 인스턴스 병렬 실행 **[확인 + 추정]**

- 프로세스 단위로 독립적이다. 싱글플레이는 소켓을 열지 않으므로(`noop_server`) 포트 충돌이 없다 **[확인]**.
- 주의 1: `Game::getInstanceNumber()`가 항상 0을 반환한다 (`BWData.cpp:1453-1456`). 원본 BWAPI의 "`ai = a.dll, b.dll` 쉼표 목록을 인스턴스 번호로 고르는" 기능(`GameUpdate.cpp:399-402`)이 OpenBW에선 무의미하다 → 프로세스마다 환경 변수를 따로 주어야 한다.
- 주의 2: 1v1 LAN 모드 기본값 `LOCAL_AUTO`는 `/tmp/openbw`의 소켓 파일을 **모두 뒤져서** 연결한다 (`BWData.cpp:552-575`). 여러 쌍을 한 머신에서 돌리면 엉뚱한 상대와 붙을 수 있으므로 쌍마다 `OPENBW_LOCAL_AUTO_DIRECTORY`를 다르게 주거나 `LOCAL`(경로 지정)/`FD`/`FILE`/`TCP`(포트 지정)를 써야 한다 **[추정: 코드 구조에서 유도]**.
- 메모리: 공개 수치 없음. 구조상 MPQ에서 읽은 전역 데이터(`global_state`)는 프로세스당 한 번 로드되고(`BWData.cpp:923-937`) 게임마다 `state`만 재생성된다. 프로세스당 수십~수백 MB 범위로 예상하지만 **측정 필요** **[추정]**.
- 한 프로세스 안에서 여러 게임을 동시에 돌리는 것은 BWAPI 포크 구조상(전역 `Broodwar` 싱글턴) 불가. 엔진 자체(`bwgame::state`)는 전역 상태가 없어 여러 `state`를 한 프로세스에 둘 수 있다 **[추정: `full_state` 구조, `BWData.cpp:939-951`]**. 즉 BWAPI를 버리고 `bwgame.h`를 직접 링크하면 멀티 인스턴스 인프로세스도 가능하다(4.4절).

### 2.5 Docker / 패키지 **[확인]**

- 공식 Docker 이미지 없음. OpenBW 조직의 `OpenBW_IDE`(2018-04 최종 갱신)가 gcc 6 + CMake + SDL2를 깔고 OpenBW/bwapi를 빌드하는 Dockerfile을 제공하며, 컨테이너 안 `/home/bwapi/build/bin/BWAPILauncher`를 실행한다. 오래됐고 MPQ는 외부에서 받아오는 방식.
- heiner/openbw(및 Pepper-Ng 포크)에는 웹(WASM) 빌드용 Dockerfile이 있다(브라우저용, 봇 실행 용도 아님).
- pip/conda 패키지 없음. Python 바인딩도 공식적으로 없다(이슈 #18에서 요청만 있음). 파이썬 연동은 TorchCraft(BWEnv.so + ZMQ) 방식이 유일한 선례.

---

## 3. OpenBW/bwapi 포크

### 3.1 API 호환성 **[확인]**

- BWAPI **4.2.0** 기반 (README 첫 줄; `bwapi/bwapi/include/BWAPI.h:75-76` `CLIENT_VERSION = 10002`).
- `bwapi/bwapi/include/BWAPI.h:5`에 `#define OPENBW_BWAPI`가 있어 봇 코드에서 조건부 컴파일 가능.
- 4.4.0/5.x는 지원하지 않는다. 업스트림 BWAPI에 OpenBW 지원이 머지된 흔적은 없다(README: "should eventually be merged ... until then").
- 포크 전용 확장 API (`bwapi/bwapi/include/BWAPI/Game.h:1745-1748` 등): `saveSnapshot/loadSnapshot/deleteSnapshot/listSnapshots`, `setRandomSeed`, `createUnit/killUnit/removeUnit`(멀티 동기화 포함, 2017-10 커밋), `sendCustomAction`, `disableTriggers`, `enableCheats`, `drawGameScreen`.
- 구형 봇(3.7.4, 4.1.2) 호환 계층: `bwapi/bwapi/compat/` (CMake `BUILD_COMPAT`, 비MSVC에서 `-m32`, `bwapi/bwapi/CMakeLists.txt:5-9`). TorchCraftAI는 이를 이용해 Windows DLL 봇을 `bwloader.so:`를 앞에 붙여 로드했다(`openbwprocess.cpp`, 3.3절).

### 3.2 AI 모듈 로드 방식 **[확인]**

- 리눅스: `dlopen(path, RTLD_NOW)` 후 `dlsym`으로 `gameInit`와 `newAIModule` 두 심볼을 찾는다 (`bwapi/bwapi/BWAPI/Source/GameUpdate.cpp:417-452`). 못 찾으면 더미 모듈을 만들고 `externalModuleConnected = false`.
- Windows: `LoadLibraryA` + `GetProcAddress`(같은 파일). 즉 봇 소스는 동일하고 빌드 산출물만 `.so`/`.dll`로 다르다.
- 경로는 `[ai] ai` 설정 = 환경 변수 `BWAPI_CONFIG_AI__AI` (`GameUpdate.cpp:388`).
- 링크: 리눅스에선 봇 `.so`가 아무것도 링크하지 않아도 된다(README; 심볼은 런처가 제공). Windows는 `BWAPILIB.lib`.

### 3.3 진입점과 게임 루프 **[확인]**

`bwapi/bwapi/BWAPILauncher/Source/Main.cpp` 전체가 핵심이다.

```
BW::sacrificeThreadForUI([]{            // UI 빌드면 메인 스레드를 UI에 양보, 아니면 그냥 실행
  BW::GameOwner gameOwner;              // 엔진 상태 소유
  BWAPI::BroodwarImpl_handle h(gameOwner.getGame());
  do {
    h->autoMenuManager.startGame();     // bwapi.ini/[auto_menu] 설정대로 게임 생성·시작
    while (!h->bwgame.gameOver()) {
      h->update();                      // BWAPI 이벤트(onStart/onFrame...) → 봇 호출
      h->bwgame.nextFrame();            // 엔진 1프레임
      if (!h->externalModuleConnected) { printf("No module loaded, exiting\n"); return 1; }
    }
    h->update(); h->onGameEnd(); h->bwgame.leaveGame();
  } while (!h->bwgame.gameClosed() && auto_restart != "" && auto_restart != "OFF");
});
```

- 종료 조건 `gameOver()` = 나갔거나(`left_game`) 내 슬롯이 승리/패배 (`BWData.cpp:1465-1472`). 빌드오더 에피소드를 시간 제한으로 끝내려면 봇이 `Broodwar->leaveGame()`을 부르면 된다 **[추정: `leaveGame()`이 `left_game=true`로 만듦, `BWData.cpp:672-680`]**.
- `auto_restart=ON`이면 같은 프로세스에서 `startGame()`부터 다시 돈다. `create_single_player_game()`은 `st = bwgame::state()`로 게임 상태를 완전히 새로 만들고 MPQ 전역 데이터는 재사용한다 (`BWData.cpp:381-399`). 즉 **에피소드 재시작 = 프로세스 재시작 없이 맵 로드만** 이다.
- `restartGame()`은 `RestartGame` 명령을 큐에 넣지만(`GameImpl.cpp:569-580`) `BUGS.txt`가 "doesn't work"라고 명시. 쓰지 말 것.
- 콘솔 출력은 오류 외엔 거의 없다(README). `setPrintTextCallback`으로 BWAPI 텍스트가 stdout에 찍힌다.

### 3.4 CMake 옵션 **[확인]**

| 옵션 | 위치 | 의미 |
|---|---|---|
| `OPENBW_DIR` | `OpenBWData/CMakeLists.txt:4-11` | `bwgame.h`가 있는 엔진 소스 경로. 환경 변수 `OPENBW_DIR`로도 가능. 없으면 FATAL |
| `OPENBW_ENABLE_UI` | `OpenBWData/CMakeLists.txt:2,13-16` | SDL2 UI 포함 여부(기본 OFF) |
| `OPENBWAPI_BUILD_STATIC_LIBS` | `bwapi/CMakeLists.txt:16`, `OpenBWData/CMakeLists.txt:26-34`, `BWAPI/CMakeLists.txt` | 정적 빌드(2020-06 PR #14) |
| `USE_OPENBW` | `bwapi/bwapi/CMakeLists.txt:2` | 기본 ON |
| `BUILD_COMPAT` | `bwapi/bwapi/CMakeLists.txt:5-9, 22-24` | 3.7.4/4.1.2 호환 계층, 32비트 |
| `CMAKE_INSTALL_PREFIX` | README | 설치 위치(README는 build 폴더에서 바로 쓰라고 권장) |

산출물: `BWAPI`(공유 lib, `BWAPILIB`+`OpenBWData` 링크), `BWAPILauncher`(실행 파일, `dl` 링크), `BWAPIClient`(정적, 스텁), `ExampleAIModule`, `TestAIModule`. 스레드 라이브러리 필요(`OpenBWData/CMakeLists.txt:45-48`).

### 3.5 환경 변수 전체 목록 **[확인]**

BWAPI 설정: `BWAPI_CONFIG_<섹션대문자>__<키대문자>` 형식이 ini보다 우선한다 (`bwapi/bwapi/BWAPI/Source/Config.cpp:85-88, 92-101`). ini 경로 자체는 `BWAPI_CONFIG_INI`로 바꿀 수 있고 기본은 `./bwapi-data/bwapi.ini` (`Config.h:25-30`).

자주 쓰는 키 (`bwapi/bwapi.ini.example`, `AutoMenuManager.cpp:33-145`):

| 환경 변수 | ini | 기본값 | 비고 |
|---|---|---|---|
| `BWAPI_CONFIG_AI__AI` | `[ai] ai` | 없음 | 봇 `.so` 경로 |
| `BWAPI_CONFIG_AUTO_MENU__AUTO_MENU` | `auto_menu` | OFF | `SINGLE_PLAYER` 또는 `LAN` |
| `BWAPI_CONFIG_AUTO_MENU__MAP` | `map` | "" | 맵 파일 또는 와일드카드 풀 |
| `BWAPI_CONFIG_AUTO_MENU__MAPITERATION` | `mapiteration` | RANDOM | RANDOM은 C `rand()` 사용(`AutoMenuManager.cpp:153-157`) |
| `BWAPI_CONFIG_AUTO_MENU__RACE` | `race` | RANDOM | |
| `BWAPI_CONFIG_AUTO_MENU__ENEMY_COUNT` | `enemy_count` | 1 | |
| `BWAPI_CONFIG_AUTO_MENU__ENEMY_RACE` (`_1`..`_7`) | `enemy_race*` | RANDOM/DEFAULT | |
| `BWAPI_CONFIG_AUTO_MENU__GAME_TYPE` | `game_type` | MELEE | TorchCraft는 `USE_MAP_SETTINGS` |
| `BWAPI_CONFIG_AUTO_MENU__AUTO_RESTART` | `auto_restart` | OFF | ON이면 런처 루프 반복 |
| `BWAPI_CONFIG_AUTO_MENU__SAVE_REPLAY` | `save_replay` | 없음 | |
| `BWAPI_CONFIG_AUTO_MENU__CHARACTER_NAME` | `character_name` | FIRST | |
| `BWAPI_CONFIG_CONFIG__SHARED_MEMORY` | `[config] shared_memory` | ON | 읽기만 하고 실제 동작 없음(3.7절) |

OpenBW 고유 (`BWData.cpp`):

| 환경 변수 | 기본값 | 위치 |
|---|---|---|
| `OPENBW_MPQ_PATH` | `.` | 399, 492, 827, 882 |
| `OPENBW_ENABLE_UI` | `1`(UI 빌드일 때) | 812 |
| `OPENBW_GAME_SPEED` | 없음(ms/프레임, UI만) | 801 |
| `OPENBW_LAN_MODE` | `LOCAL_AUTO`(Windows는 `TCP`) | 530-536; 값 `TCP`/`LOCAL`/`LOCAL_FD`/`LOCAL_AUTO`/`FD`/`FILE` |
| `OPENBW_TCP_LISTEN_HOSTNAME` / `_PORT` | `0.0.0.0` / `6112` | 540-541 |
| `OPENBW_TCP_CONNECT_HOSTNAME` / `_PORT` | `127.0.0.1` / `6112` | 542-543 |
| `OPENBW_LOCAL_AUTO_DIRECTORY` | `/tmp/openbw` | 552-553 |
| `OPENBW_LOCAL_FD`, `OPENBW_LOCAL_PATH` | 없음(필수) | 577-582 |
| `OPENBW_FD_READ` / `OPENBW_FD_WRITE` | 없음(필수) | 600-603 |
| `OPENBW_FILE_READ` / `OPENBW_FILE_WRITE` | 없음(필수, FIFO 권장) | 615-618 |

봇 코드에서 `Game::overrideEnvVar(name, value)`로 환경 변수를 덮어쓸 수도 있다 (`BWData.cpp:1012-1015`, 내부 API).

### 3.6 게임 자동 시작·재시작·2봇 대전 **[확인]**

- `AutoMenuManager::startGame()` (`bwapi/bwapi/BWAPI/Source/BWAPI/AutoMenuManager.cpp:214-315`): 맵 파일명 설정 → 게임 타입 설정 → `SINGLE_PLAYER`면 `createSinglePlayerGame`(내 종족 설정, 열린 슬롯 중 `enemy_count`만큼 상대 종족 지정, 나머지 슬롯 닫기, `startGame()`), `LAN`이면 `createMultiPlayerGame`(플레이어 2명 이상 모이면 시작).
- 싱글플레이 상대 슬롯은 `controller_computer`로 표시되지만 AI 스크립트가 없어 아무 행동도 하지 않는다(1.1절). 빌드오더 최적화처럼 상대 없이 자기 빌드만 평가하는 용도엔 오히려 적합하다 **[추정]**.
- 2봇 대전: 프로세스 두 개를 `auto_menu=LAN`으로 띄우고 `OPENBW_LAN_MODE`로 연결. 1v1만 가능, 두 쪽 맵 설정이 같아야 하며 원본 클라이언트와는 못 붙는다(README). 록스텝이므로 한쪽이 느리면 둘 다 느려진다 **[추정: sync.h 구조]**.
- TorchCraftAI(`src/gameutils/openbwprocess.cpp`)의 실제 사용례 **[확인]**: `BWAPILauncher`를 ForkServer로 fork하며 기본 환경 변수로 `OPENBW_ENABLE_UI=0`, `BWAPI_CONFIG_AUTO_MENU__AUTO_MENU=SINGLE_PLAYER`, `BWAPI_CONFIG_AUTO_MENU__GAME_TYPE=USE_MAP_SETTINGS`, `BWAPI_CONFIG_AUTO_MENU__AUTO_RESTART=OFF`, `BWAPI_CONFIG_AI__AI=<BWEnv.so>`를 주고, 준비 여부는 stdout의 "TorchCraft server listening on socket ..." 문자열로 감지, 10초(1초 × 10회 poll) 넘으면 타임아웃 처리. 종료 시 리플레이 기록을 위해 500ms 유예. 즉 FAIR도 "에피소드마다 프로세스 새로 fork + 싱글플레이" 전략을 썼다.

### 3.7 BWAPI Client(공유 메모리) 모드 **[확인: 동작 안 함]**

- `bwapi/bwapi/BWAPIClient/Source/Client.cpp:20-24`: `Client::connect()`가 `throw std::runtime_error("Client not supported :(")`.
- 서버 쪽 `Server::checkForConnections()`는 빈 함수 (`bwapi/bwapi/BWAPI/Source/BWAPI/Server.cpp:148-150`), 공유 메모리/파이프 생성 코드가 제거되어 `GameData`를 프로세스 내부(`localOnly`)로만 만든다 (`Server.cpp:29-44`).
- 결과: Windows BWAPI의 `BWAPIClient` 방식(별도 프로세스가 공유 메모리로 붙는 방식, 파이썬 바인딩 pybrood/cybw 등이 쓰는 방식)은 **불가**. 봇은 반드시 `.so` AI 모듈이어야 하고, 외부 프로세스(파이썬)와는 그 모듈 안에서 직접 소켓/ZMQ 등을 열어야 한다. TorchCraft의 `BWEnv.so`, JBWAPI의 OpenBW 브리지가 그렇게 한다 **[확인: TorchCraft 문서 "only the shared object works with OpenBW"]**.
- 이 프로젝트 구조(파이썬 에이전트 → C++ 실행기)에는 오히려 자연스럽다. C++ 실행기 = BWAPI AI 모듈 `.so`이며, `onFrame`에서 파이썬 명령을 수신해 `Broodwar` API로 변환하면 된다.

---

## 4. 결정론과 속도 제어

### 4.1 난수 시드 **[확인]**

- 엔진 RNG는 32비트 LCG 하나(`st.lcg_rand_state`, `openbw/bwgame.h:239`, 갱신식 `*22695477+1` `bwgame.h:13200`). 공격 쿨다운 지터(`bwgame.h:2876`), 명령 타이머, 크리터 이동 등 게임 내 모든 무작위가 여기서 나온다.
- 초기화 순서:
  1. 맵 로드 시 `st.lcg_rand_state = 42` (`bwgame.h:20001`).
  2. 게임 시작(`sync_functions::start_game`)에서 `rand_state = seed ^ crc32(모든 클라이언트 uid 문자열)`로 덮어씀 (`openbw/sync.h:685-690`). `seed`는 `start_game_seed`로 기본 0 (`sync.h:29`), uid는 **시계·스레드 ID로 생성** (`sync.h:33-47`).
  - 따라서 **아무 조치 없이 실행하면 매 프로세스/매 게임 시드가 달라진다.**
- 고정 방법: 포크 확장 API `Broodwar->setRandomSeed(uint32_t)` → `impl->st.lcg_rand_state = value` (`GameImpl.cpp:1265-1268`, `BWData.cpp:1593-1596`). `onStart()`(첫 `nextFrame` 전)에서 호출하면 그 뒤 진행은 입력 순서가 같은 한 결정론적이다 **[추정: start_game이 onStart보다 먼저 실행되고 이후 시드를 건드리는 코드가 없음]**. `getRandomSeed()`로 현재 값을 읽을 수 있다 (`GameImpl.cpp:894`).
- 맵 선택의 `RANDOM` 반복은 C `rand()`(`AutoMenuManager.cpp:155`)라 별개. 맵을 하나로 고정하면 무관.
- 리플레이 저장 시 시드가 기록되고(`sync.h:759`) 재생 시 복원된다(`replay.h:119, 221`).

### 4.2 상태 스냅샷 **[확인]**

- `saveSnapshot(id)`/`loadSnapshot(id)`가 `bwgame::copy_state`로 전체 게임 상태를 복사·복원한다 (`BWData.cpp:1585-1590`, 2018-04-30 커밋 "Added multiplayer support for saveSnapshot, loadSnapshot, deleteSnapshot"). 2025-01 커밋이 `state_copier`의 `build_queue_limbo` 복사 버그를 고쳤다.
- 빌드오더 탐색에서 "분기점으로 되돌려 다른 행동 시도"가 가능하다는 뜻이라 RL/탐색에 큰 장점이다. 다만 BWAPI 쪽 캐시(유닛 객체, 이벤트)가 스냅샷과 어긋날 수 있어 검증 필요 **[추정]**.

### 4.3 Wine의 원본 1.16.1보다 빠른가 **[확인: 측정치 없음]**

- 공개 벤치마크가 없다. 구조적 차이는 명확하다 **[추정]**:
  - 원본 + bwheadless: `setLocalSpeed(0)`을 써도 게임 루프가 원본 실행 파일의 타이머·렌더 경로를 거치고 Wine 계층을 지난다. 보고된 실전 속도는 보통 수백 fps 수준이라는 경험담이 커뮤니티에 있으나 이번 조사에서 1차 출처를 확보하지 못했다.
  - OpenBW 헤드리스: sleep 없음, 렌더 없음, 네이티브 바이너리. 병목은 엔진 업데이트와 BWAPI 데이터 복사.
- 결론: "더 빠를 가능성이 높다"는 추정이며 수치는 직접 재야 한다.

### 4.4 BWAPI 없이 엔진을 직접 쓰는 길 **[추정]**

- 엔진은 헤더 전용이고 전역 상태가 없다(`bwgame::state` + `global_state` + `game_state`를 호출자가 소유, `BWData.cpp:939-951`). `OpenBWData/BW/BWData.cpp`(2,582줄)가 "BWAPI가 엔진을 다루는 방법"의 완전한 예제다.
- 과거 `mini-openbwapi/`라는 경량 래퍼가 있었으나 2026-07-16 커밋에서 "long since deprecated"로 삭제됐다 **[확인]**.
- 빌드오더 최적화처럼 필요한 명령이 "훈련/건설/자원 채취" 정도라면 BWAPI 포크를 건너뛰고 `bwgame.h` + `actions.h`를 C++ 실행기에 직접 넣는 쪽이 유지보수(2020년에 멈춘 포크 의존 제거), 속도(BWAPI 복사 비용 제거), 인프로세스 멀티 인스턴스 면에서 유리할 수 있다. 대신 BWAPI의 편의 API(유닛 타입 상수, `canBuild` 판정 등)를 스스로 구현해야 한다. 2단계 검토 사항으로 둔다.

---

## 5. 플랫폼

| 플랫폼 | 상태 | 근거 |
|---|---|---|
| Linux x86_64 | **확인** | 포크 README 빌드 절차, TorchCraftAI Ubuntu 18.04 설치 문서, JBWAPI("Linux natively using openbw"), OpenBW_IDE Dockerfile, 이슈 #27의 리눅스 재현 보고 |
| Windows x64 | **확인** | README(VS2017, CMake 생성), 이슈 #27(VS2017), `_WIN32` 분기 다수. LAN은 TCP만 |
| macOS (x86) | **확인(2차)** | TorchCraftAI OSX 설치 가이드 존재, `openbwprocess.cpp`가 Apple에서 `.dylib`을 찾음 |
| ARM aarch64 (RPi/Jetson/Orange Pi) | **근거 없음** | 이슈·PR·검색에서 빌드 사례 0건. Apple Silicon 사례도 못 찾음 |
| WebAssembly | **확인** | 공식 `openbw/ui/gfxtest.cpp:2-3, 352-354, 666`에 emscripten 경로; heiner/openbw·Pepper-Ng/openbw 포크가 WASI SDK로 `openbw.wasm`을 빌드해 브라우저에서 구동(openbw.heiner.ai, 첫 실행 시 약 90MB 데이터 다운로드) |

ARM 전망 **[추정]**:
- 소스에 x86 고유 코드가 없다. `__x86_64|_mm_|immintrin|asm(` 등을 grep해도 0건이고 유일한 아키텍처 분기는 emscripten뿐이다. 고정소수점(`fp8`) 연산과 표준 C++14만 쓰므로 aarch64 GCC/Clang에서 컴파일될 가능성이 높다. WASM(32비트, 엄격한 정렬)에서 돌아간다는 사실이 이식성의 강한 간접 증거다.
- 위험 요소: (a) 2017년에 UB 수정 커밋("Fix ub: left shift of negative value")이 있었듯 UB 의존 코드가 남아 있으면 컴파일러/아키텍처에 따라 결과가 달라질 수 있다 → x86과 ARM에서 같은 시드·같은 입력으로 상태 해시를 비교하는 검증이 필요. (b) `bwgame.h` 단일 TU 컴파일에 메모리가 많이 든다(헤더 800KB, 템플릿 多) → RAM 1~2GB 보드에서는 크로스 컴파일 권장. (c) asio는 aarch64 리눅스에서 문제없다.
- 성능: 빌드오더 초반 프레임은 가볍지만 Cortex-A53급(RPi 3/Orange Pi Zero)에서는 x86의 1/5~1/10 처리량을 예상. Jetson/RPi 5급이면 현실적 **[추정]**.

---

## 6. 누가 RL/연구에 썼나

| 프로젝트 | OpenBW 사용 방식 | 상태 | 링크 |
|---|---|---|---|
| TorchCraft (FAIR) | `BWEnv.so`를 BWAPI AI 모듈로 올리고 ZMQ로 파이썬/루아에 상태 전송. 문서 `docs/user/openbw.md`에 OpenBW 실행법 | 2022-07-26 아카이브 | https://github.com/TorchCraft/TorchCraft |
| TorchCraftAI / CherryPi (FAIR) | `OpenBwProcess`가 `BWAPILauncher`를 fork, 미니게임 RL·빌드오더 전환(BOS) 학습 환경. SSCAIT 2017-18 우승 봇 | 2022-07-26 아카이브 | https://github.com/TorchCraft/TorchCraftAI , https://torchcraft.github.io/TorchCraftAI/docs/install-linux.html |
| gym-starcraft (apsdehal) | TorchCraft+OpenBW 위의 OpenAI Gym 환경. ICLR 2019 IC3Net 실험에 사용 | 비활성 | https://github.com/apsdehal/gym-starcraft |
| CherryVis | OpenBW 기반 리플레이 시각화(이슈 #29 댓글) | - | TorchCraftAI 내 |
| BWAPI4J (OpenBW 조직) | BWAPI 4.2.0 Java 래퍼, 리눅스에서 OpenBW 브리지 | 2019-07 | https://github.com/OpenBW/BWAPI4J |
| JBWAPI | 순수 Java BWAPI 4.4.0 클라이언트, "Linux natively using openbw" 목표 | 활성 | https://github.com/JavaBWAPI/JBWAPI |
| StardustDevEnvironment (dgant) | Stardust 봇의 게임 실행·통합 테스트에 OpenBW 사용(이슈 #29 댓글, 2021) | 비공개/미확인 | - |
| heiner/openbw, Pepper-Ng/openbw | 브라우저 WASM 샌드박스, 봇 대 봇 관전, P2P 1v1 | 2026 활동 | https://github.com/heiner/openbw , https://openbw.heiner.ai/ |

- 2021년 이후 OpenBW를 쓴 arXiv 논문은 이번 검색에서 찾지 못했다. SC1 RL 연구 자체가 2019년 이후 SC2(pysc2)로 옮겨 갔기 때문으로 보인다 **[추정]**.
- "bwapi-rl", "pysc1"이라는 이름의 실체 있는 프로젝트는 확인하지 못했다.
- sc-docker 기술 보고서(arXiv:1801.02193, 2018)는 향후 "OpenBW와 Remastered 지원 추가"를 계획으로 적었지만 저장소에서 구현 흔적은 못 찾았다 **[확인: 저장소 README에 OpenBW 언급 없음]**.

---

## 7. 원본 1.16.1 + Wine + Docker(sc-docker/scbw)와 비교

### 7.1 sc-docker 사실 **[확인]**

- Games & Simulations Research Group(SSCAIT 운영)의 MIT 라이선스 프로젝트. 이미지 `ggaic/starcraft:{wine,bwapi,java,play}`. 스택: Ubuntu xenial + Wine 2.20 + bwheadless v0.1 + 32비트 Java 8. ICCup 배포 1.16.1을 받아 설치.
- 지원 BWAPI: 3.7.4, 3.7.5, 4.1.2, 4.2.0, 4.4.0(README 내 표기가 섹션마다 다름). 4.4 지원 요청 이슈 #90(2020)이 열려 있음.
- 알려진 문제: headful 모드 "Unable to distribute map" 버그, 헤드리스 속도 선택 불가(#75 열림), 컨테이너 조기 종료(#86), 게임 크래시(#87), 타임아웃과 크래시(#80), 네트워크 생성 실패(#85), Docker 내 UDP 브로드캐스트로 LAN 탐색 실패(#94, 2025-09). 조직 페이지 기준 마지막 갱신 2023-02.
- 관찰 가능성: VNC(5900)로 화면 확인. 리플레이 관전용 observer-docker는 "bwheadless가 리플레이용이 아니라 헤드리스 불가".

### 7.2 비교표

| 항목 | OpenBW + BWAPI 포크 | 원본 1.16.1 + Wine (sc-docker/scbw) |
|---|---|---|
| 게임 로직 충실도 | 재구현. 리플레이 desync 이슈가 남아 있음 | 원본 그 자체 |
| 헤드리스 | 빌드 기본값. 렌더·sleep 없음 | bwheadless가 창을 숨기는 방식. 내부 루프·Wine 오버헤드 존재 |
| 속도 제한 해제 | 자동(헤드리스면 무제한) | `setLocalSpeed(0)`+`setFrameSkip` 필요, 헤드리스 속도 옵션 이슈 있음 |
| 결정론 | `setRandomSeed`로 완전 고정 가능 | 시드 제어 API 없음(원본은 게임 생성 시 시드 결정) |
| 상태 스냅샷/되돌리기 | `saveSnapshot/loadSnapshot` | 불가 |
| 에피소드 재시작 | 같은 프로세스에서 맵 재로드 | 보통 컨테이너/게임 재생성(수 초~수십 초) |
| 의존성 | gcc/cmake(+SDL2 선택). MPQ 3개 | Docker + Wine + X/VNC + 32비트 Java + 1.16.1 설치본 |
| ARM 보드 | 네이티브 컴파일 가능성 높음(미검증) | 사실상 불가(x86 Wine/바이너리; box86 등은 별도 모험) |
| 봇 인터페이스 | `.so` 모듈만. Client 모드 불가 | DLL 모듈·Client 모드 모두 가능(기존 생태계 그대로) |
| BWAPI 버전 | 4.2.0 고정 | 4.4.0까지 |
| 상대 AI | 없음(싱글플레이 상대는 무행동) | 원본 내장 컴퓨터 AI 사용 가능 |
| 유지관리 | 엔진 2026 활동, 포크 2020 정지, 1인 | 2023 정지, 이슈 다수 열림 |
| 라이선스 | 엔진 미지정(위험), 포크 LGPL-3.0 | sc-docker MIT, 게임은 블리자드 EULA |
| 디버그/관찰 | 선택적 SDL2 UI, `drawGameScreen` | VNC로 실제 화면 |

### 7.3 "수천 번의 짧은 에피소드"에 어느 쪽이 믿을 만한가 **[추정]**

- **OpenBW 쪽이 유리**하다. 이유: (1) 프로세스 재시작 없이 에피소드를 반복할 수 있고 실패 모드가 "C++ 예외로 종료"처럼 단순해 감시·재시작 자동화가 쉽다. (2) Wine·X 서버·Docker 네트워크·타이머 같은 외부 변수가 없다. (3) 시드 고정과 스냅샷으로 재현 가능한 실험을 설계할 수 있다. (4) 빌드오더 최적화는 상대 AI와 전투 정밀도가 덜 중요하고, 자원·건설·훈련 시간 로직이 중요하다. 이 부분은 OpenBW의 리플레이 호환 작업이 가장 오래 다듬은 영역이다.
- 단, 다음을 먼저 확인해야 한다: (a) 사용할 맵에서 `error("fixme ...")`나 중립 유닛 반격 경로를 타지 않는지 수백 게임 시험, (b) 빌드 시간·자원 수치가 원본(또는 Liquipedia 표)과 일치하는지 샘플 검증, (c) 메모리·fps 측정, (d) 라이선스 미지정 리스크를 조직 차원에서 수용할 수 있는지.
- 원본 + Wine은 "원본과 100% 같은 수치"가 필요하거나 내장 컴퓨터 AI 상대가 꼭 필요할 때의 대조군으로 남겨 두는 편이 좋다.

---

## 8. 이 프로젝트에 적용할 때의 권장 구성(초안) **[추정]**

1. 리눅스 x86_64 서버에서 `OPENBW_ENABLE_UI` 없이 빌드(SDL2 불필요). 정적 빌드(`OPENBWAPI_BUILD_STATIC_LIBS=ON`)로 배포 단순화.
2. C++ 실행기 = BWAPI AI 모듈 `.so`. `onStart`에서 `setRandomSeed(episode_seed)`, 소켓(ZMQ/gRPC/raw TCP)으로 파이썬 에이전트와 연결, `onFrame`마다 명령 수신 → `Broodwar` API 호출, 관측 송신. 에피소드 종료는 `leaveGame()`.
3. 실행: `OPENBW_MPQ_PATH=<mpq 디렉터리> BWAPI_CONFIG_AI__AI=<실행기.so> BWAPI_CONFIG_AUTO_MENU__AUTO_MENU=SINGLE_PLAYER BWAPI_CONFIG_AUTO_MENU__MAP=<맵> BWAPI_CONFIG_AUTO_MENU__RACE=<종족> BWAPI_CONFIG_AUTO_MENU__ENEMY_COUNT=1 BWAPI_CONFIG_AUTO_MENU__AUTO_RESTART=ON BWAPILauncher` (TorchCraftAI는 `AUTO_RESTART=OFF`로 두고 에피소드마다 프로세스를 새로 띄웠다. 어느 쪽이 안정적인지 둘 다 시험).
4. 병렬화는 프로세스 N개. 각 프로세스에 포트/소켓 경로를 환경 변수로 분리.
5. 1차 검증 항목: fps, RSS, 시드 고정 시 동일 입력 → 동일 상태 해시(`getRandomSeed()`와 자원 수치 비교), 1,000 에피소드 연속 실행 시 예외 발생률.
6. 2차 검토: BWAPI 포크를 버리고 `bwgame.h` 직접 링크(4.4절), ARM 크로스 컴파일.

---

## 9. 미해결 질문

- 1.18 MPQ가 실제로 로드되는지(README와 TorchCraftAI 문서가 상충).
- 헤드리스 처리량과 메모리 실측치.
- `saveSnapshot/loadSnapshot` 뒤 BWAPI 유닛 객체 일관성.
- aarch64 컴파일 여부와 x86 대비 상태 일치 여부.
- 라이선스: tscmoo의 공식 답변 부재. 이슈 #17에 문의를 남기는 것 외엔 방법이 없다.

## 부록: 참고한 출처

- 소스: `dl/openbw`(커밋 4b046d5), `dl/openbw-bwapi`(커밋 48124ba). 참고로 `dl/bwapi` 폴더는 이번 작업 전부터 있던 별개 클론(업스트림 BWAPI로 보임)이며 분석에 쓰지 않았다.
- https://github.com/OpenBW/openbw (이슈 #15, #17, #18, #27, #29, 커밋 목록), https://github.com/OpenBW/bwapi (README, 커밋 목록), https://github.com/openbw (조직 저장소 목록), https://github.com/OpenBW/OpenBW_IDE
- https://torchcraft.github.io/TorchCraftAI/docs/install-linux.html , https://github.com/TorchCraft/TorchCraft (README, docs/user/openbw.md), TorchCraftAI `src/gameutils/openbwprocess.cpp`·`.h`
- https://github.com/apsdehal/gym-starcraft , https://github.com/JavaBWAPI/JBWAPI , https://github.com/OpenBW/BWAPI4J
- https://github.com/heiner/openbw , https://github.com/Pepper-Ng/openbw , https://openbw.heiner.ai/
- https://github.com/Games-and-Simulations/sc-docker (README, 이슈 목록), https://arxiv.org/abs/1801.02193
- https://marianogappa.github.io/inside-brood-war/ (2차 해설), TL.net "OpenBW Introduction" 스레드(검색 요약만, 본문 403)
