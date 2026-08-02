"""Branching research directions: parallel lines of inquiry, one ledger.

Autoresearch grows a single thread of commits; its author has said the next
step is many. A direction forks from a kept trial, advances its own incumbent
in the shared ledger, and never contaminates another direction's comparisons.
"""

from __future__ import annotations

import json

import pytest

from labloop import Experiment, Goal, Ledger, Loop, Outcome
from labloop.cli import main

from .conftest import FakeWorkspace


def direction_loop(tmp_path, run, direction, propose="true"):
    exp = Experiment(run=run, metric="val", propose=propose)
    return Loop(
        exp,
        workdir=tmp_path,
        ledger=tmp_path / "l.jsonl",
        workspace=FakeWorkspace(),
        direction=direction,
    )


def test_trials_carry_their_direction(tmp_path):
    (trial,) = direction_loop(tmp_path, "echo val=1.0", "wide-lr").run(trials=1)
    assert trial.direction == "wide-lr"
    assert Ledger(tmp_path / "l.jsonl").trials()[0].direction == "wide-lr"


def test_directions_advance_independent_incumbents(tmp_path):
    # Direction A keeps 1.0. Direction B has no history: its first trial at
    # 5.0 must be kept, not reverted against A's incumbent — otherwise a
    # promising direction is strangled by a better sibling before it starts.
    direction_loop(tmp_path, "echo val=1.0", "a").run(trials=1)

    (trial,) = direction_loop(tmp_path, "echo val=5.0", "b").run(trials=1)
    assert trial.outcome is Outcome.KEPT
    assert trial.incumbent is None, "direction b has nothing to beat yet"

    # And a's incumbent is untouched by b's worse number.
    (again,) = direction_loop(tmp_path, "echo val=3.0", "a").run(trials=1)
    assert again.outcome is Outcome.REVERTED
    assert again.incumbent == 1.0


def test_a_forked_direction_starts_from_its_parents_metric(tmp_path):
    # Forked from a kept trial at 2.0: a first attempt at 3.0 is worse than
    # where the fork started and must not count as progress.
    direction_loop(tmp_path, "echo val=2.0", "main").run(trials=1)
    Ledger(tmp_path / "l.jsonl").append_fork("variant", from_index=0)

    (worse,) = direction_loop(tmp_path, "echo val=3.0", "variant").run(trials=1)
    assert worse.outcome is Outcome.REVERTED
    assert worse.incumbent == 2.0, "the fork point is the number to beat"

    (better,) = direction_loop(tmp_path, "echo val=1.5", "variant").run(trials=1)
    assert better.outcome is Outcome.KEPT


def test_the_fork_seed_does_not_leak_later_parent_progress(tmp_path):
    # After the fork, the parent keeps improving. The fork competes against
    # its fork point, not against the parent's later trials — that is what
    # makes it a separate direction rather than a spectator.
    direction_loop(tmp_path, "echo val=2.0", "main").run(trials=1)
    Ledger(tmp_path / "l.jsonl").append_fork("variant", from_index=0)
    direction_loop(tmp_path, "echo val=0.5", "main").run(trials=1)  # parent advances

    (trial,) = direction_loop(tmp_path, "echo val=1.0", "variant").run(trials=1)
    assert trial.outcome is Outcome.KEPT, "1.0 beats the fork point 2.0"
    assert trial.incumbent == 2.0


def test_indices_stay_unique_across_directions(tmp_path):
    direction_loop(tmp_path, "echo val=3.0", "a").run(trials=1)
    direction_loop(tmp_path, "echo val=2.0", "b").run(trials=1)
    direction_loop(tmp_path, "echo val=1.0", "a").run(trials=1)
    assert [t.index for t in Ledger(tmp_path / "l.jsonl")] == [0, 1, 2]


def test_the_brief_tells_the_proposer_its_direction_and_only_its_history(tmp_path):
    direction_loop(tmp_path, "echo val=1.0", "a").run(trials=1)

    seen = tmp_path / "seen.json"
    direction_loop(
        tmp_path, "echo val=9.0", "b", propose=f'cp "$LABLOOP_BRIEF" {seen}'
    ).run(trials=1)

    brief = json.loads(seen.read_text())
    assert brief["direction"] == "b"
    assert brief["history"] == [], "another direction's trials are not this one's history"


def test_directions_lists_forked_but_unstarted_ones(tmp_path):
    direction_loop(tmp_path, "echo val=1.0", "main").run(trials=1)
    ledger = Ledger(tmp_path / "l.jsonl")
    ledger.append_fork("idea", from_index=0)
    assert set(ledger.directions()) == {"main", "idea"}


# --- the branch command ------------------------------------------------------


@pytest.fixture
def project(tmp_path, monkeypatch):
    import subprocess

    def git(*args):
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)

    (tmp_path / "train.py").write_text('print("val_loss = 2.0")\n')
    (tmp_path / ".gitignore").write_text("labloop.jsonl\n__pycache__/\n")
    git("init", "-q", ".")
    git("config", "user.email", "t@t.test")
    git("config", "user.name", "t")
    git("add", "-A")
    git("commit", "-qm", "init")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PYTHONDONTWRITEBYTECODE", "1")
    return tmp_path


def kept_trial(project):
    main(["baseline", "--run", "python train.py", "--metric", "val_loss"])
    main(
        [
            "run",
            "--run",
            "python train.py",
            "--metric",
            "val_loss",
            "--propose",
            "echo 'print(\"val_loss = 1.0\")' > train.py",
        ]
    )


def test_branch_records_the_fork_and_says_how_to_run_it(project, capsys):
    kept_trial(project)
    capsys.readouterr()

    assert main(["branch", "wide-lr", "--from-trial", "1"]) == 0
    out = capsys.readouterr().out
    assert "forks from trial 1" in out
    assert "git worktree add" in out
    assert "--direction wide-lr" in out
    assert Ledger(project / "labloop.jsonl").forks() == {"wide-lr": 1}


def test_branch_refuses_a_reverted_trial(project, capsys):
    kept_trial(project)
    main(
        [
            "run",
            "--run",
            "python train.py",
            "--metric",
            "val_loss",
            "--propose",
            "echo 'print(\"val_loss = 9.0\")' > train.py",
        ]
    )
    capsys.readouterr()

    assert main(["branch", "bad", "--from-trial", "2"]) == 2
    err = capsys.readouterr().err
    assert "reverted" in err and "kept trial" in err


def test_branch_refuses_a_duplicate_or_slashed_name(project, capsys):
    kept_trial(project)
    main(["branch", "wide-lr", "--from-trial", "1"])
    assert main(["branch", "wide-lr", "--from-trial", "1"]) == 2
    assert main(["branch", "a/b", "--from-trial", "1"]) == 2


def test_log_reports_each_directions_best(project, capsys):
    kept_trial(project)
    main(["branch", "wide-lr", "--from-trial", "1"])
    main(
        [
            "run",
            "--run",
            "python train.py",
            "--metric",
            "val_loss",
            "--direction",
            "wide-lr",
            "--propose",
            "echo 'print(\"val_loss = 0.5\")' > train.py",
        ]
    )
    capsys.readouterr()

    assert main(["log", "--metric", "val_loss"]) == 0
    out = capsys.readouterr().out
    assert "main: best val_loss 1 (trial 1)" in out
    assert "wide-lr: best val_loss 0.5 (trial 2) (forked from trial 1)" in out


def test_resume_returns_to_the_direction_it_left(project, capsys):
    kept_trial(project)
    main(["branch", "wide-lr", "--from-trial", "1"])
    main(
        [
            "run",
            "--run",
            "python train.py",
            "--metric",
            "val_loss",
            "--direction",
            "wide-lr",
            "--propose",
            "echo 'print(\"val_loss = 0.5\")' > train.py",
        ]
    )
    capsys.readouterr()

    assert main(["resume"]) == 0
    trials = Ledger(project / "labloop.jsonl").trials()
    assert trials[-1].direction == "wide-lr", "resume continues the direction in force"


def test_old_ledgers_are_one_direction_named_main(tmp_path):
    path = tmp_path / "old.jsonl"
    path.write_text(
        '{"commit": null, "duration_seconds": 1.0, "incumbent": null, "index": 0, '
        '"metric": 2.0, "note": "baseline", "outcome": "kept", "stdout_tail": ""}\n'
    )
    ledger = Ledger(path)
    assert ledger.directions() == ["main"]
    assert ledger.best(Goal.MINIMIZE, direction="main").metric == 2.0


def test_branching_off_a_missing_trial_is_refused(project, capsys):
    kept_trial(project)
    assert main(["branch", "x", "--from-trial", "99"]) == 2
    assert "not in" in capsys.readouterr().err


def test_direction_names_reach_usage_error_not_traceback(project):
    kept_trial(project)
    with pytest.raises(SystemExit):
        main(["branch"])  # missing name: argparse's job
    assert main(["branch", "  ", "--from-trial", "1"]) == 2
