"""One loop per ledger, enforced rather than hoped.

Two loops appending to one ledger interleave silently: trial indices collide,
each loop advances its own idea of the incumbent, and the record stops being
a record. The dirty-tree interlock happens to catch two loops in one working
tree, but two worktrees sharing a ledger have no guard at all — and separate
worktrees over a shared ledger is exactly how parallel research directions
will run.

The lock is `flock` on a sidecar file, which has the property that matters
for overnight runs: the operating system releases it when the holding process
dies, however it dies. There is no stale-lock state to clean up, so if
acquiring fails, the holder named in the file is alive right now.

Windows has no flock; `msvcrt.locking` covers the same contract there on a
best-effort basis. CI exercises the POSIX path.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path
from types import TracebackType
from typing import IO

__all__ = ["LedgerLock", "LedgerLockedError"]


class LedgerLockedError(RuntimeError):
    """Another loop is running against this ledger right now."""


class LedgerLock:
    """Advisory exclusive lock on a ledger, held for the life of a run.

    The lock file lives in the system temp directory, keyed by the ledger's
    resolved path — never beside the ledger. A sidecar in the working tree
    would be an untracked file, and the dirty-tree interlock would refuse to
    start because of the lock protecting the start. Two worktrees pointing at
    one ledger resolve to one key, which is the collision being guarded.

    Usable as a context manager. Re-entrant within one instance, so a caller
    that locks around `run()` does not deadlock a nested `baseline()`.
    """

    def __init__(self, ledger_path: str | Path, wait: bool = False) -> None:
        resolved = str(Path(ledger_path).resolve())
        digest = hashlib.sha256(resolved.encode("utf-8")).hexdigest()[:16]
        self.path = Path(tempfile.gettempdir()) / f"labloop-{digest}.lock"
        self.wait = wait
        self._handle: IO[str] | None = None
        self._depth = 0

    def acquire(self) -> None:
        if self._depth > 0:
            self._depth += 1
            return

        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+")
        try:
            self._flock(handle)
        except (BlockingIOError, PermissionError, OSError):
            handle.seek(0)
            holder = handle.read().strip() or "unknown pid"
            handle.close()
            raise LedgerLockedError(
                f"another labloop run (pid {holder}) holds {self.path.name} — two loops "
                "over one ledger would interleave trial indices and disagree about the "
                "incumbent. Wait for it, stop it, or pass --wait to queue behind it. "
                "A crashed run cannot cause this: its lock died with it."
            ) from None

        handle.seek(0)
        handle.truncate()
        handle.write(str(os.getpid()))
        handle.flush()
        self._handle = handle
        self._depth = 1

    def _flock(self, handle: IO[str]) -> None:
        if os.name == "posix":
            import fcntl

            flags = fcntl.LOCK_EX | (0 if self.wait else fcntl.LOCK_NB)
            fcntl.flock(handle.fileno(), flags)
        else:  # pragma: no cover - exercised only on Windows
            import msvcrt

            mode = msvcrt.LK_LOCK if self.wait else msvcrt.LK_NBLCK  # type: ignore[attr-defined]
            handle.seek(0)
            msvcrt.locking(handle.fileno(), mode, 1)  # type: ignore[attr-defined]

    def release(self) -> None:
        if self._depth == 0:
            return
        self._depth -= 1
        if self._depth > 0:
            return
        if self._handle is not None:
            # Closing the descriptor releases the flock; the sidecar file is
            # left behind on purpose. Deleting it would open a race where a
            # third loop locks a fresh inode while the second still holds the
            # old one, and both believe they are alone.
            self._handle.close()
            self._handle = None

    def __enter__(self) -> LedgerLock:
        self.acquire()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.release()
