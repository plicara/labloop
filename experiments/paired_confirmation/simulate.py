"""Does a paired confirmation credit the gain a change really has?

Dogfood run 3 kept only the two trials judged against the two slowest of 21
incumbent draws, and credited them with five to seven times what an
interleaved check found: one incumbent measurement was the bar for both the
first run and the confirmation, so a slow draw passed both. This measures the
three ways the loop can confirm, on an experiment whose truth is known.

  unpaired  --confirm: the candidate is judged twice against the ledger's
            incumbent, the weaker of its two runs is kept.
  reused    --paired --confirm before the fix: the incumbent is measured once
            before the proposal and that draw judges both candidate runs.
  fresh     --paired --confirm now: a first-round winner is set aside, the
            incumbent measured again and the candidate measured again; it is
            kept only if that independent pair wins too, and its gain is then
            estimated on a third pair that no verdict depends on.

RESULTS.md also reports the intermediate design, which credited the gain from
the second pair: it ran with this script at commit 2b1c790.

The experiment prints quality + N(0, SIGMA). `quality.txt` is tracked; each
proposal lowers it by the scenario's true effect (minimize) and counts itself
in `attempt.txt`, so every proposal is a change.

  null  no proposal helps: every keep is false, every credited gain is bias.
  real  every proposal truly helps by one SIGMA.

This drives the real Loop on a real git repository, because setting a
proposal aside and restoring it is part of what is under test; only the
experiment's number is simulated. `--min-delta` follows the README: SIGMA
unpaired, SIGMA * sqrt(2) paired, since a paired verdict is a difference of
two runs. Draws are seeded per (rep, run), so results reproduce exactly.
Stdlib only, like the package.

Usage: python experiments/paired_confirmation/simulate.py [REPS] [TRIALS]
"""

from __future__ import annotations

import json
import math
import os
import statistics
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "src"))

from labloop import Experiment, Loop, Outcome  # noqa: E402
from labloop.workspace import GitWorkspace  # noqa: E402

SIGMA = 5.0
START = 100.0
EFFECTS = {"null": 0.0, "real": SIGMA}

MEASURE = """\
import pathlib, random, sys
counter = pathlib.Path(sys.argv[1])
n = int(counter.read_text()) if counter.exists() else 0
counter.write_text(str(n + 1))
quality = float(pathlib.Path("quality.txt").read_text())
print(f"m = {quality + random.Random(f'{sys.argv[2]}:{n}').gauss(0, SIGMA):.6f}")
""".replace("SIGMA", repr(SIGMA))

PROPOSE = """\
import pathlib
q = pathlib.Path("quality.txt")
q.write_text(str(float(q.read_text()) - %r))
a = pathlib.Path("attempt.txt")
a.write_text(str(int(a.read_text()) + 1))
"""


class ReusedReference(GitWorkspace):
    """A git workspace that cannot set a proposal aside.

    The loop then confirms on the incumbent draw taken before the proposal,
    which is exactly the behavior before the fix.
    """

    set_aside = None  # type: ignore[assignment]

    def __getattribute__(self, name: str):  # noqa: D105
        if name in ("set_aside", "restore"):
            raise AttributeError(name)
        return super().__getattribute__(name)


def git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def one_run(mode: str, scenario: str, rep: int, trials: int) -> dict[str, float]:
    effect = EFFECTS[scenario]
    with tempfile.TemporaryDirectory(prefix="labloop-sim-") as tmp:
        root = Path(tmp)
        repo, state = root / "repo", root / "state"
        repo.mkdir()
        state.mkdir()
        (state / "measure.py").write_text(MEASURE)
        (state / "propose.py").write_text(PROPOSE % effect)
        (repo / "quality.txt").write_text(str(START))
        (repo / "attempt.txt").write_text("0")
        (repo / ".gitignore").write_text("labloop.jsonl\n")
        git(repo, "init", "-q", "-b", "main")
        git(repo, "config", "user.name", "sim")
        git(repo, "config", "user.email", "sim@example.invalid")
        git(repo, "add", "-A")
        git(repo, "commit", "-qm", "start")

        paired = mode != "unpaired"
        exp = Experiment(
            run=f"{sys.executable} -I {state / 'measure.py'} {state / 'runs'} {scenario}-{rep}",
            metric="m",
            propose=f"{sys.executable} -I {state / 'propose.py'}",
            confirm=True,
            paired=paired,
            min_delta=SIGMA * math.sqrt(2) if paired else SIGMA,
            sandbox="none",
            brief=False,
            give_up_after=0,
        )
        workspace = ReusedReference(repo) if mode == "reused" else GitWorkspace(repo)
        loop = Loop(exp, workdir=repo, workspace=workspace)
        loop.baseline()
        results = loop.run(trials=trials)

        kept = [t for t in results if t.outcome is Outcome.KEPT]
        credited = [t.bar - t.metric for t in kept if t.bar is not None and t.metric is not None]
        runs = int((state / "runs").read_text())
        stashes = subprocess.run(["git", "stash", "list"], cwd=repo, capture_output=True,
                                 text=True).stdout
        if stashes or subprocess.run(["git", "status", "--porcelain"], cwd=repo,
                                     capture_output=True, text=True).stdout:
            raise SystemExit(f"{mode}/{scenario}/{rep}: left a stash or a dirty tree")
        return {
            "keeps": len(kept),
            "credited_total": sum(credited),
            "true_total": effect * len(kept),
            "credited_per_keep": statistics.mean(credited) if credited else 0.0,
            "runs": runs - 1,
        }


def main() -> None:
    reps = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    trials = int(sys.argv[2]) if len(sys.argv) > 2 else 40
    os.environ["LABLOOP_SANDBOX"] = "none"
    raw: dict[str, list[dict[str, float]]] = {}
    for scenario in EFFECTS:
        for mode in ("unpaired", "reused", "fresh"):
            key = f"{scenario}/{mode}"
            raw[key] = [one_run(mode, scenario, rep, trials) for rep in range(reps)]
            print(f"done {key}", file=sys.stderr, flush=True)

    (HERE / "raw_three_pair.json").write_text(json.dumps(raw, indent=1, sort_keys=True))
    print(f"{reps} runs of {trials} trials per cell; SIGMA = {SIGMA}; "
          f"true effect per proposal: null 0, real {EFFECTS['real']:g}\n")
    print("| Scenario | Confirmation | Keeps per run | Credited per keep | "
          "True per keep | Credited total / true total | Runs per trial |")
    print("| --- | --- | --- | --- | --- | --- | --- |")
    for key, runs in raw.items():
        scenario, mode = key.split("/")
        keeps = sum(r["keeps"] for r in runs)
        credited = sum(r["credited_total"] for r in runs)
        true = sum(r["true_total"] for r in runs)
        ratio = f"{credited / true:.2f}" if true else "no true gain"
        print(f"| {scenario} | {mode} | {keeps / len(runs):.2f} | "
              f"{credited / keeps if keeps else 0:.2f} | {EFFECTS[scenario]:.2f} | {ratio} | "
              f"{sum(r['runs'] for r in runs) / (len(runs) * trials):.2f} |")


if __name__ == "__main__":
    main()
