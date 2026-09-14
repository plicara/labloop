"""The bubblewrap sandbox: selection, the command it builds, and the self-check."""

from __future__ import annotations

import os

import pytest

from labloop import (
    BwrapSandbox,
    Experiment,
    Goal,
    SandboxError,
    UsageError,
    available_backends,
    resolve_sandbox,
    verify_sandbox,
)
from labloop.cli import main

HAS_BWRAP = bool(available_backends())


# --- selection: one backend, and it fails closed -----------------------------

def test_none_is_no_isolation():
    assert resolve_sandbox("none") is None
    assert resolve_sandbox(None) is None


def test_auto_refuses_without_bubblewrap(monkeypatch):
    monkeypatch.setattr("labloop.sandbox._which", lambda name: False)
    for choice in ("auto", "bwrap"):
        with pytest.raises(SandboxError):
            resolve_sandbox(choice)


def test_auto_refuses_when_user_namespaces_are_blocked(monkeypatch):
    monkeypatch.setattr("labloop.sandbox._which", lambda name: True)
    monkeypatch.setattr("labloop.sandbox.user_namespaces_work", lambda: False)
    with pytest.raises(SandboxError):
        resolve_sandbox("auto")


def test_removed_backends_are_refused():
    for gone in ("landlock", "seatbelt", "docker"):
        with pytest.raises(SandboxError):
            resolve_sandbox(gone)


# --- the command it builds ---------------------------------------------------

def test_it_reads_everything_and_writes_only_the_worktree():
    command = BwrapSandbox().wrap("make", "/wt")
    assert "--ro-bind / /" in command
    assert "--bind /wt /wt" in command
    assert "--unshare-pid" in command          # detached processes cannot outlive it


def test_a_declared_writable_dir_is_bound_read_write(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    out = tmp_path / "evidence"
    out.mkdir()
    command = BwrapSandbox().wrap("x", str(work), writable=[str(out)])
    assert f"--bind {out} {out}" in command


def test_a_writable_dir_inside_the_worktree_is_refused(tmp_path):
    with pytest.raises(SandboxError):
        BwrapSandbox().wrap("x", str(tmp_path), writable=[str(tmp_path / "out")])


def test_a_missing_writable_dir_is_refused(tmp_path):
    with pytest.raises(SandboxError):
        BwrapSandbox().wrap("x", str(tmp_path), writable=[str(tmp_path / "nope")])


def test_the_network_is_off_by_default():
    assert "--unshare-net" in BwrapSandbox().wrap("x", "/wt")


def test_the_network_can_be_turned_on():
    assert "--unshare-net" not in BwrapSandbox().wrap("x", "/wt", True)


def test_the_git_metadata_is_bound_read_only(tmp_path):
    (tmp_path / ".git").mkdir()
    command = BwrapSandbox().wrap("x", str(tmp_path))
    assert f"--ro-bind {tmp_path}/.git {tmp_path}/.git" in command


def test_a_privileged_socket_is_masked(tmp_path, monkeypatch):
    socket = tmp_path / "docker.sock"
    socket.write_text("")
    monkeypatch.setattr("labloop.sandbox._SENSITIVE_SOCKETS", (str(socket),))
    command = BwrapSandbox().wrap("x", "/wt")
    assert f"--ro-bind /dev/null {socket}" in command


# --- validation --------------------------------------------------------------

def test_the_writable_dirs_are_recorded():
    assert Experiment(run="true", metric="m", goal=Goal.MAXIMIZE,
                      sandbox_writes=("/logs",)).spec()["sandbox_writes"] == ["/logs"]
    assert Experiment(run="true", metric="m", goal=Goal.MAXIMIZE).spec()["sandbox_writes"] == []


def test_an_experiment_rejects_an_unknown_sandbox():
    with pytest.raises(UsageError):
        Experiment(run="true", metric="m", goal=Goal.MAXIMIZE, sandbox="docker")


def test_the_network_choice_is_recorded():
    assert Experiment(run="true", metric="m", goal=Goal.MAXIMIZE,
                      sandbox_network=True).spec()["sandbox_network"] is True
    assert Experiment(run="true", metric="m", goal=Goal.MAXIMIZE).spec()["sandbox_network"] is False


# --- the self-check ----------------------------------------------------------

def test_the_self_check_rejects_a_sandbox_that_does_not_confine(tmp_path):
    class Noop:
        name = "noop"

        def wrap(self, command: str, worktree: str, network: bool = False,
                 writable=()) -> str:
            return command

    with pytest.raises(SandboxError):
        verify_sandbox(Noop(), str(tmp_path))


@pytest.mark.skipif(not HAS_BWRAP, reason="bubblewrap is not available on this machine")
def test_the_self_check_accepts_bubblewrap(tmp_path):
    verify_sandbox(BwrapSandbox(), str(tmp_path))


@pytest.mark.skipif(not HAS_BWRAP, reason="bubblewrap is not available on this machine")
def test_the_self_check_proves_the_evidence_channel(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    out = tmp_path / "evidence"
    out.mkdir()
    verify_sandbox(BwrapSandbox(), str(work), writable=[str(out)])
    assert list(out.iterdir()) == []   # the probe cleans up after itself


# --- wiring through the CLI --------------------------------------------------

def test_run_refuses_when_bubblewrap_is_unavailable(project, monkeypatch, capsys):
    monkeypatch.setattr("labloop.sandbox._which", lambda name: False)
    rc = main([
        "run", "--run", "python train.py", "--metric", "val_loss",
        "--propose", "true", "--sandbox", "auto", "--trials", "1",
    ])
    assert rc == 2
    assert "bubblewrap" in capsys.readouterr().err


@pytest.mark.skipif(not HAS_BWRAP, reason="bubblewrap is not available on this machine")
def test_run_with_the_sandbox_wraps_and_verifies(project, capsys):
    assert main([
        "run", "--run", "python train.py", "--metric", "val_loss",
        "--propose", "printf 'x\\n' >> train.py", "--sandbox", "auto", "--trials", "1",
    ]) == 0
    capsys.readouterr()


# --- the library default matches the CLI -------------------------------------

def test_the_library_default_is_confined(monkeypatch):
    monkeypatch.delenv("LABLOOP_SANDBOX", raising=False)
    assert Experiment(run="true", metric="m", goal=Goal.MAXIMIZE).sandbox == "auto"


def test_the_default_is_overridable_by_environment(monkeypatch):
    monkeypatch.setenv("LABLOOP_SANDBOX", "none")
    assert Experiment(run="true", metric="m", goal=Goal.MAXIMIZE).sandbox == "none"


# --- --sandbox-write is an evidence channel, not a hole ----------------------

def _real(p):
    return os.path.realpath(str(p))


def test_a_dedicated_evidence_dir_is_allowed(tmp_path):
    from labloop.sandbox import _validate_writable
    evidence = tmp_path.parent / (tmp_path.name + "-evidence")
    evidence.mkdir()
    try:
        assert _validate_writable(str(evidence), _real(tmp_path)) == _real(evidence)
    finally:
        evidence.rmdir()


def test_writable_inside_the_worktree_is_refused(tmp_path):
    from labloop.sandbox import _validate_writable
    inside = tmp_path / "inside"
    inside.mkdir()
    with pytest.raises(SandboxError):
        _validate_writable(str(inside), _real(tmp_path))


def test_writable_that_contains_the_worktree_is_refused(tmp_path):
    from labloop.sandbox import _validate_writable
    # tmp_path's parent is an ancestor of the worktree; binding it read-write
    # would re-open the worktree and everything beside it.
    with pytest.raises(SandboxError):
        _validate_writable(str(tmp_path.parent), _real(tmp_path))


def test_the_filesystem_root_is_refused(tmp_path):
    from labloop.sandbox import _validate_writable
    with pytest.raises(SandboxError):
        _validate_writable("/", _real(tmp_path))


def test_a_shared_or_temporary_root_is_refused(tmp_path):
    from labloop.sandbox import _validate_writable
    # Any of these that exists and is not already an ancestor must still be
    # refused as a shared location rather than a dedicated evidence dir.
    for root in ("/usr", "/dev", "/proc"):
        if os.path.isdir(root) and not _real(tmp_path).startswith(_real(root) + os.sep):
            with pytest.raises(SandboxError):
                _validate_writable(root, _real(tmp_path))


def test_a_missing_writable_is_refused(tmp_path):
    from labloop.sandbox import _validate_writable
    with pytest.raises(SandboxError):
        _validate_writable(str(tmp_path.parent / "nope-does-not-exist"), _real(tmp_path))
