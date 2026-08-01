"""Loop behaviour, driven through a fake workspace.

These tests use real subprocesses (echo/sleep) but a stub workspace, so they
exercise the keep-or-revert decision without needing a git repo.
"""

from __future__ import annotations

import json

import pytest

from labloop import (
    Experiment,
    Goal,
    HarnessMismatchError,
    Ledger,
    Loop,
    Outcome,
)


class FakeWorkspace:
    def __init__(self, dirty: bool = True) -> None:
        # Dirty by default, standing in for a proposal that edited something.
        # Most tests care about the judging, not the editing.
        self._dirty = dirty
        self.reverts = 0
        self.commits: list[str] = []

    def is_dirty(self) -> bool:
        return self._dirty

    def revert(self) -> None:
        self.reverts += 1

    def commit(self, message: str) -> str:
        self.commits.append(message)
        return f"abc{len(self.commits):04d}"


def make_loop(
    tmp_path,
    run: str,
    propose: str = "true",
    goal=Goal.MINIMIZE,
    budget=30.0,
    protect=(),
    dirty=True,
):
    ws = FakeWorkspace(dirty=dirty)
    exp = Experiment(
        run=run,
        metric="val",
        goal=goal,
        budget_seconds=budget,
        propose=propose,
        protect=protect,
    )
    loop = Loop(exp, workdir=tmp_path, ledger=tmp_path / "l.jsonl", workspace=ws)
    return loop, ws


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


def test_failed_proposal_short_circuits_the_run(tmp_path):
    loop, ws = make_loop(tmp_path, run="echo val=0.001", propose="exit 3")
    (trial,) = loop.run(trials=1)
    assert trial.outcome is Outcome.FAILED
    assert trial.note == "propose command failed"
    assert not ws.commits


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


# --- harness integrity ------------------------------------------------------
#
# A keep-or-revert loop rewards whatever moves the metric, and the propose
# command can reach the evaluator. These cover the detection, not prevention:
# the change still happens, but it is recorded as a changed measurement rather
# than scored as an improvement.


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


# --- feedback to the proposer ----------------------------------------------


def test_the_proposal_is_handed_the_ledger(tmp_path):
    loop, _ = make_loop(tmp_path, run="echo val=5.0")
    loop.baseline()

    seen = tmp_path / "seen.json"
    loop, _ = make_loop(
        tmp_path,
        run="echo val=9.0",
        propose=f'cp "$LABLOOP_BRIEF" {seen}',
    )
    loop.run(trials=1)

    brief = json.loads(seen.read_text())
    assert brief["metric"] == "val"
    assert brief["incumbent"] == 5.0
    assert brief["trial"] == 1
    assert [e["index"] for e in brief["history"]] == [0]


def test_the_proposal_learns_why_the_last_trial_was_reverted(tmp_path):
    loop, _ = make_loop(tmp_path, run="echo val=5.0")
    loop.baseline()
    loop, _ = make_loop(tmp_path, run="echo val=5.0")
    loop.run(trials=1)  # ties, and is reverted

    seen = tmp_path / "seen.json"
    loop, _ = make_loop(tmp_path, run="echo val=1.0", propose=f'cp "$LABLOOP_BRIEF" {seen}')
    loop.run(trials=1)

    brief = json.loads(seen.read_text())
    reverted = next(e for e in brief["history"] if e["outcome"] == "reverted")
    assert "tied" in reverted["why"]


def test_scalars_are_readable_without_parsing_json(tmp_path):
    loop, _ = make_loop(tmp_path, run="echo val=5.0")
    loop.baseline()

    seen = tmp_path / "seen.txt"
    loop, _ = make_loop(
        tmp_path,
        run="echo val=1.0",
        propose=f'echo "$LABLOOP_METRIC $LABLOOP_GOAL $LABLOOP_INCUMBENT" > {seen}',
    )
    loop.run(trials=1)
    assert seen.read_text().split() == ["val", "minimize", "5.0"]


def test_the_brief_does_not_survive_into_the_working_tree(tmp_path):
    before = set(tmp_path.iterdir())
    loop, _ = make_loop(tmp_path, run="echo val=1.0", propose="true")
    loop.run(trials=1)

    new = {p.name for p in tmp_path.iterdir()} - {p.name for p in before}
    assert new == {"l.jsonl"}, (
        "a brief written into the workdir would dirty the tree and be committed"
    )


def test_the_brief_can_be_turned_off(tmp_path):
    seen = tmp_path / "seen.txt"
    exp = Experiment(
        run="echo val=1.0",
        metric="val",
        propose=f'echo "[${{LABLOOP_BRIEF:-unset}}]" > {seen}',
        brief=False,
    )
    loop = Loop(exp, workdir=tmp_path, ledger=tmp_path / "l.jsonl", workspace=FakeWorkspace())
    loop.run(trials=1)
    assert seen.read_text().strip() == "[unset]"
