"""멜리 2인용 맵을 "상대가 아무것도 하지 않는" Use Map Settings 맵으로 바꾼다.

    py -X utf8 bridge/tools/make_ums_map.py "<원본.scm>" "<출력.scm>" --stormlib <StormLib.dll>

바꾸는 것 (CHK, https://wiki.staredit.net/wiki/Scenario.chk):
- OWNR: P1 사람(6), P2 컴퓨터(5). 나머지 비활성.
- SIDE: P1 프로토스(2), P2 테란(1). 종족을 고정한다.
- FORC: P2 를 2번 세력으로, "무작위 시작 위치" 플래그를 끈다.
- UNIT: 멜리에서는 게임이 시작 유닛을 만들지만 UMS 는 놓인 유닛만 쓴다. P1 시작 위치에 넥서스+프로브 4,
        P2 시작 위치에 커맨드센터+SCV 4 를 놓는다. 시작 위치 유닛은 BWAPI getStartLocation 용으로 둔다.
- TRIG: 원본의 멜리 트리거 중 "항상 → 현재 플레이어 미네랄 50 설정"(모든 플레이어 실행)만 남긴다.
        UMS 는 트리거 없이는 자원이 0 이다. 승패 트리거는 뺀다(에피소드는 BWAPI 가 restartGame 으로 돌린다).
        컴퓨터 플레이어는 AI 스크립트를 돌리는 트리거가 없으면 아무것도 하지 않는다.
- VCOD 등 나머지 섹션은 그대로.

검증: 게임에서 맵이 열리는지(VCOD), 시작 미네랄 50, 상대 SCV 가 가만히 있는지 눈으로 본다.
"""
import argparse
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import chk_inspect as ci  # noqa: E402
import ctypes  # noqa: E402

NEXUS, PROBE, COMMAND_CENTER, SCV, START_LOCATION = 154, 64, 106, 7, 214
MPQ_CREATE_LISTFILE = 0x00100000
MPQ_FILE_COMPRESS = 0x00000200
MPQ_FILE_REPLACEEXISTING = 0x80000000
MPQ_COMPRESSION_PKWARE = 0x08  # 스타1 Storm.dll 이 확실히 푸는 방식


def unit_entry(uid, x, y, owner, hp=100, sh=100, en=100):
    # validProp: bit0 owner, bit1 hp, bit2 shields, bit3 energy. validSpecial 0 → 특수 상태 없음
    return struct.pack("<IHHHHHHBBBBIHHII", 0, x, y, uid, 0, 0, 0x000F, owner, hp, sh, en, 0, 0, 0, 0, 0)


def rebuild_chk(chk):
    secs = ci.parse_sections(chk)
    last = {n: d for n, _, d in secs}
    starts = {}
    u = last["UNIT"]
    for i in range(len(u) // 36):
        x, y, uid = struct.unpack_from("<HHH", u, i * 36 + 4)
        owner = u[i * 36 + 16]
        if uid == START_LOCATION:
            starts[owner] = (x, y)
    if 0 not in starts or 1 not in starts:
        raise SystemExit(f"P1/P2 시작 위치가 없다: {starts}")

    new = {}
    ownr = bytearray(last["OWNR"])
    ownr[0], ownr[1] = 6, 5
    for i in range(2, 8):
        ownr[i] = 0
    new["OWNR"] = bytes(ownr)
    side = bytearray(last["SIDE"])
    side[0], side[1] = 2, 1
    new["SIDE"] = bytes(side)
    forc = bytearray(last["FORC"])
    forc[1] = 1          # P2 → 세력 2
    forc[16] = 0         # 세력 1 플래그: 무작위 시작 위치 끔
    forc[17] = 0
    new["FORC"] = bytes(forc)

    add = []
    for owner, (depot, worker) in ((0, (NEXUS, PROBE)), (1, (COMMAND_CENTER, SCV))):
        sx, sy = starts[owner]
        add.append(unit_entry(depot, sx, sy, owner))
        # 일꾼 4기: 본진 건물 아래쪽에 한 줄. 미네랄은 두 본진 모두 위쪽/옆에 있다(chk_inspect 로 확인)
        for k in range(4):
            add.append(unit_entry(worker, sx - 48 + k * 32, sy + 80, owner))
    new["UNIT"] = u + b"".join(add)

    t = last["TRIG"]
    keep = None
    for k in range(len(t) // 2400):
        tr = t[k * 2400:(k + 1) * 2400]
        cond0 = tr[15]
        act0 = tr[320 + 26]
        if cond0 == 22 and act0 == 26:  # Always → Set Resources
            keep = tr
            break
    if keep is None:
        raise SystemExit("원본에 '미네랄 50 설정' 트리거가 없다. 직접 만들어야 한다")
    new["TRIG"] = keep

    out = bytearray()
    for name, _, data in secs:
        data = new.get(name, data)
        out += name.encode("latin-1") + struct.pack("<I", len(data)) + data
    return bytes(out), starts


def write_map(lib, out_path, chk):
    tmp = Path(out_path).with_suffix(".chk.tmp")
    tmp.write_bytes(chk)
    p = Path(out_path)
    if p.exists():
        p.unlink()
    a = ctypes.c_void_p()
    if not lib.SFileCreateArchive(str(p).encode("mbcs"), MPQ_CREATE_LISTFILE, 8, ctypes.byref(a)):
        raise RuntimeError(f"MPQ 생성 실패 {ctypes.get_last_error()}")
    try:
        ok = lib.SFileAddFileEx(a, str(tmp).encode("mbcs"), b"staredit\\scenario.chk",
                                MPQ_FILE_COMPRESS | MPQ_FILE_REPLACEEXISTING, MPQ_COMPRESSION_PKWARE, MPQ_COMPRESSION_PKWARE)
        if not ok:
            raise RuntimeError(f"CHK 추가 실패 {ctypes.get_last_error()}")
    finally:
        lib.SFileCloseArchive(a)
    tmp.unlink()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("dst")
    ap.add_argument("--stormlib", required=True)
    args = ap.parse_args()
    lib = ci.load_stormlib(args.stormlib)
    chk, _ = ci.extract_chk(lib, args.src)
    new_chk, starts = rebuild_chk(chk)
    write_map(lib, args.dst, new_chk)
    print(f"출력: {args.dst}  시작 위치 {starts}")
    chk2, names = ci.extract_chk(lib, args.dst)
    assert chk2 == new_chk, "다시 읽은 CHK 가 다르다"
    ci.summarize(chk2)


if __name__ == "__main__":
    main()
