"""Shared fixtures for the loop tests.

The loop is driven through a stub workspace so its decisions can be exercised
without a git repository. Real git is covered in test_workspace.py, and the
command line end to end in test_cli.py.
"""

from __future__ import annotations

from labloop import Experiment, Goal, Loop


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
