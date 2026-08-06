"""The cookbook's recipes still work, as far as each one can be checked.

Most recipes are `narrative`: they need a real agent, so their trajectory
cannot be re-run and their numbers are a dated record rather than a
reproducible result. That is honest, and it leaves a gap — nothing would
notice when a recipe stopped working.

The gap closes once you separate the two halves. *Whether the agent did well*
needs an agent. *Whether the harness still runs* is ordinary deterministic
code, and it is the half that actually rots:

- a Python release drops a stdlib module and the retrieval corpus loses
  documents its judgments point at (this already happened once, caught by
  `queries.check`)
- pytest changes its summary line and the test-suite recipe's pass-count
  regex reads the wrong number, or nothing
- a model's reply format drifts past the prompt recipe's parser (this
  happened too, and is why `evaluate.selftest` exists)

So every recipe declares a `verify` command in its `recipe.json`, and it runs
here whatever tier the recipe is. Only `verified` recipes additionally replay
their whole loop and get their ledger checked against the outcomes they claim.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest

COOKBOOK = Path(__file__).resolve().parent.parent / "cookbook"
TIERS = {"verified", "structural", "narrative"}


def _recipes():
    return sorted(COOKBOOK.glob("*/*/recipe.json"))


RECIPES = _recipes()
IDS = [p.parent.name for p in RECIPES]


def load(path: Path) -> dict:
    return json.loads(path.read_text())


def tier_of(path: Path) -> str:
    """The declared tier, or "" when absent.

    Collection must not depend on a recipe being well-formed: a missing
    `tier` is a finding for test_recipe_metadata_is_complete to report, not a
    KeyError that takes the whole file down and hides every other recipe.
    """
    return load(path).get("tier", "")


def run_in_copy(recipe: Path, command: str, extra_env: dict | None = None):
    """Run a command against a fresh copy of the recipe's files."""
    import os
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp) / "work"
        shutil.copytree(recipe.parent / "files", work)
        env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
        if extra_env:
            env.update(extra_env)
        return subprocess.run(
            command, shell=True, cwd=work, env=env,
            capture_output=True, text=True, timeout=300,
        )


def test_the_cookbook_has_recipes():
    """A glob that silently matches nothing would make every test below pass."""
    assert len(RECIPES) >= 5, f"found only {len(RECIPES)} recipes"


@pytest.mark.parametrize("path", RECIPES, ids=IDS)
def test_recipe_metadata_is_complete(path: Path):
    meta = load(path)
    for field in ("title", "question", "tier", "verify", "section"):
        assert meta.get(field), f"{path.parent.name} has no {field}"

    assert meta["tier"] in TIERS, f"unknown tier {meta['tier']!r}"

    if meta["tier"] == "narrative":
        # A recipe nobody re-runs has to say when and on what it was recorded,
        # or its numbers are unfalsifiable.
        recorded = meta.get("recorded", {})
        assert recorded.get("date"), "a narrative recipe must record its date"
        assert recorded.get("labloop"), "a narrative recipe must record the version"

    if meta["tier"] == "verified":
        assert meta.get("expect"), "a verified recipe must say what its ledger should contain"
        assert (path.parent / "run.sh").exists(), "a verified recipe needs a run.sh to replay"


@pytest.mark.parametrize("path", RECIPES, ids=IDS)
def test_recipe_files_exist_and_are_self_contained(path: Path):
    files = path.parent / "files"
    assert files.is_dir(), f"{path.parent.name} has no files/ directory"
    assert any(files.iterdir()), "files/ is empty"
    assert (path.parent / "README.md").exists()


@pytest.mark.parametrize("path", RECIPES, ids=IDS)
def test_recipe_harness_still_works(path: Path):
    """The deterministic half of every recipe, whatever tier it is.

    This does not check that the agent did anything good. It checks that the
    experiment still runs, the evaluator still evaluates, and the recipe's
    own integrity checks still pass.
    """
    meta = load(path)
    if not meta.get("verify"):
        pytest.fail(f"{path.parent.name} declares no verify command")
    result = run_in_copy(path, meta["verify"])
    assert result.returncode == 0, (
        f"{path.parent.name}: `{meta['verify']}` failed\n"
        f"stdout:\n{result.stdout[-2000:]}\nstderr:\n{result.stderr[-2000:]}"
    )


@pytest.mark.parametrize(
    "path",
    [p for p in RECIPES if tier_of(p) == "verified"],
    ids=[p.parent.name for p in RECIPES if tier_of(p) == "verified"],
)
def test_verified_recipe_reproduces_the_ledger_it_claims(path: Path):
    """Replay the whole loop and check the outcomes against `expect`.

    The ledger is the oracle: a recipe claiming to demonstrate a caught cheat
    has to actually produce a `harness_changed` trial.
    """
    meta = load(path)
    import os
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp) / "work"
        work.mkdir(parents=True)
        env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
        result = subprocess.run(
            ["bash", str(path.parent / "run.sh")],
            cwd=work, env=env, capture_output=True, text=True, timeout=600,
        )
        assert result.returncode == 0, (
            f"run.sh failed\nstdout:\n{result.stdout[-2000:]}\nstderr:\n{result.stderr[-2000:]}"
        )

        ledger = work / "labloop.jsonl"
        assert ledger.exists(), "the run produced no ledger"

        counts: Counter[str] = Counter()
        best = None
        for line in ledger.read_text().splitlines():
            if not line.strip():
                continue
            trial = json.loads(line)
            if "outcome" not in trial:
                continue  # manifest lines
            counts[trial["outcome"]] += 1
            if trial["outcome"] == "kept" and trial.get("metric") is not None:
                best = trial["metric"] if best is None else min(best, trial["metric"])

    expected = dict(meta["expect"])
    expected_best = expected.pop("best_metric", None)
    for outcome, want in expected.items():
        assert counts[outcome] == want, (
            f"expected {want} {outcome} trials, got {counts[outcome]} ({dict(counts)})"
        )
    if expected_best is not None:
        assert best == pytest.approx(expected_best), f"best metric was {best}"


_LABLOOP_COMMAND = re.compile(r"^\s*(labloop\b.*)$", re.M)


def _labloop_commands(text: str) -> set[str]:
    """Every `labloop ...` invocation in fenced bash blocks, whitespace-normalised."""
    found = set()
    for block in re.findall(r"```bash\n(.*?)```", text, re.S):
        joined = block.replace("\\\n", " ")
        for match in _LABLOOP_COMMAND.finditer(joined):
            found.add(" ".join(match.group(1).split()))
    return found


@pytest.mark.parametrize(
    "path",
    [p for p in RECIPES if (p.parent / "run.sh").exists()],
    ids=[p.parent.name for p in RECIPES if (p.parent / "run.sh").exists()],
)
def test_readme_shows_the_commands_run_sh_actually_runs(path: Path):
    """A command shown to a reader that is not the command we ran is a lie.

    Only `labloop` invocations are compared: the surrounding setup differs
    legitimately (the README says `cp cookbook/.../files/*.py .`, run.sh
    resolves that relative to itself).
    """
    readme = _labloop_commands((path.parent / "README.md").read_text())
    script = " ".join((path.parent / "run.sh").read_text().replace("\\\n", " ").split())

    for command in readme:
        assert command in script, (
            f"{path.parent.name}: README shows `{command}` but run.sh does not run it"
        )


def test_the_generated_index_is_current():
    """cookbook/README.md is generated; a stale one drifts from the directory."""
    result = subprocess.run(
        [sys.executable, str(COOKBOOK / "build_index.py"), "--check"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
