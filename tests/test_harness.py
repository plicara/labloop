"""Loop behaviour when a proposal reaches the thing doing the measuring.

A keep-or-revert loop rewards whatever moves the metric, and the propose
command can reach the evaluator. These cover the detection, not prevention:
the change still happens, but it is recorded as a changed measurement rather
than scored as an improvement.
"""

from __future__ import annotations

import pytest

from labloop import Experiment, HarnessMismatchError, Outcome

from .conftest import make_loop


def test_editing_the_harness_is_not_scored_as_an_improvement(tmp_path):
    (tmp_path / "eval.py").write_text("threshold = 0.5")
    loop, ws = make_loop(
        tmp_path,
        run="echo val=0.001",
        propose="echo 'threshold = 0.0' > eval.py",
        protect=("eval.py",),
    )

    (trial,) = loop.run(trials=1)

    assert trial.outcome is Outcome.HARNESS_CHANGED
    assert "eval.py" in trial.note, "the note has to name the file that moved"
    assert trial.metric is None, "a metric from a moved harness is not a result"
    assert not ws.commits, "editing the evaluator must never be committed as a win"
    assert ws.reverts == 1


def test_leaving_the_harness_alone_is_scored_normally(tmp_path):
    (tmp_path / "eval.py").write_text("threshold = 0.5")
    loop, ws = make_loop(
        tmp_path,
        run="echo val=0.001",
        propose="echo tweak > train.py",
        protect=("eval.py",),
    )

    (trial,) = loop.run(trials=1)

    assert trial.outcome is Outcome.KEPT
    assert trial.harness is not None, "a kept trial records how it was measured"
    assert ws.commits


def test_rewriting_the_ledger_is_detected_without_being_declared(tmp_path):
    loop, ws = make_loop(tmp_path, run="echo val=1.0")
    loop.baseline()

    # The ledger holds the incumbent. An agent that can lower the bar does not
    # need to beat it.
    tampering, ws = make_loop(
        tmp_path,
        run="echo val=9.0",
        propose=f"echo '{{\"index\": 0, \"outcome\": \"kept\", \"metric\": 99.0}}' "
        f"> {tmp_path / 'l.jsonl'}",
    )
    (trial,) = tampering.run(trials=1)

    assert trial.outcome is Outcome.HARNESS_CHANGED
    assert "ledger" in trial.note
    assert not ws.commits


def test_deleting_the_protected_files_is_detected(tmp_path):
    (tmp_path / "eval.py").write_text("threshold = 0.5")
    loop, ws = make_loop(
        tmp_path,
        run="echo val=0.001",
        propose="rm eval.py",
        protect=("eval.py",),
    )

    (trial,) = loop.run(trials=1)

    assert trial.outcome is Outcome.HARNESS_CHANGED
    assert "deleted" in trial.note
    assert not ws.commits


def test_an_incumbent_from_another_harness_is_refused(tmp_path):
    (tmp_path / "eval.py").write_text("threshold = 0.5")
    loop, _ = make_loop(tmp_path, run="echo val=1.0", protect=("eval.py",))
    loop.baseline()

    # The user edits the evaluator themselves between runs. Nothing cheated,
    # but the recorded metric was made by a different measurement.
    (tmp_path / "eval.py").write_text("threshold = 0.9")
    fresh, _ = make_loop(tmp_path, run="echo val=0.5", protect=("eval.py",))
    with pytest.raises(HarnessMismatchError, match="not comparable"):
        fresh.run(trials=1)


def test_an_undeclared_incumbent_is_accepted_rather_than_guessed_about(tmp_path):
    loop, _ = make_loop(tmp_path, run="echo val=1.0")
    loop.baseline()

    (tmp_path / "eval.py").write_text("added later")
    fresh, _ = make_loop(tmp_path, run="echo val=0.5", protect=("eval.py",))
    (trial,) = fresh.run(trials=1)

    assert trial.incumbent == 1.0, (
        "a trial recorded before the harness was declared carries no digest, "
        "so there is nothing to contradict"
    )


def test_a_protect_typo_fails_loudly(tmp_path):
    loop, _ = make_loop(tmp_path, run="echo val=1.0", protect=("evla.py",))
    with pytest.raises(ValueError, match="matched no files"):
        loop.baseline()


def test_protect_accepts_a_bare_string(tmp_path):
    (tmp_path / "eval.py").write_text("frozen")
    exp = Experiment(run="echo val=1", metric="val", protect="eval.py")
    assert exp.protect == ("eval.py",)
