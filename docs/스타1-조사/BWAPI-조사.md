# BWAPI로 스타크래프트 1(브루드워)을 프로그램으로 구동하기 — 조사 초안

- 조사일: 2026-11-08
- 분석한 소스: `https://github.com/bwapi/bwapi` `main` 브랜치, 커밋 `d727fed` (2026-05-08), `git clone --depth 1`
  - 클론 위치: `<조사 시 임시 클론>\bwapi`
  - 아래 `경로:줄` 표기는 모두 이 클론 루트 기준이다.
- 표기 규칙: **[확인]** = 소스 코드나 공식 문서/GitHub API에서 직접 확인. **[추정]** = 확인한 사실에서 유추했거나 2차 자료(커뮤니티 글)에 근거. **[미확인]** = 찾지 못했거나 검증 불가.
- 목적: 다른 PC의 Python RL 에이전트가 C++ 실행기(executor)에 빌드 명령을 보내고, 실행기가 BWAPI로 게임을 조작하는 구조의 타당성 검토.

---

## 0. 한 줄 결론

- BWAPI 최신 릴리스는 **4.4.0 (2019-03-12)**, LGPL-3.0, **StarCraft: Brood War 1.16.1 전용**이다. Remastered는 공식적으로 "미지원(작업 중)" 상태이며, 2021년 이후 진전 공지가 없다. **[확인]**
- BWAPI 클라이언트 모드는 **같은 PC 안에서만** 동작한다(`Local\` 네임스페이스 공유 메모리 + `\\.\pipe\` 명명 파이프). 원격 PC의 Python과 연결하려면 **게임 PC 쪽에 네트워크 브리지(C++ 실행기)를 직접 둬야 한다**. 이것이 요청하신 구조와 정확히 맞는다. **[확인]**
- 클라이언트 모드/AI 모듈 모두 **매 프레임 게임이 봇을 기다린다(블로킹)**. 네트워크 왕복이 느려도 게임 프레임이 어긋나지 않고 멈출 뿐이므로 결정론에 유리하다. **[확인]**
- 결정론: `bwapi.ini`의 `seed_override`로 시드를 고정할 수 있고, `Game::getRandomSeed()`로 읽을 수 있다. `setRandomSeed` API는 없다. 봇이 매 프레임 같은 명령을 내면 같은 결과가 나온다는 것은 브루드워 락스텝/리플레이 구조에서 유추한 것이다. **[확인/추정]**
- 빠른 에피소드 반복: `setLocalSpeed(0)` + `setGUI(false)`(내부적으로 `setFrameSkip(9999999)`) + `sound = OFF` + `auto_menu = SINGLE_PLAYER`, `auto_restart = ON` 또는 `restartGame()`(싱글 플레이 전용). 달성 가능한 초당 논리 프레임 수는 공개된 벤치마크를 찾지 못했다. **[확인/미확인]**

---

## 1. 버전, 라이선스, 지원 게임 버전

### 1.1 릴리스 **[확인]**

| 항목 | 값 | 근거 |
|---|---|---|
| 최신 릴리스 | **v4.4.0**, 2019-03-12 공개 | GitHub API `releases/latest` (2026-11-08 조회) |
| 릴리스 자산 | `BWAPI_Setup.exe` (17.8 MB, 설치기), `BWAPI.7z` (17.9 MB) | GitHub API `releases/tags/v4.4.0` |
| 이전 태그 | 4.3.0 (크래시 多, 비권장), 4.2.0 (VC++2017 이전), 4.1.2, 3.7.5 (구 토너먼트용) | releases 페이지 |
| 저장소 활동 | 마지막 push 2026-06-10, archived 아님, 브랜치 `main`, `develop`, `bwapi4`, `3.7.4` 등 | GitHub API |
| 라이선스 | **LGPL-3.0** (`LICENSE`, `LICENSE.md`) | 클론 루트 |
| 4.4.0 주요 변경 | 4.3.0 크래시 수정, `UserInput` 꺼도 사용자 메시지 수신, 클라이언트 봇 시간 측정, `BWAPILIB.lib` 사전 빌드본 미제공(VS2017 컴파일러 변경 때문에 프로젝트 참조로 빌드) | releases/tag/v4.4.0 |

`main` 브랜치(클론)는 4.4.x 계열 코드다: `CLIENT_VERSION = 10003` (`bwapi/include/BWAPI.h:74`), 툴셋 `v141_xp` (`bwapi/ExampleAIModule/ExampleAIModule.vcxproj:22`).

### 1.2 지원 게임 버전 **[확인]**

- 공식 문서 `bwapi.github.io`: "BWAPI 4.4.0 — StarCraft: Broodwar **1.16.1**용". Remastered 언급 없음. Quick Start는 "1.16.1로 업데이트, ICCup 1.16.1 말고 1.16.1 선택" (`README.md:35-45`에도 동일).
- `develop` 브랜치 README / `bwapi.github.io/bwapi5`: "BWAPI 5+ 릴리스" 링크가 있으나 **"At this time, OpenBW and StarCraft: Remastered are unsupported (but being worked on)"**. 빌드 도구는 VS Community 2019 + CMake(Windows/Mac/Linux).
- GitHub 이슈 #859 "BWAPI5 언제 나오나": 2021-02-11 메인테이너 heinermann이 "Remastered 지원은 Blizzard에 달려 있고 BWAPI 5는 그것과 무관하게 낼 수 있다, 한동안 프로젝트를 떠나 있었다"고 답. 2026-08 기준 여전히 open, 릴리스 일정 없음.
- 2026-11-08 현재 `releases/latest`는 여전히 4.4.0이다. BWAPI 5 정식 릴리스는 없다.

### 1.3 Remastered(SC:R)로 BWAPI를 돌리는 길이 있는가

| 경로 | 상태 |
|---|---|
| 공식 BWAPI 4.4.0 + SC:R | **불가 [확인]**. BWAPI.dll은 1.16.1 바이너리 오프셋에 하드코딩(`bwapi/BWAPI/Source/BW/Offsets.h:90` 등). SSCAIT 튜토리얼, Steamhammer 문서, JBWAPI 튜토리얼 모두 "1.17/1.18+ 및 Remastered 미지원, 1.16.1만 동작, 1.16.1을 Remastered와 나란히 설치 가능"이라고 기술. |
| Blizzard 공식 SC:R 봇 API | **없음 [확인/추정]**. Blizzard 포럼 스레드(2019-08~10)에 Blizzard 직원 답변 없음. 유저들이 "우선순위 낮음 목록에 있다"고 전할 뿐. `bw-web-api`(커뮤니티)는 SC:R이 띄우는 로컬 웹서버의 계정/프로필 엔드포인트를 문서화한 것이지 게임 조작 API가 아니다. |
| "BWAPI Revamped" (captain-majid) | 1.16용 통합 패키지(BWAPI + Chaoslauncher 플러그인 + CoachAI). README에 **"BWAPI won't work with v17+, aka SC:R"** 명시. 라이선스 미표기, 마지막 push 2026-03-11. **[확인]** |
| OpenBW (오픈소스 엔진 재구현) + `OpenBW/bwapi` 포크 | 원본 SC 없이 BWAPI 봇을 돌리는 대안. `OpenBW/bwapi` 마지막 push 2021-05-27, `OpenBW/openbw` 2026-08-13. 1.16.1용으로 컴파일한 봇과 바이너리 호환은 안 됨(SSCAIT). 라이선스 LGPL-3.0(bwapi 포크) / openbw는 GitHub에 라이선스 미표기. **[확인]** |
| **`moccohello/bwrapi`** ("BWAPI for StarCraft: Remastered 1.23.10") | **제3자, 매우 신생 [확인]**. 2026-11-02 push, 13 커밋, 스타 0, MIT(내부에 LGPL BWAPI 4.4 포함). DLL 인젝션으로 SC:R x64/x86에 붙고, BWAPI 4.4 이름을 그대로 쓰는 Python 3.11+ (x64) SDK와 C ABI 제공. 자동 메뉴 없음(직접 매치 시작), sync/async 모드, Windows 전용, 서버당 클라이언트 1개. 안티치트/약관 리스크 언급 없음. **검증된 사용 사례를 찾지 못했다. 실험 가치는 있으나 기반으로 삼기엔 위험.** |

정리: **확인된 동작 경로는 "StarCraft 1.16.1 + BWAPI 4.4.0"뿐이다.** Remastered 경로는 공식적으로 없고, 유일한 후보(`bwrapi`)는 미검증 신생 프로젝트다.

### 1.4 1.16.1 바이너리 입수 **[추정/미확인]**

Blizzard는 현재 SC:R(1.23.x)만 배포하며 1.16.1 패치 서버는 운영하지 않는다. 커뮤니티(sc-docker 등)는 "ICCup 1.16.1" 설치본을 쓴다. 정품 CD키/계정 보유 여부와 무관하게 배포 경로가 비공식이라는 점은 법적·운영적 리스크로 기록해 둔다. 이번 조사에서 공식 배포 링크는 찾지 못했다.

---

## 2. 주입/실행 방식: AI 모듈(DLL) vs 클라이언트(별도 프로세스)

### 2.1 BWAPI.dll 주입 **[확인]**

- `BWAPI_PluginInjector`는 Chaoslauncher/MPQDraft 플러그인이다. 일시정지된 `StarCraft.exe`에 `CreateRemoteThread(LoadLibraryA, "bwapi-data/BWAPI.dll")`로 DLL을 밀어 넣는다.
  - `bwapi/BWAPI_PluginInjector/chaoslauncher.cpp:50-90` (`ApplyPatchSuspended`, LoadLibraryA 주소 획득, 원격 스레드 생성)
  - `bwapi/BWAPI_PluginInjector/common.h:8` (`#define MODULE "BWAPI.dll"`)
  - `bwapi/BWAPI_PluginInjector/remotethread.cpp:4`, `valloc.cpp:17` (WriteProcessMemory)
- 설치기는 Chaoslauncher를 함께 배포한다 (`Installer/Installer.iss:47`). 실행 절차는 `README.md:35-58`.
- 대안 런처 **bwheadless** (tscmoo): 그래픽/사운드/입력 없이 StarCraft.exe를 콘솔 앱처럼 실행하고 `-l BWAPI.dll`로 DLL을 로드한다. CC0-1.0, 마지막 커밋 2018-06-13 (2022-01 push). 옵션은 6절 참고.

### 2.2 BWAPI.dll이 봇을 고르는 순서 **[확인]**

`bwapi/BWAPI/Source/GameUpdate.cpp:325-420`:
1. 매치 시작 시 서버(공유 메모리)에 **클라이언트가 이미 연결돼 있으면** 그 클라이언트를 쓴다 (`:333-343`, 모듈명 `<Client Connection>`).
2. 아니면 `bwapi.ini [ai] ai=` 경로의 DLL을 `LoadLibraryA`하고 `gameInit`, `newAIModule` 심볼을 찾는다 (`:349-370`, `:390-396`). 다중 인스턴스는 쉼표로 구분한 N번째 항목을 쓴다 (`:360-364`).
3. DLL 로드 실패 시 빈 `AIModule`을 만들고 `CompleteMapInformation`, `UserInput` 플래그를 켠 뒤 빨간 오류 메시지를 띄운다 (`:372-382`). 즉 클라이언트 모드에서 `ai=`를 비워도 치명적이지 않다.

클라이언트 연결 대기는 메뉴 프레임에서도 돈다: `bwapi/BWAPI/Source/BWAPI/GameEvents.cpp:419-422` → `server.update()` → `checkForConnections()` (`Server.cpp:251-253`). 따라서 **클라이언트는 매치 시작 전에 접속해 있어야** 한다.

### 2.3 AI 모듈 DLL 방식 **[확인]**

- `BWAPI::AIModule`을 상속하고 `extern "C" __declspec(dllexport)`로 `gameInit(Game*)`과 `newAIModule()`을 내보낸다 (`bwapi/ExampleAIModule/Source/Dll.cpp:6,19-22`).
- 콜백은 게임 스레드에서 호출되며, **BWAPI는 그 스레드에서만 호출해야 한다** (`bwapi/include/BWAPI/AIModule.h:18-21`). 다른 스레드(예: 네트워크 수신 스레드)에서 `Broodwar->` 호출 금지. 네트워크 수신은 큐에 넣고 `onFrame`에서 꺼내 쓰는 구조가 필요하다.
- `onStart` 전에 `Broodwar` 사용 금지 (`AIModule.h:36-38`).

### 2.4 클라이언트 모드(공유 메모리) 프로토콜 **[확인]**

| 요소 | 위치 |
|---|---|
| 클라이언트 라이브러리 | `bwapi/BWAPIClient/Source/Client.cpp` (connect/update/disconnect), 헤더 `bwapi/include/BWAPI/Client/Client.h` |
| 공유 구조체 | `bwapi/include/BWAPI/Client/GameData.h` (`struct GameData`), `GameTable.h` (`struct GameTable`, `GameInstance`), `UnitData.h`, `PlayerData.h`, `Event.h`, `Command.h`, `UnitCommand.h`, `Shape.h` |
| 서버 쪽 | `bwapi/BWAPI/Source/BWAPI/Server.cpp` |
| 예제 | `bwapi/ExampleAIClient/Source/ExampleAIClient.cpp`, `bwapi/AIModuleLoader/Source/AIModuleLoader.cpp` (클라이언트 프로세스 안에서 AI 모듈 DLL을 로드해 돌리는 어댑터) |
| CMake | `CMake/Client/CMakeLists.txt` (정적 라이브러리 `BWAPIClient`/`BWAPIClientd`) |

연결 절차 (`Client.cpp:25-149`):
1. `OpenFileMappingA("Local\\bwapi_shared_memory_game_list")` → `GameTable` 매핑 (`:37-48`). 테이블은 최대 **8개 인스턴스** (`GameTable.h:27`).
2. `serverProcessID != 0 && !isConnected`인 행을 고른다 (`:50-63`).
3. `\\.\pipe\bwapi_pipe_<PID>` 명명 파이프 열기 (`:78-82`), 타임아웃 2초대 (`:90-96`).
4. `Local\bwapi_shared_memory_<PID>`를 `sizeof(GameData)`만큼 매핑 (`:99-107`).
5. `CLIENT_VERSION`(10003) 불일치면 거부 (`:120-129`).
6. 파이프로 코드 `2`가 올 때까지 대기 (`:131-142`).

프레임 동기화:
- 서버: 매 프레임 `Server::update()` (`Server.cpp:225-257`) → `updateSharedMemory()` → `callOnFrame()`이 파이프에 `2`를 쓰고 **클라이언트가 `1`을 돌려줄 때까지 `ReadFile`로 블로킹** (`Server.cpp:737-753`) → `processCommands()`.
- 클라이언트: `Client::update()`가 `1`을 쓰고 `2`가 올 때까지 블로킹 후 이벤트를 처리 (`Client.cpp:173-205`).
- 따라서 **클라이언트 모드의 프레임 지연은 0 프레임**이다. 게임은 클라이언트가 `update()`를 부를 때까지 멈춘다. AI 모듈과 같은 프레임 데이터를 같은 프레임에 본다. 4.4.0부터 클라이언트의 프레임 처리 시간을 측정한다 (`Server.cpp:241-243`, `setLastEventTime`).
- 파이프가 끊기면 서버는 즉시 연결 해제하고 (`Server.cpp:745-751`) 그 프레임부터 DLL 없이 진행한다. 클라이언트는 `isConnected()`가 false가 되면 재연결 루프를 돈다 (`ExampleAIClient.cpp:19-25, 36-41`).

`GameData` 크기 감: `UnitData units[10000]`, `int unitArray[1700]`, 타일 배열 `bool isWalkable[1024][1024]` 등 (`GameData.h:49,52,97`), 이벤트 1만 개, 명령 2만 개 버퍼 (`GameData.h:132-137`). 수십 MB 규모의 고정 레이아웃 구조체다. 포인터 필드는 없다(정수/불리언/char 배열/double).

### 2.5 원격 PC에서 클라이언트가 될 수 있는가 **[확인]**

**불가.** 공유 메모리 이름이 `Local\` 세션 네임스페이스이고 (`Client.cpp:37,75`), 파이프가 `\\.\pipe\`(로컬) (`Client.cpp:79`)이다. 공유 메모리는 원격으로 매핑할 수 없다. 따라서:

- 게임 PC에 C++ 프로세스(AI 모듈 DLL 또는 BWAPIClient 기반 exe)를 두고, 이 프로세스가 TCP/ZeroMQ/gRPC 등으로 원격 Python과 통신하는 **2단 구조가 유일한 방법**이다. TorchCraft가 정확히 이 구조(AI 모듈 + ZMQ)였다 (7절).
- 블로킹 특성 덕분에, 원격 왕복 동안 게임이 멈추므로 **"관측 → 행동"이 같은 프레임에 반영**된다. 지연 보상은 BWAPI의 latency 프레임(4절)만 고려하면 된다.
- **[추정]** 64-bit 클라이언트 가능성: `GameData`에 포인터가 없어 레이아웃이 x86/x64에서 같다면 64-bit 프로세스도 매핑 가능하다. JBWAPI(Java, 64-bit JVM)는 BWAPIClient 라이브러리 없이 "memory mapped client file을 직접 읽는다"고 밝히고 있어 이 추정을 뒷받침한다. 다만 BWAPI가 제공하는 `BWAPIClient` 정적 라이브러리는 Win32만 빌드된다 (`CMake/Client/CMakeLists.txt`, 프로젝트 플랫폼 Win32).

---

## 3. Windows 빌드 요구사항

**[확인]**
- 공식 안내: **Visual Studio 2017** (`README.md:36`, bwapi.github.io). 프로젝트 툴셋은 `v141_xp` (`bwapi/ExampleAIModule/ExampleAIModule.vcxproj:22,27`, `bwapi/BWAPI/BWAPI.vcxproj:38-60`). VS2019/2022에서도 "v141_xp" 툴셋을 설치하거나 툴셋을 올려 빌드하는 사례가 많지만 이는 **[추정]**이며 공식 문서에는 없다.
- 플랫폼: 모든 프로젝트가 **Win32(32-bit)만** 정의 (`ExampleAIModule.vcxproj:6-10`, `BWAPI.vcxproj:6-26`). 1.16.1 게임이 32-bit이므로 주입 DLL은 반드시 32-bit여야 한다. `bwapi.sln:92-99`에 x64 솔루션 구성 이름은 있으나 프로젝트 구성은 Win32뿐이다.
- 빌드 시스템: 메인은 `bwapi/bwapi.sln` + `.vcxproj`. 보조로 `CMake/BWAPI/CMakeLists.txt`, `CMake/Client/CMakeLists.txt`(정적 라이브러리만). 전체 릴리스는 `build.bat`가 `msbuild`로 `Debug_Pipeline`, `Release_Pipeline`, `Installer_Target` 구성을 빌드 (`build.bat:22-27`), 설치기는 Inno Setup (`Installer/Installer.iss`).
- 4.4.0부터 사전 빌드 `BWAPILIB.lib`를 배포하지 않고 **`BWAPILIB` 프로젝트를 참조**로 넣는다 (`ExampleAIModule.vcxproj:100-102`, 릴리스 노트).
- SDK(설치기) 구성 (`Installer/Installer.iss:33-57`): `Starcraft/bwapi-data/BWAPI.dll`, `BWAPId.dll`, `bwapi.ini`, `data/Broodwar.map`, `SNP_DirectIP.snp`, `include/*`, `BWAPILIB/*`, `BWAPIClient/*`, `Shared/*`, `Chaoslauncher/*`, `MPQdraft/*`, `ExampleAIModule`, `ExampleAIClient`, `AIModuleLoader`, `ExampleTournamentModule`, `ExampleProjects.sln`, `documentation/*`, `vc_redist.x86.exe`.
- 공식 SDK 다운로드는 **아직 받을 수 있다**: GitHub 릴리스 v4.4.0 자산 `BWAPI_Setup.exe`, `BWAPI.7z` (2026-11-08 API 조회로 확인).

최소 AI 모듈 프로젝트 구성 (`README.md:40-44`, 예제 소스):
1. 설치 디렉터리의 `ExampleProjects.sln`을 열고 `ExampleAIModule`을 **Release|Win32**로 빌드.
2. 결과 `ExampleAIModule.dll`을 `<StarCraft>/bwapi-data/AI/`에 복사하고 `bwapi.ini [ai] ai=`가 그 경로를 가리키게 한다 (`Release_Binary/Starcraft/bwapi-data/bwapi.ini:8`).
3. 소스 뼈대: `Dll.cpp`(내보내기 2개) + `ExampleAIModule.h/.cpp`(콜백 오버라이드).

클라이언트 exe 최소 구성: `#include <BWAPI.h>`, `#include <BWAPI/Client.h>`, `BWAPIClient.connect()` 루프 → `while(!Broodwar->isInGame()) BWAPIClient.update();` → 인게임 루프에서 `Broodwar->getEvents()` 처리 후 `BWAPIClient.update()` (`ExampleAIClient.cpp:19-96`).

---

## 4. 프로토스 빌드오더 실행기에 필요한 API

모든 선언은 `bwapi/include/BWAPI/` 아래 헤더다. 설명은 헤더의 Doxygen 주석에서 가져왔다. **[확인]**

### 4.1 게임 전역 (`Game.h`)

| 함수 | 위치 | 요점/주의 |
|---|---|---|
| `getFrameCount()` | `Game.h:204` | 논리 프레임 수. 일시정지 중엔 증가 안 함. |
| `getLatency()` | `Game.h:198` | `Latency::Enum` 값 (`Latency.h:12-18`: SinglePlayer=2, LanLow=5 …). 프레임 수가 아님. |
| `getLatencyFrames()` | `Game.h:1301` | 명령 발행→실행까지 최대 프레임 수. 구현 `BWAPI/Source/BWAPI/GameImpl.cpp:781-792`: `LatencyFrames[GameSpeed] * (Latency + callDelay + 1)`, 싱글은 callDelay=1. 값은 런타임에 읽어서 쓰는 게 안전. |
| `getRemainingLatencyFrames()` | `Game.h:1316` | 지금 보낸 명령이 실행되기까지 남은 프레임 (`GameImpl.cpp:798-801`). |
| `isLatComEnabled()/setLatCom(bool)` | `Game.h:1352,1364` | 지연 보상. 켜져 있으면 명령 직후 BWAPI가 예상 상태를 미리 반영. 관측 일관성이 중요하면 끄는 것을 고려. |
| `enableFlag(int)` / `isFlagEnabled` | `Game.h:329,315` | `Flag::CompleteMapInformation=0`, `Flag::UserInput=1` (`Flag.h:13,17`). **프레임 0(`onStart`)에서만 가능**, 이후엔 `Access_Denied` (`GameImpl.cpp:233-243`). |
| `setLocalSpeed(int ms)` | `Game.h:937` | 프레임당 ms. 기본 Fastest=42ms. **0은 "지연 없음"이지 최대 속도 보장이 아님. `setFrameSkip`과 함께 쓰라**고 주석에 명시 (`Game.h:924-926`). UMS 트리거 글리치 버그 주석 (`:928-929`). `speed_override`가 ini에 있으면 무시됨 (`GameImpl.cpp:632-639`). |
| `setFrameSkip(int)` | `Game.h:1439` | 그래픽 1프레임당 논리 프레임 수. 0 이하면 `Invalid_Parameter` (`GameImpl.cpp:661-672`). |
| `setGUI(bool)` / `isGUIEnabled()` | `Game.h:1393,1373` | 렌더링 및 BWAPI 드로잉 비활성. 구현은 `data->hasGUI = enabled; setFrameSkip(enabled ? -1 : 9999999)` (`BWAPI/Source/BWAPI/GameDrawing.cpp:199-205`). 헤더 예제: `onStart`에서 `setLocalSpeed(0); setGUI(false);` "수천 판 최대한 빨리" (`Game.h:1385-1390`). |
| `getFPS()/getAverageFPS()` | `Game.h:225,232` | 논리 FPS 측정에 사용 가능. |
| `restartGame()` | `Game.h:912` | F10 메뉴의 재시작과 동일, **싱글 플레이 전용**. 구현: `isMultiplayer()`면 `Invalid_Parameter`, 아니면 `BW::Orders::RestartGame` 큐잉 (`GameImpl.cpp:570-581`). 성공 여부 반환 없음(`@todo`). |
| `leaveGame()` | `Game.h:906` | 항복 후 점수 화면으로. 구현은 `GameState=0; gwNextGameMode=6` (`GameImpl.cpp:560-568`). 토너먼트 모듈이 막을 수 있음. |
| `pauseGame()/resumeGame()/isPaused()` | `Game.h:898,902,889` | |
| `isInGame()`, `isReplay()`, `isMultiplayer()`, `isBattleNet()` | `Game.h:870,894,876,882` | |
| `canBuildHere(TilePosition, UnitType, Unit builder=nullptr, bool checkExplored=false)` | `Game.h:721` | 크립/**파일런 전력**/자원 거리/타일 buildable/유닛 가림 검사. builder를 주면 경로 존재도 검사하고 builder 자신은 가림 목록에서 제외 (`Game.h:690-720`). |
| `canMake(UnitType, Unit builder=nullptr)` | `Game.h:738` | 자원/서플라이/테크트리/요구 유닛 검사. |
| `getBuildLocation(UnitType, TilePosition desired, int maxRange=64, bool creep=false)` | `Game.h` (비가상, `TilePosition getBuildLocation` 선언 직전 주석 참조) | 기본 컴퓨터 AI 방식의 단순 배치. **못 찾으면 `TilePositions::Invalid` 반환** → 예제는 `if (targetBuildLocation)`로 검사 (`ExampleAIModule.cpp:163-164`). |
| `self()`, `enemy()` | `Game.h:977,987` | `enemy()`는 첫 적만. |
| `getMinerals()`, `getNeutralUnits()`, `getStartLocations()` | `Game.h:79,90,786` | |
| `sendText(fmt,...)`, `printf(fmt,...)`, `operator<<` | `Game.h:789-805` 부근 | `sendText`는 채팅으로 송신(리플레이에 남음), `printf`는 로컬 화면 출력. **반드시 `"%s", text.c_str()` 형태로** (`ExampleAIModule.cpp:198-203`). |
| `getLastError()` | `Game.h:472` | 명령 실패 사유 (`Error.h`: `Unit_Busy`, `Insufficient_Minerals/Gas/Supply/Tech`, `Unbuildable_Location`, `Invalid_Tile_Position` …). |
| `getEvents()` | `Game.h:131` | 클라이언트 모드에서 콜백 대신 사용. `EventType.h:10-27` (`MatchStart/MatchEnd/MatchFrame/MenuFrame/UnitCreate/UnitDestroy/UnitMorph/UnitComplete` …). |
| `setCommandOptimizationLevel(int)` | `Game.h:1590` | 같은 명령 묶기(APM 감소). 예제는 2. |
| `getRandomSeed()` | `Game.h:1728` | 5절. |
| `getClientVersion()`, `getAPM()`, `elapsedTime()` | `Game.h:1339,1413,1495` | |

### 4.2 유닛 (`Unit.h`)

| 함수 | 위치 | 요점/주의 |
|---|---|---|
| `build(UnitType, TilePosition target=None)` | `Unit.h:1401` | 일꾼에게 건설 명령. **target 생략 시 `train`으로 리다이렉트** (`BWAPILIB/Source/Unit.cpp:372-377`). 반환 true = "BWAPI가 게임에 넘겼다"는 뜻이고 **이후 실패 가능성 있음** (`Unit.h:1392-1396`). |
| `train(UnitType)` | `Unit.h:1438` | 생산 큐에 추가. 자원/서플라이/요구사항 필요. 해처리면 라바로 자동 전달. |
| `gather(Unit target, bool shiftQueue=false)` | `Unit.h:1603` | 미네랄/가스 채취. 예제는 `u->gather(u->getClosestUnit(IsMineralField || IsRefinery))` (`ExampleAIModule.cpp:118`). |
| `returnCargo()` | `Unit.h` (gather 아래) | 자원 들고 있는 일꾼 처리 (`ExampleAIModule.cpp:111-114`). |
| `isIdle()` | `Unit.h:1084` | `isCompleted`를 함의. |
| `isTraining()` | `Unit.h:1262` | **큐에 있어도 서플라이/유닛 수 제한으로 진행이 없으면 false** (`Unit.h:1255-1256`). |
| `getTrainingQueue()` | `Unit.h:563` | 오래된 순서대로 `UnitType::list`. |
| `isConstructing()` | `Unit.h:972` | 건설 중이거나 **건설 지점으로 이동 중**이면 true. |
| `isCompleted()`, `isBeingConstructed()`, `getBuildUnit()`, `getBuildType()`, `getRemainingBuildTime()`, `getRemainingTrainTime()` | `Unit.h:964,630,556,585,597` | 4.4.0부터 생산 중 유닛의 `getBuildUnit()`은 생산 건물을 돌려줌. |
| `getLastCommandFrame()`, `getLastCommand()` | `Unit.h:329,335` | "마지막으로 성공적으로 BWAPI에 전달된 명령의 프레임". 중복 발행 방지에 사용. |
| `isPowered()` | `Unit.h:1294` | 프로토스 건물 전력. 예제는 `!isPowered()` 유닛을 건너뜀 (`ExampleAIModule.cpp:92`). |
| `canBuild(...)`, `canTrain(...)`, `canGather(...)` | `Unit.h:2153-2164, 2179-2184, 2280-2285` | 사전 검사. |
| `issueCommand(UnitCommand)` | `Unit.h:1344` | 모든 명령의 공통 경로. |
| `exists()` | `Unit.h:82` | 유닛 포인터를 다룰 때 매번 확인 (`ExampleAIModule.cpp:82-85`). |

### 4.3 플레이어 (`Player.h`)

| 함수 | 위치 | 요점 |
|---|---|---|
| `minerals()`, `gas()` | `Player.h:191,198` | |
| `supplyUsed(Race=None)`, `supplyTotal(Race=None)` | `Player.h:303,292` | **인게임 표시의 2배 단위**(프로브 1기 = 2). 헤더 예제 `supplyUsed()+8 >= supplyTotal()` (`Player.h:286-289`). |
| `allUnitCount(type)`, `completedUnitCount(type)`, `incompleteUnitCount(type)` | `Player.h:319,361`, 예제 `ExampleAIModule.cpp:150` | 중복 건설 방지에 사용. |
| `getUnits()`, `getRace()`, `isVictorious()`, `isDefeated()`, `leftGame()`, `getStartLocation()` | `Player.h:76,96,174,179,184,169` | |

### 4.4 콜백 (`AIModule.h`) / 이벤트

`onStart` (`:39`), `onEnd(bool isWinner)` (`:48`, 리플레이면 false), `onFrame` (`:52`), `onSendText` (`:64`, `UserInput` 꺼지면 호출 안 됨), `onReceiveText`, `onPlayerLeft`, `onNukeDetect`, `onUnitDiscover/Evade/Show/Hide`, `onUnitCreate` (**저그 모프와 가스 위 건설은 제외** — `AIModule.h` 주석), `onUnitDestroy`, `onUnitMorph`, `onUnitRenegade`, `onSaveGame`, `onUnitComplete`. 리플레이도 같은 콜백을 부른다 (`AIModule.h:23-24`).

### 4.5 소스/문서에 적힌 함정(gotcha) 모음

1. **명령 성공 ≠ 실행 보장.** `build/train/gather`의 true는 "넘겼다"는 뜻. 다음 프레임 이후 `isConstructing`, `getTrainingQueue`, `getLastError`로 확인해야 한다 (`Unit.h:1392-1396`, `1428-1430`).
2. **지연 프레임.** 명령은 `getLatencyFrames()` 뒤에 실행된다. 예제는 `getFrameCount() % getLatencyFrames() != 0`이면 `onFrame`을 건너뛰어 스팸을 막는다 (`ExampleAIModule.cpp:74-77`). 같은 유닛에 매 프레임 같은 명령을 다시 내리면 APM만 오르고 상태가 흔들린다. `getLastCommandFrame()`과 비교해 재발행을 억제하라.
3. **일꾼이 반드시 idle일 필요는 없다.** `canBuild`는 "방해 불가 상태 아님(`isInterruptible`), 건설 중 아님, 완성됨"만 요구하고, `isIdle`은 **건물에만** 요구한다 (`bwapi/Shared/Templates.h:773-789`). 예제도 `IsIdle || IsGatheringMinerals`인 일꾼을 고른다 (`ExampleAIModule.cpp:155-157`). 채취 중인 프로브에 바로 `build`를 내려도 된다.
4. **건물에 `train`은 idle일 때만** (`Templates.h:784-785`의 건물 조건). 실제로는 큐가 5개까지 쌓이지만 BWAPI의 `canBuild` 경로는 건물이 `isIdle`이 아닐 때 `Unit_Busy`를 반환한다. 생산 건물에 `train`을 내릴 때는 `canTrain` (`Templates.h` 해당 절) 결과와 `getTrainingQueue().size()`를 함께 보는 것이 안전하다 **[추정: `canTrain` 조건은 별도 확인 필요]**.
5. **`getBuildLocation`은 `TilePositions::Invalid`를 돌려줄 수 있다.** 검사 없이 `build`에 넘기면 `Invalid_Tile_Position`.
6. **프로토스 전력.** `canBuildHere`가 파일런 전력 범위를 검사한다 (`Game.h:691-692`). 파일런 완성(`onUnitComplete`) 전에는 게이트웨이 위치가 무효다. 건물의 `isPowered()`가 false면 생산 명령을 내리지 말 것 (`ExampleAIModule.cpp:92`).
7. **플래그는 프레임 0에서만** (`GameImpl.cpp:238-243`).
8. **서플라이는 2배 단위.**
9. **`isTraining`의 거짓 음성**: 서플라이 막힘 시 false (`Unit.h:1255-1256`). "큐가 비어 있는지"는 `getTrainingQueue().empty()`로 판단.
10. **명령 가능 프레임**: `prepareIssueCommand`가 `lastCommandFrame`을 갱신하고 명령 버퍼/지연 보상 버퍼에 넣는다 (`BWAPI/Source/BWAPI/UnitImpl.cpp:48-85`). 한 프레임에 같은 유닛에 여러 명령을 내리면 마지막 것만 의미가 있다고 보는 게 안전하다 **[추정]**. `CommandOptimizer`는 같은 종류의 명령을 12기 단위로 묶는다 (`CommandOptimizer.cpp:190-215`).
11. **스레드 제약**: 콜백 스레드 밖에서 BWAPI 호출 금지 (`AIModule.h:18-21`). 원격 수신 스레드는 큐만 채우고 `onFrame`에서 소비.
12. **`speed_override`가 설정되면 `setLocalSpeed`는 무시**된다 (`GameImpl.cpp:632-639`, `GameEvents.cpp:26`).
13. **`restartGame`은 멀티플레이어(=bwheadless의 호스트/조인, LAN 포함)에서 실패**한다 (`GameImpl.cpp:573-577`). bwheadless로 띄우면 `isMultiplayer()`가 true일 가능성이 높아 재시작은 `auto_menu`/`leaveGame` 경로를 써야 한다 **[추정]**.

---

## 5. 결정론과 속도

### 5.1 랜덤 시드 **[확인]**

- `Game::getRandomSeed()` (`Game.h:1728`, 4.2.0부터): "이 게임 생성에 쓰인 초기 시드. 오류를 결정론적으로 재현하기 위한 것. 게임과 리플레이 모두에서 동작". 구현은 `BW::BWDATA::ReplayHead.gameSeed.randSeed` 읽기 (`GameImpl.cpp:907-910`). 클라이언트에도 `GameData::randomSeed`로 전달 (`GameData.h:70`, `Server.cpp:497`).
- **`setRandomSeed` API는 없다** (`grep` 결과: `getRandomSeed`만 존재).
- 대신 `bwapi.ini [starcraft] seed_override = <정수>` (`bwapi.ini:171-178`). 구현: BWAPI가 `GetSystemTimeAsFileTime`을 디투어해서 고정 시각을 돌려준다 (`bwapi/BWAPI/Source/Detours.cpp:112-124`). 스타크래프트는 시스템 시각으로 시드를 만들므로 결과적으로 시드가 고정된다. 멀티플레이에서는 호스트가 이 시드를 모두에게 배포한다(ini 주석). `auto_menu`의 맵 랜덤 선택용 `mt19937`도 같은 값으로 시드한다 (`AutoMenuManager.cpp:21-29`).

### 5.2 같은 행동열 → 같은 결과인가 **[추정]**

- 브루드워는 리플레이가 "명령 스트림 + 시드"만으로 재생되는 락스텝 결정론 엔진이다. 따라서 **시드가 같고, 매 프레임 내리는 명령(유닛, 종류, 대상, 프레임 번호)이 같으면 게임 상태는 같다**. 이는 엔진 구조에서 유추한 것이며 BWAPI 문서가 명시적으로 보증하는 문장은 없다(`getRandomSeed` 주석의 "deterministically reproduce"가 가장 가까운 근거).
- 깨지는 조건: 봇이 벽시계(`elapsedTime`, `GetTickCount`)에 의존하는 분기, 비결정적 반복 순서(해시 컨테이너)로 유닛을 고르는 경우, 지연 보상(`setLatCom`) 켜짐 상태에서 예측 상태를 관측으로 쓰는 경우, 블리자드 AI 상대의 경우 상대 행동도 같은 시드에 묶이므로 재현되지만 맵/상대 종족이 `Random`이면 메뉴 단계 시드도 관여한다.
- 클라이언트/AI 모듈 모두 프레임을 블로킹하므로 원격 RL의 추론 지연은 결정론에 영향을 주지 않는다 **[확인: 블로킹 구조]**.

### 5.3 헤드리스에 가까운 속도 **[확인/미확인]**

- 레시피: `setLocalSpeed(0)` + `setGUI(false)`(=`setFrameSkip(9999999)`) + `bwapi.ini [starcraft] sound = OFF` (`bwapi.ini:165-166`, 공식 위키 "음소거와 달리 사운드 엔진 자체를 끈다") + `[window] windowed = ON`(선택). starcraftai.com 위키: GUI를 끄면 그리기/이미지 처리 루틴을 호출하지 않고 게임 루프에 머문다, CPU 스로틀링 옵션이 성능에 영향을 주지 않는다.
- bwheadless를 쓰면 창/사운드/입력 자체가 없다 (`-l BWAPI.dll`).
- **달성 가능한 논리 FPS 수치는 공개 벤치마크를 찾지 못했다.** 공식 위키/문서에 숫자가 없다. 자체 측정 필요(`getAverageFPS()`).
- 참고: 게임 타이머 기준 Fastest는 42ms/프레임 ≈ 23.8 FPS (`Game.h:915-922`).

---

## 6. 에피소드 자동 재시작

### 6.1 방법 비교

| 방법 | 조건 | 근거 |
|---|---|---|
| `Broodwar->restartGame()` | **싱글 플레이만**. 메뉴 없이 같은 맵/설정으로 즉시 재시작. `onEnd` → `onStart` 재호출 **[추정: 콜백 순서는 미확인]** | `GameImpl.cpp:570-581`, `Game.h:908-912` |
| `leaveGame()` + `auto_restart = ON` | 점수 화면에서 BWAPI가 "OK"를 눌러주고(`AutoMenuManager.cpp:473-481`, `GLUE_SCORE_*` 케이스) 다시 `auto_menu` 절차로 새 게임 생성. 맵 와일드카드/랜덤 종족 등 매 판 설정을 바꿀 수 있음. | `bwapi.ini:35-39` |
| 게임 자연 종료 + `auto_restart = ON` | 위와 동일. | |
| 프로세스 재기동(bwheadless/Chaoslauncher) | 가장 느리지만 메모리 누수/상태 오염을 끊는다. sc-docker가 쓰는 방식. | |

매치 종료 판정: 모든 플레이어가 승/패/이탈이면 `MatchEnd` 이벤트 후 `MenuFrame` (`GameUpdate.cpp:70-88`). 클라이언트는 `isInGame()`이 false가 되면 `onMatchEnd` (`Client.cpp:203-204`).

### 6.2 `bwapi.ini` 키 전체 (기본 ini `Release_Binary/Starcraft/bwapi-data/bwapi.ini` + 로더 `AutoMenuManager.cpp:43-146`, `Config.cpp:95-114`, `GameMenu.cpp:25-27`) **[확인]**

**[ai]**
- `ai` = AI 모듈 DLL 경로. 쉼표로 다중 인스턴스별 지정, 부족하면 마지막 항목 사용. 절대 경로 가능 (`:1-8`).
- `ai_dbg` = DEBUG 빌드용 DLL (`:9`).
- `tournament` = 토너먼트 모듈 DLL(RELEASE 전용) (`:11-13`).

**[auto_menu]**
- `auto_menu` = `OFF | SINGLE_PLAYER | LAN | BATTLE_NET` (`:16-18`). 리플레이는 `map`에 `.rep` 경로.
- `character_name` = `FIRST | WAIT | <이름>` (`:20-24`).
- `pause_dbg` = `ON|OFF`, DEBUG에서 디버거 붙을 때까지 대기 (`:26-29`).
- `lan_mode` = 멀티플레이 목록 텍스트 그대로(`Local Area Network (UDP)`, `Local PC`, `Direct IP`) (`:31-33`).
- `auto_restart` = `ON|OFF`, 종료 화면 자동 통과 후 다음 매치 (`:35-39`).
- `map` = 호스트할 맵 경로(StarCraft 폴더 기준), 파일명에 `?`/`*` 와일드카드. 비우면 참가 (`:41-45`).
- `game` = 참가할 게임 이름 또는 `JOIN_FIRST`; 없고 `map`이 있으면 생성 (`:47-52`).
- `mapiteration` = `RANDOM | SEQUENCE` (`:54-56`).
- `race` = `Terran|Protoss|Zerg|Random` (+ 로더는 `RandomTP/TZ/PZ` 처리, `AutoMenuManager.cpp:393-399`), 쉼표로 인스턴스별 (`:58-64`).
- `enemy_count` = 1~7, 싱글 전용 (`:66-68`, 로더가 0~7로 클램프 `:137-138`).
- `enemy_race` = `Terran|Protoss|Zerg|Random|RandomTP|RandomTZ|RandomPZ|RandomTPZ` (`:70-72`).
- `enemy_race_1..7` = 슬롯별, `Default`면 `enemy_race` (`:74-82`).
- `game_type` = `TOP_VS_BOTTOM|MELEE|FREE_FOR_ALL|ONE_ON_ONE|USE_MAP_SETTINGS|CAPTURE_THE_FLAG|GREED|SLAUGHTER|SUDDEN_DEATH|TEAM_MELEE|TEAM_FREE_FOR_ALL|TEAM_CAPTURE_THE_FLAG` (`:84-86`).
- `game_type_extra` = 보조 드롭다운 값(`3 vs 1`, `2500` 등) (`:88-97`).
- `save_replay` = 리플레이 저장 경로. `%BOTNAME%`, `%BOTNAME6%`, `%BOTRACE%`, `%MAP%`, `%ALLYNAMES%`, `%ALLYRACES%`, `%ENEMYNAMES%`, `%ENEMYRACES%`, `%GAMERESULT%`, `$`+strftime 서식 (`:99-101`, 공식 위키 Configuration).
- `wait_for_min_players` = 네트워크 게임 시작 최소 인원(BWAPI 포함) (`:103-106`, 기본 2).
- `wait_for_max_players` = 이 인원이 차면 즉시 시작 (`:108-111`, 기본 8).
- `wait_for_time` = 최소 인원 충족 후 대기 ms (`:113-116`, ini 기본 60000, 코드 기본 30000).

**[config]**
- `holiday` = `ON|OFF` (위키: 현재 동작 없음) (`:119-121`).
- `shared_memory` = `ON|OFF`, OFF면 BWAPI 서버(클라이언트 모드) 비활성 — WINE 우회용 (`:123-126`, `Config.cpp:103`).
- `console_attach_on_startup`, `console_alloc_on_startup`, `console_attach_auto`, `console_alloc_auto` = `TRUE|FALSE`, stdout/stderr 콘솔 (`:128-145`).
- `show_warnings` = `YES|NO` (ini에는 없고 코드에만, `Config.cpp:100`).

**[window]**
- `windowed` = `ON|OFF` (`:150-152`), `left`, `top`, `width`, `height` (`:154-162`, 최소 크기 클램프 `Config.cpp:116-120`).

**[starcraft]**
- `sound` = `ON|OFF` 사운드 엔진 (`:164-166`).
- `screenshots` = `gif|pcx|tga|bmp` (`:168-169`).
- `seed_override` = 10진 정수. 주석 처리 시 시스템 시각 사용 (`:171-178`).
- `speed_override` = 프레임당 ms, 설정하면 봇의 속도 변경 차단; 음수면 기본 (`:180-183`).
- `drop_players` = `ON|OFF` 타임아웃 시 드롭 (`:185-189`).

**환경 변수 오버라이드** (공식 위키 Configuration): `BWAPI_CONFIG_<SECTION>__<KEY>` (대문자, 더블 언더스코어)로 어떤 키든 덮어쓰기, `BWAPI_CONFIG_INI`로 ini 파일 경로 변경. 컨테이너/자동화에 유용. **[확인: 위키]**

### 6.3 RL용 권장 조합 **[추정]**

```
[ai]        ai = (클라이언트 모드면 임의/빈 값; AI 모듈이면 실행기 DLL 경로)
[auto_menu] auto_menu = SINGLE_PLAYER, map = maps/<고정맵>.scx, race = Protoss,
            enemy_count = 1, enemy_race = <고정>, game_type = MELEE, auto_restart = ON,
            save_replay = (비우거나 디스크 여유 확인)
[starcraft] sound = OFF, seed_override = <에피소드별로 바꾸려면 BWAPI_CONFIG_STARCRAFT__SEED_OVERRIDE 환경변수로 프로세스 재기동>
[window]    windowed = ON (디버깅), 운영 시 bwheadless 고려
```
`onStart`에서 `setLocalSpeed(0); setGUI(false); setLatCom(false)` 검토. 한 에피소드가 끝나면 `restartGame()`(싱글) 또는 `leaveGame()`+`auto_restart`. 시드는 프로세스 수명 동안 고정이므로(ini는 시작 시 읽음, `GameMenu.cpp:25`; `reloadConfig()`는 메뉴 단계에서 호출됨 — 매 판 ini를 다시 읽는지는 **[미확인]**) 시드를 판마다 바꾸려면 재기동이 확실하다.

### 6.4 bwheadless 옵션 (`tscmoo/bwheadless` `main.cpp` usage 문자열) **[확인]**

`-e/--exe` (기본 `StarCraft.exe`), `-h/--host`, `-j/--join`, `-n/--name`, `-g/--game`, `-m/--map`, `-r/--race`, `-l/--dll` (여러 번 가능, BWAPI.dll 로드), `--networkprovider UDPN|SMEM` (기본 SMEM = BWAPI의 Local PC), `--lan`, `--localpc`, `--lan-sendto IP` (6111/6112 포트), `--installpath PATH` (BWAPI가 `bwapi-data/bwapi.ini`를 찾는 경로). 호스트/조인 구조라 **멀티플레이 게임**을 만든다. 블리자드 AI 상대 싱글 플레이는 bwheadless 옵션에 없다(`auto_menu`로는 가능할지 **[미확인]**).

---

## 7. Python 브리지 현황 (2026-11-08 GitHub API 기준)

| 프로젝트 | 바인딩 방식 | 대상 버전 | 마지막 push / 상태 | 라이선스 | 원격 PC |
|---|---|---|---|---|---|
| **pybrood** (neumond) | pybind11, 자체 코드 생성기로 MSVC 프로젝트 생성, `BWAPIClient.lib` 링크(클라이언트 모드로 추정) | BWAPI 4.1.2, Python 3.5, Win32 | 2018-06-16, 사실상 중단 | MIT | 불가(공유 메모리) |
| **PyBW** (crass) | SWIG, 별도 `pybwClient.exe`(클라이언트 모드) | BWAPI 3.7, Python 2.6, VS2008 | 2011-11-30, 사망 | 미표기 | 불가 |
| **TorchCraft** (Facebook) | BWAPI **AI 모듈 DLL** 안에서 ZMQ 서버, Python/C++/Lua 클라이언트, zstd 압축 | SC 1.16.1 + BWAPI 4.x (정확한 버전 미확인) | **archived 2022-07-26**, 마지막 push 2021-08-30 | BSD (Facebook) + PATENTS | **가능** (`-t <server_ip>`, 포트 11111). RL 참조 설계로 가치 큼 |
| **scbw / sc-docker** (Games-and-Simulations) | Python 런처(`scbw.play`)가 Docker+Wine 안의 SC 1.16.1(ICCup)과 bwheadless를 띄움. 봇은 컨테이너 안에서 BWAPI 클라이언트/DLL/Java로 실행 | BWAPI 3.7.4/3.7.5/4.1.2/4.2.0/4.4.0 | 2023-02-25, archived 아님 | MIT | 봇은 컨테이너 내부; `--headless`, `--game_speed 0` 옵션(PyPI 설명). 게임 파일 다운로드 호스트가 죽었다는 보고 있음 |
| **bwrapi** (moccohello) | SC:R에 DLL 인젝션, BWAPI 4.4 호환 C ABI + Python 3.11+ x64 SDK (`bwrapi.bwapi`, `AIModule` 상속, `Broodwar` 객체), sync/async | **SC:R 1.23.10** | 2026-11-02, 13 커밋, 스타 0 | MIT (+LGPL BWAPI 포함) | 미표기, Windows 전용, 서버당 1 클라이언트 |
| cybw, bwapi-py, python-bwapi, PyBWAPI | **찾지 못함** (검색 2회) | — | — | — | — |
| (참고) **JBWAPI** (Java) | BWAPIClient 라이브러리 없이 memory-mapped 파일을 직접 읽음, async 지원 | BWAPI 4.4.0 | 2026-11-07 활발 | MIT | 불가(로컬) — 그러나 "직접 mmap" 접근의 실증 |

결론: **원격 PC를 지원하는 기성 Python 브리지는 TorchCraft뿐이고 이미 아카이브됐다.** 요청하신 "C++ 실행기 + 원격 Python" 구조를 직접 만드는 것이 현실적이며, TorchCraft 소스(ZMQ + 직렬화 + AI 모듈)가 가장 가까운 참고 설계다.

### 설계 메모 **[추정]**

- 실행기는 **AI 모듈 DLL**보다 **BWAPIClient 기반 exe**가 디버깅/크래시 격리에 유리하다(게임 프로세스 밖, 재연결 가능 `Client.cpp:150-172`). 단 클라이언트는 매치 전 접속 필요(2.2절).
- 네트워크 프로토콜은 "프레임 N 관측 → 행동 리스트 → ack" 동기식이면 충분하다. 게임이 어차피 블로킹된다.
- 빌드오더 수준 행동이면 관측은 `minerals/gas/supplyUsed/supplyTotal/frameCount/각 유닛타입 count(all/completed/incomplete)/생산 큐`로 압축 가능. `GameData` 전체(수십 MB)를 보내지 말 것.
- 행동 실행은 실행기 안에서 매크로로: `train(type)`→idle 게이트웨이/넥서스 선택, `build(type)`→`getBuildLocation`(또는 BWEB)→채취 중 프로브 선택→`build`→`isConstructing`/`onUnitCreate`로 확인→실패 시 재시도. 재발행 억제에 `getLastCommandFrame()`.

---

## 8. BWEM / BWEB (맵 분석·배치 라이브러리)

| 라이브러리 | 내용 | 라이선스 | 상태 |
|---|---|---|---|
| **BWEM** (Igor Dimitrijevic, SourceForge `bwem`) | 지역/초크/베이스 분석. BWTA 후속으로 사실상 표준 | **MIT/X11** (SourceForge, 홈페이지, `BWEM-community/LICENSE` 첫 줄 "(MIT/X11 License) Copyright (c) 2015, 2017, Igor Dimitrijevic") | 원본 1.4.1; 커뮤니티 포크 `N00byEdge/BWEM-community` 마지막 push 2021-06-01 |
| **BWEB** (Cmccrave) | BWEM 기반 건물 배치: Blocks(종족별 건물 블록, 1.13.0에서 저그 추가), Walls(초크 벽+방어+문), Stations(각 베이스 배치), JPS 경로 탐색. BWEM 초기화 후 초기화 필요 | **MIT** | 마지막 push 2026-04-22, 활발 |

프로토스 빌드 실행기라면 `getBuildLocation`으로 시작하고, 파일런 전력 범위를 고려한 안정적 배치가 필요해지면 BWEB Blocks를 붙이는 순서가 자연스럽다 **[추정]**. BWEM/BWEB 모두 C++ 라이브러리이므로 실행기(C++) 쪽에 넣는다.

---

## 9. 리스크·미해결 사항 요약

1. **1.16.1 입수와 라이선스**: 공식 배포 없음. [미확인]
2. **BWAPI 5/Remastered**: 2021 이후 진전 없음. `bwrapi`는 미검증.
3. **속도 수치**: 헤드리스 논리 FPS 벤치마크 없음 → 자체 측정 필요.
4. **`restartGame` 후 콜백 순서/유닛 ID 리셋, 멀티 인스턴스에서의 동작**: 소스 주석만으로는 불명. 실험 필요.
5. **64-bit 클라이언트의 `GameData` 레이아웃 호환**: JBWAPI 사례로 가능성 높으나 C++로는 Win32 빌드를 쓰는 게 안전.
6. **VS2017 `v141_xp` 툴셋 확보**: 최신 VS에서 별도 설치 필요(추정).
7. **블리자드 AI 상대 싱글 플레이를 bwheadless로 띄울 수 있는지**: 미확인. 창 모드 + GUI off로 대체 가능.

## 10. 참고 자료

- BWAPI 저장소/릴리스: https://github.com/bwapi/bwapi , https://github.com/bwapi/bwapi/releases/tag/v4.4.0
- 공식 문서: https://bwapi.github.io/ , https://bwapi.github.io/bwapi5/index.html
- 설정 위키: https://github.com/bwapi/bwapi/wiki/Configuration
- 이슈 #859 (BWAPI 5 일정): https://github.com/bwapi/bwapi/issues/859
- Blizzard 포럼 "BWAPI with Starcraft Remastered": https://us.forums.blizzard.com/en/starcraft/t/bwapi-with-starcraft-remastered-newest-version/565
- bwheadless: https://github.com/tscmoo/bwheadless
- sc-docker / scbw: https://github.com/Games-and-Simulations/sc-docker , https://pypi.org/project/scbw
- TorchCraft: https://github.com/TorchCraft/TorchCraft
- pybrood: https://github.com/neumond/pybrood ; PyBW: https://github.com/crass/PyBW
- bwrapi (SC:R): https://github.com/moccohello/bwrapi
- JBWAPI: https://github.com/JavaBWAPI/JBWAPI
- BWEM: https://bwem.sourceforge.net/ , https://github.com/N00byEdge/BWEM-community ; BWEB: https://github.com/Cmccrave/BWEB
- 속도 팁: https://starcraftai.com/wiki/Increasing_StarCraft_Speed
- OpenBW: https://github.com/OpenBW/bwapi , https://github.com/OpenBW/openbw
