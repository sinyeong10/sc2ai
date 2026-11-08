# 맵 도구: 상대가 아무것도 하지 않는 UMS 맵 만들기

빌드 최적화 데이터에서 상대 변수를 없애기 위해, 멜리 2인용 맵을 **Use Map Settings** 맵으로 바꾼다.
UMS 에서 컴퓨터 플레이어는 AI 스크립트를 돌리는 트리거가 없으면 아무것도 하지 않는다(일꾼도 채취하지 않음).

- `chk_inspect.py`: 맵(.scm/.scx = MPQ)에서 `staredit\scenario.chk` 를 꺼내 OWNR/SIDE/FORC/UNIT/TRIG 를 요약한다.
- `make_ums_map.py`: 변환. P1 사람(프로토스), P2 컴퓨터(테란), 각 시작 위치에 본진 건물 + 일꾼 4, 트리거는 원본의
  "항상 → 미네랄 50 설정"만 남긴다(UMS 는 트리거 없이는 자원 0). 승패 트리거는 뺀다. VCOD 등 다른 섹션은 그대로.

## StormLib

MPQ 읽기/쓰기는 [StormLib](https://github.com/ladislav-zezula/StormLib)(MIT)을 ctypes 로 쓴다. 저장소에 넣지 않았으므로 직접 빌드한다.
파이썬이 64비트면 64비트 DLL. ANSI 빌드(기본, `STORM_UNICODE=OFF`)를 전제로 경로를 `char*` 로 넘긴다.

```
git clone --depth 1 https://github.com/ladislav-zezula/StormLib <어딘가>/stormlib-src
cmake -S <어딘가>/stormlib-src -B <어딘가>/stormlib-build -A x64 -DBUILD_SHARED_LIBS=ON -DSTORM_SKIP_INSTALL=ON -DSTORM_USE_BUNDLED_LIBRARIES=ON
cmake --build <어딘가>/stormlib-build --config Release
→ <어딘가>/stormlib-build/Release/StormLib.dll
```

## 사용

```
py -X utf8 bridge/tools/chk_inspect.py "C:/sin/StarCraft/Maps/BroodWar/(2)Astral Balance.scm" --stormlib <StormLib.dll>
py -X utf8 bridge/tools/make_ums_map.py "C:/sin/StarCraft/Maps/BroodWar/(2)Astral Balance.scm" "C:/sin/StarCraft/Maps/sc2ai/(2)Astral Balance UMS.scm" --stormlib <StormLib.dll>
```

`bwapi.ini`: `map = maps/sc2ai/(2)Astral Balance UMS.scm`, `game_type = USE_MAP_SETTINGS`.

변환한 맵은 블리자드 맵의 파생물이라 저장소에 넣지 않는다. 2026-11-08 에 Astral Balance 로 만든 맵이 1.16.1 에서 정상적으로
열렸고(VCOD 통과), 시작 미네랄 50, 상대 SCV 정지, N=5 명령열 10회 종료 프레임이 모두 4557 이었다.

참고: CHK 형식은 https://wiki.staredit.net/wiki/Scenario.chk , 유닛 ID 는 BWAPI `UnitType.h` 의 열거 순서(SCV 7, 프로브 64,
커맨드센터 106, 넥서스 154, 시작 위치 214).
