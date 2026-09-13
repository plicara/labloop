"""Opt-in OS isolation for the propose step.

labloop *detects* edits to the protected set; it does not, by itself, stop a
proposer from writing code the measurement later loads from somewhere the digest
was never pointed at (a `.pyc` in the bytecode mirror, a shim, a shadow package
outside the worktree). The only real boundary is OS isolation: run the untrusted
propose step somewhere it can write **only the worktree**, so anything planted
elsewhere is denied and anything planted inside is part of the diff.

This module is that boundary. It picks a backend and turns `(command, worktree)`
into a confined invocation.

Backends, best first:

* **bubblewrap** (Linux, if user namespaces work) — namespaces, no daemon, ~ms.
* **Landlock** (Linux) — unprivileged, no namespaces, no daemon; this ships a
  small dependency-free wrapper (`_landlock.py`), so it is available out of the box.
* **Seatbelt** (macOS) — `/usr/bin/sandbox-exec` with a generated profile, the
  same mechanism Codex, fence and greywall use.
* **Docker** (explicit only) — the heavy fallback; a daemon and an image.

Every backend denies writes outside the worktree, **including `/tmp`**: the
bytecode mirror labloop itself creates under `/tmp` must not be writable by the
proposer, or the race this feature exists to close comes back. Scratch is
redirected inside the worktree.

Nothing here runs unless you ask: `--sandbox none` (the default) is exactly the
0.3.0 behaviour. `--sandbox auto` is the recommended setting. When isolation is
requested and no backend is available the loop refuses to start rather than
running unconfined — a silent fail-open is worse than an error.
"""
from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .runner import run_command

__all__ = [
    "BwrapSandbox",
    "DockerSandbox",
    "LandlockSandbox",
    "Sandbox",
    "SandboxError",
    "SeatbeltSandbox",
    "TemplateSandbox",
    "available_backends",
    "resolve_sandbox",
    "verify_sandbox",
]

_SCRATCH = ".labloop-tmp"          # inside the worktree, so scratch is never a hole
_SHELL = "/bin/sh"


class SandboxError(RuntimeError):
    """Isolation was requested but cannot be provided, or failed its self-check."""


@dataclass(frozen=True)
class TemplateSandbox:
    """A caller-supplied command template containing `{command}`/`{workdir}`."""

    name: str
    template: str

    def wrap(self, command: str, worktree: str) -> str:
        return self.template.replace("{workdir}", worktree).replace("{command}", command)


@dataclass(frozen=True)
class BwrapSandbox:
    """bubblewrap: read-only root, the worktree writable, /tmp mapped inside it."""

    name: str = "bwrap"

    def wrap(self, command: str, worktree: str) -> str:
        wt = shlex.quote(worktree)
        scratch = shlex.quote(os.path.join(worktree, _SCRATCH))
        return (
            f"mkdir -p {scratch} && exec bwrap --die-with-parent --ro-bind / / "
            f"--dev /dev --proc /proc --bind {wt} {wt} --bind {scratch} /tmp "
            f"--chdir {wt} --setenv TMPDIR /tmp -- "
            f"{_SHELL} -c {shlex.quote(command)}"
        )


@dataclass(frozen=True)
class LandlockSandbox:
    """Landlock via the bundled dependency-free wrapper (`_landlock.py`)."""

    python: str = sys.executable
    name: str = "landlock"

    def wrap(self, command: str, worktree: str) -> str:
        return (
            f"{shlex.quote(self.python)} -m labloop._landlock {shlex.quote(worktree)} -- "
            f"{_SHELL} -c {shlex.quote(command)}"
        )


_SEATBELT_PROFILE = """(version 1)
(deny default)
(allow process*)
(allow signal (target self))
(allow sysctl-read)
(allow mach-lookup)
(allow network*)
(allow file-read*)
(allow file-write* (subpath "{worktree}"))
(allow file-write-data (literal "/dev/null") (literal "/dev/stdout")
                    (literal "/dev/stderr") (literal "/dev/tty")
                    (literal "/dev/dtracehelper"))
"""


@dataclass(frozen=True)
class SeatbeltSandbox:
    """macOS Seatbelt: deny by default, read everywhere, write the worktree."""

    name: str = "seatbelt"

    def wrap(self, command: str, worktree: str) -> str:
        profile = _SEATBELT_PROFILE.format(worktree=worktree)
        scratch = shlex.quote(os.path.join(worktree, _SCRATCH))
        return (
            f"mkdir -p {scratch} && exec env TMPDIR={scratch} "
            f"/usr/bin/sandbox-exec -p {shlex.quote(profile)} "
            f"{_SHELL} -c {shlex.quote(command)}"
        )


@dataclass(frozen=True)
class DockerSandbox:
    """Docker: read-only root, the worktree bind-mounted, ephemeral /tmp."""

    image: str = "python:3.12-slim"
    name: str = "docker"

    def wrap(self, command: str, worktree: str) -> str:
        wt = shlex.quote(worktree)
        return (
            f"exec docker run --rm --init --read-only --cap-drop=ALL "
            f"--security-opt=no-new-privileges --pids-limit 2048 "
            f"-v {wt}:{wt}:rw -w {wt} --tmpfs /tmp:rw,exec,nosuid,nodev "
            f"-e TMPDIR=/tmp --network bridge "
            f"{self.image} {_SHELL} -c {shlex.quote(command)}"
        )


# A backend is any of these; a Protocol would only add ceremony here.
Sandbox = TemplateSandbox | BwrapSandbox | LandlockSandbox | SeatbeltSandbox | DockerSandbox


# --- availability probes (each is cheap; results are what matters) ---

def _which(name: str) -> bool:
    return shutil.which(name) is not None


def landlock_available() -> bool:
    """Whether the running kernel has the Landlock LSM enabled."""
    try:
        return "landlock" in Path("/sys/kernel/security/lsm").read_text()
    except OSError:
        return False


def user_namespaces_work() -> bool:
    """Whether an unprivileged user can map a user namespace (needed by bwrap)."""
    if not _which("unshare"):
        return False
    return subprocess.run(
        ["unshare", "--user", "--map-root-user", "true"], capture_output=True
    ).returncode == 0


def seatbelt_available() -> bool:
    return sys.platform == "darwin" and os.path.exists("/usr/bin/sandbox-exec")


def available_backends() -> list[str]:
    found = []
    if seatbelt_available():
        found.append("seatbelt")
    if _which("bwrap") and user_namespaces_work():
        found.append("bwrap")
    if landlock_available():
        found.append("landlock")
    if _which("docker"):
        found.append("docker")
    return found


def resolve_sandbox(choice: str | None, template: str | None = None) -> Sandbox | None:
    """Turn `--sandbox`/`--sandbox-exec` into a backend, or None for no isolation.

    Fails loudly when isolation is *requested* but unavailable: a run that asked
    for a boundary and silently got none is worse off than one that was told no.
    """
    if template is not None:
        if "{command}" not in template:
            raise SandboxError("--sandbox-exec template must contain {command}")
        return TemplateSandbox("custom", template)
    if choice in (None, "none"):
        return None
    if choice == "auto":
        if seatbelt_available():
            return SeatbeltSandbox()
        if _which("bwrap") and user_namespaces_work():
            return BwrapSandbox()
        if landlock_available():
            return LandlockSandbox()
        raise SandboxError(
            "no sandbox backend available (tried macOS Seatbelt, bubblewrap, Landlock). "
            "Install bubblewrap, use a Landlock kernel, or --sandbox use an explicit "
            "backend; refusing to run the proposer unconfined."
        )
    if choice == "bwrap":
        if not _which("bwrap"):
            raise SandboxError("--sandbox bwrap requested but bwrap is not on PATH")
        if not user_namespaces_work():
            raise SandboxError(
                "--sandbox bwrap requested but unprivileged user namespaces are blocked "
                "(on Ubuntu, kernel.apparmor_restrict_unprivileged_userns=1)"
            )
        return BwrapSandbox()
    if choice == "landlock":
        if not landlock_available():
            raise SandboxError("--sandbox landlock requested but this kernel has no Landlock LSM")
        return LandlockSandbox()
    if choice == "seatbelt":
        if not seatbelt_available():
            raise SandboxError("--sandbox seatbelt is macOS-only (/usr/bin/sandbox-exec not found)")
        return SeatbeltSandbox()
    if choice == "docker":
        if not _which("docker"):
            raise SandboxError("--sandbox docker requested but docker is not on PATH")
        return DockerSandbox()
    raise SandboxError(f"unknown sandbox {choice!r}")


def verify_sandbox(sandbox: Sandbox, worktree: str) -> None:
    """Prove the sandbox confines *this* machine before trial 0.

    A "best effort" backend can run completely unsandboxed while reporting
    success, so the probe must show both halves: a write inside the worktree
    works, and a write outside it is denied. If either is wrong, refuse.
    """
    outside_dir = tempfile.mkdtemp(prefix="labloop-verify-")
    inside = os.path.join(worktree, ".labloop-verify")
    outside = os.path.join(outside_dir, "escape")
    probe = f"touch {shlex.quote(inside)} && echo x > {shlex.quote(outside)}"
    try:
        run_command(sandbox.wrap(probe, worktree), cwd=worktree, timeout=60)
        leaked = os.path.exists(outside)
        confined = os.path.exists(inside)
    finally:
        for path in (inside, outside):
            try:
                os.unlink(path)
            except OSError:
                pass
        shutil.rmtree(outside_dir, ignore_errors=True)
    if not confined:
        raise SandboxError(
            f"{sandbox.name} sandbox self-check could not even write inside the worktree — "
            "the backend is not running; refusing to start"
        )
    if leaked:
        raise SandboxError(
            f"{sandbox.name} sandbox self-check FAILED: it allowed a write outside the "
            "worktree. Refusing to start — a proposer could plant code the measurement loads."
        )
