"""Git operations backing keep-or-revert.

The loop needs four things from version control: know whether the tree is
clean, say what changed, throw away a change, or record one. Keeping that
behind an interface means the loop logic never shells out to git directly, and
tests can substitute an in-memory workspace.
"""

from __future__ import annotations

import atexit
import os
import re
import subprocess
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Protocol

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
    def untracked_paths(self) -> list[str]: ...
    def ignored_paths(self) -> list[str]: ...
    def revert(self) -> None: ...
    def commit(self, message: str, paths: Sequence[str] | None = None) -> str: ...


# The loop also calls `describe_change(paths) -> list[dict]` when a workspace
# has it. It is not in the protocol so that a workspace written against 1.0
# keeps working; it then records no change summary.

MAX_DESCRIBED_FILES = 20
"""Files described per change. A proposal that rewrote a whole tree is
summarized by its first files and a count, not by every one of them."""

_MAX_WHERE = 6
_MAX_SYMBOL = 60
_SNIFF_BYTES = 1 << 20

# Git ships function-name rules for these languages but applies them only when
# an attribute asks. Naming them here makes hunk headers say `def digest(` for
# a method instead of the enclosing `class Loop:`. A repository's own
# .gitattributes still wins, since it outranks the global attributes file.
_DIFF_DRIVERS = """\
*.py diff=python
*.pyi diff=python
*.rs diff=rust
*.go diff=golang
*.c diff=cpp
*.h diff=cpp
*.cc diff=cpp
*.cpp diff=cpp
*.hpp diff=cpp
*.java diff=java
*.kt diff=kotlin
*.cs diff=csharp
*.rb diff=ruby
*.php diff=php
*.sh diff=bash
"""

# Only source files get a `where`. Elsewhere git's default rule quotes any
# line that starts with a letter, which in a notes or data file is prose the
# proposer wrote — and the brief must not carry the proposer's words.
_SOURCE_SUFFIXES = frozenset(
    line.split()[0][1:] for line in _DIFF_DRIVERS.splitlines() if line
) | {".js", ".jsx", ".ts", ".tsx", ".mjs", ".swift", ".scala", ".lua", ".jl", ".r", ".m"}

_DEFINITION = re.compile(
    r"\b(?:def|class|fn|func|struct|enum|trait|impl|interface|function|module|sub)\b"
    r"\s*(?:\([^)]*\)\s*)?([A-Za-z_][A-Za-z0-9_]*)"
)
_CALLABLE = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)\s*\(")


def _symbol(context: str) -> str | None:
    """The name a hunk header's context line defines, and nothing else.

    `def b(self):` gives `b`; `func (r *T) Name(` gives `Name`; a C-family
    `static int sum(int n)` gives `sum`. Reducing the line to an identifier
    keeps the summary to the shape of the code: comments, strings and the
    rest of the line stay out of what the next proposer reads.
    """
    found = _DEFINITION.search(context) or _CALLABLE.search(context)
    return found.group(1)[:_MAX_SYMBOL] if found else None


_drivers_file: str | None = None


def _remove_quietly(path: str) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass


def _diff_drivers() -> str:
    """A global attributes file mapping extensions to git's builtin drivers."""
    global _drivers_file
    if _drivers_file is None or not os.path.exists(_drivers_file):
        fd, name = tempfile.mkstemp(prefix="labloop-diff-drivers-", suffix=".attributes")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(_DIFF_DRIVERS)
        atexit.register(_remove_quietly, name)
        _drivers_file = name
    return _drivers_file


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

    def ignored_paths(self) -> list[str]:
        """Ignored-but-present paths, as the workdir sees them.

        Porcelain omits ignored files, so this is what a *tracked*
        `.gitignore` edit can hide: a proposer that appends its own shadow
        to `.gitignore` parks `json.py` where untracked_paths() never
        looks. Callers (the import-shadow guard) scan these alongside the
        untracked set — a stdlib-named file ignored before the baseline is
        flagged too, fail-closed: it has been shadowable all along.
        """
        result = subprocess.run(
            ["git", "ls-files", "--others", "--ignored", "--exclude-standard", "-z"],
            cwd=str(self._toplevel()),
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"git ls-files failed: {result.stderr.strip()}")
        return sorted(self._from_toplevel(t) for t in result.stdout.split("\0") if t)

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

    def set_aside(self, paths: Sequence[str], label: str) -> None:
        """Stash exactly `paths` under `label`, then discard the rest: the tree is HEAD.

        For measuring the incumbent while a proposal exists. git's stash
        rather than a copy kept by labloop, so a crash between the two halves
        leaves the proposal in `git stash list` under its label instead of in
        a temporary directory nobody knows about.
        """
        self._git(
            "stash", "push", "--include-untracked", "-m", label, "--",
            *(self._to_toplevel(p) for p in paths),
        )
        if not self._our_stash_on_top(label):
            # "No local changes to save" creates no entry; carrying on would
            # make restore() pop whatever the user had stashed.
            raise RuntimeError(f"nothing was set aside for {label!r}")
        self.revert()

    def restore(self, label: str) -> None:
        """Bring back what set_aside(label) stashed, onto a clean tree.

        Refuses unless the newest stash is ours, so it never applies one the
        user made. If git cannot apply it, the entry stays in the stash list.
        """
        if not self._our_stash_on_top(label):
            raise RuntimeError(f"the newest stash is not {label!r}; nothing restored")
        self.revert()
        self._git("stash", "pop")

    def _our_stash_on_top(self, label: str) -> bool:
        result = subprocess.run(
            ["git", "stash", "list", "-n", "1", "--format=%gs"],
            cwd=str(self._toplevel()),
            capture_output=True,
            text=True,
        )
        # The reflog subject is "On <branch>: <message>".
        return result.returncode == 0 and result.stdout.strip().endswith(f": {label}")

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

    def describe_change(self, paths: Sequence[str]) -> list[dict[str, Any]]:
        """What changed in `paths` against HEAD: counts and enclosing definitions.

        One `git diff -U0` covers every tracked file, because this runs once per
        trial inside the loop it is meant to cost nothing in. The `where` list
        names the definitions git prints after each `@@` in source files — the
        definition above the hunk, so a change to a `def` line itself names
        the one before it — reduced to bare identifiers. External diff and
        textconv drivers are off: the summary has to be the same whichever
        machine reads the tree.
        """
        wanted = sorted(paths)
        described = wanted[:MAX_DESCRIBED_FILES]
        top = {self._to_toplevel(p): p for p in described}
        result = subprocess.run(
            [
                "git",
                "-c", f"core.attributesFile={_diff_drivers()}",
                "-c", "core.quotePath=false",
                "diff", "-U0", "--no-color", "--no-renames", "--no-ext-diff",
                "--no-textconv", "HEAD", "--", *top,
            ],
            cwd=str(self._toplevel()),
            capture_output=True,
            text=True,
            errors="replace",
        )
        if result.returncode != 0:
            raise RuntimeError(f"git diff failed: {result.stderr.strip()}")

        headers = {f"diff --git a/{t} b/{t}": p for t, p in top.items()}
        files: dict[str, dict[str, Any]] = {}
        current: dict[str, Any] | None = None
        in_hunk = False
        for line in result.stdout.splitlines():
            if line.startswith("diff --git "):
                path = headers.get(line)
                current = None if path is None else files.setdefault(
                    path,
                    {"path": path, "status": "modified", "added": 0, "removed": 0,
                     "where": [], "source": Path(path).suffix.lower() in _SOURCE_SUFFIXES},
                )
                in_hunk = False
            elif current is None:
                continue
            elif line.startswith("@@"):
                in_hunk = True
                name = current["source"] and _symbol(line.split("@@", 2)[-1])
                where = current["where"]
                if name and name not in where and len(where) < _MAX_WHERE:
                    where.append(name)
            elif in_hunk and line.startswith("+"):
                current["added"] += 1
            elif in_hunk and line.startswith("-"):
                current["removed"] += 1
            elif not in_hunk and line.startswith("new file mode"):
                current["status"] = "added"
            elif not in_hunk and line.startswith("deleted file mode"):
                current["status"] = "deleted"
            elif not in_hunk and line.startswith("Binary files"):
                current.update(status="binary", added=None, removed=None)

        # Untracked files are invisible to `git diff HEAD`; read them directly.
        for path in described:
            if path in files:
                continue
            target = self.root / path
            if not target.is_file() or target.is_symlink():
                continue
            with target.open("rb") as fh:
                head = fh.read(_SNIFF_BYTES)
            if b"\0" in head:
                files[path] = {"path": path, "status": "binary", "added": None,
                               "removed": None, "where": []}
            else:
                added = head.count(b"\n") + (1 if head and not head.endswith(b"\n") else 0)
                files[path] = {"path": path, "status": "added", "added": added,
                               "removed": 0, "where": []}

        for entry in files.values():
            entry.pop("source", None)
        summary = [files[p] for p in described if p in files]
        if len(wanted) > len(described):
            summary.append({"more": len(wanted) - len(described)})
        return summary

    def untracked_paths(self) -> list[str]:
        """Untracked paths as the workdir sees them (`??` in porcelain).

        Untracked-only on purpose: callers (the import-shadow guard) flag
        files a proposal *added*. A stdlib-named file tracked since the
        baseline is vendored source the proposer is allowed to edit —
        flagging it would reject honest edits to a package that happens to
        name a module like the standard library does.
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
        paths: list[str] = []
        index = 0
        while index < len(tokens):
            token = tokens[index]
            if not token:
                index += 1
                continue
            status, name = token[:2], token[3:]
            if "?" in status:
                paths.append(self._from_toplevel(name))
            # A rename or copy carries the original name as its own token.
            if "R" in status or "C" in status:
                index += 1
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
