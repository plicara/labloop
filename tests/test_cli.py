"""The command line, exercised the way a user meets it.

These run the real `main` against real subprocesses in a real git repository.
The CLI is the only part most people ever touch, and its job — exit codes,
diagnosis on failure, the shape of a line — is not covered by testing the loop
underneath it.
"""

from __future__ import annotations

import json
import subprocess

import pytest

from labloop.cli import main


def git(*args, cwd):
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout


@pytest.fixture
def project(tmp_path, monkeypatch):
    """A committed git repo whose experiment prints a metric."""
    (tmp_path / "train.py").write_text('print("val_loss = 2.0")\n')
    (tmp_path / "eval.py").write_text("threshold = 0.5\n")
    (tmp_path / ".gitignore").write_text("labloop.jsonl\n__pycache__/\n")
    git("init", "-q", ".", cwd=tmp_path)
    git("config", "user.email", "t@t.test", cwd=tmp_path)
    git("config", "user.name", "t", cwd=tmp_path)
    git("add", "-A", cwd=tmp_path)
    git("commit", "-qm", "init", cwd=tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PYTHONDONTWRITEBYTECODE", "1")
    return tmp_path


def ledger(project):
    return [json.loads(line) for line in (project / "labloop.jsonl").read_text().splitlines()]


def test_baseline_records_and_reports(project, capsys):
    assert main(["baseline", "--run", "python train.py", "--metric", "val_loss"]) == 0
    out = capsys.readouterr().out
    assert "[+] trial   0" in out
    assert "best val_loss: 2 (trial 0)" in out
    assert ledger(project)[0]["metric"] == 2.0


def test_a_kept_trial_shows_its_commit(project, capsys):
    main(["baseline", "--run", "python train.py", "--metric", "val_loss"])
    code = main(
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
    assert code == 0
    assert "[+] trial   1" in capsys.readouterr().out


def test_a_dirty_tree_is_refused_with_exit_2(project, capsys):
    (project / "train.py").write_text('print("val_loss = 9.9")\n')
    code = main(
        ["run", "--run", "python train.py", "--metric", "val_loss", "--propose", "true"]
    )
    assert code == 2
    assert "uncommitted changes" in capsys.readouterr().err


def test_a_failing_run_shows_the_reason_not_just_the_verdict(project, capsys):
    # The whole point: a mistyped command otherwise repeats one unhelpful line
    # per trial, with the actual error only in the ledger.
    main(["baseline", "--run", "python train.py", "--metric", "val_loss"])
    main(
        [
            "run",
            "--run",
            "python train.py",
            "--metric",
            "val_loss",
            "--propose",
            "python no_such_agent.py",
        ]
    )
    out = capsys.readouterr().out
    assert "[!]" in out
    # The line is elided in the middle when long, so both ends survive: the
    # file it could not open, and why.
    assert "agent.py" in out and "No such file or directory" in out, (
        "the diagnosis must reach the terminal, not only the ledger"
    )


def test_the_wrong_metric_name_shows_what_was_printed(project, capsys):
    main(
        [
            "run",
            "--run",
            "python train.py",
            "--metric",
            "accuracy",
            "--propose",
            "date > note.txt",
        ]
    )
    out = capsys.readouterr().out
    assert "[?]" in out
    assert "val_loss = 2.0" in out


def test_protect_typo_is_refused_rather_than_silently_ignored(project, capsys):
    code = main(
        ["baseline", "--run", "python train.py", "--metric", "val_loss", "--protect", "evla.py"]
    )
    assert code == 2
    assert "matched no files" in capsys.readouterr().err


def test_editing_a_protected_file_is_marked_and_named(project, capsys):
    code = main(
        [
            "run",
            "--run",
            "python train.py",
            "--metric",
            "val_loss",
            "--protect",
            "eval.py",
            "--propose",
            "echo cheat > eval.py",
        ]
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "[H]" in out and "eval.py" in out
    assert (project / "eval.py").read_text() == "threshold = 0.5\n", "and it was reverted"


def test_a_proposal_that_adds_a_new_module_is_committed_whole(project, capsys):
    # Agents write new files, not only edits. An untracked file has to count
    # as a change and reach the commit.
    main(["baseline", "--run", "python train.py", "--metric", "val_loss"])
    code = main(
        [
            "run",
            "--run",
            "python train.py",
            "--metric",
            "val_loss",
            "--propose",
            "echo 'print(\"val_loss = 1.0\")' > train.py && echo 'helper = 1' > helper.py",
        ]
    )
    assert code == 0
    assert "[+] trial   1" in capsys.readouterr().out
    tracked = git("ls-files", cwd=project)
    assert "helper.py" in tracked


def test_run_artifacts_are_not_committed_and_do_not_linger(project, capsys):
    # The nanogpt case: the experiment writes a checkpoint every trial. The
    # commit must record the change and the decision log, not the artifact —
    # and the artifact must not survive to dirty the next trial either.
    (project / "train.py").write_text(
        'open("checkpoint.bin", "wb").write(b"\\0" * 100_000)\nprint("val_loss = 1.0")\n'
    )
    git("commit", "-aqm", "writes a checkpoint", cwd=project)

    main(["baseline", "--run", "python train.py", "--metric", "val_loss"])
    code = main(
        [
            "run",
            "--run",
            "python train.py",
            "--metric",
            "val_loss",
            "--propose",
            r"sed -i 's/= 1\.0/= 0.5/' train.py",
        ]
    )
    assert code == 0
    assert "[+] trial   1" in capsys.readouterr().out

    tracked = git("ls-files", cwd=project)
    assert "checkpoint.bin" not in tracked, "artifacts must not enter the history"
    assert "labloop-history.jsonl" in tracked, "the decision log must"
    assert not (project / "checkpoint.bin").exists(), "and must not dirty the next trial"
    assert git("status", "--porcelain", cwd=project).strip() == ""


def test_the_decision_log_respects_a_gitignore_that_covers_it(project, capsys):
    # A user who gitignored labloop* has said what they want. The log is
    # still written locally, just not forced into the commit.
    (project / ".gitignore").write_text("labloop*.jsonl\n__pycache__/\n")
    git("commit", "-aqm", "ignore labloop files", cwd=project)

    main(["baseline", "--run", "python train.py", "--metric", "val_loss"])
    code = main(
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
    assert code == 0
    assert "[+] trial   1" in capsys.readouterr().out
    assert "labloop-history.jsonl" not in git("ls-files", cwd=project)
    assert (project / "labloop-history.jsonl").exists()


def test_noise_reports_a_spread_without_writing_a_ledger(project, capsys):
    code = main(["noise", "--run", "python train.py", "--metric", "val_loss", "--repeat", "3"])
    assert code == 0
    out = capsys.readouterr().out
    assert "spread: none" in out, "a deterministic experiment has no spread"
    assert not (project / "labloop.jsonl").exists()


def test_noise_on_a_varying_metric_recommends_the_settings(project, capsys):
    (project / "train.py").write_text(
        "import random\nprint(f'val_loss = {random.random():.4f}')\n"
    )
    git("commit", "-aqm", "noisy", cwd=project)
    main(["noise", "--run", "python train.py", "--metric", "val_loss", "--repeat", "4"])
    out = capsys.readouterr().out
    assert "--min-delta" in out and "--confirm" in out
    assert "standard deviation" in out, (
        "the range widens with every extra run; the deviation is what compares"
    )


def test_noise_on_a_broken_experiment_says_so(project, capsys):
    with pytest.raises(RuntimeError, match="usable val_loss"):
        main(["noise", "--run", "exit 1", "--metric", "val_loss"])


def test_log_replays_the_ledger_and_counts_outcomes(project, capsys):
    main(["baseline", "--run", "python train.py", "--metric", "val_loss"])
    main(
        [
            "run",
            "--run",
            "python train.py",
            "--metric",
            "val_loss",
            "--propose",
            "date > note.txt",
        ]
    )
    capsys.readouterr()

    assert main(["log", "--metric", "val_loss"]) == 0
    out = capsys.readouterr().out
    assert "kept=1" in out and "reverted=1" in out
    assert "val_loss: 2 (trial 0)" in out


def test_log_on_an_empty_ledger_says_so(project, capsys):
    assert main(["log"]) == 0
    assert "no trials recorded" in capsys.readouterr().out


def test_a_long_diagnosis_keeps_both_ends(project, capsys):
    main(["baseline", "--run", "python train.py", "--metric", "val_loss"])
    filler = "x" * 400
    main(
        [
            "run",
            "--run",
            "python train.py",
            "--metric",
            "val_loss",
            "--propose",
            f"echo 'START {filler} END' && exit 1",
        ]
    )
    line = next(ln for ln in capsys.readouterr().out.splitlines() if "START" in ln)
    assert "START" in line and "END" in line
    assert "…" in line and len(line) < 200


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        (["--workdir", "/no/such/dir"], "not a directory"),
        (["--budget", "0"], "must be positive"),
        (["--min-delta", "-1"], "must not be negative"),
        (["--protect", "/etc/hostname"], "must be relative"),
        (["--protect", "../outside.txt"], "points outside"),
        (["--protect", "typo.py"], "matched no files"),
    ],
)
def test_bad_input_is_a_message_not_a_traceback(project, capsys, argv, expected):
    # A user's first typo should not look like the tool breaking.
    code = main(["baseline", "--run", "python train.py", "--metric", "val_loss", *argv])
    assert code == 2
    assert expected in capsys.readouterr().err


def test_a_bug_is_not_disguised_as_bad_input(project, monkeypatch):
    # UsageError is caught so bad input reads as bad input. A ValueError from
    # anywhere else is a defect and has to keep surfacing as one.
    import labloop.cli as cli_module

    def boom(*args, **kwargs):
        raise ValueError("something internal went wrong")

    monkeypatch.setattr(cli_module.Loop, "baseline", boom)
    with pytest.raises(ValueError, match="something internal"):
        main(["baseline", "--run", "python train.py", "--metric", "val_loss"])


def test_a_non_positive_trial_count_is_refused(project):
    with pytest.raises(SystemExit) as exit_info:
        main(["run", "--run", "x", "--metric", "m", "--propose", "true", "--trials", "0"])
    assert exit_info.value.code == 2


def test_two_concurrent_runs_produce_one_winner_and_one_refusal(project):
    # The roadmap's acceptance test for locking: launch two real labloop
    # processes against one ledger; one must win, one must be refused with
    # exit 2, and the ledger must hold no interleaved indices.
    import os
    import sys

    command = [
        sys.executable,
        "-m",
        "labloop.cli",
        "run",
        "--run",
        "sleep 0.4; python train.py",
        "--metric",
        "val_loss",
        "--propose",
        "date > note.txt",
        "--trials",
        "2",
    ]
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}

    def launch():
        return subprocess.Popen(
            command,
            cwd=project,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

    first, second = launch(), launch()
    _, err_first = first.communicate(timeout=60)
    _, err_second = second.communicate(timeout=60)

    codes = sorted([first.returncode, second.returncode])
    assert codes == [0, 2], f"expected one winner and one refusal, got {codes}"
    loser_err = err_first if first.returncode == 2 else err_second
    assert "another labloop run" in loser_err

    indices = [entry["index"] for entry in ledger(project)]
    assert indices == list(range(len(indices))), (
        f"interleaved or duplicated trial indices: {indices}"
    )


def test_version_is_reported(capsys):
    with pytest.raises(SystemExit) as exit_info:
        main(["--version"])
    assert exit_info.value.code == 0
    assert "labloop" in capsys.readouterr().out


def test_a_missing_subcommand_is_an_error(capsys):
    with pytest.raises(SystemExit) as exit_info:
        main([])
    assert exit_info.value.code == 2
