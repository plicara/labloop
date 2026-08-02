"""Git operations backing keep-or-revert.

The loop needs four things from version control: know whether the tree is
clean, say what changed, throw away a change, or record one. Keeping that
behind an interface means the loop logic never shells out to git directly, and
tests can substitute an in-memory workspace.
"""

from __future__ import annotations

import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

__all__ = ["Workspace", "GitWorkspace", "DirtyTreeError"]


class DirtyTreeError(RuntimeError):
    """The working tree had uncommitted changes when the loop started."""


class Workspace(Protocol):
    def is_dirty(self) -> bool: ...
    def changed_paths(self) -> list[str]: ...
    def revert(self) -> None: ...
    def commit(self, message: str, paths: Sequence[str] | None = None) -> str: ...


class GitWorkspace:
    def __init__(self, root: str | Path = ".") -> None:
        self.root = Path(root)

    def _git(self, *args: str) -> str:
        result = subprocess.run(
            ["git", *args],
            cwd=str(self.root),
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
        return result.stdout.strip()

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
            ["git", "status", "--porcelain", "-z"],
            cwd=str(self.root),
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
            paths.add(name)
            # A rename or copy carries the original name as its own token.
            if "R" in status or "C" in status:
                index += 1
                paths.add(tokens[index])
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
            wanted = [p for p in paths if not self._is_ignored(p)]
            if not wanted:
                raise RuntimeError("nothing to commit: every named path is gitignored")
            self._git("add", "-A", "--", *wanted)
        self._git("commit", "-m", message)
        return self._git("rev-parse", "--short", "HEAD")

    def _is_ignored(self, path: str) -> bool:
        result = subprocess.run(
            ["git", "check-ignore", "-q", "--", path],
            cwd=str(self.root),
            capture_output=True,
        )
        return result.returncode == 0
