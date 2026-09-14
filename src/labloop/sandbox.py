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
* optionally, writable binds outside the worktree (`--sandbox-write`), the one
  sanctioned evidence channel: a sandboxed proposer cannot otherwise leave any
  record of what it tried. Each path is canonicalised and validated — refused if
  it is inside the worktree, an ancestor of it, or a shared/temporary root — so
  the channel cannot be turned into a broad hole (see `_validate_writable`).
* a PID namespace and `--die-with-parent`, so a process the proposer detaches
  cannot outlive the propose step and race the measurement;
* the network is off by default (`--unshare-net`) and enabled with
  `--sandbox-network`.

What this does **not** do:

* The network namespace blocks IP traffic. Unix-domain sockets are filesystem
  objects and stay reachable, so a same-user process listening on a local socket
  can still receive what the proposer sends; the masks below cover the
  root-equivalent container sockets, not every possible local relay. Treat
  "network off" as "no IP egress", not as "cannot talk to anything".
* Reads are open by design (fix that with a credential-free host, not here), and
  bubblewrap shares the host kernel — it is not a virtual machine.

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
from collections.abc import Sequence
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


#: Directories a writable bind must never be: the filesystem root and the
#: shared/temporary/cache roots. Binding one read-write re-opens a broad area
#: after the read-only root — `/tmp` exposes the bytecode mirror the sandbox
#: relies on keeping out of reach, and `/` disables the sandbox entirely.
_BROAD_ROOTS = frozenset({
    "/", "/tmp", "/var/tmp", "/var", "/run", "/dev", "/proc", "/sys",
    "/etc", "/usr", "/usr/local", "/opt", "/srv", "/mnt", "/media", "/root",
    os.path.realpath(os.path.expanduser("~")),
})


def _validate_writable(path: str, worktree: str) -> str:
    """Return the real path of a sanctioned writable bind, or raise.

    `--sandbox-write` is an evidence channel, not a general hole: a directory
    that is neither inside the worktree (the trial would commit or revert it)
    nor an ancestor of it (which would re-open the worktree and everything beside
    it read-write), and not a shared or temporary root.
    """
    real = os.path.realpath(path)
    if not os.path.isdir(real):
        raise SandboxError(
            f"--sandbox-write {path!r} does not exist — create it first, so a typo "
            "fails loudly here instead of silently losing the evidence."
        )
    if real == worktree or real.startswith(worktree + os.sep):
        raise SandboxError(
            f"--sandbox-write {path!r} is inside the worktree — it would be committed "
            "or reverted with the trial instead of surviving it."
        )
    if worktree == real or worktree.startswith(real + os.sep):
        raise SandboxError(
            f"--sandbox-write {path!r} is an ancestor of the worktree — binding it "
            "read-write would re-open the worktree and everything beside it. Point it "
            "at a dedicated evidence directory that does not contain the worktree."
        )
    if real in _BROAD_ROOTS:
        raise SandboxError(
            f"--sandbox-write {path!r} is a shared or temporary location, not a "
            "dedicated evidence directory. Give it a directory of its own."
        )
    return real


@dataclass(frozen=True)
class BwrapSandbox:
    """A bubblewrap confinement: read all, write only the worktree."""

    name: str = "bwrap"

    def _args(self, command: str, worktree: str, network: bool,
               writable: Sequence[str] = ()) -> list[str]:
        # Absolute and canonical: a relative worktree makes `--chdir` resolve
        # against the sandbox root; a symlinked one would let a writable bind
        # point back inside it past the containment check.
        worktree = os.path.realpath(worktree)
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
        for path in writable:
            outside = _validate_writable(path, worktree)
            args += ["--bind", outside, outside]
        git = os.path.join(worktree, ".git")
        if os.path.exists(git):
            args += ["--ro-bind", git, git]           # no hook/refdir planting
        masked: set[str] = set()
        for socket in _SENSITIVE_SOCKETS:
            if not os.path.exists(socket):
                continue
            # /var/run is a symlink to /run and bwrap cannot make a mount point
            # at the symlinked spelling, so mask the real path; two names for
            # one socket must not produce two mounts.
            real = os.path.realpath(socket)
            if real not in masked:
                masked.add(real)
                args += ["--ro-bind", "/dev/null", real]
        if not network:
            args += ["--unshare-net"]
        args += ["--chdir", worktree, "--setenv", "TMPDIR", scratch,
                 "--", _SHELL, "-c", command]
        return args

    def wrap(self, command: str, worktree: str, network: bool = False,
             writable: Sequence[str] = ()) -> str:
        # The outer `exec` is our shell handing off to bwrap; the command itself
        # is NOT prefixed with `exec`, which would swallow any `&&` chain in it
        # (and quietly defeat the self-check, whose probe chains two writes).
        args = self._args(command, worktree, network, writable)
        return "exec " + " ".join(shlex.quote(a) for a in args)


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


def verify_sandbox(sandbox: Sandbox, worktree: str,
                   writable: Sequence[str] = ()) -> None:
    """Prove the sandbox confines *this* machine before trial 0.

    A write inside the worktree must work and a write outside it must be denied.
    If either is wrong, refuse — a sandbox that silently does nothing is the
    failure mode this whole feature exists to prevent. Each declared writable
    dir gets the same treatment in reverse: a write there must work, or the
    evidence channel is silently broken and every trial's reasoning is lost.
    """
    outside_dir = tempfile.mkdtemp(prefix="labloop-verify-")
    worktree = os.path.abspath(worktree)
    inside = os.path.join(worktree, ".labloop-verify")
    outside = os.path.join(outside_dir, "escape")
    write_probes = [
        os.path.join(os.path.realpath(path), ".labloop-verify-write")
        for path in writable
    ]
    steps = [f"touch {shlex.quote(inside)}"]
    steps += [f"touch {shlex.quote(path)}" for path in write_probes]
    steps += [f"echo x > {shlex.quote(outside)}"]
    probe = " && ".join(steps)
    try:
        run_command(sandbox.wrap(probe, worktree, writable=writable), cwd=worktree, timeout=60)
        leaked = os.path.exists(outside)
        confined = os.path.exists(inside)
        evidenced = [os.path.exists(path) for path in write_probes]
    finally:
        for path in (inside, outside, *write_probes):
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
    if not all(evidenced):
        missing = [path for path, ok in zip(write_probes, evidenced, strict=True) if not ok]
        raise SandboxError(
            f"{sandbox.name} sandbox self-check could not write to the declared "
            f"evidence dir(s) {missing} — every trial's reasoning would be "
            "silently lost. Refusing to start."
        )
    if leaked:
        raise SandboxError(
            f"{sandbox.name} sandbox self-check FAILED: it allowed a write outside the "
            "worktree. Refusing to start — a proposer could plant code the measurement loads."
        )
