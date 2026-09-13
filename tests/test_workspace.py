"""GitWorkspace against a real repository.

The loop is tested through a stub so its decisions can be exercised without
git. That leaves the three git operations the whole design rests on — is it
dirty, throw it away, record it — checked by nothing.
"""

from __future__ import annotations

import subprocess

import pytest

from labloop import DirtyTreeError, GitWorkspace

from .conftest import replace_text


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


def test_missing_git_repo_names_the_fix(tmp_path):
    """A first run in a scratch directory must state the fix, not traceback."""
    from labloop.workspace import GitWorkspace, NotAGitRepositoryError

    with pytest.raises(NotAGitRepositoryError, match="git init"):
        GitWorkspace(tmp_path).is_dirty()


# --- the workdir below the repository top ---------------------------------
#
# `--workdir sub` is a supported layout, but `git status` reports paths from
# the repository root while the loop hands the workdir-relative history file
# to `commit`. Sharing one path base is what lets a measured improvement
# actually be kept instead of dying on `fatal: pathspec ... did not match`.


@pytest.fixture
def subdir_repo(tmp_path):
    """A repo whose project lives in sub/, so workdir != toplevel."""
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "train.py").write_text("original\n")
    (sub / ".gitignore").write_text("labloop.jsonl\n__pycache__/\n")
    git("init", "-q", ".", cwd=tmp_path)
    git("config", "user.email", "t@t.test", cwd=tmp_path)
    git("config", "user.name", "t", cwd=tmp_path)
    git("add", "-A", cwd=tmp_path)
    git("commit", "-qm", "init", cwd=tmp_path)
    return tmp_path, sub


def test_from_a_subdirectory_sees_the_edit(subdir_repo):
    _, sub = subdir_repo
    (sub / "train.py").write_text("changed\n")
    assert GitWorkspace(sub).changed_paths() == ["train.py"]


def test_from_a_subdirectory_commits_and_records(subdir_repo):
    root, sub = subdir_repo
    (sub / "train.py").write_text("better\n")

    workspace = GitWorkspace(sub)
    commit = workspace.commit("labloop: val_loss 1.0", workspace.changed_paths())

    assert commit in git("log", "--oneline", cwd=root)
    assert workspace.is_dirty() is False
    assert git("show", "HEAD:sub/train.py", cwd=root) == "better\n"


def test_from_a_subdirectory_commits_the_workdir_history_file(subdir_repo):
    # The loop passes `labloop-history.jsonl` by its workdir-relative name
    # beside changed_paths(), which git reports from the repo root. Both must
    # land in the same commit.
    root, sub = subdir_repo
    (sub / "train.py").write_text("better\n")
    (sub / "labloop-history.jsonl").write_text('{"index": 1}\n')

    workspace = GitWorkspace(sub)
    workspace.commit("labloop: val_loss 1.0", [*workspace.changed_paths(), "labloop-history.jsonl"])

    tracked = git("ls-files", cwd=root).splitlines()
    assert "sub/train.py" in tracked
    assert "sub/labloop-history.jsonl" in tracked
    assert workspace.is_dirty() is False


def test_from_a_subdirectory_reverts(subdir_repo):
    _, sub = subdir_repo
    (sub / "train.py").write_text("changed\n")
    (sub / "junk.py").write_text("junk\n")

    workspace = GitWorkspace(sub)
    workspace.revert()

    assert (sub / "train.py").read_text() == "original\n"
    assert not (sub / "junk.py").exists()
    assert workspace.is_dirty() is False


def test_from_a_subdirectory_the_dirty_check_covers_the_whole_repo(subdir_repo):
    # A revert resets the repository, not just the workdir. Gating on a
    # workdir-only status would let a revert destroy a sibling directory the
    # loop never measured, which is exactly what require_clean exists to stop.
    root, sub = subdir_repo
    (root / "sibling.txt").write_text("unrelated work\n")

    workspace = GitWorkspace(sub)
    assert workspace.is_dirty() is True
    with pytest.raises(DirtyTreeError, match="uncommitted changes"):
        workspace.require_clean()


def test_from_a_subdirectory_revert_cleans_repo_wide(subdir_repo):
    # `git clean` from a subdirectory only cleans that subtree, so the tree
    # would stay dirty and the next trial would balk. Running from the top
    # clears what require_clean governs.
    root, sub = subdir_repo
    (root / "sibling.txt").write_text("left by a proposal\n")

    GitWorkspace(sub).revert()

    assert not (root / "sibling.txt").exists()
    assert GitWorkspace(sub).is_dirty() is False


def test_a_commit_of_only_ignored_paths_in_a_subdir_is_refused(subdir_repo):
    root, sub = subdir_repo
    (sub / ".gitignore").write_text("*.log\n")
    git("add", "-A", cwd=root)
    git("commit", "-qm", "ignore logs", cwd=root)
    (sub / "ignored.log").write_text("noise\n")

    with pytest.raises(RuntimeError, match="gitignored"):
        GitWorkspace(sub).commit("labloop: x", ["ignored.log"])


def test_a_kept_trial_commits_when_the_workdir_is_a_subdirectory(subdir_repo, monkeypatch):
    """The reported bug: measuring in sub/ worked, the keep did not commit."""
    from labloop.cli import main

    root, sub = subdir_repo
    (sub / "train.py").write_text('print("val_loss = 2.0")\n')
    git("add", "-A", cwd=root)
    git("commit", "-qm", "add experiment", cwd=root)

    monkeypatch.chdir(root)
    monkeypatch.setenv("PYTHONDONTWRITEBYTECODE", "1")
    code = main(
        [
            "run",
            "--workdir",
            str(sub),
            "--run",
            "python train.py",
            "--metric",
            "val_loss",
            "--propose",
            replace_text("train.py", "2.0", "1.0"),
        ]
    )

    assert code == 0
    assert "labloop:" in git("log", "--oneline", cwd=root)
    assert git("show", "HEAD:sub/train.py", cwd=root) == 'print("val_loss = 1.0")\n'
    assert "sub/labloop-history.jsonl" in git("ls-files", cwd=root).splitlines()
    assert GitWorkspace(sub).is_dirty() is False
