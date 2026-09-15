"""Protected inputs must remain unchanged through measurement, not just proposal."""

from __future__ import annotations

import shlex
import sys

import pytest

from labloop import Experiment, GitWorkspace, Goal, HarnessMismatchError, Loop, Outcome
from labloop.cli import main


def write_command(name: str, content: str) -> str:
    code = f"from pathlib import Path; Path({name!r}).write_text({content!r})"
    return f"{shlex.quote(sys.executable)} -c {shlex.quote(code)}"


def experiment(**kwargs):
    return Experiment(run=f"{shlex.quote(sys.executable)} train.py", metric="val_loss",
                      goal=Goal.MINIMIZE, protect=("eval.py",), sandbox="none", **kwargs)


def test_a_runtime_harness_edit_is_rejected_before_the_metric_is_accepted(project):
    payload = 'from pathlib import Path\nPath("eval.py").write_text("forged\\n")\n'
    payload += 'print("val_loss = 0.01")\n'
    loop = Loop(experiment(propose=write_command("train.py", payload)), workdir=project)
    loop.baseline()

    (trial,) = loop.run(trials=1)

    assert trial.outcome is Outcome.HARNESS_CHANGED
    assert trial.metric is None
    assert "run modified the harness: eval.py" in trial.note
    assert loop.ledger.best(Goal.MINIMIZE).metric == 2
    assert (project / "eval.py").read_text() == "threshold = 0.5\n"
    assert not GitWorkspace(project).is_dirty()


def test_a_confirmation_run_cannot_change_the_harness(project):
    payload = '''from pathlib import Path
counter = Path("__pycache__/confirm-count")
count = int(counter.read_text()) + 1 if counter.exists() else 1
counter.parent.mkdir(exist_ok=True)
counter.write_text(str(count))
if count == 2:
    Path("eval.py").write_text("forged\\n")
print("val_loss = 0.01")
'''
    loop = Loop(experiment(propose=write_command("train.py", payload), confirm=True),
                workdir=project)
    loop.baseline()
    (trial,) = loop.run(trials=1)
    assert trial.outcome is Outcome.HARNESS_CHANGED
    assert trial.metric is None
    assert "confirmation run modified the harness: eval.py" in trial.note
    assert loop.ledger.best(Goal.MINIMIZE).metric == 2
    assert (project / "eval.py").read_text() == "threshold = 0.5\n"


@pytest.mark.parametrize("dirty", [False, True])
def test_a_baseline_harness_edit_is_not_an_incumbent(project, dirty):
    if dirty:
        (project / "notes.txt").write_text("uncommitted user work")
    exp = experiment()
    exp.run = write_command("eval.py", "forged\n") + " && echo 'val_loss = 0.01'"
    loop = Loop(exp, workdir=project)

    trial = loop.baseline()

    assert trial.outcome is Outcome.HARNESS_CHANGED
    assert trial.metric is None
    assert "baseline run modified the harness: eval.py" in trial.note
    assert loop.ledger.best(Goal.MINIMIZE) is None
    if dirty:
        assert (project / "notes.txt").read_text() == "uncommitted user work"
        assert GitWorkspace(project).is_dirty()
    else:
        assert (project / "eval.py").read_text() == "threshold = 0.5\n"
        assert not GitWorkspace(project).is_dirty()


def test_noise_measurements_refuse_a_changed_harness_without_discarding_user_work(project):
    (project / "notes.txt").write_text("uncommitted user work")
    exp = experiment()
    exp.run = write_command("eval.py", "changed during noise\n") + " && echo 'val_loss = 0.01'"
    loop = Loop(exp, workdir=project)
    with pytest.raises(HarnessMismatchError, match="noise run modified the harness: eval.py"):
        loop.measure_noise(repeats=2)
    assert (project / "notes.txt").read_text() == "uncommitted user work"
    assert not loop.ledger.path.exists()


@pytest.mark.parametrize("phase", ["run", "confirmation run", "baseline run", "noise run"])
@pytest.mark.parametrize("mutation", ["overwrite", "delete", "symlink"])
def test_measurement_ledger_tampering_is_restored(project, tmp_path_factory, phase, mutation):
    target = tmp_path_factory.mktemp("ledger-target") / "untouched"
    target.write_text("user data outside the project")
    actions = {
        "overwrite": 'ledger.write_text(ledger.read_text().replace("2.0", "99.0"))',
        "delete": "ledger.unlink()",
        "symlink": f"ledger.unlink(); ledger.symlink_to({str(target)!r})",
    }
    trigger = 2 if phase == "confirmation run" else 1
    payload = f'''from pathlib import Path
counter = Path("__pycache__/ledger-count")
count = int(counter.read_text()) + 1 if counter.exists() else 1
counter.parent.mkdir(exist_ok=True)
counter.write_text(str(count))
if count == {trigger}:
    ledger = Path("labloop.jsonl")
    {actions[mutation]}
print("val_loss = 0.01")
'''
    exp = experiment(propose=write_command("train.py", payload),
                     confirm=phase == "confirmation run")
    loop = Loop(exp, workdir=project)
    loop.baseline()
    trusted = loop.ledger.path.read_bytes()
    if phase in ("baseline run", "noise run"):
        exp.run = f"{shlex.quote(sys.executable)} -c {shlex.quote(payload)}"
    if phase == "noise run":
        with pytest.raises(HarnessMismatchError, match=f"{phase} modified the ledger"):
            loop.measure_noise(repeats=2)
        assert loop.ledger.path.read_bytes() == trusted
    else:
        trial = loop.baseline() if phase == "baseline run" else loop.run(trials=1)[0]
        assert trial.outcome is Outcome.HARNESS_CHANGED
        assert trial.metric is None
        assert f"{phase} modified the ledger" in trial.note
        assert loop.ledger.path.read_bytes().startswith(trusted)
        assert [t.index for t in loop.ledger] == [0, 1]
    assert loop.ledger.best(Goal.MINIMIZE).metric == 2
    assert not loop.ledger.path.is_symlink()
    assert target.read_text() == "user data outside the project"


def test_noise_removes_a_ledger_created_by_the_measurement(project):
    exp = experiment()
    exp.run = write_command("labloop.jsonl", "forged") + " && echo 'val_loss = 0.01'"
    loop = Loop(exp, workdir=project)
    with pytest.raises(HarnessMismatchError, match="noise run modified the ledger"):
        loop.measure_noise(repeats=2)
    assert not loop.ledger.path.exists()


@pytest.mark.parametrize("ending", ["raise RuntimeError('failed')", "import time; time.sleep(3)"])
def test_integrity_checks_take_priority_over_measurement_failure(project, ending):
    payload = 'from pathlib import Path\nPath("eval.py").write_text("forged\\n")\n' + ending
    loop = Loop(experiment(propose=write_command("train.py", payload), budget_seconds=0.5),
                workdir=project)
    loop.baseline()
    (trial,) = loop.run(trials=1)
    assert trial.outcome is Outcome.HARNESS_CHANGED
    assert "run modified the harness" in trial.note
    assert trial.metric is None


def test_measurement_artifacts_outside_the_protected_set_are_allowed(project):
    payload = '''from pathlib import Path
Path("checkpoint.bin").write_bytes(b"weights")
print("val_loss = 1")
'''
    loop = Loop(experiment(propose=write_command("train.py", payload), confirm=True),
                workdir=project)
    loop.baseline()
    (trial,) = loop.run(trials=1)
    assert trial.outcome is Outcome.KEPT
    assert trial.metric == 1
    assert not (project / "checkpoint.bin").exists()
    assert not GitWorkspace(project).is_dirty()


def test_cli_reports_runtime_rejection_and_keeps_the_original_incumbent(project, capsys):
    args = ["--run", f"{shlex.quote(sys.executable)} train.py", "--metric", "val_loss",
            "--protect", "eval.py"]
    assert main(["baseline", *args]) == 0
    capsys.readouterr()
    payload = 'from pathlib import Path\nPath("eval.py").write_text("forged")\n'
    payload += 'print("val_loss = 0.01")\n'
    assert main(["run", *args, "--sandbox", "none",
                 "--propose", write_command("train.py", payload)]) == 0
    out = capsys.readouterr().out
    assert "[H] trial   1" in out
    assert "run modified the harness: eval.py" in out
    assert "best val_loss: 2 (trial 0)" in out
    assert not GitWorkspace(project).is_dirty()


def test_cli_noise_refuses_tampering_without_printing_statistics(project, capsys):
    command = write_command("eval.py", "forged") + " && echo 'val_loss = 0.01'"
    assert main(["noise", "--run", command, "--metric", "val_loss",
                 "--protect", "eval.py", "--repeat", "2"]) == 2
    output = capsys.readouterr()
    assert "noise run modified the harness: eval.py" in output.err
    assert "spread:" not in output.out
    assert not (project / "labloop.jsonl").exists()
