"""GitWorkspace against a real repository.

The loop is tested through a stub so its decisions can be exercised without
git. That leaves the three git operations the whole design rests on — is it
dirty, throw it away, record it — checked by nothing.
"""

from __future__ import annotations

import subprocess

import pytest

from labloop import DirtyTreeError, GitWorkspace


def git(*args, cwd):
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout


@pytest.fixture
def repo(tmp_path):
    (tmp_path / "train.py").write_text("original\n")
    git("init", "-q", ".", cwd=tmp_path)
    git("config", "user.email", "t@t.test", cwd=tmp_path)
    git("config", "user.name", "t", cwd=tmp_path)
    git("add", "-A", cwd=tmp_path)
    git("commit", "-qm", "init", cwd=tmp_path)
    return tmp_path


def test_a_clean_tree_is_clean(repo):
    assert GitWorkspace(repo).is_dirty() is False


def test_an_edit_makes_it_dirty(repo):
    (repo / "train.py").write_text("changed\n")
    assert GitWorkspace(repo).is_dirty() is True


def test_an_untracked_file_makes_it_dirty(repo):
    (repo / "new.py").write_text("hello\n")
    assert GitWorkspace(repo).is_dirty() is True


def test_revert_undoes_an_edit(repo):
    (repo / "train.py").write_text("changed\n")
    GitWorkspace(repo).revert()
    assert (repo / "train.py").read_text() == "original\n"


def test_revert_removes_new_files(repo):
    (repo / "junk.py").write_text("junk\n")
    (repo / "sub").mkdir()
    (repo / "sub" / "more.py").write_text("junk\n")
    GitWorkspace(repo).revert()
    assert not (repo / "junk.py").exists()
    assert not (repo / "sub").exists()


def test_revert_undoes_a_staged_change(repo):
    # `git checkout -- .` restores the working tree from the index, so a
    # staged change survives it and the tree stays dirty forever. A proposal
    # that runs `git add`, or a commit git refused after the add succeeded,
    # both land here.
    (repo / "train.py").write_text("changed\n")
    git("add", "-A", cwd=repo)

    workspace = GitWorkspace(repo)
    workspace.revert()

    assert (repo / "train.py").read_text() == "original\n"
    assert workspace.is_dirty() is False, "a staged change must not survive a revert"


def test_revert_undoes_a_staged_deletion(repo):
    git("rm", "-q", "train.py", cwd=repo)
    workspace = GitWorkspace(repo)
    workspace.revert()
    assert (repo / "train.py").read_text() == "original\n"
    assert workspace.is_dirty() is False


def test_revert_leaves_ignored_files_alone(repo):
    # Checkpoints, caches, virtualenvs. Deleting them would make every trial
    # pay to rebuild what git was told not to track.
    (repo / ".gitignore").write_text("artifacts/\n")
    git("add", "-A", cwd=repo)
    git("commit", "-qm", "ignore", cwd=repo)
    (repo / "artifacts").mkdir()
    (repo / "artifacts" / "model.bin").write_text("weights\n")

    GitWorkspace(repo).revert()
    assert (repo / "artifacts" / "model.bin").exists()


def test_commit_records_the_change_and_returns_its_hash(repo):
    (repo / "train.py").write_text("better\n")
    commit = GitWorkspace(repo).commit("labloop: val_loss 1.0")

    assert len(commit) >= 7
    assert commit in git("log", "--oneline", cwd=repo)
    assert GitWorkspace(repo).is_dirty() is False


def test_require_clean_passes_on_a_clean_tree(repo):
    GitWorkspace(repo).require_clean()


def test_require_clean_refuses_a_dirty_tree(repo):
    (repo / "train.py").write_text("work in progress\n")
    with pytest.raises(DirtyTreeError, match="uncommitted changes"):
        GitWorkspace(repo).require_clean()


def test_a_refused_commit_raises_with_gits_reason(repo):
    hooks = repo / ".git" / "hooks"
    hooks.mkdir(exist_ok=True)
    hook = hooks / "pre-commit"
    hook.write_text("#!/bin/sh\necho 'lint failed' >&2\nexit 1\n")
    hook.chmod(0o755)

    (repo / "train.py").write_text("better\n")
    with pytest.raises(RuntimeError, match="lint failed"):
        GitWorkspace(repo).commit("labloop: val_loss 1.0")


def test_a_refused_commit_can_still_be_reverted(repo):
    # The add succeeded before the commit was refused, so the change is
    # staged. If revert cannot clear that, the next trial finds a dirty tree
    # and the run is stuck.
    hooks = repo / ".git" / "hooks"
    hooks.mkdir(exist_ok=True)
    hook = hooks / "pre-commit"
    hook.write_text("#!/bin/sh\nexit 1\n")
    hook.chmod(0o755)

    workspace = GitWorkspace(repo)
    (repo / "train.py").write_text("better\n")
    with pytest.raises(RuntimeError):
        workspace.commit("labloop: val_loss 1.0")

    workspace.revert()
    assert workspace.is_dirty() is False
    assert (repo / "train.py").read_text() == "original\n"
