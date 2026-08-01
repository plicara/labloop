"""Settings for an experiment whose metric moves on its own.

Keep-or-revert assumes a change in the metric means a change in the code. An
experiment that scores differently run to run breaks that, and the loop will
commit the luckier draws and report them as progress. These cover the two
settings that push back, and the command that tells you whether you need
them.
"""

from __future__ import annotations

import pytest

from labloop import Experiment, Goal, Outcome

from .conftest import make_loop


def test_min_delta_requires_more_than_a_hair(tmp_path):
    loop, ws = make_loop(tmp_path, run="echo val=1.0")
    loop.baseline()

    loop, ws = make_loop(tmp_path, run="echo val=0.99")
    loop.experiment.min_delta = 0.05
    (trial,) = loop.run(trials=1)
    assert trial.outcome is Outcome.REVERTED, "0.01 better is inside the noise band"

    loop, ws = make_loop(tmp_path, run="echo val=0.8")
    loop.experiment.min_delta = 0.05
    (trial,) = loop.run(trials=1)
    assert trial.outcome is Outcome.KEPT


def test_min_delta_applies_to_maximize_too(tmp_path):
    loop, _ = make_loop(tmp_path, run="echo val=0.7", goal=Goal.MAXIMIZE)
    loop.baseline()
    loop, _ = make_loop(tmp_path, run="echo val=0.71", goal=Goal.MAXIMIZE)
    loop.experiment.min_delta = 0.05
    (trial,) = loop.run(trials=1)
    assert trial.outcome is Outcome.REVERTED


def test_a_negative_min_delta_is_rejected():
    with pytest.raises(ValueError, match="min_delta"):
        Experiment(run="x", metric="m", min_delta=-0.1)


def test_confirm_reverts_a_win_that_does_not_repeat(tmp_path):
    # The experiment reports 0.1 once and then 9.9 — a lucky first draw.
    flip = tmp_path / "flip.sh"
    flip.write_text(
        "#!/bin/sh\nif [ -f seen ]; then echo val=9.9; else touch seen; echo val=0.1; fi\n"
    )
    flip.chmod(0o755)

    loop, ws = make_loop(tmp_path, run="echo val=1.0")
    loop.baseline()

    loop, ws = make_loop(tmp_path, run=str(flip))
    loop.experiment.confirm = True
    (trial,) = loop.run(trials=1)

    assert trial.outcome is Outcome.REVERTED
    assert "second run" in trial.note
    assert not ws.commits, "a win that does not repeat is not a win"


def test_confirm_keeps_a_win_that_repeats_but_records_the_weaker_number(tmp_path):
    loop, _ = make_loop(tmp_path, run="echo val=1.0")
    loop.baseline()

    loop, ws = make_loop(tmp_path, run="echo val=0.5")
    loop.experiment.confirm = True
    (trial,) = loop.run(trials=1)

    assert trial.outcome is Outcome.KEPT
    assert trial.metric == 0.5
    assert ws.commits


def test_confirm_advances_the_incumbent_to_the_weaker_measurement(tmp_path):
    # Both runs beat the incumbent, but by different amounts. Taking the
    # luckier one sets a bar only luck can clear, which is what walks a noisy
    # metric downwards.
    flip = tmp_path / "flip.sh"
    flip.write_text(
        "#!/bin/sh\nif [ -f seen ]; then echo val=0.8; else touch seen; echo val=0.2; fi\n"
    )
    flip.chmod(0o755)

    loop, _ = make_loop(tmp_path, run="echo val=1.0")
    loop.baseline()
    loop, _ = make_loop(tmp_path, run=str(flip))
    loop.experiment.confirm = True
    (trial,) = loop.run(trials=1)

    assert trial.outcome is Outcome.KEPT
    assert trial.metric == 0.8, "the incumbent advances to the weaker of the two"


def test_confirm_takes_the_weaker_measurement_under_maximize_too(tmp_path):
    # Weaker means smaller when higher is better, so the two goals need
    # opposite reductions and a wrong one silently ratchets faster.
    flip = tmp_path / "flip.sh"
    flip.write_text(
        "#!/bin/sh\nif [ -f seen ]; then echo acc=0.90; else touch seen; echo acc=0.99; fi\n"
    )
    flip.chmod(0o755)

    loop, _ = make_loop(tmp_path, run="echo acc=0.5", goal=Goal.MAXIMIZE)
    loop.experiment.metric = "acc"
    loop.baseline()

    loop, _ = make_loop(tmp_path, run=str(flip), goal=Goal.MAXIMIZE)
    loop.experiment.metric = "acc"
    loop.experiment.confirm = True
    (trial,) = loop.run(trials=1)

    assert trial.outcome is Outcome.KEPT
    assert trial.metric == 0.90


def test_measure_noise_runs_without_touching_the_ledger(tmp_path):
    loop, _ = make_loop(tmp_path, run="echo val=1.0")
    values = loop.measure_noise(repeats=3)

    assert values == [1.0, 1.0, 1.0]
    assert not (tmp_path / "l.jsonl").exists(), (
        "calibration runs are not trials and must not become the incumbent"
    )


def test_measure_noise_needs_at_least_two_runs(tmp_path):
    loop, _ = make_loop(tmp_path, run="echo val=1.0")
    with pytest.raises(ValueError, match="at least 2"):
        loop.measure_noise(repeats=1)


def test_measure_noise_refuses_a_broken_experiment(tmp_path):
    loop, _ = make_loop(tmp_path, run="exit 1")
    with pytest.raises(RuntimeError, match="usable val"):
        loop.measure_noise(repeats=2)
