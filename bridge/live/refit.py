"""라이브 이벤트 로그로 계획기의 시간·채취 상수를 다시 맞춘다.

    py -X utf8 bridge/live/refit.py            # 보고서만 (bridge/results/live_refit.md)
    py -X utf8 bridge/live/refit.py --write    # + bridge/results/live_params.json (live_run 이 시작할 때 읽어 적용)

측정 (bridge/results/live/*.jsonl 의 observe 스냅샷과 plan/request 이벤트):
- 건물 이동 시간: 요청이 실행(issued: 일꾼에게 건설 명령)된 프레임 → 배치(done) 프레임.
  계획기 상수 '명령 → 완성' = 이동 시간 중앙값 + BW 건설 시간.
- 가스 채취율: 완성 어시밀레이터마다 일꾼 3 일 때 틱 사이 가스 증가 (소비가 낀 구간 = 감소 구간은 뺀다).
- 미네랄 채취율: 모형(기지별 덩이 수·일꾼 수로 계산한 예상) 대비 실측 비율. 검증용이며 적용하지 않는다
  (수입 상수는 2026-11-08 전수 실측으로 고정, docs/스타1-자원채취율-분석.md).
- 계획 지연: 계획이 예상한 실행 프레임 대비 실제 실행 프레임 (행동별 중앙값). 보고용.
표본이 MIN_SAMPLES 보다 적은 항목은 쓰지 않는다. 값은 SANE 범위로 자른다.
"""
from __future__ import annotations

import argparse
import glob
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# BW 건설 시간(프레임, BWAPI UnitType::buildTime). 행동 번호는 실행기 기준
BUILD_TIME = {1: 450, 2: 900, 4: 1800, 5: 600, 6: 900, 10: 900, 11: 900, 14: 600}
NAME = {1: "pylon", 2: "gateway", 4: "nexus", 5: "assimilator", 6: "core", 10: "citadel", 11: "archives", 14: "forge",
        0: "probe", 3: "zealot", 7: "dragoon", 12: "high_templar", 13: "dark_templar", 15: "up_weapons", 16: "up_armor", 17: "up_shields"}
# 어느 상수에 들어가나: ("P", 키) = sc1_sim 매개변수, ("EXTRA", 키) = expansion_estimate.EXTRA 의 시간, ("FORGE", -) = planner.FORGE_FRAMES
TARGET = {1: ("P", "pylon"), 2: ("P", "gate"), 4: ("EXTRA", "nexus"), 5: ("EXTRA", "assim"), 6: ("EXTRA", "core"),
          10: ("EXTRA", "citadel"), 11: ("EXTRA", "archives"), 14: ("FORGE", "FORGE_FRAMES")}
MIN_SAMPLES = 3
SANE_TRAVEL = (0, 900)       # 이동 시간 범위(프레임). 앞마당 정찰 대기까지 포함하면 길 수 있다
SANE_GAS = (0.10, 0.35)      # 어시밀레이터 하나(일꾼 3)당 가스/프레임


def iter_events(paths):
    for path in paths:
        with open(path, encoding="utf-8") as f:
            for ln in f:
                ln = ln.strip()
                if ln:
                    try:
                        yield path, json.loads(ln)
                    except json.JSONDecodeError:
                        continue


def model_mineral_rate(snap, P):
    """기지마다 (덩이 수 c, 채취 일꾼 n) 로 ExpSim._rate_b 와 같은 식."""
    total = 0.0
    for b in snap.get("bases") or []:
        n, c = int(b.get("workers", 0)), int(b.get("patches", 0))
        if c <= 0 or not b.get("done", True):
            continue
        total += P["income"] * min(n, c) + P["income_add"] * max(0, min(n, 2 * c) - c) + P["income_over"] * max(0, n - 2 * c)
    return total


def measure(paths, P):
    travel: dict[int, dict] = {}          # 행동 → {(파일, 요청 id): 이동 프레임}
    gas_sum = gas_frames = 0.0
    min_obs = min_model = 0.0
    lateness: dict[int, list] = {}
    plan_ids = {}                          # (파일, 요청 id) → 예상 실행 프레임(계획 계산 시간만큼 민 값)
    issued_at = {}                         # (파일, 요청 id) → 실제 실행 프레임
    prev = {}
    pending_plan = {}                      # 파일 → (남은 행동열, 예상열, 밀림)
    files = set()
    for path, e in iter_events(paths):
        files.add(path)
        ev = e.get("event")
        if ev == "plan":
            shift = int(float(e.get("seconds", 0)) * 24) + 24
            pending_plan[path] = (list(e.get("actions", [])), list(e.get("expected_frames", [])), shift)
        elif ev == "request":
            pp = pending_plan.get(path)
            if pp and pp[0] and pp[0][0] == e.get("action") and e.get("accepted"):
                acts, exps, shift = pp
                acts.pop(0)
                exp = exps.pop(0) if exps else None
                if exp is not None:
                    plan_ids[(path, e["request_id"])] = (e["action"], int(exp) + shift)
            elif pp and pp[0] and pp[0][0] != e.get("action"):
                pending_plan[path] = None  # 계획 밖 요청(인구 유지·일꾼 보충)이 끼면 짝짓기를 멈춘다
        elif ev == "observe":
            s = e.get("snapshot") or {}
            for r in s.get("requests", []):
                key = (path, r.get("id"))
                if r.get("issued_frame", -1) >= 0 and key not in issued_at:
                    issued_at[key] = int(r["issued_frame"])
                a = r.get("action")
                if a in BUILD_TIME and r.get("state") == "done" and r.get("issued_frame", -1) >= 0 and r.get("done_frame", -1) >= r["issued_frame"]:
                    travel.setdefault(a, {})[key] = int(r["done_frame"]) - int(r["issued_frame"])
            q = prev.get(path)
            prev[path] = s
            if not q or not s.get("live", True):
                continue
            dt = int(s["frame"]) - int(q["frame"])
            if dt <= 0 or dt > 48:
                continue
            # 가스: 두 스냅샷 모두 완성 어시밀레이터 n ≥ 1, 가스 일꾼 = 3n, 감소(소비) 없음
            na = int(((s.get("buildings") or {}).get("assimilator") or {}).get("ready", 0))
            nb = int(((q.get("buildings") or {}).get("assimilator") or {}).get("ready", 0))
            gw_s, gw_q = int((s.get("workers") or {}).get("gas", -1)), int((q.get("workers") or {}).get("gas", -1))
            dg = int(s["gas"]) - int(q["gas"])
            if na >= 1 and na == nb and gw_s == gw_q == 3 * na and dg >= 0:
                gas_sum += dg / na
                gas_frames += dt
            # 미네랄: 감소 없음, 기지 구성이 같을 때. 모형 대비 비율
            dm = int(s["minerals"]) - int(q["minerals"])
            if dm >= 0 and [(b.get("workers"), b.get("patches")) for b in s.get("bases") or []] == [(b.get("workers"), b.get("patches")) for b in q.get("bases") or []]:
                rate = model_mineral_rate(q, P)
                if rate > 0:
                    min_obs += dm
                    min_model += rate * dt
    for key, (a, exp) in plan_ids.items():
        if key in issued_at:
            lateness.setdefault(a, []).append(issued_at[key] - exp)
    return {"files": len(files), "travel": {a: list(v.values()) for a, v in travel.items()},
            "gas_rate": (gas_sum / gas_frames) if gas_frames else None, "gas_frames": gas_frames,
            "mineral_ratio": (min_obs / min_model) if min_model else None, "mineral_frames": min_model,
            "lateness": lateness}


def fit(m, P0, extra0, forge0):
    """측정 → 새 상수와 표 행."""
    out = {"P": {}, "EXTRA": {}}
    rows = []
    for a, (where, key) in sorted(TARGET.items()):
        xs = [x for x in m["travel"].get(a, []) if SANE_TRAVEL[0] <= x <= SANE_TRAVEL[1]]
        cur = P0.get(key) if where == "P" else (extra0[key][2] if where == "EXTRA" else forge0)
        if len(xs) < MIN_SAMPLES:
            rows.append((NAME[a], len(xs), "-", "-", cur, cur, "표본 부족"))
            continue
        med = int(statistics.median(xs))
        p90 = int(sorted(xs)[int(0.9 * (len(xs) - 1))])
        new = med + BUILD_TIME[a]
        if where == "P":
            out["P"][key] = new
        elif where == "EXTRA":
            out["EXTRA"][key] = new
        else:
            out["FORGE_FRAMES"] = new
        rows.append((NAME[a], len(xs), med, p90, cur, new, "적용" if new != cur else "같음"))
    g = m["gas_rate"]
    if g is not None and m["gas_frames"] >= 2400:
        out["GAS_PER_BASE"] = round(min(max(g, SANE_GAS[0]), SANE_GAS[1]), 4)
    return out, rows


def apply_params(path, P, log=print):
    """live_params.json 을 계획기에 적용한다 (live_run 시작 때). 바뀐 항목 목록을 돌려준다."""
    path = Path(path)
    if not path.exists():
        return []
    import expansion_estimate as ee
    from live import planner
    d = json.loads(path.read_text(encoding="utf-8"))
    changes = []
    for k, v in (d.get("P") or {}).items():
        if k in P and P[k] != v:
            changes.append(f"{k} {P[k]}→{v}")
            P[k] = v
    for k, v in (d.get("EXTRA") or {}).items():
        if k in ee.EXTRA and ee.EXTRA[k][2] != int(v):
            m_, g_, old = ee.EXTRA[k]
            ee.EXTRA[k] = (m_, g_, int(v))
            changes.append(f"{k} {old}→{int(v)}")
    if "FORGE_FRAMES" in d and planner.FORGE_FRAMES != int(d["FORGE_FRAMES"]):
        changes.append(f"forge {planner.FORGE_FRAMES}→{int(d['FORGE_FRAMES'])}")
        planner.FORGE_FRAMES = int(d["FORGE_FRAMES"])
    if "GAS_PER_BASE" in d and ee.GAS_PER_BASE != float(d["GAS_PER_BASE"]):
        changes.append(f"gas {ee.GAS_PER_BASE}→{float(d['GAS_PER_BASE'])}")
        ee.GAS_PER_BASE = float(d["GAS_PER_BASE"])
    return changes


def run(paths, report_path=None, params_path=None, write=False, verbose=True):
    """측정 → 보고서(report_path) → write 면 params_path 에 새 상수. (새 상수 dict, 보고서 줄) 을 돌려준다."""
    import sc1_sim as ss
    import expansion_estimate as ee
    from live import planner
    P = dict(ss.DEFAULT_PARAMS)
    m = measure(paths, P)
    new, rows = fit(m, P, ee.EXTRA, planner.FORGE_FRAMES)
    lines = ["# 라이브 로그 재보정", "", f"로그 {m['files']}개. `py -X utf8 bridge/live/refit.py` 로 다시 만든다 (live_run 은 게임이 끝날 때마다 자동).", "",
             "## 건물: 명령 → 완성 상수", "", "이동 = 일꾼에게 건설 명령(issued) → 배치(done). 새 값 = 이동 중앙값 + BW 건설 시간.", "",
             "| 건물 | 표본 | 이동 중앙값 | 이동 90% | 기본값 | 새 값 | 판단 |", "|---|---|---|---|---|---|---|"]
    lines += [f"| {r[0]} | {r[1]} | {r[2]} | {r[3]} | {r[4]} | {r[5]} | {r[6]} |" for r in rows]
    lines += ["", "## 채취율", ""]
    if m["gas_rate"] is not None:
        lines.append(f"- 가스: 어시밀레이터 하나(일꾼 3)당 {m['gas_rate']:.4f}/프레임 ({int(m['gas_frames'])}프레임), 기본값 {ee.GAS_PER_BASE}"
                     + ("" if "GAS_PER_BASE" in new else " — 표본 부족(2400프레임 미만)으로 적용 안 함"))
    else:
        lines.append("- 가스: 조건(어시밀레이터마다 일꾼 3)을 만족하는 구간 없음")
    if m["mineral_ratio"] is not None:
        lines.append(f"- 미네랄: 실측/모형 = {m['mineral_ratio']:.3f} (모형 기준 {int(m['mineral_frames'])}). 검증용, 적용 안 함")
    lines += ["", "## 계획 지연 (실제 실행 − 예상 실행, 프레임)", "", "| 행동 | 표본 | 중앙값 | 90% |", "|---|---|---|---|"]
    for a, xs in sorted(m["lateness"].items()):
        xs = sorted(xs)
        lines.append(f"| {NAME.get(a, a)} | {len(xs)} | {int(statistics.median(xs))} | {xs[int(0.9 * (len(xs) - 1))]} |")
    lines += ["", "지연이 크면: 돈·인구·선행 건물 대기를 계획기가 짧게 본 것이다. 건물 상수 재보정 뒤 다시 본다."]
    if report_path:
        Path(report_path).write_text("\n".join(lines) + "\n", encoding="utf-8")
    if write and params_path:
        Path(params_path).write_text(json.dumps(new, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    if verbose:
        print("\n".join(lines))
    return new, lines


def recent_logs(pattern, n):
    """가장 최근 n개 로그 (파일 이름이 시각이라 정렬 = 시간순)."""
    return sorted(glob.glob(pattern))[-n:] if n > 0 else sorted(glob.glob(pattern))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--logs", default=str(ROOT / "results" / "live" / "*.jsonl"))
    ap.add_argument("--last", type=int, default=0, help="최근 N개 로그만 (0 = 전부)")
    ap.add_argument("--report", default=str(ROOT / "results" / "live_refit.md"))
    ap.add_argument("--params", default=str(ROOT / "results" / "live_params.json"))
    ap.add_argument("--write", action="store_true", help="live_params.json 에 쓴다")
    args = ap.parse_args()
    run(recent_logs(args.logs, args.last), args.report, args.params, args.write)
    if args.write:
        print(f"\n썼다: {args.params} → live_run 이 다음 시작 때 적용")


if __name__ == "__main__":
    main()
