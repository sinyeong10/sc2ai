# BuildExecutor: 스타1용 빌드 명령 실행기 (BWAPI AI 모듈)

`bridge/protocol.md` v1을 TCP로 받아 스타1 안에서 실행한다. 같은 소스가 두 호스트에서 빌드된다.

> **작업 전에 먼저 볼 공식 자료**: API는 https://bwapi.github.io/ (이 모듈이 구현하는 콜백은
> [AIModule](https://bwapi.github.io/class_b_w_a_p_i_1_1_a_i_module.html)), 런타임과 버전은
> https://github.com/bwapi/bwapi/releases (v4.4.0 = 서브모듈 태그). 아래 표의 함수명이 헤더·문서와 다르면 문서가 맞다.

| 호스트 | 산출물 | 게임 | 플랫폼 |
|---|---|---|---|
| BWAPI 4.4.0 + 스타1 1.16.1 | `BuildExecutor.dll` (32비트) | 원본 게임 | Windows (또는 Wine/Docker) |
| OpenBW + OpenBW/bwapi 포크 (**보류**, 서브모듈만) | `libBuildExecutor.so` | 엔진 재구현, 헤드리스 | Linux x86_64 (ARM 미확인) |

AI(Python)는 `bridge/env.py`의 `RemoteBackend`로 붙는다. 어느 호스트인지는 `hello` 응답의 `backend`로 안다.

**이 소스는 작성 환경에 C++ 툴체인과 스타1이 없어 컴파일·실행을 확인하지 못했다.** 메시지 처리 순서는
`bridge/executor_sim.py`(참조 구현, 시험 통과)와 같게 맞췄다. 첫 빌드에서 확인할 것을 아래에 적었다.

## 지금의 범위 (2026-11-08 결정)

작업 PC가 Windows라 **BWAPI(1.16.1) 경로만 빌드한다. OpenBW는 서브모듈로 소스만 고정해 두고 빌드하지 않는다.**

| 서브모듈 | 원본 | 고정 지점 | 용도 |
|---|---|---|---|
| `third_party/bwapi` | github.com/bwapi/bwapi | 태그 **v4.4.0** | CMake 기본 `BWAPI_SRC`. `include/`와 `BWAPILIB/Source`를 이 모듈에 함께 컴파일 |
| `third_party/openbw` | github.com/OpenBW/openbw | master (2026-08-13) | 2차 환경 소스. LICENSE 없음 그대로 |
| `third_party/openbw-bwapi` | github.com/OpenBW/bwapi | `develop-openbw` (2020-06-11) | OpenBW용 BWAPI 4.2.0 포크. `BUGS.txt`, `bwapi.ini.example` 참고 |

### Windows 빌드 순서

선행 조건 셋:

1. 스타1 **1.16.1** 설치본(Remastered는 BWAPI가 못 붙는다). Remastered와 다른 폴더에 둔다.
2. **BWAPI 4.4.0 릴리스 설치본**(`BWAPI_Setup.exe`). 게임에 주입되는 런타임 `BWAPI.dll`과 Chaoslauncher 인젝터가 여기서 나온다.
   서브모듈 `third_party/bwapi`는 컴파일용 소스일 뿐 런타임을 대신하지 않는다.
3. **Visual Studio 2022 Build Tools** "C++ 데스크톱 개발" 워크로드(32비트 MSVC + CMake 포함).
   `winget install Microsoft.VisualStudio.2022.BuildTools --override "--add Microsoft.VisualStudio.Workload.VCTools --includeRecommended --passive"`
   공식 예제의 v141_xp 툴셋은 XP 대상일 때만 필요하다. Windows 10/11에서는 최신 툴셋으로 32비트만 맞추면 된다.

"Developer PowerShell for VS 2022"에서:

```
git submodule update --init third_party/bwapi
cmake -S bridge/cpp -B build-win -A Win32
cmake --build build-win --config Release
```

`build-win/Release/BuildExecutor.dll`을 게임 폴더 `bwapi-data/AI/`에 두고 `bwapi.ini.example`을 `bwapi-data/bwapi.ini`로 복사한다.

서브모듈로 BWAPILIB을 컴파일할 때 주의: `BWAPILIB/Source/BWAPI.cpp`가 포함하는 `svnrev.h`는 저장소에 없고 공식 빌드가 생성한다.
CMake가 설치본과 같은 내용(`SVN_REV = 5016`, v4.4.0)을 빌드 폴더 `gen/`에 만들어 준다. 설치본 헤더 74개를 서브모듈과 대조한 결과
이 파일 하나만 빠져 있고 나머지는 동일했다(2026-11-08).

이 PC의 현재 상태(2026-11-08): 게임 1.16.1은 `C:\sin\StarCraft`, BWAPI 4.4.0 런타임은 설치본이 `C:\sin\StarCraft\bwapi-data\`에 넣었고
SDK·Chaoslauncher는 `C:\Users\cbrnt\BWAPI\`. 레지스트리 `HKCU\Software\Blizzard Entertainment\Starcraft\InstallPath`를 게임 폴더로 등록했다
(Chaoslauncher와 인젝터가 이 값으로 게임을 찾는다). 남은 것은 Build Tools.
v4.4.0의 `ExampleAIModule.vcxproj`와 `BWAPILIB.vcxproj`에서 확인한 설정(`v141_xp`, `NOMINMAX;WIN32;_WIN32_WINNT=0x0501;NTDDI_VERSION=0x05010300`,
BWAPILIB은 정적 라이브러리)을 CMake에 옮겼다. 공식 예제는 동적 CRT지만 여기선 정적 CRT로 둔다.

## 파일

- `src/BuildExecutor.{h,cpp}`: AI 모듈. 자동 기능 A1~A9와 프로토콜 처리.
- `src/TcpLineServer.{h,cpp}`: 줄 단위 TCP 서버. 읽기/쓰기 스레드와 게임 스레드를 큐로 분리. 게임 스레드는 소켓에서 막히지 않는다.
- `src/MiniJson.h`: 의존성 없는 평평한 JSON 읽기/쓰기.
- `src/Dll.cpp`: `gameInit`, `newAIModule` 내보내기.
- `CMakeLists.txt`, `bwapi.ini.example`.

## 환경 변수

| 이름 | 기본 | 뜻 |
|---|---|---|
| `BUILD_EXEC_HOST` | `0.0.0.0` | 바인드 주소. 다른 PC에서 붙으려면 기본값 |
| `BUILD_EXEC_PORT` | `15800` | 포트. 인스턴스를 여럿 띄우면 하나씩 올린다 |
| `BUILD_EXEC_GUI` | `0` | `1`이면 화면을 그린다(디버그). 0이면 `setGUI(false)` |
| `BUILD_EXEC_FRAME_SKIP` | `0` | `setFrameSkip` 값 |
| `BUILD_EXEC_WAIT_EVERY` | `200` | 대기 중 `wait` 메시지 간격(프레임) |
| `BUILD_EXEC_LOG` | `build_exec_log.jsonl` | 명령 실행 시점 관측 로그 |

Windows에서 스타1은 Chaoslauncher/BWAPI 인젝터가 띄우므로 환경 변수는 런처를 실행하는 셸에 둔다.
OpenBW는 `BWAPILauncher`를 실행하는 셸에 둔다.

## 실게임에서 배운 것 (2026-11-08, 1.16.1)

- **BWAPI 는 게임이 끝날 때 모듈 객체를 delete 하고 DLL 을 내린다** (`GameInternals.cpp`). 그래서 TCP 서버와 마지막 응답 등은
  `ExecutorShared`(프로세스 수명)에 두고, `Dll.cpp` 가 `GetModuleHandleEx(PIN)` 으로 DLL 을 고정한다. 소멸자는 서버를 멈추지 않는다.
  멈추면 accept 스레드와 소멸자가 같은 읽기 스레드를 join 해 terminate(0xc0000409)로 게임이 죽었다.
- **건물 비용은 일꾼이 놓을 때 빠진다.** 놓이지 않은 건설 명령의 비용(`watches_`)을 예약해 두고 판정한다. 자리도 예약한다.
  건설하러 가는 일꾼은 `pickBuilder` 에서 뺀다(다시 뽑으면 앞 명령이 취소된다).
- reset 이 게임 재시작을 요구하면 `restartGame()` 뒤 새 모듈 객체의 `onStart` 가 공유 상태의 id 로 응답한다. 실측: 에피소드 하나 8~9초.
- Chaoslauncher 는 관리자 권한이 필요하다(SeDebugPrivilege). 호환성 플래그 `RUNASADMIN` 을 레지스트리에 두면 더블클릭으로 된다.
  이미 떠 있는 인스턴스가 있으면 새로 띄워도 "Already running" 으로 꺼진다(트레이 확인).
- 상대 변수는 `bridge/tools/make_ums_map.py` 로 만든 UMS 맵으로 없앤다(상대 컴퓨터에 AI 스크립트 없음).

## 스레드와 흐름

```
클라이언트 ──TCP──► readLoop ──inbox──► onFrame(handleMessages)
                                           │ step: pending_ 에 두고 매 프레임 tryExecute()
                                           │ reset: wantRestart_ → restartGame() → onStart 에서 응답
                                           ▼
클라이언트 ◄─TCP─── writeLoop ◄─outbox── reply()
```

- `step`은 명령이 실제로 내려진 프레임에 응답한다. 대기 중에는 `waitEvery_`마다 `wait`를 보낸다.
- 건설 명령은 `build()`를 내린 프레임에 응답하고(SC2 로그와 같은 규약), `BuildWatch`가 건물이 놓였는지 확인해
  막혔으면 같은 명령을 다시 내린다. 새 명령이 아니므로 로그에 더 찍히지 않는다.
- 같은 `id`의 `step`이 다시 오면 마지막 응답을 다시 보낸다.
- 클라이언트가 끊기면 대기 명령을 버리고 다음 연결을 기다린다.

## 조사로 확인된 사실과 코드의 대응 (2026-11-08, `docs/스타1-빌드최적화-설계.md` 참고)

| 사실 (출처: BWAPI 저장소 `bwapi/`, OpenBW/bwapi 포크) | 코드의 대응 |
|---|---|
| BWAPI 최신 릴리스 4.4.0(2019), LGPL-3.0, **스타1 1.16.1 전용**. Remastered 미지원(issue #859, 2021 이후 진전 없음) | 원본 경로는 1.16.1 + BWAPI 4.4.0으로 고정 |
| 공식 예제는 VS2017 `v141_xp`, Win32. 4.4.0부터 `BWAPILIB` 프로젝트 소스를 참조(미리 빌드된 lib 없음) | CMake `-DBWAPI_SRC`로 BWAPILIB 소스를 함께 컴파일 |
| AI 모듈 진입점 `gameInit`, `newAIModule` (`GameUpdate.cpp:333-396`) | `Dll.cpp` |
| BWAPIClient(공유 메모리 + 파이프)는 **같은 PC 전용**, 매 프레임 클라이언트 응답을 기다림(`Server.cpp:737-753`) | 원격 PC는 모듈 안 TCP 서버로. 프레임 블로킹은 `onFrame`에서 `waitLine` |
| `enableFlag`는 0프레임에서만(`GameImpl.cpp:238-243`) | `onStart`에서 호출 |
| `setGUI(false)` = `setFrameSkip(9999999)` (`GameDrawing.cpp:199-205`). `speed_override`가 있으면 `setLocalSpeed` 무시 | ini의 `speed_override`를 비움 |
| `restartGame()`은 싱글 플레이어 전용(`GameImpl.cpp:570-581`). bwheadless는 멀티 호스팅이라 동작하지 않을 가능성 | 1.16.1: `restartGame()`. OpenBW: `leaveGame()` + `auto_restart` |
| `setRandomSeed` 없음. 시드는 `bwapi.ini [starcraft] seed_override`(`Detours.cpp:112-124`). OpenBW 포크에만 `setRandomSeed` | `#ifdef OPENBW` 분기, ini 예시에 `seed_override` |
| `Unit::build`는 일꾼이 놀고 있지 않아도 받는다(건설 중만 아니면). true 반환 ≠ 실행 보장 | `BuildWatch`로 건물 생성 확인 후 재발행 |
| `isTraining`은 인구 막힘 때 false | 쓰지 않음. 큐 길이와 남은 시간으로 게이트 선택 |
| OpenBW 포크는 **BWAPI 4.2.0** API, `.so`를 `dlopen`. Client 모드 "not supported". `setFrameSkip` 무효, 헤드리스는 무제한 속도 | 4.2.0에 있는 호출만 썼다(확인 필요: `setCommandOptimizationLevel`, `getFPS`) |
| OpenBW `restartGame()` 깨짐(BUGS.txt). `BWAPILauncher`가 `auto_restart != OFF`면 MPQ 재로딩 없이 다음 게임 | 위 `leaveGame()` 분기 |
| OpenBW에는 컴퓨터 AI가 없어 상대가 가만히 있음 | 빌드 실험에 유리. 1.16.1에서는 상대 종족·맵으로 공격을 피해야 함 |
| 인구는 2배 단위(`Player.h:292,303`) | `state`에 2로 나눠 넣음 |

여기 없는 호출(`getStaticMinerals`, `hasPower`, `canBuildHere`, `getTrainingQueue`, `getRemainingTrainTime`, `getLatencyFrames`)은
BWAPI 4.x 헤더에 있지만 이 모듈을 컴파일해 보지 않았으므로 첫 빌드에서 오류가 나면 헤더를 본다.

## 자동 기능과 SC2 봇의 차이 (시뮬레이터 적합값에 영향)

| 항목 | SC2 봇(incredibot-sct.py) | 이 실행기 |
|---|---|---|
| 일꾼 배분 | python-sc2 `distribute_workers()` (매 프레임, 비결정적) | 거리순 고정 배정, 놀면 자기 패치로 |
| 건설 일꾼 | python-sc2 `build()`가 고름 | 미네랄 안 든 가장 가까운 프로브 |
| 파일런 위치 | 넥서스→적 방향 3(첫), 5~7(이후) 무작위 | 5(첫), 7(이후) 고정 + 나선 탐색 |
| 게이트 위치 | 넥서스에서 가장 가까운 파일런 근처 | 첫 완성 파일런 주변 나선 탐색 |
| 질럿 게이트 배정 | 첫 완성 게이트 큐 + 빈 게이트로 재분배 | 큐 짧고 남은 시간 적은 게이트 |
| 시간 증폭 | 넥서스 에너지로 게이트에 사용 | 스타1에 없음 |
| 종료 프레임 | 다음 iteration 기록(+end_lag≈12) | 완성 이벤트 프레임 |
| 시간 단위 | 1 iteration ≈ 5.5 게임 루프 | 1 프레임 |

노이즈의 출처로 의심되던 일꾼 배분과 건설 위치를 결정론으로 바꿨다(작업 노트 10절). 같은 명령열을 여러 번 돌려
분산이 SC2(중앙값 5, 최대 50 iteration)보다 줄어드는지가 첫 실험이다.
