"""Git operations backing keep-or-revert.

The loop needs exactly three things from version control: know whether the
tree is clean, throw away a change, or record one. Keeping that behind an
interface means the loop logic never shells out to git directly, and tests can
substitute an in-memory workspace.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Protocol

__all__ = ["Workspace", "GitWorkspace", "DirtyTreeError"]


class DirtyTreeError(RuntimeError):
    """The working tree had uncommitted changes when the loop started."""


class Workspace(Protocol):
    def is_dirty(self) -> bool: ...
    def revert(self) -> None: ...
    def commit(self, message: str) -> str: ...


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
                "interrupted run, discard them with `git checkout -- . && git clean -fd` "
                "— committing one would put a change nothing measured into the history."
            )

    def revert(self) -> None:
        self._git("checkout", "--", ".")
        self._git("clean", "-fd")

    def commit(self, message: str) -> str:
        self._git("add", "-A")
        self._git("commit", "-m", message)
        return self._git("rev-parse", "--short", "HEAD")
