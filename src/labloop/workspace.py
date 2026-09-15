"""Git operations backing keep-or-revert.

The loop needs four things from version control: know whether the tree is
clean, say what changed, throw away a change, or record one. Keeping that
behind an interface means the loop logic never shells out to git directly, and
tests can substitute an in-memory workspace.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

__all__ = [
    "Workspace",
    "GitWorkspace",
    "DirtyTreeError",
    "GitIdentityError",
    "NotAGitRepositoryError",
]


class DirtyTreeError(RuntimeError):
    """The working tree had uncommitted changes when the loop started."""


class GitIdentityError(RuntimeError):
    """Git has no committer identity, so a kept change could not be committed.

    Its own type because it is a setup problem with a known fix, not a bug in
    the loop — and one worth catching before trial 0 rather than after a real
    improvement has already been measured and then thrown away.
    """


class NotAGitRepositoryError(RuntimeError):
    """The working directory is not inside a git repository.

    Its own type so the CLI can state the fix, rather than surfacing a
    traceback from a git invocation nobody asked about.
    """


class Workspace(Protocol):
    def is_dirty(self) -> bool: ...
    def changed_paths(self) -> list[str]: ...
    def revert(self) -> None: ...
    def commit(self, message: str, paths: Sequence[str] | None = None) -> str: ...


class GitWorkspace:
    """Git operations rooted at a workdir that may sit below the repo top.

    `git status --porcelain` reports paths relative to the repository root even
    when run from a subdirectory, so a workdir below the top has two competing
    path bases. Resolving the top once and running every command there gives
    status and add one base; paths crossing the API are translated to and from
    the workdir so callers (the loop writes its history beside the project)
    keep addressing files the way they always have.
    """

    def __init__(self, root: str | Path = ".") -> None:
        self.root = Path(root)
        self._top: Path | None = None

    def _run(self, args: Sequence[str], cwd: Path) -> str:
        result = subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            stderr = result.stderr.strip()
            if "not a git repository" in stderr.lower():
                raise NotAGitRepositoryError(
                    f"{self.root} is not inside a git repository, and the loop keeps "
                    f"and reverts trials as commits — run `git init` first"
                )
            raise RuntimeError(f"git {' '.join(args)} failed: {stderr}")
        return result.stdout

    def _toplevel(self) -> Path:
        """The repository root, resolved once and cached."""
        if self._top is None:
            self._top = Path(
                self._run(("rev-parse", "--show-toplevel"), self.root).strip()
            ).resolve()
        return self._top

    def _from_toplevel(self, path: str) -> str:
        """A repo-root-relative git path, as the caller's workdir sees it."""
        return os.path.relpath(self._toplevel() / path, self.root.resolve())

    def _to_toplevel(self, path: str) -> str:
        """A workdir-relative caller path, as git from the repo top sees it."""
        return os.path.relpath(self.root.resolve() / path, self._toplevel())

    def _git(self, *args: str) -> str:
        return self._run(args, self._toplevel()).strip()

    def is_dirty(self) -> bool:
        return bool(self._git("status", "--porcelain"))

    def require_clean(self) -> None:
        """Refuse to start on a dirty tree.

        The loop reverts by discarding changes. If the tree already held work
        when it started, a revert would destroy it.
        """
        if self.is_dirty():
            raise DirtyTreeError(
                "working tree has uncommitted changes, and the loop reverts by "
                "discarding, so it would destroy them. If they are your work, "
                "commit or stash them. If they are an unjudged change left by an "
                "interrupted run, discard them with `git reset --hard && git clean -fd` "
                "— committing one would put a change nothing measured into the history."
            )

    def require_identity(self) -> None:
        """Refuse to start when git cannot name a committer.

        `git var GIT_COMMITTER_IDENT` is the same lookup `git commit` performs,
        so a failure here is exactly the failure a keep would hit — caught
        before trial 0 instead of after a real improvement was measured and
        then discarded because the commit was refused.
        """
        result = subprocess.run(
            ["git", "var", "GIT_COMMITTER_IDENT"],
            cwd=str(self._toplevel()),
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise GitIdentityError(
                "git has no committer identity, so a kept change could not be "
                "committed and the trial's improvement would be lost. Set one "
                "before starting:\n"
                '  git config user.name "Your Name"\n'
                '  git config user.email "you@example.com"'
            )

    def revert(self) -> None:
        """Put the tree back to the last commit, staged changes included.

        `git checkout -- .` only restores the working tree from the index, so
        anything already staged survives it and the tree stays dirty forever —
        which is what a proposal that runs `git add` leaves behind, and what a
        commit git refused leaves behind, since the add succeeded. A hard
        reset is the operation that actually means "discard".
        """
        self._git("reset", "--hard")
        self._git("clean", "-fd")

    def changed_paths(self) -> list[str]:
        """Every path the tree differs from HEAD on, staged or not.

        Parsed from `--porcelain -z`: NUL separators survive filenames with
        spaces, and nothing here strips the status columns — the plain form
        went through a helper that trimmed the first line's leading space,
        which silently turned ` M train.py` into `rain.py`.
        """
        result = subprocess.run(
            ["git", "status", "--porcelain", "-z", "--untracked-files=all"],
            cwd=str(self._toplevel()),
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"git status failed: {result.stderr.strip()}")

        tokens = result.stdout.split("\0")
        paths: set[str] = set()
        index = 0
        while index < len(tokens):
            token = tokens[index]
            if not token:
                index += 1
                continue
            status, name = token[:2], token[3:]
            paths.add(self._from_toplevel(name))
            # A rename or copy carries the original name as its own token.
            if "R" in status or "C" in status:
                index += 1
                paths.add(self._from_toplevel(tokens[index]))
            index += 1
        return sorted(paths)

    def commit(self, message: str, paths: Sequence[str] | None = None) -> str:
        """Record a change. With `paths`, only those; otherwise everything.

        Ignored paths are dropped rather than forced in: `git add` refuses
        them, and a user who gitignored a file has already said what they want.
        """
        if paths is None:
            self._git("add", "-A")
        else:
            wanted = [
                self._to_toplevel(p)
                for p in paths
                if not self._is_ignored(p) and self._exists_or_tracked(p)
            ]
            if not wanted:
                raise RuntimeError("nothing to commit: every named path is gitignored")
            self._git("add", "-A", "--", *wanted)
        self._git("commit", "-m", message)
        return self._git("rev-parse", "--short", "HEAD")

    def _exists_or_tracked(self, path: str) -> bool:
        """Whether a caller path is on disk or in the index.

        changed_paths() reports both sides of a rename; the vanished side is in
        neither the worktree nor the index, and `git add` fails on it. The
        surviving side carries the rename.
        """
        top = self._to_toplevel(path)
        if (self._toplevel() / top).exists():
            return True
        result = subprocess.run(
            ["git", "ls-files", "--error-unmatch", "--", top],
            cwd=str(self._toplevel()),
            capture_output=True,
        )
        return result.returncode == 0

    def _is_ignored(self, path: str) -> bool:
        result = subprocess.run(
            ["git", "check-ignore", "-q", "--", self._to_toplevel(path)],
            cwd=str(self._toplevel()),
            capture_output=True,
        )
        return result.returncode == 0
