"""The sandbox dispatcher: backend selection, wrapping, and the self-check.

The pure tests pin the command shapes and the fail-closed behaviour; the last
two exercise a real backend when the machine has one.
"""

from __future__ import annotations

import shlex

import pytest

from labloop import (
    BwrapSandbox,
    DockerSandbox,
    Experiment,
    Goal,
    LandlockSandbox,
    SandboxError,
    SeatbeltSandbox,
    TemplateSandbox,
    UsageError,
    available_backends,
    resolve_sandbox,
    verify_sandbox,
)
from labloop.cli import main
from labloop.sandbox import landlock_available

HAS_BACKEND = bool(available_backends())


# --- selection ---------------------------------------------------------------

def test_no_choice_is_no_isolation():
    assert resolve_sandbox(None) is None
    assert resolve_sandbox("none") is None


def test_a_custom_template_wins_and_is_used_verbatim():
    sandbox = resolve_sandbox("none", "echo {command} # {workdir}")
    assert sandbox is not None
    assert sandbox.wrap("do x", "/wt") == "echo do x # /wt"


def test_a_template_without_the_placeholder_is_refused():
    with pytest.raises(SandboxError):
        resolve_sandbox(None, "echo hello")


def test_auto_returns_a_backend_or_fails_loudly(monkeypatch):
    if HAS_BACKEND:
        assert resolve_sandbox("auto") is not None
    else:
        with pytest.raises(SandboxError):
            resolve_sandbox("auto")


def test_auto_never_picks_docker(monkeypatch):
    # Docker is the heavy fallback; auto must not choose it even if present,
    # unless nothing lighter exists.
    monkeypatch.setattr("labloop.sandbox._which", lambda name: name == "docker")
    monkeypatch.setattr("labloop.sandbox.seatbelt_available", lambda: False)
    monkeypatch.setattr("labloop.sandbox.landlock_available", lambda: False)
    monkeypatch.setattr("labloop.sandbox.user_namespaces_work", lambda: False)
    with pytest.raises(SandboxError):
        resolve_sandbox("auto")


def test_naming_an_absent_backend_is_an_error(monkeypatch):
    monkeypatch.setattr("labloop.sandbox._which", lambda name: False)
    monkeypatch.setattr("labloop.sandbox.landlock_available", lambda: False)
    monkeypatch.setattr("labloop.sandbox.seatbelt_available", lambda: False)
    for name in ("bwrap", "docker", "landlock", "seatbelt"):
        with pytest.raises(SandboxError):
            resolve_sandbox(name)


# --- command shapes ----------------------------------------------------------

def test_bwrap_confines_writes_to_the_worktree_and_maps_tmp_inside_it():
    command = BwrapSandbox().wrap("make", "/wt")
    assert "bwrap" in command
    assert "--ro-bind / /" in command
    assert "--bind /wt /wt" in command
    assert "--bind /wt/.labloop-tmp /tmp" in command      # /tmp must NOT be the real one


def test_landlock_runs_the_bundled_wrapper():
    command = LandlockSandbox(python="/usr/bin/python3").wrap("make", "/wt")
    assert "-m labloop._landlock /wt --" in command
    assert shlex.quote("make") in command


def test_seatbelt_denies_by_default_and_allows_only_the_worktree():
    command = SeatbeltSandbox().wrap("make", "/wt")
    assert "/usr/bin/sandbox-exec" in command
    assert "(deny default)" in command
    assert '(allow file-write* (subpath "/wt"))' in command


def test_docker_is_read_only_and_mounts_only_the_worktree():
    command = DockerSandbox(image="img:1").wrap("make", "/wt")
    assert "docker run --rm" in command and "--read-only" in command
    assert "-v /wt:/wt:rw" in command
    assert "img:1" in command


# --- experiment validation ---------------------------------------------------

def test_an_experiment_rejects_an_unknown_sandbox():
    with pytest.raises(UsageError):
        Experiment(run="true", metric="m", goal=Goal.MAXIMIZE, sandbox="firejail")


def test_an_experiment_rejects_a_template_without_the_placeholder():
    with pytest.raises(UsageError):
        Experiment(run="true", metric="m", goal=Goal.MAXIMIZE, sandbox_exec="bwrap /")


# --- the self-check ----------------------------------------------------------

def test_the_self_check_rejects_a_sandbox_that_does_not_confine(tmp_path):
    # A template that runs the command unchanged is not a sandbox; the probe
    # must notice the write outside landing.
    noop = TemplateSandbox("noop", "{command}")
    with pytest.raises(SandboxError):
        verify_sandbox(noop, str(tmp_path))


@pytest.mark.skipif(not landlock_available(), reason="no Landlock on this kernel")
def test_the_self_check_accepts_the_landlock_backend(tmp_path):
    verify_sandbox(LandlockSandbox(), str(tmp_path))   # raises if it fails


# --- wiring ------------------------------------------------------------------

def test_a_non_confining_template_is_refused_at_startup(project, capsys):
    # --sandbox-exec is also verified: a template that merely prefixes the
    # command is not a sandbox, and the self-check must catch that before trial 0.
    assert main([
        "run", "--run", "python train.py", "--metric", "val_loss",
        "--propose", "true",
        "--sandbox-exec", "env LABLOOP_PROBE=1 {command}",
        "--trials", "1",
    ]) == 2
    assert "self-check FAILED" in capsys.readouterr().err


@pytest.mark.skipif(not landlock_available(), reason="no Landlock on this kernel")
def test_run_with_the_auto_sandbox_wraps_and_verifies(project, capsys):
    # End to end through a real backend: the self-check runs, the propose step
    # is confined, and a change inside the worktree still lands.
    assert main([
        "run", "--run", "python train.py", "--metric", "val_loss",
        "--propose", "printf 'x\\n' >> train.py", "--sandbox", "auto",
        "--trials", "1",
    ]) == 0
    capsys.readouterr()
