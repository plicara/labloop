"""Opt-in OS isolation for the propose step.

labloop *detects* edits to the protected set; it does not sandbox a shell
command. That is a real limit, not a gap: a same-user process can write code
the measurement loads from outside the protected set — a package that shadows a
protected module, or a `.pyc` raced into the bytecode mirror — and the digest
cannot see code it was never pointed at. The only boundary is OS isolation:
run the untrusted step somewhere it can write *only the worktree*, so anything
it plants elsewhere fails and anything it plants inside is digested.

This module is that boundary's seam, deliberately small. A sandbox is a command
template with `{command}` (and optional `{workdir}`) placeholders; `labloop`
builds one for bubblewrap or Docker when you ask for it, or you pass your own.
The propose step is wrapped; the run step is not, because the measurement may
legitimately need the network and the propose step is where the writing happens.

Nothing here is required. `--sandbox none` (the default) is exactly 0.3.0.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass

from .types import UsageError

__all__ = [
    "TemplateSandbox",
    "bwrap_template",
    "detect_sandbox",
    "docker_template",
    "resolve_sandbox",
]

# A template must place the real command somewhere, or the sandbox would run
# nothing and the trial would silently measure the unchanged tree.
_PLACEHOLDER = "{command}"


@dataclass(frozen=True)
class TemplateSandbox:
    """A command template that confines a child to the worktree.

    `template` must contain `{command}`; `{workdir}` is filled with the loop's
    working directory when present. The name is for logs and the manifest.
    """

    name: str
    template: str

    def __post_init__(self) -> None:
        if _PLACEHOLDER not in self.template:
            raise UsageError(
                f"sandbox template must contain {_PLACEHOLDER!r} (it would otherwise "
                "run nothing and every trial would measure the unchanged tree)"
            )

    def wrap(self, command: str, workdir: str) -> str:
        return (
            self.template.replace("{workdir}", workdir).replace(_PLACEHOLDER, command)
        )


def bwrap_template() -> str:
    """Bubblewrap: read-only everything, the worktree writable.

    Network stays up — a proposing agent usually needs it — and the root
    filesystem is read-only, so a write outside the worktree fails instead of
    landing in a place the digest does not inspect.
    """
    return (
        "bwrap --die-with-parent --dev /dev --proc /proc --ro-bind / / "
        "--bind {workdir} {workdir} --chdir {workdir} -- {command}"
    )


def docker_template(image: str = "python:3.12-slim") -> str:
    """Docker: the container filesystem is the confine.

    Writes outside the bind-mounted worktree vanish with the container. The
    image must be able to run the propose command (its language, its tools).
    """
    return (
        f"docker run --rm -v {{workdir}}:{{workdir}} -w {{workdir}} "
        f"{image} sh -lc {_PLACEHOLDER}"
    )


def detect_sandbox() -> TemplateSandbox | None:
    """The strongest sandbox this machine can offer, or None.

    bubblewrap is preferred: it is lighter than a container and needs no daemon.
    """
    if shutil.which("bwrap"):
        return TemplateSandbox("bwrap", bwrap_template())
    if shutil.which("docker"):
        return TemplateSandbox("docker", docker_template())
    return None


def resolve_sandbox(choice: str | None, template: str | None) -> TemplateSandbox | None:
    """Turn the CLI's `--sandbox`/`--sandbox-exec` into a sandbox, or None.

    Fails loudly when isolation is *requested* but unavailable: a user who asked
    for a boundary and silently got none is worse off than one who was told no.
    """
    if template is not None:
        return TemplateSandbox("custom", template)
    if choice in (None, "none"):
        return None
    if choice == "auto":
        found = detect_sandbox()
        if found is None:
            raise UsageError(
                "--sandbox auto found no isolation backend (bwrap or docker) — "
                "install one, pass --sandbox-exec, or use --sandbox none and accept "
                "that a proposer can write outside the worktree"
            )
        return found
    if choice == "bwrap":
        if not shutil.which("bwrap"):
            raise UsageError("--sandbox bwrap requested but bwrap is not on PATH")
        return TemplateSandbox("bwrap", bwrap_template())
    if choice == "docker":
        if not shutil.which("docker"):
            raise UsageError("--sandbox docker requested but docker is not on PATH")
        return TemplateSandbox("docker", docker_template())
    raise UsageError(f"unknown sandbox {choice!r}")
