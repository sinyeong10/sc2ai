"""스타1 맵(.scm/.scx = MPQ)에서 staredit\\scenario.chk 를 꺼내 섹션을 요약한다.

    py -X utf8 bridge/tools/chk_inspect.py "C:/sin/StarCraft/Maps/BroodWar/(2)Astral Balance.scm" --stormlib <StormLib.dll>

StormLib(https://github.com/ladislav-zezula/StormLib, MIT)을 ctypes 로 쓴다. 64비트 파이썬이면 64비트 DLL.
"""
import argparse
import ctypes
import struct
import sys
from collections import Counter

# CHK 섹션 파싱 (https://wiki.staredit.net/wiki/Scenario.chk)
PLAYER_TYPE = {0: "inactive", 3: "rescue", 5: "computer", 6: "human", 7: "neutral", 8: "closed"}
RACE = {0: "zerg", 1: "terran", 2: "protoss", 5: "user-select", 6: "random", 7: "inactive"}
UNIT_NAMES = {7: "SCV", 64: "Probe", 106: "Command Center", 154: "Nexus", 176: "Mineral Field", 177: "Mineral Field 2",
              178: "Mineral Field 3", 188: "Vespene Geyser", 214: "Start Location"}


def load_stormlib(path):
    lib = ctypes.WinDLL(path, use_last_error=True)  # ANSI 빌드(STORM_UNICODE=OFF): 경로는 char*
    lib.SFileOpenArchive.argtypes = [ctypes.c_char_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.POINTER(ctypes.c_void_p)]
    lib.SFileOpenArchive.restype = ctypes.c_bool
    lib.SFileOpenFileEx.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint32, ctypes.POINTER(ctypes.c_void_p)]
    lib.SFileOpenFileEx.restype = ctypes.c_bool
    lib.SFileGetFileSize.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
    lib.SFileGetFileSize.restype = ctypes.c_uint32
    lib.SFileReadFile.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32), ctypes.c_void_p]
    lib.SFileReadFile.restype = ctypes.c_bool
    lib.SFileCloseFile.argtypes = [ctypes.c_void_p]
    lib.SFileCloseArchive.argtypes = [ctypes.c_void_p]
    lib.SFileCreateArchive.argtypes = [ctypes.c_char_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.POINTER(ctypes.c_void_p)]
    lib.SFileCreateArchive.restype = ctypes.c_bool
    lib.SFileAddFileEx.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32]
    lib.SFileAddFileEx.restype = ctypes.c_bool
    lib.SFileHasFile.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
    lib.SFileHasFile.restype = ctypes.c_bool
    return lib


def read_file(lib, archive, name):
    h = ctypes.c_void_p()
    if not lib.SFileOpenFileEx(archive, name.encode("ascii"), 0, ctypes.byref(h)):
        raise RuntimeError(f"{name} 없음 (GetLastError={ctypes.get_last_error()})")
    size = lib.SFileGetFileSize(h, None)
    buf = ctypes.create_string_buffer(size)
    got = ctypes.c_uint32()
    ok = lib.SFileReadFile(h, buf, size, ctypes.byref(got), None)
    lib.SFileCloseFile(h)
    if not ok or got.value != size:
        raise RuntimeError(f"{name} 읽기 실패 {got.value}/{size}")
    return buf.raw


def extract_chk(lib, map_path):
    a = ctypes.c_void_p()
    if not lib.SFileOpenArchive(map_path.encode("mbcs"), 0, 0x00000100, ctypes.byref(a)):  # MPQ_OPEN_READ_ONLY
        raise RuntimeError(f"맵 열기 실패: {map_path} (err {ctypes.get_last_error()})")
    try:
        names = [n for n in lib_list(lib, a) if n]
        chk = read_file(lib, a, "staredit\\scenario.chk")
    finally:
        lib.SFileCloseArchive(a)
    return chk, names


def lib_list(lib, a):
    # 맵의 MPQ 에는 보통 listfile 이 없다. 알려진 이름만 확인한다
    known = ["staredit\\scenario.chk", "(listfile)", "(attributes)"]
    return [n for n in known if lib.SFileHasFile(a, n.encode("ascii"))]


def parse_sections(chk):
    """섹션 목록 [(name, offset, data)]. 같은 이름이 여러 번 나올 수 있다(나중 것이 덮어쓴다)."""
    out = []
    off = 0
    while off + 8 <= len(chk):
        name = chk[off:off + 4].decode("latin-1")
        size = struct.unpack_from("<i", chk, off + 4)[0]
        if size < 0:  # 음수 크기 = 역방향 덮어쓰기 꼼수(보호 맵). 블리자드 맵에는 없다
            break
        out.append((name, off, chk[off + 8:off + 8 + size]))
        off += 8 + size
    return out


def summarize(chk):
    secs = parse_sections(chk)
    last = {}
    for name, off, data in secs:
        last[name] = data
    print(f"CHK {len(chk)} bytes, 섹션 {len(secs)}개: " + " ".join(f"{n}({len(d)})" for n, _, d in secs))
    if "VER " in last:
        print("VER :", struct.unpack("<H", last["VER "][:2])[0], "(59=hybrid, 63=brood war, 205=remastered)")
    if "OWNR" in last:
        print("OWNR:", [PLAYER_TYPE.get(b, b) for b in last["OWNR"][:8]])
    if "SIDE" in last:
        print("SIDE:", [RACE.get(b, b) for b in last["SIDE"][:8]])
    if "FORC" in last:
        f = last["FORC"]
        print("FORC: player→force", list(f[:8]), "names", struct.unpack("<4H", f[8:16]), "flags", list(f[16:20]))
    if "DIM " in last:
        print("DIM :", struct.unpack("<HH", last["DIM "][:4]))
    if "UNIT" in last:
        u = last["UNIT"]
        n = len(u) // 36
        cnt = Counter()
        starts = []
        for i in range(n):
            x, y, uid, _, _, _, owner = struct.unpack_from("<HHHHHHB", u, i * 36 + 4)
            cnt[(uid, owner)] += 1
            if uid == 214:
                starts.append((owner, x, y))
        print(f"UNIT: {n}개")
        for (uid, owner), c in sorted(cnt.items()):
            print(f"   id {uid:>3} {UNIT_NAMES.get(uid, '?'):<16} owner P{owner + 1}: {c}")
        print("   start locations (owner, x, y):", starts)
    if "TRIG" in last:
        print("TRIG:", len(last["TRIG"]) // 2400, "triggers")
    else:
        print("TRIG: 없음")
    return secs, last


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("map")
    ap.add_argument("--stormlib", required=True)
    ap.add_argument("--dump", help="CHK 를 이 파일로 저장")
    args = ap.parse_args()
    lib = load_stormlib(args.stormlib)
    chk, names = extract_chk(lib, args.map)
    print("MPQ 안 파일:", names)
    summarize(chk)
    if args.dump:
        open(args.dump, "wb").write(chk)
        print("저장:", args.dump)


if __name__ == "__main__":
    main()
