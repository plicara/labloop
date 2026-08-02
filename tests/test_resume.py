"""Run manifests, spec-drift refusal, and `labloop resume`.

An overnight run dies. The ledger survives by design, but re-typing the
invocation and hoping it matches is not a recovery strategy: if the metric
name drifted, the trials being compared measure different quantities and
nobody is told. The manifest records the spec that was actually in force,
resume continues under it, and identity drift is refused by name.
"""

from __future__ import annotations

import json

import pytest

from labloop import Experiment, Ledger, UsageError
from labloop.cli import main

from .conftest import make_loop


def manifests(path):
    lines = [json.loads(line) for line in path.read_text().splitlines()]
    return [entry for entry in lines if entry.get("manifest") == 1]


def test_a_run_records_the_spec_it_started_under(tmp_path):
    loop, _ = make_loop(tmp_path, run="echo val=1.0", propose="true")
    loop.run(trials=1)

    (manifest,) = manifests(tmp_path / "l.jsonl")
    assert manifest["run"] == "echo val=1.0"
    assert manifest["metric"] == "val"
    assert manifest["goal"] == "minimize"
    assert manifest["propose"] == "true"


def test_an_unchanged_spec_is_recorded_once_not_per_invocation(tmp_path):
    for _ in range(3):
        loop, _ = make_loop(tmp_path, run="echo val=1.0")
        loop.baseline()
    assert len(manifests(tmp_path / "l.jsonl")) == 1


def test_a_changed_budget_appends_a_new_manifest_without_complaint(tmp_path):
    loop, _ = make_loop(tmp_path, run="echo val=1.0", budget=30.0)
    loop.baseline()
    loop, _ = make_loop(tmp_path, run="echo val=1.0", budget=60.0)
    loop.baseline()
    assert len(manifests(tmp_path / "l.jsonl")) == 2, (
        "budgets change the schedule, not the meaning; both specs are recorded"
    )


def test_manifest_lines_are_invisible_to_the_trial_reader(tmp_path):
    loop, _ = make_loop(tmp_path, run="echo val=1.0", propose="true")
    loop.run(trials=1)

    ledger = Ledger(tmp_path / "l.jsonl")
    assert len(ledger.trials()) == 1
    assert ledger.next_index() == 1
    assert sum(ledger.summary().values()) == 1


def test_changing_the_metric_name_is_refused_by_name(tmp_path):
    loop, _ = make_loop(tmp_path, run="echo val=1.0")
    loop.baseline()

    changed, _ = make_loop(tmp_path, run="echo other=1.0")
    changed.experiment.metric = "other"
    with pytest.raises(UsageError, match="metric"):
        changed.run(trials=1)


def test_changing_the_goal_is_refused_by_name(tmp_path):
    from labloop import Goal

    loop, _ = make_loop(tmp_path, run="echo val=1.0")
    loop.baseline()

    flipped, _ = make_loop(tmp_path, run="echo val=2.0", goal=Goal.MAXIMIZE)
    with pytest.raises(UsageError, match="goal"):
        flipped.run(trials=1)


def test_the_spec_never_carries_the_environment(tmp_path):
    # env is where credentials live, and the ledger is a file that gets
    # shared. A resumed run takes its environment from the shell it runs in.
    exp = Experiment(run="echo val=1", metric="val", env={"API_KEY": "secret"})
    assert "env" not in exp.spec()
    assert "secret" not in json.dumps(exp.spec())


def test_spec_round_trips_through_from_spec(tmp_path):
    original = Experiment(
        run="python eval.py",
        metric="val_err",
        goal="maximize",
        budget_seconds=120.0,
        propose="agent.sh",
        protect=("eval.py", "data"),
        confirm=True,
        min_delta=0.05,
        give_up_after=7,
        propose_budget=600.0,
    )
    restored = Experiment.from_spec(original.spec())
    assert restored.spec() == original.spec()


# --- the resume command, end to end -----------------------------------------


def test_resume_continues_under_the_recorded_spec(project, capsys):
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
    capsys.readouterr()

    # The "crash": the process is gone; nothing is retyped.
    assert main(["resume"]) == 0
    out = capsys.readouterr().out
    assert "trial   2" in out, "resume picks up the numbering where the run stopped"
    assert "best val_loss" in out

    trials = [
        json.loads(line)
        for line in (project / "labloop.jsonl").read_text().splitlines()
        if "outcome" in json.loads(line)
    ]
    assert [t["index"] for t in trials] == [0, 1, 2]
    assert trials[2]["incumbent"] == 1.0, "the incumbent survived the crash"


def test_resume_without_a_manifest_says_what_to_do(project, capsys):
    (project / "labloop.jsonl").write_text(
        '{"commit": null, "duration_seconds": 1.0, "incumbent": null, "index": 0, '
        '"metric": 2.0, "note": "baseline", "outcome": "kept", "stdout_tail": ""}\n'
    )
    assert main(["resume"]) == 2
    assert "no recorded spec" in capsys.readouterr().err


def test_resume_finds_the_last_run_spec_even_after_a_later_baseline(project, capsys):
    # Run trials, re-measure with a baseline, crash. The baseline's manifest
    # is newer, but it is not a run — refusing to resume here would throw
    # away a perfectly good run spec because the user re-measured.
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
    main(["baseline", "--run", "python train.py", "--metric", "val_loss"])
    capsys.readouterr()

    assert main(["resume"]) == 0
    out = capsys.readouterr().out
    assert "trial   3" in out, "resume picks the last spec that can actually run"


def test_resume_of_a_baseline_only_ledger_is_refused(project, capsys):
    main(["baseline", "--run", "python train.py", "--metric", "val_loss"])
    capsys.readouterr()
    assert main(["resume"]) == 2
    assert "nothing to resume" in capsys.readouterr().err


def test_resume_on_an_empty_directory_is_refused(project, capsys):
    assert main(["resume"]) == 2
    assert "no recorded spec" in capsys.readouterr().err
