"""How the loop decides: keep, revert, or neither."""

from __future__ import annotations

import json

import pytest

from labloop import (
    Experiment,
    Goal,
    Ledger,
    Loop,
    Outcome,
    StalledError,
)

from .conftest import FakeWorkspace, make_loop


def test_baseline_records_metric(tmp_path):
    loop, _ = make_loop(tmp_path, run="echo val=2.0")
    trial = loop.baseline()
    assert trial.outcome is Outcome.KEPT
    assert trial.metric == 2.0
    assert trial.incumbent is None


def test_first_trial_is_kept_without_incumbent(tmp_path):
    loop, ws = make_loop(tmp_path, run="echo val=5.0")
    (trial,) = loop.run(trials=1)
    assert trial.outcome is Outcome.KEPT
    assert ws.commits and ws.reverts == 0


def test_improvement_is_kept_and_regression_reverted(tmp_path):
    loop, ws = make_loop(tmp_path, run="echo val=5.0")
    loop.baseline()

    loop.experiment.run = "echo val=1.0"
    (better,) = loop.run(trials=1)
    assert better.outcome is Outcome.KEPT
    assert better.incumbent == 5.0

    loop.experiment.run = "echo val=9.0"
    (worse,) = loop.run(trials=1)
    assert worse.outcome is Outcome.REVERTED
    assert worse.incumbent == 1.0, "incumbent advances only on a kept trial"
    assert ws.reverts == 1


def test_ties_are_reverted(tmp_path):
    loop, ws = make_loop(tmp_path, run="echo val=1.0")
    loop.baseline()
    (trial,) = loop.run(trials=1)
    assert trial.outcome is Outcome.REVERTED, "a tie is not an improvement"
    assert ws.reverts == 1


def test_maximize_goal_inverts_the_comparison(tmp_path):
    loop, _ = make_loop(tmp_path, run="echo val=1.0", goal=Goal.MAXIMIZE)
    loop.baseline()
    loop.experiment.run = "echo val=2.0"
    (trial,) = loop.run(trials=1)
    assert trial.outcome is Outcome.KEPT


def test_crash_is_reverted_not_scored(tmp_path):
    loop, ws = make_loop(tmp_path, run="echo val=0.1 && exit 1")
    (trial,) = loop.run(trials=1)
    assert trial.outcome is Outcome.FAILED
    assert ws.reverts == 1
    assert not ws.commits, "a crashing trial must never be committed"


def test_a_crash_that_printed_nothing_is_a_crash_not_a_missing_metric(tmp_path):
    # The obvious real case: the run dies before it can print anything. Read
    # in the wrong order this reports `no_metric`, sending you to check your
    # print statement rather than the stack trace.
    loop, ws = make_loop(tmp_path, run="echo 'Traceback...' >&2; exit 1")
    (trial,) = loop.run(trials=1)
    assert trial.outcome is Outcome.FAILED
    assert ws.reverts == 1


def test_a_diverged_run_is_not_reported_as_a_missing_metric(tmp_path):
    loop, ws = make_loop(tmp_path, run="echo val=nan")
    (trial,) = loop.run(trials=1)
    assert trial.outcome is Outcome.NOT_FINITE
    assert "nan" in trial.note
    assert ws.reverts == 1
    assert not ws.commits


def test_a_non_finite_metric_never_becomes_the_incumbent(tmp_path):
    # Nothing compares better than nan, so keeping one would revert every
    # later trial forever and the loop would silently stop making progress.
    loop, _ = make_loop(tmp_path, run="echo val=nan")
    loop.baseline()

    fresh, ws = make_loop(tmp_path, run="echo val=0.5")
    (trial,) = fresh.run(trials=1)
    assert trial.outcome is Outcome.KEPT
    assert trial.incumbent is None, "a nan baseline leaves nothing to beat"
    assert ws.commits


def test_infinity_is_refused_the_same_way(tmp_path):
    loop, ws = make_loop(tmp_path, run="echo val=inf")
    (trial,) = loop.run(trials=1)
    assert trial.outcome is Outcome.NOT_FINITE
    assert not ws.commits


def test_the_ledger_never_stores_a_metric_json_cannot_express(tmp_path):
    # NaN is not valid JSON. Writing it would break every other tool reading
    # the ledger, which is meant to be a queryable artifact.
    loop, _ = make_loop(tmp_path, run="echo val=nan")
    loop.baseline()
    raw = (tmp_path / "l.jsonl").read_text()
    assert "NaN" not in raw and "Infinity" not in raw
    assert json.loads(raw.strip())["metric"] is None


def test_a_ledger_already_holding_a_nan_still_recovers(tmp_path):
    # Written by a version that kept them. The loop must not stay stuck.
    path = tmp_path / "l.jsonl"
    path.write_text(
        '{"commit": null, "duration_seconds": 1.0, "harness": null, "incumbent": null, '
        '"index": 0, "metric": NaN, "note": "baseline", "outcome": "kept", "stdout_tail": ""}\n'
    )
    assert Ledger(path).best(Goal.MINIMIZE) is None

    loop, ws = make_loop(tmp_path, run="echo val=0.5")
    (trial,) = loop.run(trials=1)
    assert trial.outcome is Outcome.KEPT and ws.commits


def test_missing_metric_is_distinguished_from_a_bad_score(tmp_path):
    loop, ws = make_loop(tmp_path, run="echo nothing useful")
    (trial,) = loop.run(trials=1)
    assert trial.outcome is Outcome.NO_METRIC
    assert trial.metric is None
    assert ws.reverts == 1


def test_timeout_is_recorded_and_reverted(tmp_path):
    loop, ws = make_loop(tmp_path, run="sleep 5", budget=0.5)
    (trial,) = loop.run(trials=1)
    assert trial.outcome is Outcome.TIMED_OUT
    assert ws.reverts == 1


def test_a_proposal_that_edited_nothing_is_recorded_not_committed(tmp_path):
    # An agent that thinks it is done, or silently fails to apply its edit.
    # git refuses an empty commit, which used to end the run with a traceback
    # and no record of the trial at all.
    loop, ws = make_loop(tmp_path, run="echo val=0.5", dirty=False)
    (trial,) = loop.run(trials=1)

    assert trial.outcome is Outcome.NO_CHANGE
    assert not ws.commits
    assert ws.reverts == 0, "there is nothing to revert"
    assert Ledger(tmp_path / "l.jsonl").trials(), "the trial still reaches the ledger"


def test_a_no_op_proposal_does_not_spend_the_budget_on_the_experiment(tmp_path):
    # The tree is the incumbent's tree; re-measuring it would only record
    # noise as progress.
    loop, _ = make_loop(tmp_path, run="sleep 10 && echo val=0.1", budget=2.0, dirty=False)
    (trial,) = loop.run(trials=1)

    assert trial.outcome is Outcome.NO_CHANGE
    assert trial.duration_seconds < 2.0, "the run command should never have started"


def test_a_proposal_killed_at_the_budget_is_a_timeout_not_a_crash(tmp_path):
    # Agents think for a while. Reported as "failed", you go looking for a
    # crash in something that was only slow.
    loop, ws = make_loop(tmp_path, run="echo val=1.0", propose="sleep 10", budget=0.5)
    (trial,) = loop.run(trials=1)

    assert trial.outcome is Outcome.TIMED_OUT
    assert "budget" in trial.note
    assert ws.reverts == 1


def test_the_proposal_can_have_its_own_budget(tmp_path):
    # An agent that thinks for longer than the experiment runs is ordinary,
    # and one number for both would kill it.
    loop, _ = make_loop(tmp_path, run="echo val=1.0", propose="sleep 1", budget=0.3)
    loop.experiment.propose_budget = 30.0
    (trial,) = loop.run(trials=1)
    assert trial.outcome is Outcome.KEPT


def test_the_proposal_budget_defaults_to_the_run_budget():
    exp = Experiment(run="x", metric="m", budget_seconds=45.0)
    assert exp.propose_timeout == 45.0
    exp.propose_budget = 120.0
    assert exp.propose_timeout == 120.0


def test_a_non_positive_proposal_budget_is_rejected():
    with pytest.raises(ValueError, match="propose_budget"):
        Experiment(run="x", metric="m", propose_budget=0)


def test_failed_proposal_short_circuits_the_run(tmp_path):
    loop, ws = make_loop(tmp_path, run="echo val=0.001", propose="exit 3")
    (trial,) = loop.run(trials=1)
    assert trial.outcome is Outcome.FAILED
    assert trial.note == "propose command failed"
    assert not ws.commits


# --- giving up on a broken setup ---


def test_a_proposal_that_never_works_stops_the_run(tmp_path):
    # A mistyped propose command used to fail identically for every trial in
    # an overnight budget while looking busy.
    loop, _ = make_loop(tmp_path, run="echo val=1.0", propose="exit 3")
    loop.experiment.give_up_after = 3

    with pytest.raises(StalledError, match="3 trials in a row"):
        loop.run(trials=100)

    trials = Ledger(tmp_path / "l.jsonl").trials()
    assert len(trials) == 3, "it stops at the threshold, not after the whole budget"
    assert all(t.outcome is Outcome.FAILED for t in trials)


def test_a_commit_git_refuses_is_recorded_not_a_crash(tmp_path):
    # A pre-commit hook that rejects the change. The trial measured a real
    # improvement and then vanished with a traceback, taking the ledger entry
    # with it.
    loop, ws = make_loop(tmp_path, run="echo val=0.5")

    def refuse(message):
        raise RuntimeError("git commit failed: lint failed: no docstring")

    ws.commit = refuse
    (trial,) = loop.run(trials=1)

    assert trial.outcome is Outcome.FAILED
    assert trial.metric == 0.5, "the measurement was real and is kept in the record"
    assert "could not be committed" in trial.note
    assert "lint failed" in trial.note, "the git reason has to survive"
    assert ws.reverts == 1, "the tree must match the ledger for the next trial"
    assert Ledger(tmp_path / "l.jsonl").trials()


def test_a_repo_that_never_accepts_a_commit_stops_the_run(tmp_path):
    # These trials carry a metric, so a stall rule keyed on "no metric" would
    # let them run all night.
    loop, ws = make_loop(tmp_path, run="echo val=0.5")
    ws.commit = lambda message: (_ for _ in ()).throw(RuntimeError("hook says no"))
    loop.experiment.give_up_after = 3

    with pytest.raises(StalledError, match="no verdict"):
        loop.run(trials=50)
    assert len(Ledger(tmp_path / "l.jsonl").trials()) == 3


def test_giving_up_can_be_switched_off(tmp_path):
    loop, _ = make_loop(tmp_path, run="echo val=1.0", propose="exit 3")
    loop.experiment.give_up_after = 0
    loop.run(trials=4)
    assert len(Ledger(tmp_path / "l.jsonl").trials()) == 4


def test_a_measured_trial_resets_the_count(tmp_path):
    # Occasional failures are ordinary — an agent that hits a rate limit now
    # and then must not end the run. Only an unbroken run of them counts.
    flaky = tmp_path / "flaky.sh"
    flaky.write_text(
        "#!/bin/sh\n"
        "n=$(cat n 2>/dev/null || echo 0); echo $((n+1)) > n\n"
        "[ $((n % 3)) -eq 2 ] && exit 1\n"
        "exit 0\n"
    )
    flaky.chmod(0o755)

    loop, _ = make_loop(tmp_path, run="echo val=1.0", propose=str(flaky))
    loop.experiment.give_up_after = 2
    loop.run(trials=9)

    outcomes = [t.outcome for t in Ledger(tmp_path / "l.jsonl").trials()]
    assert len(outcomes) == 9, "intermittent failures must not stop the run"
    assert Outcome.FAILED in outcomes


def test_the_stall_message_says_what_went_wrong(tmp_path):
    loop, _ = make_loop(tmp_path, run="echo nothing", propose="true")
    loop.experiment.give_up_after = 2

    with pytest.raises(StalledError) as exc:
        loop.run(trials=50)

    message = str(exc.value)
    assert "no_metric" in message
    assert "nothing is lost" in message, "the ledger still holds every trial"


def test_a_negative_give_up_after_is_rejected():
    with pytest.raises(ValueError, match="give_up_after"):
        Experiment(run="x", metric="m", give_up_after=-1)


def test_an_interrupted_trial_still_reaches_the_ledger(tmp_path):
    # Overnight runs get stopped by hand. "Every trial is recorded" has to
    # survive that, or the record has a hole exactly where someone was
    # watching.
    loop, _ = make_loop(tmp_path, run="echo val=1.0")
    loop.baseline()

    loop, _ = make_loop(tmp_path, run="echo val=0.5")
    loop.workspace.commit = _raise_interrupt

    with pytest.raises(KeyboardInterrupt):
        loop.run(trials=1)

    last = Ledger(tmp_path / "l.jsonl").trials()[-1]
    assert last.outcome is Outcome.INTERRUPTED
    assert last.incumbent == 1.0


def _raise_interrupt(message: str) -> str:
    raise KeyboardInterrupt


def test_run_without_propose_is_rejected(tmp_path):
    exp = Experiment(run="echo val=1", metric="val")
    loop = Loop(exp, workdir=tmp_path, ledger=tmp_path / "l.jsonl", workspace=FakeWorkspace())
    with pytest.raises(ValueError, match="propose"):
        loop.run()


def test_incumbent_carries_across_separate_runs(tmp_path):
    loop, _ = make_loop(tmp_path, run="echo val=1.0")
    loop.baseline()

    fresh, ws = make_loop(tmp_path, run="echo val=4.0")
    (trial,) = fresh.run(trials=1)
    assert trial.incumbent == 1.0, "the ledger is the source of truth for the incumbent"
    assert trial.outcome is Outcome.REVERTED


def test_a_relative_ledger_belongs_to_the_project_not_the_shell(tmp_path, monkeypatch):
    # Running the same project from two directories used to produce two
    # ledgers, the second starting with no incumbent and renumbering from
    # zero, while git history said otherwise.
    project = tmp_path / "project"
    project.mkdir()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()

    monkeypatch.chdir(elsewhere)
    exp = Experiment(run="echo val=1.0", metric="val", propose="true")
    Loop(exp, workdir=project, workspace=FakeWorkspace()).baseline()

    assert (project / "labloop.jsonl").exists()
    assert not (elsewhere / "labloop.jsonl").exists()


def test_an_absolute_ledger_path_is_left_alone(tmp_path):
    somewhere = tmp_path / "records" / "l.jsonl"
    exp = Experiment(run="echo val=1.0", metric="val")
    Loop(exp, workdir=tmp_path, ledger=somewhere, workspace=FakeWorkspace()).baseline()
    assert somewhere.exists()


def test_a_ledger_written_before_harness_digests_existed_still_loads(tmp_path):
    # Exactly what 0.1.0 wrote. The ledger is append-only and long-lived, so
    # fields added later must not strand the trials already in it.
    path = tmp_path / "old.jsonl"
    path.write_text(
        '{"commit": null, "duration_seconds": 1.0, "incumbent": null, "index": 0, '
        '"metric": 2.0, "note": "baseline", "outcome": "kept", "stdout_tail": ""}\n'
    )
    (trial,) = Ledger(path).trials()
    assert trial.metric == 2.0
    assert trial.harness is None
    assert Ledger(path).best(Goal.MINIMIZE).metric == 2.0


def test_ledger_best_and_summary(tmp_path):
    loop, _ = make_loop(tmp_path, run="echo val=3.0")
    loop.baseline()
    loop.experiment.run = "echo val=2.0"
    loop.run(trials=1)
    loop.experiment.run = "echo val=8.0"
    loop.run(trials=1)

    ledger = Ledger(tmp_path / "l.jsonl")
    best = ledger.best(Goal.MINIMIZE)
    assert best is not None and best.metric == 2.0
    assert ledger.summary()["kept"] == 2
    assert ledger.summary()["reverted"] == 1
    assert ledger.next_index() == 3
