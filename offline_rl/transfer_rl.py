"""질럿 2에서만 학습한 RL 에이전트를 질럿 3·4·5에 학습 없이 적용한다 (목표 전이).

질문: "질럿 2로 학습하고 질럿 5로 검증"을 RL 에이전트 자체에 대해 할 수 있는가.
표 형식 Q는 N마다 상태가 달라 전이가 불가능하므로, 상태를 목표 상대 특징
(남은 질럿 수, 일꾼, 파일런, 게이트, 미네랄, 인구 여유 등)으로 두고 함수 근사를 쓴다.

  학습 환경 : 질럿 2 로그로 적합한 시뮬레이터(build_sim), 목표 2 에피소드만.
  에이전트  : compact 표 Q(기준선) / 선형 Q / 소형 MLP Q / 선형 softmax 정책(REINFORCE)
  평가      : 목표 2(학습 확인), 3·4·5(학습 없이 탐욕 실행) 종료 프레임을 전수 최적과 비교.
              목표 5는 로그의 실제 종료 프레임도 찾아 적는다.
  미세 조정 : 질럿 2로 사전 학습한 에이전트와 처음부터 시작한 에이전트가 목표 5에서
              최적에 닿기까지 필요한 에피소드 수를 비교한다 (전이의 두 번째 쓰임).

보상 = -(다음 명령까지 프레임), gamma = 1, 행동 마스킹 = 열거 규칙(게이트 상한 3).
표준 라이브러리만 사용한다.
"""
from __future__ import annotations

import math
import random
import statistics
import sys
import time
from collections import defaultdict, deque
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_sim as bs  # noqa: E402
import zealot_n as zn  # noqa: E402

OUT_DIR = bs.OUT_DIR
ALLOWED = zn.make_allowed(3)
ACTIONS = (0, 1, 2, 3)
MAX_LEN = 30
FAIL_R = -10.0          # 실행 불가 명령 (보상은 /100 단위)
SCALE = 100.0

FEATURE_NAMES = ["bias", "rem", "pending", "waiting", "workers", "mining", "pyl_ready", "pyl_build",
                 "gate_ready", "gate_build", "minerals", "supply_free", "supply_deficit", "nexus_busy",
                 "rem*gate_ready", "rem*gates", "rem*mining", "rem*supply_free", "rem^2"]


# --------------------------------------------------------------------------- 상태 특징 (목표 상대)
def features(sim: bs.BuildSim, prefix, target):
    """시뮬레이터 내부 상태를 목표 상대 특징으로 만든다. 절대 시각 t는 넣지 않는다
    (N이 커지면 t 범위가 학습 범위를 벗어나 외삽 오류의 원인이 되기 쉽다)."""
    t = max(sim.t, 0)
    w, p, g, z = prefix.count(0), prefix.count(1), prefix.count(2), prefix.count(3)
    pyl_ready = sum(1 for c in sim.pylon_done if c <= t)
    gate_ready = sum(1 for c in sim.gate_ready if c <= t)
    z_started = sum(1 for s in sim.zealot_start if s <= t)
    z_done = sum(1 for d in sim.zealot_done if d <= t)
    rem = target - z                    # 아직 명령하지 않은 질럿
    pending = z - z_done                # 명령했지만 미완성
    waiting = z - z_started             # 명령했지만 생산 시작 전
    minerals = sim.minerals_at(t)
    free = sim.cap_at(t) - sim.used_at(t)
    mining = sum(d for te, d in sim.events if te <= t)
    nexus_busy = 1.0 if sim.nexus_free > t else 0.0
    gates = g
    r = rem / 5
    return [1.0, r, pending / 5, waiting / 5, w / 16, mining / 16, pyl_ready / 3, (p - pyl_ready) / 3,
            gate_ready / 3, (g - gate_ready) / 3, minerals / 200, free / 8, max(0, 2 * rem - free) / 8,
            nexus_busy, r * gate_ready / 3, r * gates / 3, r * mining / 16, r * free / 8, r * r]


def compact_key(sim, prefix, target):
    return zn.compact_state(sim, prefix, target)


# --------------------------------------------------------------------------- 에이전트
class Tabular:
    name = "compact 표 Q"

    def __init__(self, rng, lr=0.1):
        self.Q = defaultdict(float)
        self.lr = lr

    def q(self, obs, acts):
        return {a: self.Q[(obs[1], a)] for a in acts}

    def update(self, obs, a, r, obs2, acts2, done):
        tv = r if done else r + max(self.Q[(obs2[1], b)] for b in acts2)
        self.Q[(obs[1], a)] += self.lr * (tv - self.Q[(obs[1], a)])

    def size(self):
        return len({s for s, _ in self.Q})


class LinearQ:
    name = "선형 Q"

    def __init__(self, rng, lr=0.01, replay=3, sync=200):
        d = len(FEATURE_NAMES)
        self.w = [[0.0] * d for _ in ACTIONS]
        self.w_t = [row[:] for row in self.w]
        self.lr, self.replay, self.sync = lr, replay, sync
        self.buf = deque(maxlen=20000)
        self.rng, self.n = rng, 0

    @staticmethod
    def _dot(w, x):
        return sum(wi * xi for wi, xi in zip(w, x))

    def q(self, obs, acts):
        return {a: self._dot(self.w[a], obs[0]) for a in acts}

    def _fit(self, obs, a, r, obs2, acts2, done):
        tv = r if done else r + max(self._dot(self.w_t[b], obs2[0]) for b in acts2)
        x = obs[0]
        err = tv - self._dot(self.w[a], x)
        row = self.w[a]
        for i, xi in enumerate(x):
            row[i] += self.lr * err * xi

    def update(self, obs, a, r, obs2, acts2, done):
        tr = (obs, a, r, obs2, acts2, done)
        self.buf.append(tr)
        self._fit(*tr)
        for _ in range(min(self.replay, len(self.buf) - 1)):
            self._fit(*self.rng.choice(self.buf))
        self.n += 1
        if self.n % self.sync == 0:
            self.w_t = [row[:] for row in self.w]

    def size(self):
        return len(FEATURE_NAMES) * len(ACTIONS)


class MLPQ:
    name = "MLP Q"

    def __init__(self, rng, hidden=16, lr=0.002, replay=3, sync=200):
        d = len(FEATURE_NAMES)
        s = 1.0 / math.sqrt(d)
        self.W1 = [[rng.uniform(-s, s) for _ in range(d)] for _ in range(hidden)]
        self.b1 = [0.0] * hidden
        s2 = 1.0 / math.sqrt(hidden)
        self.W2 = [[rng.uniform(-s2, s2) for _ in range(hidden)] for _ in ACTIONS]
        self.b2 = [0.0] * len(ACTIONS)
        self.params = [self.W1, self.b1, self.W2, self.b2]
        self.target = self._clone()
        self.m = [self._zeros(p) for p in self.params]
        self.v = [self._zeros(p) for p in self.params]
        self.lr, self.replay, self.sync = lr, replay, sync
        self.buf = deque(maxlen=20000)
        self.rng, self.n, self.steps = rng, 0, 0

    @staticmethod
    def _zeros(p):
        return [[0.0] * len(r) for r in p] if isinstance(p[0], list) else [0.0] * len(p)

    def _clone(self):
        return [[r[:] for r in self.W1], self.b1[:], [r[:] for r in self.W2], self.b2[:]]

    @staticmethod
    def _forward(params, x):
        W1, b1, W2, b2 = params
        h = [math.tanh(sum(wi * xi for wi, xi in zip(row, x)) + b) for row, b in zip(W1, b1)]
        out = [sum(wi * hi for wi, hi in zip(row, h)) + b for row, b in zip(W2, b2)]
        return h, out

    def q(self, obs, acts):
        _, out = self._forward(self.params, obs[0])
        return {a: out[a] for a in acts}

    def _fit(self, obs, a, r, obs2, acts2, done):
        if done:
            tv = r
        else:
            _, o2 = self._forward(self.target, obs2[0])
            tv = r + max(o2[b] for b in acts2)
        x = obs[0]
        h, out = self._forward(self.params, x)
        err = out[a] - tv                      # dL/dout_a (L = err^2/2)
        g = [self._zeros(p) for p in self.params]
        gW1, gb1, gW2, gb2 = g
        for j, hj in enumerate(h):
            gW2[a][j] = err * hj
        gb2[a] = err
        for j, hj in enumerate(h):
            dh = err * self.W2[a][j] * (1 - hj * hj)
            gb1[j] = dh
            row = gW1[j]
            for i, xi in enumerate(x):
                row[i] = dh * xi
        self._adam(g)

    def _adam(self, g, b1=0.9, b2=0.999, eps=1e-8):
        self.steps += 1
        c1, c2 = 1 - b1 ** self.steps, 1 - b2 ** self.steps
        for p, gp, m, v in zip(self.params, g, self.m, self.v):
            if isinstance(p[0], list):
                for pr, gr, mr, vr in zip(p, gp, m, v):
                    for i, gi in enumerate(gr):
                        mr[i] = b1 * mr[i] + (1 - b1) * gi
                        vr[i] = b2 * vr[i] + (1 - b2) * gi * gi
                        pr[i] -= self.lr * (mr[i] / c1) / (math.sqrt(vr[i] / c2) + eps)
            else:
                for i, gi in enumerate(gp):
                    m[i] = b1 * m[i] + (1 - b1) * gi
                    v[i] = b2 * v[i] + (1 - b2) * gi * gi
                    p[i] -= self.lr * (m[i] / c1) / (math.sqrt(v[i] / c2) + eps)

    def update(self, obs, a, r, obs2, acts2, done):
        tr = (obs, a, r, obs2, acts2, done)
        self.buf.append(tr)
        self._fit(*tr)
        for _ in range(min(self.replay, len(self.buf) - 1)):
            self._fit(*self.rng.choice(self.buf))
        self.n += 1
        if self.n % self.sync == 0:
            self.target = self._clone()

    def size(self):
        d, hdn = len(FEATURE_NAMES), len(self.b1)
        return d * hdn + hdn + hdn * len(ACTIONS) + len(ACTIONS)


class SoftmaxPolicy:
    """선형 softmax 정책, REINFORCE + 상태 무관 기준선(이동 평균). 에피소드 끝에 갱신."""
    name = "선형 정책(REINFORCE)"
    policy = True

    def __init__(self, rng, lr=0.02):
        d = len(FEATURE_NAMES)
        self.th = [[0.0] * d for _ in ACTIONS]
        self.lr, self.rng = lr, rng
        self.baseline, self.nb = 0.0, 0

    def probs(self, obs, acts):
        x = obs[0]
        logits = {a: sum(wi * xi for wi, xi in zip(self.th[a], x)) for a in acts}
        mx = max(logits.values())
        e = {a: math.exp(v - mx) for a, v in logits.items()}
        s = sum(e.values())
        return {a: v / s for a, v in e.items()}

    def q(self, obs, acts):           # 탐욕 선택용: 확률을 점수로 쓴다
        return self.probs(obs, acts)

    def sample(self, obs, acts):
        pr = self.probs(obs, acts)
        u, c = self.rng.random(), 0.0
        for a, p in pr.items():
            c += p
            if u <= c:
                return a
        return acts[-1]

    def end_episode(self, traj):
        # traj: [(obs, acts, a, r)], gamma=1 → G_t = 이후 보상 합
        G = 0.0
        rets = []
        for _, _, _, r in reversed(traj):
            G += r
            rets.append(G)
        rets.reverse()
        self.nb += 1
        self.baseline += (rets[0] - self.baseline) / min(self.nb, 100)
        for (obs, acts, a, _), G in zip(traj, rets):
            adv = G - self.baseline
            pr = self.probs(obs, acts)
            x = obs[0]
            for b in acts:
                coef = self.lr * adv * ((1.0 if b == a else 0.0) - pr[b])
                row = self.th[b]
                for i, xi in enumerate(x):
                    row[i] += coef * xi

    def size(self):
        return len(FEATURE_NAMES) * len(ACTIONS)


AGENTS = {"tabular": Tabular, "linear": LinearQ, "mlp": MLPQ, "pg": SoftmaxPolicy}


# --------------------------------------------------------------------------- 환경 상호작용
def observe(sim, prefix, target):
    return (features(sim, prefix, target), compact_key(sim, prefix, target))


def run_episode(agent, P, target, eps_greedy, rng, learn=True):
    """한 에피소드. 돌려주는 값: (종료 프레임 또는 None, 명령열)."""
    sim = bs.BuildSim(P, target)
    prefix, traj = [], []
    obs = observe(sim, prefix, target)
    acts = ALLOWED(prefix, target)
    policy = getattr(agent, "policy", False)
    while True:
        if not acts or len(prefix) >= MAX_LEN:
            end = None
            break
        if policy:
            a = agent.sample(obs, acts) if learn else max(acts, key=lambda b: agent.q(obs, acts)[b])
        elif rng.random() < eps_greedy:
            a = rng.choice(acts)
        else:
            qv = agent.q(obs, acts)
            a = max(acts, key=qv.get)
        t_prev = max(sim.t, 0)
        t = sim.step(a)
        prefix.append(a)
        if t is None:
            r, done, obs2, acts2, end = FAIL_R, True, None, [], None
        elif sim.end is not None:
            r, done, obs2, acts2, end = -(sim.end - t_prev) / SCALE, True, None, [], sim.end
        else:
            obs2 = observe(sim, prefix, target)
            acts2 = ALLOWED(prefix, target)
            r, done, end = -(t - t_prev) / SCALE, False, None
            if not acts2:
                done = True
        if learn:
            if policy:
                traj.append((obs, acts, a, r))
            else:
                agent.update(obs, a, r, obs2, acts2, done)
        if done:
            break
        obs, acts = obs2, acts2
    if learn and policy and traj:
        agent.end_episode(traj)
    return end, tuple(prefix)


def greedy(agent, P, target):
    return run_episode(agent, P, target, 0.0, random.Random(0), learn=False)


def train(agent, P, target, episodes, rng, eval_targets=(), eval_every=0, eps_start=0.3, eps_end=0.05):
    """목표 target으로 학습. eval_every마다 eval_targets 각각의 탐욕 종료 프레임을 기록."""
    curve = []
    for ep in range(1, episodes + 1):
        e = max(eps_end, eps_start * (1 - ep / (0.7 * episodes)))
        run_episode(agent, P, target, e, rng)
        if eval_every and (ep % eval_every == 0 or ep == episodes):
            curve.append((ep, {n: greedy(agent, P, n)[0] for n in eval_targets}))
    return curve


# --------------------------------------------------------------------------- 실험
def fmt(v):
    return "-" if v is None else f"{v:.0f}" if isinstance(v, float) else str(v)


def main():
    import argparse

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--agents", default="tabular,linear,mlp,pg")
    ap.add_argument("--episodes", type=int, default=20000, help="질럿 2 학습 에피소드")
    ap.add_argument("--seeds", type=int, default=3)
    ap.add_argument("--eval-every", type=int, default=1000)
    ap.add_argument("--finetune", type=int, default=20000, help="목표 5 미세 조정 에피소드 (0이면 생략)")
    ap.add_argument("--finetune-agents", default="linear,mlp")
    ap.add_argument("--eval-targets", default="2,3,4,5")
    ap.add_argument("--tag", default="")
    args = ap.parse_args()

    P, refit = zn.load_params()
    targets = [int(x) for x in args.eval_targets.split(",")]
    print(f"시뮬레이터 매개변수 {'재적합' if refit else 'sim_params.csv'}; 학습 목표 2, 평가 목표 {targets}", flush=True)

    # 정답: 전수 최적 (게이트 상한 3)
    opt = {}
    for n in targets:
        res, cnt = bs.exhaustive_sim(P, n, allowed=ALLOWED, max_len=MAX_LEN)
        opt[n] = (res[0][0], list(res[0][1]), cnt)
        print(f"  전수 최적 N={n}: {res[0][0]} {list(res[0][1])} ({cnt}개)", flush=True)

    # 질럿 5 로그 (검증용 실제 프레임)
    actual5 = {}
    if 5 in targets:
        eps5 = bs.load(5)
        by = defaultdict(list)
        for ep in eps5:
            by[ep["actions"]].append(ep["end_frame"])
        actual5 = {o: statistics.fmean(v) for o, v in by.items()}
        print(f"  질럿 5 로그 명령열 {len(actual5)}개", flush=True)

    lines = ["# 질럿 2로만 학습한 RL 에이전트의 질럿 3·4·5 전이\n",
             f"학습: 시뮬레이터(질럿 2 로그 적합) 위 목표 2, {args.episodes} 에피소드, {args.seeds} 시드. "
             "평가: 목표 3·4·5는 학습 없이 탐욕 실행 (zero-shot). 보상 -프레임/100, gamma=1, 행동 마스킹 = 열거 규칙(게이트 상한 3).\n",
             "상태 특징(목표 상대): " + ", ".join(FEATURE_NAMES) + ". 절대 시각은 넣지 않았다.\n",
             "\n전수 최적(정답): " + ", ".join(f"N={n} {opt[n][0]} {opt[n][1]}" for n in targets) + "\n"]
    curves_csv = ["agent,seed,phase,episode," + ",".join(f"N{n}" for n in targets)]

    # ---- 1. 질럿 2 학습 → zero-shot 평가
    lines.append("\n## 1. 질럿 2 학습 후 학습 없이 적용\n")
    lines.append("| 에이전트 | 매개변수 수 | 시드 | " + " | ".join(f"N={n} (최적 {opt[n][0]})" for n in targets) + " | N=5 명령열 | N=5 로그 실제 |")
    lines.append("|---|---|---|" + "---|" * len(targets) + "---|---|")
    trained = {}
    for key in args.agents.split(","):
        cls = AGENTS[key]
        for seed in range(args.seeds):
            rng = random.Random(seed)
            agent = cls(rng)
            t0 = time.time()
            curve = train(agent, P, 2, args.episodes, rng, eval_targets=targets, eval_every=args.eval_every)
            for ep, d in curve:
                curves_csv.append(f"{key},{seed},pretrain,{ep}," + ",".join(fmt(d[n]) for n in targets))
            row = {}
            for n in targets:
                row[n] = greedy(agent, P, n)
            seq5 = row[5][1] if 5 in row else ()
            act5 = actual5.get(seq5)
            cells = " | ".join(f"{fmt(row[n][0])}" + (f" (+{row[n][0]-opt[n][0]})" if row[n][0] is not None and row[n][0] > opt[n][0] else "") for n in targets)
            lines.append(f"| {cls.name} | {agent.size()} | {seed} | {cells} | {list(seq5)} | {fmt(act5) if act5 is not None else '로그에 없음'} |")
            print(f"[{cls.name} seed {seed}] {time.time()-t0:.0f}초 " + " ".join(f"N{n}={fmt(row[n][0])}" for n in targets)
                  + f" seq5={list(seq5)} 실제={fmt(act5)}", flush=True)
            trained[(key, seed)] = agent

    # ---- 2. 목표 5 미세 조정: 사전 학습 vs 처음부터
    if args.finetune:
        lines.append(f"\n## 2. 목표 5 미세 조정 ({args.finetune} 에피소드): 질럿 2 사전 학습 vs 처음부터\n")
        lines.append("처음으로 탐욕 결과가 최적(722)과 최적+10 이내에 든 에피소드. 표 형식 history Q는 N=5에서 약 18만 에피소드가 필요했다(zealot_n_results_a.md).\n")
        lines.append("| 에이전트 | 시드 | 시작 | 첫 ≤최적+10 | 첫 =최적 | 마지막 탐욕 |")
        lines.append("|---|---|---|---|---|---|")
        for key in args.finetune_agents.split(","):
            cls = AGENTS[key]
            for seed in range(args.seeds):
                for label, agent in (("질럿 2 사전 학습", trained.get((key, seed))), ("처음부터", None)):
                    rng = random.Random(1000 + seed)
                    if agent is None:
                        agent = cls(rng)
                    t0 = time.time()
                    curve = train(agent, P, 5, args.finetune, rng, eval_targets=(5,), eval_every=args.eval_every // 4 or 1,
                                  eps_start=0.3 if label == "처음부터" else 0.1)
                    first10 = next((ep for ep, d in curve if d[5] is not None and d[5] <= opt[5][0] + 10), None)
                    first0 = next((ep for ep, d in curve if d[5] is not None and d[5] <= opt[5][0]), None)
                    last = curve[-1][1][5]
                    for ep, d in curve:
                        curves_csv.append(f"{key},{seed},finetune-{'pre' if label != '처음부터' else 'scratch'},{ep}," + ",".join(fmt(d.get(n)) for n in targets))
                    lines.append(f"| {cls.name} | {seed} | {label} | {fmt(first10)} | {fmt(first0)} | {fmt(last)} |")
                    print(f"[미세조정 {cls.name} seed {seed} {label}] {time.time()-t0:.0f}초 첫≤+10 {first10} 첫=최적 {first0} 마지막 {last}", flush=True)

    lines.append("\n## 읽는 법\n")
    lines.append("- 1절에서 N=3·4·5 값이 최적에 가까우면 목표 상대 특징 위의 함수 근사가 N을 넘어 일반화한 것이다. "
                 "compact 표 Q는 N=5의 초반 상태(남은 질럿 5)를 본 적이 없어 비교 기준선이다.")
    lines.append("- 2절은 전이가 zero-shot으로 안 되더라도 사전 학습이 큰 N의 학습을 얼마나 앞당기는지 본다.")
    out_md = OUT_DIR / f"transfer_rl_results{args.tag}.md"
    out_csv = OUT_DIR / f"transfer_rl_curves{args.tag}.csv"
    out_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    out_csv.write_text("\n".join(curves_csv) + "\n", encoding="utf-8")
    print(f"결과: {out_md}\n       {out_csv}", flush=True)


if __name__ == "__main__":
    main()
