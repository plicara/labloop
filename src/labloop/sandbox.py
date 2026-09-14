"""OS isolation for the propose step, via bubblewrap (Linux only).

labloop *detects* edits to the protected set. It cannot stop a proposer writing
code the measurement later loads from somewhere the digest was never pointed at.
The boundary is OS isolation: run the untrusted propose step where it can write
only the worktree.

There is exactly **one** backend — bubblewrap — on purpose. Every extra backend
is another set of escape paths to reason about, and a pure-syscall Landlock
sandbox we tried could not express the things that actually mattered here
(hiding the project's git metadata, hiding privileged local sockets, and
stopping packet traffic, not just web connections). bubblewrap builds a mount
namespace, a PID namespace, and (optionally) a network namespace, which is what
closes those.

What bubblewrap gives us, and how this module configures it:

* read everything, write only the worktree (`--ro-bind / /`, `--bind <wt> <wt>`);
* the project's `.git` is bound **read-only**, so a proposer cannot plant a git
  hook that would then run *outside* the sandbox when labloop itself commits;
* privileged local sockets (docker/podman/containerd) are masked with
  `/dev/null`, so a user in the `docker` group — effectively root — is not a
  way out;
* a private `/tmp` (a tmpfs), so the bytecode mirror labloop creates under the
  real `/tmp` is unreachable;
* a PID namespace and `--die-with-parent`, so a process the proposer detaches
  cannot outlive the propose step and race the measurement;
* the network is off by default (`--unshare-net`) and enabled with
  `--sandbox-network`.

Linux only, by decision: on any other platform `--sandbox auto` refuses to run
rather than running unconfined. bubblewrap also needs unprivileged user
namespaces, which some distributions disable; that is detected and reported,
never worked around.
"""
from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import tempfile
from dataclasses import dataclass

from .runner import run_command

__all__ = [
    "BwrapSandbox",
    "Sandbox",
    "SandboxError",
    "available_backends",
    "resolve_sandbox",
    "verify_sandbox",
]

_SHELL = "/bin/sh"

#: Same-user access to these is root-equivalent (the daemon runs as root and
#: does the namespaces for you). Masked inside the sandbox when present.
_SENSITIVE_SOCKETS = (
    "/run/docker.sock",
    "/var/run/docker.sock",
    "/run/podman/podman.sock",
    "/var/run/podman/podman.sock",
    "/run/containerd/containerd.sock",
    "/run/k3s/containerd/containerd.sock",
)


class SandboxError(RuntimeError):
    """Isolation was requested but cannot be provided, or failed its self-check."""


@dataclass(frozen=True)
class BwrapSandbox:
    """A bubblewrap confinement: read all, write only the worktree."""

    name: str = "bwrap"

    def _args(self, command: str, worktree: str, network: bool) -> list[str]:
        # Absolute: a relative worktree makes `--chdir` resolve against the
        # sandbox root, so the write would land on a read-only path.
        worktree = os.path.abspath(worktree)
        # No --tmpfs /tmp: it would mask the worktree whenever the worktree lives
        # under /tmp, and the read-only root already makes the host /tmp
        # unwritable, which is what keeps the bytecode mirror out of reach.
        # Scratch goes inside the worktree instead.
        scratch = os.path.join(worktree, ".labloop-tmp")
        args = [
            "bwrap",
            "--die-with-parent",
            "--unshare-pid",
            "--ro-bind", "/", "/",
            "--dev", "/dev",
            "--proc", "/proc",
            "--bind", worktree, worktree,
            "--tmpfs", scratch,
        ]
        git = os.path.join(worktree, ".git")
        if os.path.exists(git):
            args += ["--ro-bind", git, git]           # no hook/refdir planting
        for socket in _SENSITIVE_SOCKETS:
            if os.path.exists(socket):
                # /var/run is a symlink to /run; bwrap cannot create a mount
                # point at the symlinked spelling, so mask the real path.
                args += ["--ro-bind", "/dev/null", os.path.realpath(socket)]
        if not network:
            args += ["--unshare-net"]
        args += ["--chdir", worktree, "--setenv", "TMPDIR", scratch,
                 "--", _SHELL, "-c", command]
        return args

    def wrap(self, command: str, worktree: str, network: bool = False) -> str:
        # The outer `exec` is our shell handing off to bwrap; the command itself
        # is NOT prefixed with `exec`, which would swallow any `&&` chain in it
        # (and quietly defeat the self-check, whose probe chains two writes).
        return "exec " + " ".join(shlex.quote(a) for a in self._args(command, worktree, network))


#: One backend, so the sandbox type is just that backend.
Sandbox = BwrapSandbox


# --- availability ------------------------------------------------------------

def _which(name: str) -> bool:
    return shutil.which(name) is not None


def user_namespaces_work() -> bool:
    """Whether an unprivileged user can map a user namespace (bubblewrap needs it)."""
    if not _which("unshare"):
        return False
    return subprocess.run(
        ["unshare", "--user", "--map-root-user", "true"], capture_output=True
    ).returncode == 0


def available_backends() -> list[str]:
    if _which("bwrap") and user_namespaces_work():
        return ["bwrap"]
    return []


def resolve_sandbox(choice: str | None = "auto") -> Sandbox | None:
    """Turn `--sandbox` into the backend, or None for no isolation.

    `auto` and `bwrap` are the same now that there is one backend; both refuse
    loudly when bubblewrap cannot run, because a proposer that asked to be
    confined and silently was not is worse off than one that was told no.
    """
    if choice in (None, "none"):
        return None
    if choice in ("auto", "bwrap"):
        if not _which("bwrap"):
            raise SandboxError(
                "no sandbox backend: bubblewrap (bwrap) is not installed. "
                "Install it (e.g. `apt install bubblewrap`), or pass --sandbox none "
                "to run the proposer unconfined."
            )
        if not user_namespaces_work():
            raise SandboxError(
                "bubblewrap is installed but unprivileged user namespaces are blocked, "
                "so it cannot confine anything (on Ubuntu this is "
                "kernel.apparmor_restrict_unprivileged_userns=1). Enable them, or pass "
                "--sandbox none to run the proposer unconfined."
            )
        return BwrapSandbox()
    raise SandboxError(f"unknown sandbox {choice!r} (this build supports: auto, bwrap, none)")


def verify_sandbox(sandbox: Sandbox, worktree: str) -> None:
    """Prove the sandbox confines *this* machine before trial 0.

    A write inside the worktree must work and a write outside it must be denied.
    If either is wrong, refuse — a sandbox that silently does nothing is the
    failure mode this whole feature exists to prevent.
    """
    outside_dir = tempfile.mkdtemp(prefix="labloop-verify-")
    worktree = os.path.abspath(worktree)
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
