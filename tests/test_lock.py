"""One loop per ledger.

Two loops appending to one ledger interleave trial indices and disagree about
the incumbent. The lock is flock-based, so the operating system releases it
when the holder dies — there is no stale-lock state, and if acquiring fails
the named holder is alive right now.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap

import pytest

from labloop import Experiment, LedgerLock, LedgerLockedError, Loop

from .conftest import FakeWorkspace, make_loop


def test_the_lock_is_exclusive(tmp_path):
    ledger = tmp_path / "l.jsonl"
    with LedgerLock(ledger):
        with pytest.raises(LedgerLockedError, match="another labloop run"):
            LedgerLock(ledger).acquire()


def test_the_error_names_the_holder(tmp_path):
    ledger = tmp_path / "l.jsonl"
    with LedgerLock(ledger):
        with pytest.raises(LedgerLockedError, match=str(os.getpid())):
            LedgerLock(ledger).acquire()


def test_release_frees_it(tmp_path):
    ledger = tmp_path / "l.jsonl"
    lock = LedgerLock(ledger)
    lock.acquire()
    lock.release()
    with LedgerLock(ledger):
        pass


def test_reentrant_within_one_instance(tmp_path):
    # run() locks, and a nested baseline() must not deadlock against it.
    lock = LedgerLock(tmp_path / "l.jsonl")
    with lock:
        with lock:
            pass
        # Still held after the inner exit: the outer scope is not done.
        with pytest.raises(LedgerLockedError):
            LedgerLock(tmp_path / "l.jsonl").acquire()


def test_different_ledgers_do_not_contend(tmp_path):
    with LedgerLock(tmp_path / "a.jsonl"):
        with LedgerLock(tmp_path / "b.jsonl"):
            pass


def test_two_paths_to_one_ledger_do_contend(tmp_path):
    # Two worktrees pointing at a shared ledger reach it by different
    # spellings; the lock keys on the resolved path.
    (tmp_path / "sub").mkdir()
    direct = tmp_path / "l.jsonl"
    roundabout = tmp_path / "sub" / ".." / "l.jsonl"
    with LedgerLock(direct):
        with pytest.raises(LedgerLockedError):
            LedgerLock(roundabout).acquire()


def test_a_dead_holder_releases_automatically(tmp_path):
    # The property the design rests on: a crashed overnight run must not
    # leave a lock that a human has to find and delete.
    ledger = tmp_path / "l.jsonl"
    child = subprocess.run(
        [
            sys.executable,
            "-c",
            textwrap.dedent(
                f"""
                import sys
                sys.path.insert(0, {json.dumps(str(next(iter(sys.path))))})
                from labloop import LedgerLock
                LedgerLock({json.dumps(str(ledger))}).acquire()
                # exit without releasing: simulates a crash
                """
            ),
        ],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": os.pathsep.join(sys.path)},
    )
    assert child.returncode == 0, child.stderr
    with LedgerLock(ledger):
        pass  # acquiring after the holder died must succeed


def test_the_loop_refuses_a_locked_ledger(tmp_path):
    loop, _ = make_loop(tmp_path, run="echo val=1.0")
    with LedgerLock(tmp_path / "l.jsonl"):
        with pytest.raises(LedgerLockedError):
            loop.run(trials=1)


def test_baseline_holds_the_lock_too(tmp_path):
    loop, _ = make_loop(tmp_path, run="echo val=1.0")
    with LedgerLock(tmp_path / "l.jsonl"):
        with pytest.raises(LedgerLockedError):
            loop.baseline()


def test_wait_queues_instead_of_failing(tmp_path):
    exp = Experiment(run="echo val=1.0", metric="val", propose="true")
    loop = Loop(
        exp,
        workdir=tmp_path,
        ledger=tmp_path / "l.jsonl",
        workspace=FakeWorkspace(),
        wait_for_lock=True,
    )
    # Nothing holds the lock; --wait must not change the uncontended path.
    (trial,) = loop.run(trials=1)
    assert trial.outcome.value == "kept"


def test_the_lock_never_touches_the_working_tree(tmp_path):
    # A lock file beside the ledger would be an untracked file, and the
    # dirty-tree interlock would refuse to start because of the lock that
    # protects the start.
    loop, _ = make_loop(tmp_path, run="echo val=1.0")
    loop.baseline()
    assert list(tmp_path.iterdir()) == [tmp_path / "l.jsonl"], (
        "only the ledger belongs in the workdir"
    )
