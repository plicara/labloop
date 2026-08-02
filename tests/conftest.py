"""Shared fixtures for the loop tests.

The loop is driven through a stub workspace so its decisions can be exercised
without a git repository. Real git is covered in test_workspace.py, and the
command line end to end in test_cli.py.
"""

from __future__ import annotations

import subprocess

import pytest

from labloop import Experiment, Goal, Loop


def run_git(*args, cwd):
    """git, checked, captured — the form every test wants."""
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout


@pytest.fixture
def project(tmp_path, monkeypatch):
    """A committed git repo whose experiment prints val_loss, as cwd.

    One fixture instead of a copy per test file: four hand-rolled variants
    of the same repo is how one of them ends up subtly different.
    """
    (tmp_path / "train.py").write_text('print("val_loss = 2.0")\n')
    (tmp_path / "eval.py").write_text("threshold = 0.5\n")
    (tmp_path / ".gitignore").write_text("labloop.jsonl\n__pycache__/\n")
    run_git("init", "-q", ".", cwd=tmp_path)
    run_git("config", "user.email", "t@t.test", cwd=tmp_path)
    run_git("config", "user.name", "t", cwd=tmp_path)
    run_git("add", "-A", cwd=tmp_path)
    run_git("commit", "-qm", "init", cwd=tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PYTHONDONTWRITEBYTECODE", "1")
    return tmp_path


class FakeWorkspace:
    def __init__(self, dirty: bool = True) -> None:
        # Dirty by default, standing in for a proposal that edited something.
        # Most tests care about the judging, not the editing.
        self._dirty = dirty
        self._just_committed = False
        self.reverts = 0
        self.commits: list[str] = []
        self.committed_paths: list[list[str] | None] = []

    def is_dirty(self) -> bool:
        # Immediately after a commit the tree matches HEAD (this fake has no
        # artifacts), but the next trial's proposal dirties it again. The
        # loop checks exactly once between the two, so one clean answer per
        # commit models git faithfully.
        if self._just_committed:
            self._just_committed = False
            return False
        return self._dirty

    def changed_paths(self) -> list[str]:
        return ["train.py"] if self._dirty else []

    def revert(self) -> None:
        self.reverts += 1

    def commit(self, message: str, paths=None) -> str:
        self.commits.append(message)
        self.committed_paths.append(list(paths) if paths is not None else None)
        self._just_committed = True
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
    """A loop over `tmp_path` with a stub workspace, plus that stub."""
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
