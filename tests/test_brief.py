"""What the proposer is told before its next attempt."""

from __future__ import annotations

import json

from labloop import Experiment, Goal, Loop, Outcome, Trial
from labloop.brief import build, environment

from .conftest import FakeWorkspace, make_loop


def experiment(**kw):
    base = dict(run="python train.py", metric="val_loss", propose="agent")
    return Experiment(**{**base, **kw})


def trial(index, outcome, metric=None, incumbent=None, **kw):
    return Trial(
        index=index,
        outcome=outcome,
        metric=metric,
        incumbent=incumbent,
        duration_seconds=1.0,
        **kw,
    )


def why(brief, index):
    return next(e["why"] for e in brief["history"] if e["index"] == index)


def test_brief_states_what_is_being_optimized(tmp_path):
    brief = build(experiment(goal=Goal.MAXIMIZE), [], index=0, incumbent=None)
    assert brief["metric"] == "val_loss"
    assert brief["goal"] == "maximize"
    assert brief["incumbent"] is None
    assert brief["history"] == []


def test_a_tie_is_explained_as_a_tie_not_just_reverted():
    history = [trial(1, Outcome.REVERTED, metric=2.0, incumbent=2.0)]
    brief = build(experiment(), history, index=2, incumbent=2.0)
    assert "tied" in why(brief, 1), (
        "the proposer cannot tell a tie from a regression by the outcome alone"
    )


def test_a_regression_names_the_number_it_had_to_beat():
    history = [trial(1, Outcome.REVERTED, metric=2.5, incumbent=2.0)]
    brief = build(experiment(), history, index=2, incumbent=2.0)
    assert why(brief, 1) == "reverted: val_loss 2.5 did not beat 2; lower is better"


def test_the_direction_follows_the_goal():
    history = [trial(1, Outcome.REVERTED, metric=0.4, incumbent=0.9)]
    brief = build(experiment(goal=Goal.MAXIMIZE), history, index=2, incumbent=0.9)
    assert "higher is better" in why(brief, 1)


def test_a_missing_metric_says_how_to_print_it():
    history = [trial(1, Outcome.NO_METRIC, stdout_tail="training complete\n")]
    brief = build(experiment(), history, index=2, incumbent=None)
    assert "val_loss=<number>" in why(brief, 1)


def test_a_timeout_names_the_budget():
    history = [trial(1, Outcome.TIMED_OUT)]
    brief = build(experiment(budget_seconds=30), history, index=2, incumbent=None)
    assert "30s budget" in why(brief, 1)


def test_a_harness_change_says_what_to_do_instead():
    history = [trial(1, Outcome.HARNESS_CHANGED, note="proposal modified the harness")]
    brief = build(experiment(protect=("eval.py",)), history, index=2, incumbent=None)
    assert "must not be edited" in why(brief, 1)
    assert brief["protected"] == ["eval.py"]


def test_failures_carry_their_output_but_scored_trials_do_not():
    history = [
        trial(1, Outcome.FAILED, stdout_tail="ImportError: no module named torch"),
        trial(2, Outcome.REVERTED, metric=3.0, incumbent=2.0, stdout_tail="val_loss=3.0"),
    ]
    brief = build(experiment(), history, index=3, incumbent=2.0)
    entries = {e["index"]: e for e in brief["history"]}
    assert "ImportError" in entries[1]["output_tail"]
    assert "output_tail" not in entries[2], "a trial that produced a number explains itself"


def test_history_is_bounded():
    history = [trial(i, Outcome.REVERTED, metric=1.0, incumbent=0.5) for i in range(50)]
    brief = build(experiment(), history, index=50, incumbent=0.5, recent=5)
    assert len(brief["history"]) == 5
    assert [e["index"] for e in brief["history"]] == [45, 46, 47, 48, 49]
    assert brief["counts"]["reverted"] == 50, "counts cover everything, not just the window"


def test_environment_exposes_the_essentials_without_a_json_parser():
    brief = build(experiment(), [], index=4, incumbent=2.25)
    env = environment("/tmp/b.json", brief)
    assert env["LABLOOP_BRIEF"] == "/tmp/b.json"
    assert env["LABLOOP_TRIAL"] == "4"
    assert env["LABLOOP_METRIC"] == "val_loss"
    assert env["LABLOOP_INCUMBENT"] == "2.25"


def test_no_incumbent_is_an_empty_string_not_a_missing_variable():
    brief = build(experiment(), [], index=0, incumbent=None)
    assert environment("/tmp/b.json", brief)["LABLOOP_INCUMBENT"] == ""


def test_brief_is_json_serializable():
    history = [
        trial(0, Outcome.KEPT, metric=2.0, commit="abc1234"),
        trial(1, Outcome.FAILED, stdout_tail="boom"),
    ]
    brief = build(experiment(), history, index=2, incumbent=2.0)
    assert json.loads(json.dumps(brief)) == brief


# --- reaching the proposal command ------------------------------------------


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
