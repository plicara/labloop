"""How long does labloop itself take per trial? The harness for dogfooding.

labloop runs on labloop: an outer loop lets an agent edit `src/labloop`, and
this script is its `--run` command. It is protected, along with `tests/`, so
the agent can only win by making labloop's own machinery cheaper.

Two gates, then one number:

1. The full test suite must pass. A faster loop that is wrong is not faster.
2. A scripted inner loop runs on a fixture project with the default sandbox,
   and every trial must reach exactly the outcome its schedule dictates. An
   optimization that skips a check, a commit, or a revert changes an outcome
   and fails the run instead of scoring.

The number is `trial_overhead_ms`: wall-clock milliseconds per inner trial,
minus nothing. The inner propose and run commands are trivial and fixed, so
what moves is git, digesting, sandbox setup, the brief, and the ledger.
"""

from __future__ import annotations

import os
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from labloop import Experiment, Goal, Loop  # noqa: E402
from labloop.types import Outcome  # noqa: E402

ROUNDS = 3
TRIALS = 12

# score.txt value written by the proposer for each inner trial, against a
# baseline of 100 (minimize). None means the proposal edits nothing.
SCHEDULE: list[float | None] = [90, 95, 90, None, 80, 80, 85, 70, None, 75, 60, 60]
EXPECTED = [
    Outcome.KEPT, Outcome.REVERTED, Outcome.REVERTED, Outcome.NO_CHANGE,
    Outcome.KEPT, Outcome.REVERTED, Outcome.REVERTED, Outcome.KEPT,
    Outcome.NO_CHANGE, Outcome.REVERTED, Outcome.KEPT, Outcome.REVERTED,
]

PROPOSE = f"""\
import os
schedule = {SCHEDULE!r}
value = schedule[int(os.environ["LABLOOP_TRIAL"]) - 1]
if value is not None:
    open("score.txt", "w").write(str(value))
    open("notes/attempt.txt", "w").write(os.environ["LABLOOP_TRIAL"])
"""


def git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def fixture(where: Path) -> None:
    """A small but not trivial project: source, notes, and protected data."""
    (where / "src").mkdir()
    (where / "notes").mkdir()
    (where / "data").mkdir()
    for i in range(300):
        (where / "src" / f"mod_{i:03}.py").write_text(f"VALUE = {i}\n" * 40)
    for i in range(200):
        (where / "data" / f"row_{i:03}.csv").write_text(f"{i},{i * i}\n" * 200)
    (where / "data" / "holdout.bin").write_bytes(os.urandom(4 * 1024 * 1024))
    (where / "notes" / "attempt.txt").write_text("0")
    (where / "score.txt").write_text("100")
    (where / "propose.py").write_text(PROPOSE)
    (where / "evaluate.py").write_text(
        "print('score =', open('score.txt').read().strip())\n"
    )
    (where / ".gitignore").write_text("labloop.jsonl\n__pycache__/\n")
    git(where, "init", "-q", "-b", "main")
    git(where, "config", "user.name", "bench")
    git(where, "config", "user.email", "bench@example.invalid")
    git(where, "add", "-A")
    git(where, "commit", "-q", "-m", "fixture")


def one_round() -> float:
    with tempfile.TemporaryDirectory(prefix="labloop-bench-") as tmp:
        where = Path(tmp)
        fixture(where)
        exp = Experiment(
            run=f"{sys.executable} evaluate.py",
            metric="score",
            goal=Goal.MINIMIZE,
            budget_seconds=60,
            propose=f"{sys.executable} propose.py",
            protect=("evaluate.py", "propose.py", "data"),
            sandbox="auto",
            strict_metric=True,
            guard_imports=True,
        )
        loop = Loop(exp, workdir=where)
        base = loop.baseline()
        if base.outcome is not Outcome.KEPT:
            sys.exit(f"baseline was {base.outcome.value}: {base.note}")
        started = time.perf_counter()
        trials = loop.run(trials=TRIALS)
        elapsed = time.perf_counter() - started

        got = [t.outcome for t in trials]
        if got != EXPECTED:
            sys.exit(f"outcomes changed:\n  expected {[o.value for o in EXPECTED]}\n"
                     f"  got      {[o.value for o in got]}")
        if (where / "score.txt").read_text() != "60":
            sys.exit("the kept tree does not hold the best score")
        log = subprocess.run(["git", "log", "--oneline"], cwd=where, check=True,
                             capture_output=True, text=True).stdout.splitlines()
        if len(log) != 1 + EXPECTED.count(Outcome.KEPT):
            sys.exit(f"expected {1 + EXPECTED.count(Outcome.KEPT)} commits, got {len(log)}")
        status = subprocess.run(["git", "status", "--porcelain"], cwd=where, check=True,
                                capture_output=True, text=True).stdout
        if status.strip():
            sys.exit(f"inner tree left dirty:\n{status}")
        return elapsed / TRIALS * 1000


def main() -> None:
    if shutil.which("bwrap") is None:
        sys.exit("bench needs bubblewrap: the default sandbox is part of the cost")
    tests = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider"],
        cwd=ROOT, capture_output=True, text=True,
    )
    if tests.returncode != 0:
        print(tests.stdout[-4000:])
        print(tests.stderr[-2000:])
        sys.exit("test suite failed")
    per_round = [one_round() for _ in range(ROUNDS)]
    print("rounds_ms:", " ".join(f"{r:.1f}" for r in per_round), file=sys.stderr)
    print(f"trial_overhead_ms = {statistics.median(per_round):.2f}")


if __name__ == "__main__":
    main()
