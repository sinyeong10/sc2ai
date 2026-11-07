"""질럿 2 데이터로 학습한 표(Q)가 질럿 5 문제에서 쓰일 수 있는지: 상태 추상화별로
질럿 5 결정 상태(상태, 행동) 중 질럿 2 데이터에 한 번이라도 나온 비율을 센다.
비율이 0에 가까우면 표 형식 학습은 어떤 추상화를 써도 질럿 2 → 질럿 5로 옮겨지지 않는다."""
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import zealot2_offline_rl as base  # noqa: E402


def load(target):
    base.TARGET = target
    eps = []
    for p in base.LOG_FILES_BY_TARGET[target]:
        if p.exists():
            eps.extend(base.parse_log(p))
    return eps


def keys(eps, fn):
    out = defaultdict(int)
    for ep in eps:
        prefix = []
        for s, a, _ in base.decisions_of(ep):
            out[(fn(s, prefix), a)] += 1
            prefix.append(a)
    return out


def main():
    eps2, eps5 = load(2), load(5)
    lines = ["# 상태 추상화별 질럿 2 → 질럿 5 표 공유 비율\n",
             "질럿 5 로그의 (상태, 행동) 쌍 가운데 질럿 2 로그에도 나온 것의 비율. "
             "에피소드 안에서 결정 순서(1번째, 2번째, ...)별로도 센다. "
             "'결정 시점의 질럿 수'가 2 이상인 상태는 질럿 2 데이터에 있을 수 없다.\n",
             "| 추상화 | 질럿 5 (s,a) 종류 | 질럿 2에도 있는 종류 | 비율 | 질럿 5 결정 횟수 기준 비율 |",
             "|---|---|---|---|---|"]
    for name, fn in base.ABSTRACTIONS.items():
        base.TARGET = 2
        k2 = keys(eps2, fn)
        base.TARGET = 5
        k5 = keys(eps5, fn)
        shared = [k for k in k5 if k in k2]
        n_dec = sum(k5.values())
        n_shared_dec = sum(k5[k] for k in shared)
        lines.append(f"| {name} | {len(k5)} | {len(shared)} | {len(shared) / len(k5):.1%} | {n_shared_dec / n_dec:.1%} |")
        print(name, len(k5), len(shared), f"{len(shared) / len(k5):.1%}", f"{n_shared_dec / n_dec:.1%}")
    # 결정 순서별 (history 기준): k번째 결정이 질럿 2 데이터에 있는 비율
    base.TARGET = 2
    k2 = keys(eps2, base.abs_history)
    base.TARGET = 5
    by_depth = defaultdict(lambda: [0, 0])
    for ep in eps5:
        prefix = []
        for s, a, _ in base.decisions_of(ep):
            d = len(prefix)
            by_depth[d][0] += 1
            if (tuple(prefix), a) in k2:
                by_depth[d][1] += 1
            prefix.append(a)
    lines.append("\nhistory 추상화에서 결정 순서별 공유 비율:\n")
    lines.append("| 결정 순서 | 질럿 5 결정 수 | 질럿 2에 있는 수 | 비율 |")
    lines.append("|---|---|---|---|")
    for d in sorted(by_depth):
        n, m = by_depth[d]
        lines.append(f"| {d + 1} | {n} | {m} | {m / n:.1%} |")
    out = base.OUT_DIR / "state_coverage.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("저장:", out)


if __name__ == "__main__":
    main()
