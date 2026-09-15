"""Branching research directions: parallel lines of inquiry, one ledger.

Autoresearch grows a single thread of commits; its author has said the next
step is many. A direction forks from a kept trial, advances its own incumbent
in the shared ledger, and never contaminates another direction's comparisons.
"""

from __future__ import annotations

import json
import threading

import pytest

from labloop import Experiment, Goal, Ledger, Loop, Outcome, Trial, UsageError
from labloop.cli import main

from .conftest import FakeWorkspace


def direction_loop(tmp_path, run, direction, propose="true", wait=False):
    exp = Experiment(run=run, metric="val", propose=propose)
    return Loop(
        exp,
        workdir=tmp_path,
        ledger=tmp_path / "l.jsonl",
        workspace=FakeWorkspace(),
        wait_for_lock=wait,
        direction=direction,
    )


def test_trials_carry_their_direction(tmp_path):
    direction_loop(tmp_path, "echo val=2.0", "main").run(trials=1)
    Ledger(tmp_path / "l.jsonl").append_fork("wide-lr", from_index=0)

    (trial,) = direction_loop(tmp_path, "echo val=1.0", "wide-lr").run(trials=1)
    assert trial.direction == "wide-lr"
    assert Ledger(tmp_path / "l.jsonl").trials()[-1].direction == "wide-lr"


def test_directions_advance_independent_incumbents(tmp_path):
    # Both fork from a 10.0 baseline. Direction A advances to 1.0; direction
    # B's 5.0 beats the fork point and must be kept — not reverted against
    # A's better number, or a promising direction is strangled by a better
    # sibling before it starts.
    direction_loop(tmp_path, "echo val=10.0", "main").run(trials=1)
    ledger = Ledger(tmp_path / "l.jsonl")
    ledger.append_fork("a", from_index=0)
    ledger.append_fork("b", from_index=0)

    direction_loop(tmp_path, "echo val=1.0", "a").run(trials=1)
    (trial,) = direction_loop(tmp_path, "echo val=5.0", "b").run(trials=1)
    assert trial.outcome is Outcome.KEPT
    assert trial.incumbent == 10.0, "b competes with its fork point, not with a"

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
    direction_loop(tmp_path, "echo val=9.0", "main").run(trials=1)
    ledger = Ledger(tmp_path / "l.jsonl")
    ledger.append_fork("a", from_index=0)
    ledger.append_fork("b", from_index=0)

    direction_loop(tmp_path, "echo val=3.0", "a").run(trials=1)
    direction_loop(tmp_path, "echo val=2.0", "b").run(trials=1)
    direction_loop(tmp_path, "echo val=1.0", "a").run(trials=1)
    assert [t.index for t in Ledger(tmp_path / "l.jsonl")] == [0, 1, 2, 3]


def test_the_ledger_lock_is_taken_per_trial_not_per_run(tmp_path, monkeypatch):
    # The bug was a run-level lock around every trial, so a second direction
    # could not start until the first finished its whole run. Counting the
    # lock's acquisitions pins the fix without relying on thread timing.
    import labloop.loop as loop_module

    acquisitions = []
    real_lock = loop_module.LedgerLock

    class CountingLock:
        def __init__(self, *args, **kwargs):
            self._inner = real_lock(*args, **kwargs)

        def __enter__(self):
            acquisitions.append(1)
            self._inner.__enter__()
            return self

        def __exit__(self, *exc):
            return self._inner.__exit__(*exc)

    monkeypatch.setattr(loop_module, "LedgerLock", CountingLock)
    direction_loop(tmp_path, "echo val=1.0", "main", wait=True).run(trials=3)

    # One for the manifest, then one per trial. A run-level lock takes one
    # for all three, which is < 3 and fails here.
    assert len(acquisitions) >= 3


def test_two_directions_run_concurrently_over_one_ledger(tmp_path):
    # Two directions share one ledger and run at the same time. The lock is
    # handed out per trial, so they may interleave; whichever order it lands
    # in, every trial is recorded once, indices never collide, and each
    # direction is judged against its own incumbent. (The lock is flock, so
    # which direction wins a given handoff is the kernel's business, not an
    # assertion this test can make deterministically.)
    trials = 3
    direction_loop(tmp_path, "echo val=10.0", "main").run(trials=1)
    ledger = Ledger(tmp_path / "l.jsonl")
    ledger.append_fork("a", from_index=0)
    ledger.append_fork("b", from_index=0)

    started = threading.Barrier(2)
    results: dict[str, list] = {}
    failures: list[BaseException] = []

    def drive(direction: str, metric: float) -> None:
        loop = Loop(
            Experiment(
                run=f"sleep 0.05; echo val={metric}", metric="val", propose="true"
            ),
            workdir=tmp_path,
            ledger=tmp_path / "l.jsonl",
            workspace=FakeWorkspace(),
            wait_for_lock=True,
            direction=direction,
        )
        try:
            started.wait(timeout=10)
            results[direction] = loop.run(trials=trials)
        except BaseException as exc:  # surfaced by the main thread
            failures.append(exc)

    threads = [
        threading.Thread(target=drive, args=("a", 1.0)),
        threading.Thread(target=drive, args=("b", 2.0)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
        assert not thread.is_alive(), "a direction never finished; the lock starved it"
    assert not failures, failures
    assert set(results) == {"a", "b"}, "both directions must make progress"

    recorded = Ledger(tmp_path / "l.jsonl")
    indices = [trial.index for trial in recorded]
    assert len(indices) == len(set(indices)), "trial indices collided"
    assert sorted(indices) == list(range(len(indices))), "indices should be dense"

    # Each direction is judged against its own fork point, and the ledger
    # agrees with what the loops reported.
    assert recorded.best(Goal.MINIMIZE, direction="a").metric == 1.0
    assert recorded.best(Goal.MINIMIZE, direction="b").metric == 2.0
    assert [trial.metric for trial in results["a"]] == [1.0] * trials
    assert [trial.metric for trial in results["b"]] == [2.0] * trials


def test_a_peers_kept_trial_sets_the_bar_for_the_next_trial(tmp_path):
    # The incumbent is re-read from the ledger each trial, not remembered from
    # before the loop. A peer keeping a better trial mid-run must move the bar;
    # a stale in-memory incumbent would have kept the next, worse, change.
    direction_loop(tmp_path, "echo val=10.0", "main").run(trials=1)  # baseline

    loop = direction_loop(tmp_path, "echo val=5.0", "main")

    def record_peer_after_trial(trial):
        # Inject a peer result at the trusted controller boundary, after the
        # trial is recorded. Measurement commands must never write the ledger.
        if trial.index == 1:
            loop.ledger.append(Trial(
                index=loop.ledger.next_index(), outcome=Outcome.KEPT, metric=1.0,
                incumbent=5.0, duration_seconds=0.0, note="peer", direction="main",
            ))
            loop.experiment.run = "echo val=2.0"

    loop.reporter = record_peer_after_trial
    first, second = loop.run(trials=2)

    assert first.outcome is Outcome.KEPT and first.metric == 5.0
    # 2.0 is worse than the peer's 1.0. A stale incumbent of 5.0 keeps it.
    assert second.outcome is Outcome.REVERTED
    assert second.incumbent == 1.0


def test_the_brief_tells_the_proposer_its_direction_and_only_its_history(tmp_path):
    direction_loop(tmp_path, "echo val=9.0", "main").run(trials=1)
    ledger = Ledger(tmp_path / "l.jsonl")
    ledger.append_fork("a", from_index=0)
    ledger.append_fork("b", from_index=0)
    direction_loop(tmp_path, "echo val=1.0", "a").run(trials=1)

    seen = tmp_path / "seen.json"
    direction_loop(
        tmp_path, "echo val=8.0", "b", propose=f'cp "$LABLOOP_BRIEF" {seen}'
    ).run(trials=1)

    brief = json.loads(seen.read_text())
    assert brief["direction"] == "b"
    assert brief["history"] == [], "another direction's trials are not this one's history"


def test_directions_lists_forked_but_unstarted_ones(tmp_path):
    direction_loop(tmp_path, "echo val=1.0", "main").run(trials=1)
    ledger = Ledger(tmp_path / "l.jsonl")
    ledger.append_fork("idea", from_index=0)
    assert set(ledger.directions()) == {"main", "idea"}


def test_an_unforked_direction_is_refused_and_the_typo_is_named(tmp_path):
    # Dogfooding found this: `--direction aneal` for `anneal` silently created
    # a phantom direction with no incumbent, and its first trial — a 43x
    # regression — was kept and committed as an improvement. Directions are
    # born by forking, not by typo.
    direction_loop(tmp_path, "echo val=2.0", "main").run(trials=1)
    Ledger(tmp_path / "l.jsonl").append_fork("anneal", from_index=0)

    with pytest.raises(UsageError, match="anneal") as caught:
        direction_loop(tmp_path, "echo val=9.0", "aneal").run(trials=1)
    assert "aneal" in str(caught.value), "the refusal names what was typed"

    trials = Ledger(tmp_path / "l.jsonl").trials()
    assert all(t.direction != "aneal" for t in trials), "nothing was recorded under the typo"


def test_the_refusal_lists_known_directions_when_nothing_is_close(tmp_path):
    direction_loop(tmp_path, "echo val=2.0", "main").run(trials=1)
    Ledger(tmp_path / "l.jsonl").append_fork("anneal", from_index=0)

    with pytest.raises(UsageError, match="labloop branch"):
        direction_loop(tmp_path, "echo val=9.0", "zzz").run(trials=1)


def test_main_needs_no_fork(tmp_path):
    (trial,) = direction_loop(tmp_path, "echo val=1.0", "main").run(trials=1)
    assert trial.outcome is Outcome.KEPT


def test_baseline_is_held_to_the_same_rule(tmp_path):
    direction_loop(tmp_path, "echo val=2.0", "main").run(trials=1)
    loop = direction_loop(tmp_path, "echo val=1.0", "nowhere")
    with pytest.raises(UsageError, match="nowhere"):
        loop.baseline()


# --- the branch command ------------------------------------------------------


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
