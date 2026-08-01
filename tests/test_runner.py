"""Running a command under a wall-clock budget.

The timeout path is the one worth testing: a training script that spawns
workers and is then killed at the budget must not leave them running, or the
next trial competes with them for the machine.
"""

from __future__ import annotations

import os
import signal
import subprocess
import time
from contextlib import suppress

import pytest

from labloop import run_command

MARK = "88931"  # a distinctive sleep duration, easy to find among real processes


def sleepers() -> list[int]:
    listing = subprocess.run(["ps", "-eo", "pid,args"], capture_output=True, text=True).stdout
    return [
        int(line.split()[0])
        for line in listing.splitlines()
        if f"sleep {MARK}" in line and "ps -eo" not in line
    ]


@pytest.fixture
def no_stragglers():
    """Clean up after a failure, so one leak does not fail every later run."""
    yield
    for pid in sleepers():
        with suppress(ProcessLookupError, PermissionError):
            os.kill(pid, signal.SIGKILL)


def test_captures_output_and_exit_code(tmp_path):
    completed = run_command("echo hello", cwd=tmp_path)
    assert completed.ok
    assert completed.returncode == 0
    assert "hello" in completed.output


def test_stderr_is_merged_into_the_output(tmp_path):
    completed = run_command("echo oops >&2", cwd=tmp_path)
    assert "oops" in completed.output


def test_a_non_zero_exit_is_not_ok(tmp_path):
    completed = run_command("exit 3", cwd=tmp_path)
    assert completed.returncode == 3
    assert not completed.ok
    assert not completed.timed_out


def test_output_that_is_not_utf8_does_not_crash(tmp_path):
    completed = run_command(
        r"""python -c 'import os; os.write(1, b"val=1.5 \xff\xfe\n")'""", cwd=tmp_path
    )
    assert completed.ok
    assert "val=1.5" in completed.output


def test_the_tail_is_bounded(tmp_path):
    completed = run_command("python -c \"print('x' * 20000)\"", cwd=tmp_path)
    assert len(completed.output) > 10000
    assert len(completed.tail) <= 4000, "the ledger stores the tail, not the whole log"


def test_a_timeout_is_reported_not_raised(tmp_path):
    completed = run_command("sleep 5", cwd=tmp_path, timeout=0.3)
    assert completed.timed_out
    assert not completed.ok
    assert completed.returncode is None


def test_output_printed_before_a_timeout_survives(tmp_path):
    completed = run_command("echo partial; sleep 5", cwd=tmp_path, timeout=0.5)
    assert completed.timed_out
    assert "partial" in completed.output, "the ledger should keep how far it got"


def test_the_environment_is_extended_not_replaced(tmp_path):
    completed = run_command("echo $LABLOOP_PROBE:$HOME", cwd=tmp_path, env={"LABLOOP_PROBE": "x"})
    assert completed.output.strip().startswith("x:")
    assert completed.output.strip() != "x:", "the inherited environment must survive"


def test_the_command_runs_in_the_given_directory(tmp_path):
    (tmp_path / "marker.txt").write_text("here\n")
    assert "marker.txt" in run_command("ls", cwd=tmp_path).output


@pytest.mark.skipif(os.name != "posix", reason="process groups are POSIX")
def test_a_timeout_kills_children_the_command_spawned(tmp_path, no_stragglers):
    # The documented guarantee: a training script's workers must not outlive
    # the trial that started them and contend with the next one.
    script = tmp_path / "spawn.sh"
    script.write_text(f"#!/bin/sh\nsleep {MARK} &\nsleep {MARK} &\nsleep {MARK}\n")
    script.chmod(0o755)

    assert sleepers() == [], "a stale process would make this meaningless"
    completed = run_command(str(script), cwd=tmp_path, timeout=0.5)
    assert completed.timed_out

    deadline = time.monotonic() + 5
    while sleepers() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert sleepers() == [], "children outlived the timeout"


def test_duration_is_measured(tmp_path):
    completed = run_command("sleep 0.2", cwd=tmp_path)
    assert completed.duration_seconds >= 0.2
