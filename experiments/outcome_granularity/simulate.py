"""Does outcome granularity change how fast the loop converges?

labloop distinguishes nine trial outcomes where Karpathy's autoresearch has
roughly two (kept, not kept) and labloop 0.1.0 had five. The granularity only
matters if a proposer that reads it converges faster — otherwise it is
debugging convenience for the human, not signal for the agent.

This drives the real Loop, real metric extraction, and the real brief
machinery. Only the subprocess and git are simulated, so hundreds of
replicated runs finish in minutes. The three arms differ in exactly one
thing: how much of the outcome label the proposer sees. (Only the label — the
brief's `why` strings are withheld from all arms, since they would leak the
fine-grained outcome to the coarse arms.)

  bare  kept / not-kept.
  five  the 0.1.0 set: kept, reverted, failed, timed_out, no_metric —
        a diverged (nan) run reads as no_metric, a no-op edit as failed.
  nine  the current set: nan, timeout, crash and no-op are all distinct.

Task: minimize val over (lr, depth, epochs), optimum near (0.08, 6, 1150),
starting from a working config (0.02, 4, 800) the way autoresearch starts
from a working repo. Every axis has a cliff just past its optimum, so an
optimizer climbing properly will fall off them and the question is whether
knowing *which* cliff it fell off buys anything:

  lr > 0.18      -> nan (diverged)      truth: come back down in lr
  depth >= 7     -> crash               truth: come back down in depth
  epochs > 1400  -> timeout             truth: come back down in epochs

The proposer also emits a no-op edit 10% of the time, as real agents do.

Every arm shares one response toolkit; an arm that cannot tell causes apart
plays a hedge over the responses its label could call for. That is the cost
of coarseness being measured — a coarse label forces a mixed strategy.

  nine:  reverted->PERTURB  nan->LR_DOWN  timeout->EPOCHS_DOWN
         crash->DEPTH_DOWN  no_change->PERTURB(retry)
  five:  no_metric (missing|nan) -> 50% LR_DOWN / 50% RESTART
         failed (crash|noop)     -> 50% DEPTH_DOWN / 50% PERTURB
         timeout->EPOCHS_DOWN, reverted->PERTURB
  bare:  not-kept -> 60% PERTURB, 10% each LR_DOWN/EPOCHS_DOWN/DEPTH_DOWN/
         RESTART (reverted dominates in practice, and an operator hedging
         blind would weight it so; stated here because it is a design choice)

Statistics: REPS independent seeds per arm; endpoints are best-metric-found
and mean best-so-far (area under the convergence curve). Pairwise two-sided
Mann-Whitney U (normal approximation, tie-corrected), a 10k-resample
permutation test on the difference in means as a cross-check, and Cliff's
delta for effect size. No scipy: the package under test is stdlib-only and
so is its evidence.
"""

from __future__ import annotations

import json
import math
import random
import statistics
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import labloop.loop as loop_module  # noqa: E402
from labloop import Experiment, Goal, Loop  # noqa: E402
from labloop.runner import Completed  # noqa: E402

TRIALS = 40
REPS = 200
ARMS = ("bare", "five", "nine")
NOOP_RATE = 0.10

DEGRADE_FIVE = {"not_finite": "no_metric", "no_change": "failed"}


# --- the simulated experiment ----------------------------------------------


def true_val(lr: float, depth: int, epochs: int, noise: random.Random) -> float:
    lr_term = (math.log10(lr) - math.log10(0.08)) ** 2
    depth_term = 0.35 * (depth - 6) ** 2
    epoch_term = 1.2 * (math.log10(epochs) - math.log10(1150)) ** 2
    return 1.0 + lr_term + depth_term + epoch_term + noise.gauss(0, 0.004)


def run_experiment(config: dict, noise: random.Random) -> Completed:
    lr, depth, epochs = config["lr"], config["depth"], config["epochs"]
    if depth >= 7:
        return Completed(1, "Traceback...\nOverflowError: depth too large\n", 0.0, False)
    if lr > 0.18:
        return Completed(0, "val = nan\n", 0.0, False)
    if epochs > 1400:
        return Completed(None, "epoch 1...\n", 0.0, True)
    return Completed(0, f"val = {true_val(lr, depth, epochs, noise):.6f}\n", 0.0, False)


# --- one shared response toolkit, hedged per arm ----------------------------


def _perturb(config: dict, rng: random.Random) -> dict:
    return {
        "lr": min(1.0, max(1e-4, config["lr"] * math.exp(rng.gauss(0, 0.25)))),
        "depth": min(8, max(1, config["depth"] + rng.choice([-1, 0, 0, 1]))),
        "epochs": min(2000, max(50, int(config["epochs"] * math.exp(rng.gauss(0, 0.25))))),
    }


def _lr_down(config: dict, _rng: random.Random) -> dict:
    return {**config, "lr": config["lr"] / 3.0}


def _epochs_down(config: dict, _rng: random.Random) -> dict:
    return {**config, "epochs": max(50, int(config["epochs"] * 0.6))}


def _depth_down(config: dict, _rng: random.Random) -> dict:
    return {**config, "depth": max(1, config["depth"] - 1)}


def _restart(_config: dict, rng: random.Random) -> dict:
    return {
        "lr": 10 ** rng.uniform(-4, 0),
        "depth": rng.randint(1, 8),
        "epochs": rng.randint(50, 2000),
    }


def _hedge(rng: random.Random, weighted: list[tuple[float, object]]) -> object:
    roll, acc = rng.random(), 0.0
    for weight, move in weighted:
        acc += weight
        if roll < acc:
            return move
    return weighted[-1][1]


def propose(config: dict, arm: str, label: str | None, rng: random.Random) -> dict:
    if rng.random() < NOOP_RATE:
        return dict(config)  # the no-op edit real agents emit

    if label is None or label == "kept" or label == "reverted":
        move = _perturb
    elif arm == "nine":
        move = {
            "not_finite": _lr_down,
            "timed_out": _epochs_down,
            "failed": _depth_down,
            "no_change": _perturb,
            "no_metric": _restart,
        }.get(label, _perturb)
    elif arm == "five":
        if label == "no_metric":  # missing print OR diverged — cannot tell
            move = _hedge(rng, [(0.5, _lr_down), (0.5, _restart)])
        elif label == "failed":  # crash OR no-op edit — cannot tell
            move = _hedge(rng, [(0.5, _depth_down), (0.5, _perturb)])
        elif label == "timed_out":
            move = _epochs_down
        else:
            move = _perturb
    else:  # bare: not-kept, cause unknowable
        move = _hedge(
            rng,
            [
                (0.6, _perturb),
                (0.1, _lr_down),
                (0.1, _epochs_down),
                (0.1, _depth_down),
                (0.1, _restart),
            ],
        )
    return move(config, rng)


def degrade(outcome: str, arm: str) -> str:
    if arm == "five":
        return DEGRADE_FIVE.get(outcome, outcome)
    if arm == "bare":
        return "kept" if outcome == "kept" else "not_kept"
    return outcome


# --- glue: fake runner + fake workspace around the real Loop ----------------


class SimWorkspace:
    """config.json semantics without git: snapshot on commit, restore on revert."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.committed = path.read_text()
        self.n = 0

    def is_dirty(self) -> bool:
        return self.path.read_text() != self.committed

    def changed_paths(self):
        return ["config.json"] if self.is_dirty() else []

    def revert(self) -> None:
        self.path.write_text(self.committed)

    def commit(self, message: str, paths=None) -> str:
        self.committed = self.path.read_text()
        self.n += 1
        return f"c{self.n:04d}"


def one_run(arm: str, seed: int, workdir: Path) -> dict:
    noise = random.Random(seed * 3 + 1)
    agent_rng = random.Random(seed * 3 + 2)
    config_path = workdir / "config.json"
    config_path.write_text(json.dumps({"lr": 0.02, "depth": 4, "epochs": 800}))

    def fake_run_command(command, cwd=".", timeout=300.0, env=None):
        config = json.loads(config_path.read_text())
        if command == "AGENT":
            label = None
            if env and "LABLOOP_BRIEF" in env:
                history = json.load(open(env["LABLOOP_BRIEF"]))["history"]
                if history:
                    label = degrade(history[-1]["outcome"], arm)
            config_path.write_text(json.dumps(propose(config, arm, label, agent_rng)))
            return Completed(0, "proposed\n", 0.0, False)
        return run_experiment(config, noise)

    loop_module.run_command = fake_run_command
    try:
        exp = Experiment(
            run="RUN", metric="val", goal=Goal.MINIMIZE, propose="AGENT", give_up_after=0
        )
        loop = Loop(
            exp,
            workdir=workdir,
            ledger=workdir / "ledger.jsonl",
            workspace=SimWorkspace(config_path),
        )
        loop.baseline()
        best_so_far, curve, outcomes = math.inf, [], Counter()
        for trial in loop.run(trials=TRIALS):
            outcomes[trial.outcome.value] += 1
            if trial.outcome.value == "kept" and trial.metric is not None:
                best_so_far = min(best_so_far, trial.metric)
            curve.append(best_so_far if math.isfinite(best_so_far) else None)
        finite = [v for v in curve if v is not None]
        return {
            "best": finite[-1] if finite else 10.0,
            "auc": statistics.mean(finite) if finite else 10.0,
            "outcomes": dict(outcomes),
        }
    finally:
        loop_module.run_command = __import__("labloop.runner", fromlist=["run_command"]).run_command
        for f in workdir.iterdir():
            f.unlink()


# --- statistics, stdlib only -------------------------------------------------


def mann_whitney(a: list[float], b: list[float]) -> tuple[float, float]:
    """Two-sided Mann-Whitney U via normal approximation with tie correction."""
    pooled = [(v, 0) for v in a] + [(v, 1) for v in b]
    pooled.sort(key=lambda t: t[0])
    values = [v for v, _ in pooled]
    ranks: dict[int, float] = {}
    i = 0
    while i < len(values):
        j = i
        while j < len(values) and values[j] == values[i]:
            j += 1
        for k in range(i, j):
            ranks[k] = (i + j + 1) / 2  # 1-based average rank for the tie block
        i = j
    rank_sum_a = sum(ranks[idx] for idx, (_, group) in enumerate(pooled) if group == 0)
    n1, n2 = len(a), len(b)
    u = rank_sum_a - n1 * (n1 + 1) / 2
    tie_term = 0.0
    i = 0
    while i < len(values):
        j = i
        while j < len(values) and values[j] == values[i]:
            j += 1
        tie_term += (j - i) ** 3 - (j - i)
        i = j
    n = n1 + n2
    var_u = n1 * n2 / 12 * ((n + 1) - tie_term / (n * (n - 1)))
    if var_u == 0:
        return u, 1.0
    z = (u - n1 * n2 / 2) / math.sqrt(var_u)
    return u, 2 * (1 - _phi(abs(z)))


def _phi(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def permutation_p(a: list[float], b: list[float], resamples: int = 10_000) -> float:
    rng = random.Random(0)
    observed = abs(statistics.mean(a) - statistics.mean(b))
    pooled = a + b
    hits = 0
    for _ in range(resamples):
        rng.shuffle(pooled)
        diff = abs(statistics.mean(pooled[: len(a)]) - statistics.mean(pooled[len(a):]))
        if diff >= observed - 1e-15:
            hits += 1
    return (hits + 1) / (resamples + 1)


def cliffs_delta(a: list[float], b: list[float]) -> float:
    gt = sum(1 for x in a for y in b if x > y)
    lt = sum(1 for x in a for y in b if x < y)
    return (gt - lt) / (len(a) * len(b))


def main() -> None:
    import tempfile

    workdir = Path(tempfile.mkdtemp(prefix="labloop-sim-"))
    results: dict[str, list[dict]] = {arm: [] for arm in ARMS}
    for arm in ARMS:
        for seed in range(REPS):
            results[arm].append(one_run(arm, seed, workdir))
        bests = [r["best"] for r in results[arm]]
        fired = Counter()
        for r in results[arm]:
            fired.update(r["outcomes"])
        print(
            f"{arm:>5}: best-after-{TRIALS}  mean {statistics.mean(bests):.4f}  "
            f"median {statistics.median(bests):.4f}  sd {statistics.stdev(bests):.4f}"
        )
        print(f"       outcomes fired: {dict(sorted(fired.items()))}")

    print()
    for endpoint in ("best", "auc"):
        print(f"endpoint: {endpoint} (lower is better)")
        for x, y in (("bare", "five"), ("five", "nine"), ("bare", "nine")):
            a = [r[endpoint] for r in results[x]]
            b = [r[endpoint] for r in results[y]]
            _, p_mw = mann_whitney(a, b)
            p_perm = permutation_p(a, b)
            print(
                f"  {x} vs {y}:  means {statistics.mean(a):.4f} / {statistics.mean(b):.4f}"
                f"   MW p={p_mw:.2g}  perm p={p_perm:.2g}  cliffs_d={cliffs_delta(a, b):+.3f}"
            )
        print()

    out = Path(__file__).parent / "raw_results.json"
    out.write_text(json.dumps(results, indent=0))
    print(f"raw per-seed results -> {out}")


if __name__ == "__main__":
    main()
