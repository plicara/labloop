"""Paired measurement: judge a candidate against its incumbent measured now.

Found by dogfooding: the ledger's incumbent was measured up to an hour before
the candidate it judged, and slow drift on the machine turned into credited
gains four times the size an interleaved check found.
"""

from __future__ import annotations

import json
import sys

import pytest

from labloop import Experiment, Loop, Outcome, Trial
from labloop.brief import build
from labloop.cli import _summarize, main

from .conftest import make_loop, replace_text
from .conftest import run_git as git


def test_a_trial_is_judged_against_its_remeasured_incumbent_when_there_is_one():
    plain = Trial(index=1, outcome=Outcome.REVERTED, metric=2.0, incumbent=1.0,
                  duration_seconds=1.0)
    paired = Trial(index=1, outcome=Outcome.REVERTED, metric=2.0, incumbent=1.0,
                   duration_seconds=1.0, remeasured=1.7)
    assert plain.bar == 1.0
    assert paired.bar == 1.7


def test_remeasured_survives_the_ledger_round_trip():
    trial = Trial(index=1, outcome=Outcome.KEPT, metric=1.5, incumbent=2.0,
                  duration_seconds=1.0, remeasured=1.8)
    restored = Trial.from_dict(trial.to_dict())
    assert restored == trial
    assert "bar" not in trial.to_dict(), "derived, so not stored"


def test_the_confirmation_and_estimate_references_survive_the_ledger_round_trip():
    trial = Trial(index=1, outcome=Outcome.KEPT, metric=1.5, incumbent=2.0,
                  duration_seconds=1.0, remeasured=1.8, confirmation=1.6,
                  confirmation_reference=1.9, estimate_reference=1.7)
    assert Trial.from_dict(trial.to_dict()) == trial
    assert trial.bar == 1.7, "the metric is judged against the reference it was paired with"


def test_paired_is_off_by_default_and_recorded_in_the_manifest():
    assert Experiment(run="x", metric="m").paired is False
    spec = Experiment(run="x", metric="m", paired=True).spec()
    assert spec["paired"] is True
    assert Experiment.from_spec(spec).paired is True


# --- the loop ----------------------------------------------------------------


def sequence(tmp_path, *values):
    """A run command printing `values` in order, one per run; "fail" exits 1.

    Stands in for a machine whose speed moves between runs: the same tree
    measures differently depending on when it is measured.
    """
    script = tmp_path / "measure.py"
    counter = tmp_path / "runs"
    script.write_text(
        "import pathlib, sys\n"
        f"p = pathlib.Path({str(counter)!r})\n"
        "n = int(p.read_text()) if p.exists() else 0\n"
        "p.write_text(str(n + 1))\n"
        f"values = {list(values)!r}\n"
        "v = values[min(n, len(values) - 1)]\n"
        "if v == 'fail':\n"
        "    sys.exit(1)\n"
        "print(f'val={v}')\n"
    )
    return f"{sys.executable} {script}", counter


def paired_loop(tmp_path, *values, **kw):
    run, counter = sequence(tmp_path, *values)
    loop, ws = make_loop(tmp_path, run=run, **kw)
    loop.experiment.paired = True
    return loop, ws, counter


def test_a_slower_machine_does_not_block_a_real_gain(tmp_path):
    # Recorded 1.0; the machine has since slowed so the incumbent measures 2.0.
    # A candidate at 1.8 is a real 10% gain that the stale 1.0 would reject.
    loop, _, _ = paired_loop(tmp_path, 1.0, 2.0, 1.8)
    loop.baseline()
    (trial,) = loop.run(trials=1)
    assert trial.outcome is Outcome.KEPT
    assert (trial.incumbent, trial.remeasured, trial.metric) == (1.0, 2.0, 1.8)


def test_a_faster_machine_does_not_manufacture_a_gain(tmp_path):
    # Recorded 2.0; the machine sped up so the incumbent measures 1.0. A
    # candidate at 1.5 only looks better than the stale number.
    loop, _, _ = paired_loop(tmp_path, 2.0, 1.0, 1.5)
    loop.baseline()
    (trial,) = loop.run(trials=1)
    assert trial.outcome is Outcome.REVERTED
    assert trial.remeasured == 1.0
    assert trial.note == "did not beat 1"


def test_without_an_incumbent_nothing_is_remeasured(tmp_path):
    loop, _, counter = paired_loop(tmp_path, 1.0)
    (trial,) = loop.run(trials=1)
    assert trial.outcome is Outcome.KEPT
    assert trial.remeasured is None
    assert counter.read_text() == "1", "one run: the candidate's"


def test_a_broken_incumbent_fails_the_trial_before_any_proposal(tmp_path):
    marker = tmp_path / "proposed"
    loop, ws, _ = paired_loop(tmp_path, 1.0, "fail", propose=f"touch {marker}")
    loop.baseline()
    (trial,) = loop.run(trials=1)
    assert trial.outcome is Outcome.FAILED
    assert "re-measured" in trial.note
    assert trial.remeasured is None
    assert not marker.exists(), "no proposal is spent on an unmeasurable incumbent"


def test_tampering_during_the_incumbent_run_is_caught_and_named(tmp_path):
    (tmp_path / "eval.py").write_text("threshold = 0.5\n")
    script = tmp_path / "measure.sh"
    script.write_text(
        "#!/bin/sh\n"
        "if [ -f seen ]; then echo 'threshold = 0.1' > eval.py; else touch seen; fi\n"
        "echo val=1.0\n"
    )
    script.chmod(0o755)
    loop, _ = make_loop(tmp_path, run=str(script), protect=("eval.py",))
    loop.experiment.paired = True
    loop.baseline()
    (trial,) = loop.run(trials=1)
    assert trial.outcome is Outcome.HARNESS_CHANGED
    assert "incumbent run modified the harness: eval.py" in trial.note


def test_confirmation_is_judged_against_the_remeasured_incumbent(tmp_path):
    # Recorded 1.0, incumbent now 2.0; the candidate wins at 1.8, then 1.9.
    loop, _, _ = paired_loop(tmp_path, 1.0, 2.0, 1.8, 1.9)
    loop.experiment.confirm = True
    loop.baseline()
    (trial,) = loop.run(trials=1)
    assert trial.outcome is Outcome.KEPT
    assert trial.metric == 1.9, "the incumbent advances to the weaker measurement"
    assert trial.confirmation == 1.9


def test_the_remeasurements_artifacts_never_reach_the_proposal(project):
    # Real git: the run writes a cache, and the proposal edits train.py. The
    # cache left by the incumbent run must not be committed or summarized.
    (project / "train.py").write_text(
        "import pathlib\npathlib.Path('cache.bin').write_text('x')\nprint('val_loss = 2.0')\n"
    )
    git("add", "-A", cwd=project)
    git("commit", "-qm", "cache", cwd=project)
    loop = Loop(
        Experiment(run="python train.py", metric="val_loss", paired=True,
                   propose=replace_text("train.py", "2.0", "1.0")),
        workdir=project,
    )
    loop.baseline()
    (trial,) = loop.run(trials=1)
    assert trial.outcome is Outcome.KEPT
    assert trial.remeasured == 2.0
    assert [entry["path"] for entry in trial.change] == ["train.py"]
    committed = git("show", "--name-only", "--format=", "HEAD", cwd=project).split()
    assert "cache.bin" not in committed


# --- what people and proposers are told ------------------------------------


def test_the_brief_explains_a_verdict_against_the_number_it_was_reached_on():
    trial = Trial(index=3, outcome=Outcome.REVERTED, metric=1.5, incumbent=2.0,
                  duration_seconds=1.0, remeasured=1.0)
    (entry,) = build(Experiment(run="x", metric="val", propose="a"), [trial],
                     index=4, incumbent=1.0)["history"]
    assert entry["why"] == "reverted: val 1.5 did not beat 1; lower is better"


def test_a_paired_proposer_is_told_the_remeasured_number_to_beat(tmp_path):
    seen = tmp_path / "brief.json"
    loop, _, _ = paired_loop(tmp_path, 1.0, 2.0, 1.8,
                             propose=f"cp \"$LABLOOP_BRIEF\" {seen}")
    loop.baseline()
    loop.run(trials=1)
    assert json.loads(seen.read_text())["incumbent"] == 2.0


def test_the_commit_names_the_number_it_beat(tmp_path):
    loop, ws, _ = paired_loop(tmp_path, 1.0, 2.0, 1.8)
    loop.baseline()
    loop.run(trials=1)
    assert ws.commits[-1] == "labloop: val 1.8 (was 2)"


# --- the command line --------------------------------------------------------


def test_paired_from_the_command_line_survives_resume(project, capsys):
    main(["baseline", "--run", "python train.py", "--metric", "val_loss"])
    main(["run", "--run", "python train.py", "--metric", "val_loss", "--paired",
          "--propose", replace_text("train.py", "2.0", "1.5"), "--trials", "1"])
    out = capsys.readouterr().out
    assert "vs 2 now" in out, "the line shows what the trial was judged against"

    main(["resume", "--trials", "1"])
    trials = [json.loads(line) for line in (project / "labloop.jsonl").read_text().splitlines()
              if '"outcome"' in line]
    assert trials[-1]["remeasured"] == 1.5, "resume kept pairing: the incumbent was re-measured"


def test_a_paired_run_ends_on_its_latest_keep_not_a_stale_best(tmp_path, capsys):
    # Recorded 1.0 on a fast machine; it slowed, and 1.8 beat the incumbent's 2.0.
    loop, _, _ = paired_loop(tmp_path, 1.0, 2.0, 1.8)
    loop.baseline()
    loop.run(trials=1)
    _summarize(loop)
    assert capsys.readouterr().out.strip() == "latest kept val: 1.8 (trial 1)"


# --- a confirmation on a fresh pair ------------------------------------------


def two_trees(project, tmp_path_factory, incumbent, candidate, tamper_on=None):
    """An experiment on real git printing scripted draws for each tree.

    The proposal adds `candidate.txt`; a run that sees it draws from
    `candidate`, otherwise from `incumbent`. Counters live outside the tree.
    `tamper_on=n` makes the n-th incumbent draw rewrite the protected eval.py.
    """
    state = tmp_path_factory.mktemp("draws")
    script = state / "measure.py"
    script.write_text(
        "import pathlib, sys\n"
        "tree = 'candidate' if pathlib.Path('candidate.txt').exists() else 'incumbent'\n"
        f"counter = pathlib.Path({str(state)!r}) / tree\n"
        "n = int(counter.read_text()) if counter.exists() else 0\n"
        "counter.write_text(str(n + 1))\n"
        f"draws = {{'incumbent': {list(incumbent)!r}, 'candidate': {list(candidate)!r}}}[tree]\n"
        f"if tree == 'incumbent' and n == {tamper_on!r}:\n"
        "    pathlib.Path('eval.py').write_text('threshold = 0.1\\n')\n"
        "v = draws[min(n, len(draws) - 1)]\n"
        "if v == 'fail':\n"
        "    sys.exit(1)\n"
        "print(f'val_loss = {v}')\n"
    )
    loop = Loop(
        Experiment(run=f"{sys.executable} {script}", metric="val_loss", paired=True,
                   confirm=True, protect=("eval.py",), propose="echo c > candidate.txt"),
        workdir=project,
    )
    loop.baseline()
    return loop


def stash_list(project):
    return git("stash", "list", cwd=project)


def test_an_unlucky_incumbent_draw_no_longer_carries_the_confirmation(
    project, tmp_path_factory
):
    # The run-3 failure: the incumbent draws slow (3.0), the candidate's 2.0
    # wins on it, and reusing that draw would confirm 2.0 too. A fresh
    # incumbent measurement (2.0) shows there is no gain.
    loop = two_trees(project, tmp_path_factory, incumbent=[2.0, 3.0, 2.0],
                     candidate=[2.0, 2.0])
    (trial,) = loop.run(trials=1)
    assert trial.outcome is Outcome.REVERTED
    assert (trial.remeasured, trial.confirmation, trial.confirmation_reference) == (3.0, 2.0, 2.0)
    assert "fresh pair" in trial.note
    assert not (project / "candidate.txt").exists()
    assert stash_list(project) == ""


def test_a_gain_won_twice_is_kept_and_estimated_on_a_third_pair(project, tmp_path_factory):
    loop = two_trees(project, tmp_path_factory, incumbent=[2.0, 2.0, 2.1, 2.2],
                     candidate=[1.0, 1.5, 1.6])
    (trial,) = loop.run(trials=1)
    assert trial.outcome is Outcome.KEPT
    assert (trial.remeasured, trial.confirmation, trial.confirmation_reference) == (2.0, 1.5, 2.1)
    assert (trial.metric, trial.estimate_reference) == (1.6, 2.2), "the third pair"
    assert trial.bar == 2.2
    assert "gain estimated on a third pair: 1.6 vs 2.2" in trial.note
    assert git("log", "-1", "--format=%s", cwd=project).strip() == (
        "labloop: val_loss 1.6 (was 2.2)"
    )
    assert "candidate.txt" in git("show", "--name-only", "--format=", "HEAD", cwd=project)
    assert stash_list(project) == ""


def test_an_incumbent_that_fails_its_second_measurement_fails_the_trial_cleanly(
    project, tmp_path_factory
):
    loop = two_trees(project, tmp_path_factory, incumbent=[2.0, 2.0, "fail"],
                     candidate=[1.0, 1.0])
    (trial,) = loop.run(trials=1)
    assert trial.outcome is Outcome.FAILED
    assert "incumbent confirmation run: the incumbent gave no usable val_loss" in trial.note
    assert not (project / "candidate.txt").exists()
    assert git("status", "--porcelain", cwd=project) == ""
    assert stash_list(project) == ""


def test_tampering_during_the_incumbent_confirmation_run_is_caught(project, tmp_path_factory):
    loop = two_trees(project, tmp_path_factory, incumbent=[2.0, 2.0, 2.0],
                     candidate=[1.0, 1.0], tamper_on=2)
    (trial,) = loop.run(trials=1)
    assert trial.outcome is Outcome.HARNESS_CHANGED
    assert "incumbent confirmation run modified the harness: eval.py" in trial.note
    assert git("status", "--porcelain", cwd=project) == ""
    assert stash_list(project) == ""


def test_a_users_own_stash_survives_paired_confirmations(project, tmp_path_factory):
    (project / "eval.py").write_text("threshold = 0.7\n")
    git("stash", "push", "-qm", "my work", cwd=project)
    loop = two_trees(project, tmp_path_factory, incumbent=[2.0, 2.0, 2.1, 2.0, 2.0],
                     candidate=[1.0, 1.5, 3.0])
    loop.run(trials=2)
    listed = stash_list(project)
    assert listed.count("\n") == 1 and "my work" in listed


def test_the_estimate_does_not_reopen_the_verdict(project, tmp_path_factory):
    # Won twice, then the third pair shows no gain. The third pair measures the
    # kept change; letting it veto would make it one more lucky-survivor test.
    loop = two_trees(project, tmp_path_factory, incumbent=[2.0, 2.0, 2.0, 2.0],
                     candidate=[1.0, 1.0, 2.3])
    (trial,) = loop.run(trials=1)
    assert trial.outcome is Outcome.KEPT
    assert trial.bar - trial.metric == pytest.approx(-0.3), "an honest, unflattering estimate"


def test_a_candidate_that_fails_its_estimate_run_is_not_kept(project, tmp_path_factory):
    loop = two_trees(project, tmp_path_factory, incumbent=[2.0, 2.0, 2.0],
                     candidate=[1.0, 1.0, "fail"])
    (trial,) = loop.run(trials=1)
    assert trial.outcome is Outcome.FAILED
    assert "estimate run" in trial.note
    assert git("status", "--porcelain", cwd=project) == ""
    assert stash_list(project) == ""


def test_tampering_during_the_incumbent_estimate_run_is_caught(project, tmp_path_factory):
    loop = two_trees(project, tmp_path_factory, incumbent=[2.0, 2.0, 2.0, 2.0],
                     candidate=[1.0, 1.0, 1.0], tamper_on=3)
    (trial,) = loop.run(trials=1)
    assert trial.outcome is Outcome.HARNESS_CHANGED
    assert "incumbent estimate run modified the harness: eval.py" in trial.note
    assert git("status", "--porcelain", cwd=project) == ""
    assert stash_list(project) == ""
