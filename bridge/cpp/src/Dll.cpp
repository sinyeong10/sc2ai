// AI 모듈 진입점. Windows(BWAPI 1.16.1 DLL)와 OpenBW(.so) 공통.
//
// BWAPI는 게임이 끝날 때마다 AI 모듈 객체를 delete 하고 라이브러리를 내린다
// (bwapi/BWAPI/Source/BWAPI/GameInternals.cpp: delete client → FreeLibrary). 그러면 TCP 서버와 클라이언트 연결이
// 게임마다 끊긴다. 여기서 라이브러리를 프로세스에 고정(pin)해 내려가지 않게 하고, 서버 등 공유 상태는
// executorShared()(프로세스 수명)에 두어 reset → restartGame → 새 모듈 객체로 이어지게 한다.
#include <BWAPI.h>

#include "BuildExecutor.h"

#ifdef _WIN32
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#define EXPORT extern "C" __declspec(dllexport)

static void pinSelf() {
    HMODULE h = nullptr;
    GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_PIN,
                       reinterpret_cast<LPCWSTR>(&pinSelf), &h);
}

BOOL APIENTRY DllMain(HMODULE, DWORD reason, LPVOID) {
    if (reason == DLL_PROCESS_ATTACH) pinSelf();
    return TRUE;
}
#else
#ifndef _GNU_SOURCE
#define _GNU_SOURCE
#endif
#include <dlfcn.h>
#define EXPORT extern "C" __attribute__((visibility("default")))

__attribute__((constructor)) static void pinSelf() {
    Dl_info info;
    if (dladdr(reinterpret_cast<void*>(&pinSelf), &info) && info.dli_fname)
        dlopen(info.dli_fname, RTLD_NOW | RTLD_NOLOAD | RTLD_NODELETE);  // dlclose 되어도 내려가지 않는다
}
#endif

EXPORT void gameInit(BWAPI::Game* game) { BWAPI::BroodwarPtr = game; }
EXPORT BWAPI::AIModule* newAIModule() { return new BuildExecutor(); }
