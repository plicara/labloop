"""Detecting when the measurement changed underneath the loop.

A keep-or-revert loop optimizes whatever the metric rewards, and the propose
command has write access to the whole working tree — including the code and
data that produce the metric. An agent can score well by editing the evaluator
instead of improving anything, and published runs show it does: agents have
overwritten test cases, memorized evaluation answers, and read sibling runs
through shared git state.

labloop does not prevent that. A shell command can do anything, and claiming
otherwise would be a stronger promise than this design can keep. It *detects*
it. Files that define the measurement are digested with SHA-256 before the
propose command runs and again afterwards; if the digest moved, the metric was
produced by a different measurement than the incumbent's and the two numbers
cannot be compared. A number that cannot be compared is not a result.

Recording the digest on each trial is what makes the ledger auditable later:
two trials carrying the same digest were measured the same way.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from pathlib import Path

__all__ = [
    "HarnessMismatchError",
    "NoProtectedFilesError",
    "file_digest",
    "harness_digest",
]

_CHUNK = 1 << 16


class HarnessMismatchError(RuntimeError):
    """The incumbent in the ledger was measured by a different harness."""


class NoProtectedFilesError(ValueError):
    """The protected patterns matched nothing."""


def harness_digest(root: str | Path, patterns: Sequence[str]) -> str | None:
    """Digest every file matched by `patterns`, relative to `root`.

    Returns None when no patterns are given — the check is opt-in, and an
    absent digest records that nothing was claimed rather than that nothing
    changed.

    Path names are hashed alongside contents, so renaming, adding, or deleting
    a protected file moves the digest even when every surviving byte is
    identical. Symlinks are excluded: following one would let a replaced file
    hash as its target, and dropping it from the set moves the digest anyway.
    """
    if not patterns:
        return None

    root = Path(root)
    names = _matching(root, patterns)
    if not names:
        raise NoProtectedFilesError(
            f"protected patterns {list(patterns)} matched no files under {root} — "
            "a typo here would silently disable the check"
        )

    outer = hashlib.sha256()
    for name in sorted(names):
        outer.update(name.encode("utf-8"))
        outer.update(b"\0")
        outer.update(_digest_file(root / name))
        outer.update(b"\n")
    return outer.hexdigest()


def file_digest(path: str | Path) -> str | None:
    """Digest one file, or None if it is not there."""
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        return None
    return _digest_file(path).hex()


def _matching(root: Path, patterns: Sequence[str]) -> set[str]:
    """Every regular file matched by the patterns, as paths relative to root.

    A pattern naming a directory covers the whole subtree. Frozen evaluation
    data is usually a directory, and having to enumerate it file by file would
    make the common case the easy one to get wrong.
    """
    names: set[str] = set()
    for pattern in patterns:
        for path in root.glob(pattern):
            if path.is_symlink():
                continue
            if path.is_dir():
                names.update(
                    child.relative_to(root).as_posix()
                    for child in path.rglob("*")
                    if child.is_file() and not child.is_symlink()
                )
            elif path.is_file():
                names.add(path.relative_to(root).as_posix())
    return names


def _digest_file(path: Path) -> bytes:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(_CHUNK):
            digest.update(chunk)
    return digest.digest()
