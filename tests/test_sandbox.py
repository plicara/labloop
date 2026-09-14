"""The bubblewrap sandbox: selection, the command it builds, and the self-check."""

from __future__ import annotations

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

        def wrap(self, command: str, worktree: str, network: bool = False) -> str:
            return command

    with pytest.raises(SandboxError):
        verify_sandbox(Noop(), str(tmp_path))


@pytest.mark.skipif(not HAS_BWRAP, reason="bubblewrap is not available on this machine")
def test_the_self_check_accepts_bubblewrap(tmp_path):
    verify_sandbox(BwrapSandbox(), str(tmp_path))


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
