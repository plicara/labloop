"""Running a command under a wall-clock budget."""

from __future__ import annotations

import os
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

__all__ = ["Completed", "run_command"]

_TAIL_CHARS = 4000


@dataclass(frozen=True)
class Completed:
    returncode: int | None
    output: str
    duration_seconds: float
    timed_out: bool

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and not self.timed_out

    @property
    def tail(self) -> str:
        return self.output[-_TAIL_CHARS:]


def run_command(
    command: str,
    cwd: str | Path = ".",
    timeout: float = 300.0,
    env: dict[str, str] | None = None,
) -> Completed:
    """Run `command` in a shell, capturing merged stdout/stderr.

    On timeout the whole process group is killed, not just the shell. A
    training script that spawns workers would otherwise leave them running and
    contending for the GPU with the next trial.
    """
    merged_env = {**os.environ, **(env or {})}
    start = time.monotonic()

    popen_kwargs: dict = {
        "cwd": str(cwd),
        "shell": True,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.STDOUT,
        "text": True,
        "errors": "replace",
        "env": merged_env,
    }
    if os.name == "posix":
        popen_kwargs["start_new_session"] = True

    process = subprocess.Popen(command, **popen_kwargs)

    timed_out = False
    try:
        output, _ = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        _terminate(process)
        output, _ = process.communicate()

    return Completed(
        returncode=None if timed_out else process.returncode,
        output=output or "",
        duration_seconds=time.monotonic() - start,
        timed_out=timed_out,
    )


def _terminate(process: subprocess.Popen) -> None:
    """Kill the process and any children it spawned."""
    if os.name == "posix":
        try:
            group = os.getpgid(process.pid)
            os.killpg(group, signal.SIGTERM)
            try:
                process.wait(timeout=10)
                return
            except subprocess.TimeoutExpired:
                os.killpg(group, signal.SIGKILL)
            return
        except (ProcessLookupError, PermissionError):
            pass
    process.kill()
