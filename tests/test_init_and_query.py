"""`labloop init` and the ledger query surface.

init writes as little as possible and ends with copy-paste commands; the log
filters make "the trial history as a queryable artifact" a statement about
the tool rather than about jq.
"""

from __future__ import annotations

import json

import pytest

from labloop.cli import main

from .conftest import run_git as git  # noqa: E402


@pytest.fixture
def empty_repo(tmp_path, monkeypatch):
    git("init", "-q", ".", cwd=tmp_path)
    git("config", "user.email", "t@t.test", cwd=tmp_path)
    git("config", "user.name", "t", cwd=tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PYTHONDONTWRITEBYTECODE", "1")
    return tmp_path


def test_init_then_baseline_works_hands_free(empty_repo, capsys):
    # The roadmap's acceptance: an empty git repo, no hand edits.
    assert main(["init"]) == 0
    out = capsys.readouterr().out
    assert ".gitignore" in out
    assert "labloop-example.py" in out

    git("add", "-A", cwd=empty_repo)
    git("commit", "-qm", "labloop setup", cwd=empty_repo)
    assert (
        main(["baseline", "--run", "python labloop-example.py", "--metric", "val_loss"]) == 0
    )
    assert "best val_loss" in capsys.readouterr().out


def test_init_gitignores_the_ledger(empty_repo):
    main(["init"])
    ignored = (empty_repo / ".gitignore").read_text()
    assert "labloop.jsonl" in ignored
    assert "__pycache__/" in ignored


def test_init_is_idempotent_and_respects_existing_entries(empty_repo, capsys):
    (empty_repo / ".gitignore").write_text("labloop.jsonl\n__pycache__/\nmy-stuff/\n")
    main(["init"])
    main(["init"])
    lines = (empty_repo / ".gitignore").read_text().splitlines()
    assert lines.count("labloop.jsonl") == 1, "no duplicate entries however often it runs"
    assert "my-stuff/" in lines, "the user's own entries survive"


def test_init_does_not_shadow_an_existing_experiment(empty_repo, capsys):
    (empty_repo / "train.py").write_text("print('mine')\n")
    main(["init"])
    assert not (empty_repo / "labloop-example.py").exists(), (
        "a repo with Python files gets no stand-in experiment"
    )
    assert "<your command>" in capsys.readouterr().out


def test_init_outside_git_says_what_to_do(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert main(["init"]) == 2
    assert "git init" in capsys.readouterr().err


# --- querying the ledger -----------------------------------------------------


@pytest.fixture
def busy_project(empty_repo, capsys):
    main(["init"])
    git("add", "-A", cwd=empty_repo)
    git("commit", "-qm", "setup", cwd=empty_repo)
    main(["baseline", "--run", "python labloop-example.py", "--metric", "val_loss"])
    main(
        [
            "run",
            "--run",
            "python labloop-example.py",
            "--metric",
            "val_loss",
            "--propose",
            "sed -i 's/LR = 0.5/LR = 0.1/' labloop-example.py",
        ]
    )
    main(
        [
            "run",
            "--run",
            "python labloop-example.py",
            "--metric",
            "val_loss",
            "--propose",
            "sed -i 's/LR = 0.1/LR = 0.4/' labloop-example.py",
        ]
    )
    capsys.readouterr()
    return empty_repo


def test_log_json_is_one_strict_json_object_per_trial(busy_project, capsys):
    assert main(["log", "--json"]) == 0
    lines = capsys.readouterr().out.strip().splitlines()
    parsed = [json.loads(line) for line in lines]
    assert len(parsed) == 3
    assert {p["outcome"] for p in parsed} == {"kept", "reverted"}
    assert all("index" in p and "direction" in p for p in parsed)


def test_log_filters_by_outcome(busy_project, capsys):
    assert main(["log", "--outcome", "reverted", "--json"]) == 0
    (only,) = [json.loads(line) for line in capsys.readouterr().out.strip().splitlines()]
    assert only["outcome"] == "reverted"
    assert only["metric"] == pytest.approx(0.37)


def test_log_filters_by_since_trial(busy_project, capsys):
    assert main(["log", "--since-trial", "2", "--json"]) == 0
    (only,) = [json.loads(line) for line in capsys.readouterr().out.strip().splitlines()]
    assert only["index"] == 2


def test_filters_that_match_nothing_say_so(busy_project, capsys):
    assert main(["log", "--outcome", "timed_out"]) == 0
    assert "no trials match" in capsys.readouterr().out


def test_compare_reports_two_directions_side_by_side(busy_project, capsys):
    main(["branch", "alt", "--from-trial", "1"])
    main(
        [
            "run",
            "--run",
            "python labloop-example.py",
            "--metric",
            "val_loss",
            "--direction",
            "alt",
            "--propose",
            "sed -i 's/LR = .*/LR = 0.05/' labloop-example.py",
        ]
    )
    capsys.readouterr()

    assert main(["log", "--metric", "val_loss", "--compare", "main", "alt"]) == 0
    out = capsys.readouterr().out
    assert "main: val_loss" in out
    assert "alt: val_loss" in out


def test_compare_refuses_an_unknown_direction(busy_project, capsys):
    assert main(["log", "--compare", "main", "imaginary"]) == 2
    assert "imaginary" in capsys.readouterr().err
