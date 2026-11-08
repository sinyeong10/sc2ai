# 빌드 명령 실행기 (BWAPI AI 모듈)
#
# 1차 경로: Windows, 스타1 1.16.1 + BWAPI 4.4.0 (32비트 필수). BWAPI 소스는 서브모듈 third_party/bwapi(v4.4.0 고정)에서 읽는다.
#   git submodule update --init third_party/bwapi
#   cmake -S bridge/cpp -B build-win -A Win32
#   cmake --build build-win --config Release
#   → build-win/Release/BuildExecutor.dll 을 bwapi.ini의 ai 항목에 적는다.
#   다른 SDK를 쓰려면 -DBWAPI_SRC=<bwapi 저장소>/bwapi 또는 -DBWAPI_DIR=<include/, lib/BWAPI.lib 가 있는 SDK> 를 준다.
#
# 2차 경로: OpenBW (Linux). 서브모듈 third_party/openbw, third_party/openbw-bwapi 는 등록만 해 두었고 빌드는 아직 하지 않았다.
#   OpenBW/bwapi 포크를 먼저 빌드·설치한 뒤
#   cmake -S bridge/cpp -B build-openbw -DOPENBW=ON -DBWAPI_DIR=/opt/openbw   # include/, lib/ 가 있는 접두사
#   cmake --build build-openbw
#   → BWAPI_CONFIG_AI__AI=$PWD/build-openbw/libBuildExecutor.so BWAPILauncher
#
# 저장소 작성 환경에는 C++ 툴체인이 없어 컴파일을 확인하지 못했다. 처음 빌드할 때 오류가 나면
# BWAPI 헤더의 함수명(README의 "확인할 API" 표)을 먼저 본다.
cmake_minimum_required(VERSION 3.16)
project(BuildExecutor CXX)

set(CMAKE_CXX_STANDARD 14)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

option(OPENBW "OpenBW의 BWAPI 포크로 빌드한다 (Linux .so)" OFF)
set(BWAPI_DIR "" CACHE PATH "BWAPI SDK 또는 OpenBW 설치 접두사 (include/BWAPI.h, lib/)")
# 기본값은 서브모듈. 비어 있으면(서브모듈을 받지 않았으면) BWAPI_DIR 로 떨어진다.
set(BWAPI_SRC "${CMAKE_CURRENT_SOURCE_DIR}/../../third_party/bwapi/bwapi" CACHE PATH
    "bwapi 저장소의 bwapi/ 디렉터리 (include/, BWAPILIB/Source 포함)")

add_library(BuildExecutor SHARED
    src/Dll.cpp
    src/BuildExecutor.cpp
    src/TcpLineServer.cpp)

target_include_directories(BuildExecutor PRIVATE src)

if(OPENBW)
    if(BWAPI_DIR STREQUAL "")
        message(FATAL_ERROR "OpenBW 빌드는 -DBWAPI_DIR=<OpenBW/bwapi 설치 접두사> 가 필요하다")
    endif()
    target_include_directories(BuildExecutor PRIVATE ${BWAPI_DIR}/include)
    target_compile_definitions(BuildExecutor PRIVATE OPENBW=1)
    # OpenBW의 bwapi는 libBWAPI.so (또는 BWAPILIB) 를 제공한다. 설치 구성에 따라 이름이 다르다.
    find_library(BWAPI_LIB NAMES BWAPI BWAPILIB bwapi PATHS ${BWAPI_DIR}/lib ${BWAPI_DIR}/lib64)
    if(NOT BWAPI_LIB)
        message(FATAL_ERROR "OpenBW의 BWAPI 라이브러리를 ${BWAPI_DIR}/lib 에서 찾지 못했다")
    endif()
    target_link_libraries(BuildExecutor PRIVATE ${BWAPI_LIB} pthread)
    set_target_properties(BuildExecutor PROPERTIES CXX_VISIBILITY_PRESET hidden)
else()
    if(NOT CMAKE_SIZEOF_VOID_P EQUAL 4)
        message(FATAL_ERROR "스타1 1.16.1용 BWAPI 모듈은 32비트(-A Win32)로 빌드해야 한다")
    endif()
    # 소스가 UTF-8(한글 주석)이라 MSVC 기본 코드 페이지(949)로 읽으면 excpt.h 의 extern "C" 에서 C2059 가 난다(2026-11-08 확인)
    target_compile_options(BuildExecutor PRIVATE $<$<CXX_COMPILER_ID:MSVC>:/utf-8>)
    # ExampleAIModule.vcxproj / BWAPILIB.vcxproj (v4.4.0) 의 정의를 따른다: XP 대상, NOMINMAX
    target_compile_definitions(BuildExecutor PRIVATE
        _CRT_SECURE_NO_WARNINGS NOMINMAX WIN32 _WINDOWS _USRDLL
        _WIN32_WINNT=0x0501 NTDDI_VERSION=0x05010300)
    # BWAPI 4.4.0부터 미리 빌드된 BWAPI.lib을 배포하지 않고 BWAPILIB 프로젝트(정적 라이브러리) 소스를 함께 컴파일한다
    # (ExampleAIModule.vcxproj가 BWAPILIB.vcxproj를 참조). 서브모듈 third_party/bwapi 가 그 소스다.
    if(EXISTS ${BWAPI_SRC}/BWAPILIB/Source AND EXISTS ${BWAPI_SRC}/include/BWAPI.h)
        # UnitCommand.cpp 는 BWAPILIB/ 바로 아래에 있다(BWAPILIB.vcxproj 참조). 빠지면 UnitCommand::* 가 LNK2019.
        file(GLOB BWAPILIB_SOURCES ${BWAPI_SRC}/BWAPILIB/Source/*.cpp ${BWAPI_SRC}/BWAPILIB/*.cpp)
        target_sources(BuildExecutor PRIVATE ${BWAPILIB_SOURCES})
        # BWAPILIB/Source/BWAPI.cpp 는 <svnrev.h> 를 포함한다. 이 파일은 저장소에 없고(.gitignore) 공식 빌드의 SVNRevGen 이
        # 만든다. 릴리스 설치본(C:\Users\<user>\BWAPI\include\svnrev.h)의 v4.4.0 값은 SVN_REV = 5016. 같은 내용을 빌드 폴더에 만든다.
        set(BWAPI_SVN_REV 5016 CACHE STRING "svnrev.h 의 SVN_REV (v4.4.0 설치본 기준 5016)")
        file(WRITE ${CMAKE_BINARY_DIR}/gen/svnrev.h
            "#pragma once\nstatic const int SVN_REV = ${BWAPI_SVN_REV};\n\n#include \"starcraftver.h\"\n")
        target_include_directories(BuildExecutor PRIVATE ${BWAPI_SRC}/include ${BWAPI_SRC}/BWAPILIB/Source ${CMAKE_BINARY_DIR}/gen)
        target_link_libraries(BuildExecutor PRIVATE ws2_32)
        message(STATUS "BWAPILIB 소스를 함께 컴파일: ${BWAPI_SRC}")
    elseif(NOT BWAPI_DIR STREQUAL "")
        target_include_directories(BuildExecutor PRIVATE ${BWAPI_DIR}/include)
        target_link_libraries(BuildExecutor PRIVATE
            optimized ${BWAPI_DIR}/lib/BWAPI.lib
            debug ${BWAPI_DIR}/lib/BWAPId.lib
            ws2_32)
        message(STATUS "미리 빌드된 BWAPI.lib 링크: ${BWAPI_DIR}")
    else()
        message(FATAL_ERROR
            "BWAPI 소스를 찾지 못했다. 'git submodule update --init third_party/bwapi' 를 실행하거나 "
            "-DBWAPI_SRC=<bwapi 저장소>/bwapi 또는 -DBWAPI_DIR=<SDK> 를 준다")
    endif()
    # 공식 프로젝트는 VS2017 v141_xp 32비트. 다른 툴체인이면 게임(1.16.1, XP 시대 바이너리)과의 호환을 먼저 본다.
    # 공식 예제는 동적 CRT(MultiThreadedDLL)지만 여기선 정적 CRT: 게임 PC에 VC 재배포 패키지가 없어도 로드되게 한다
    set_property(TARGET BuildExecutor PROPERTY MSVC_RUNTIME_LIBRARY "MultiThreaded$<$<CONFIG:Debug>:Debug>")
endif()
