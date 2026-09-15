"""The bubblewrap sandbox: selection, the command it builds, and the self-check."""

from __future__ import annotations

import os
import shlex
import sys
import time
from pathlib import Path

import pytest

from labloop import (
    BwrapSandbox,
    Experiment,
    Goal,
    SandboxError,
    UsageError,
    available_backends,
    resolve_sandbox,
    run_command,
    verify_sandbox,
)
from labloop.cli import main

HAS_BWRAP = bool(available_backends())


@pytest.fixture
def evidence_root(tmp_path_factory, monkeypatch):
    home = tmp_path_factory.mktemp("evidence-home")
    root = home / ".local" / "state" / "labloop" / "evidence"
    root.mkdir(parents=True)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    return root


@pytest.mark.parametrize("location", [".ssh", ".config", "arbitrary"])
def test_writes_outside_the_evidence_root_are_refused(tmp_path, evidence_root, location):
    outside = tmp_path / location
    outside.mkdir()
    with pytest.raises(SandboxError, match="evidence"):
        BwrapSandbox().wrap("true", str(tmp_path / "work"), writable=[str(outside)])


def test_the_evidence_root_itself_is_refused(tmp_path, evidence_root):
    with pytest.raises(SandboxError):
        BwrapSandbox().wrap("true", str(tmp_path / "work"), writable=[str(evidence_root)])


def test_an_evidence_symlink_cannot_grant_an_outside_directory(tmp_path, evidence_root):
    outside = tmp_path / "credentials"
    outside.mkdir()
    link = evidence_root / "linked"
    link.symlink_to(outside, target_is_directory=True)
    with pytest.raises(SandboxError):
        BwrapSandbox().wrap("true", str(tmp_path / "work"), writable=[str(link)])


def test_the_evidence_root_cannot_be_redirected(tmp_path, evidence_root):
    outside = tmp_path / "credentials"
    (outside / "run").mkdir(parents=True)
    evidence_root.rmdir()
    evidence_root.symlink_to(outside, target_is_directory=True)
    with pytest.raises(SandboxError):
        BwrapSandbox().wrap("true", str(tmp_path / "work"),
                            writable=[str(evidence_root / "run")])


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


def test_the_wrapper_explicitly_drops_capabilities_and_detaches_the_terminal():
    args = shlex.split(BwrapSandbox().wrap("true", "/wt"))
    assert "--new-session" in args
    assert "--cap-drop" in args
    assert args[args.index("--cap-drop") + 1] == "ALL"


def test_a_declared_writable_dir_is_bound_read_write(tmp_path, evidence_root):
    work = tmp_path / "work"
    work.mkdir()
    out = evidence_root / "run"
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


def test_the_self_check_preserves_existing_files(tmp_path, evidence_root):
    work = tmp_path / "work"
    work.mkdir()
    evidence = evidence_root / "run"
    evidence.mkdir()
    inside = work / ".labloop-verify"
    outside = evidence / ".labloop-verify-write"
    inside.write_text("user work")
    outside.write_text("user evidence")

    class Unavailable:
        name = "unavailable"

        def wrap(self, command, worktree, network=False, writable=()):
            raise SandboxError("unavailable")

    with pytest.raises(SandboxError, match="unavailable"):
        verify_sandbox(Unavailable(), str(work), writable=[str(evidence)])
    assert inside.read_text() == "user work"
    assert outside.read_text() == "user evidence"


@pytest.mark.skipif(not HAS_BWRAP, reason="bubblewrap is not available on this machine")
def test_the_self_check_accepts_bubblewrap(tmp_path):
    verify_sandbox(BwrapSandbox(), str(tmp_path))


@pytest.mark.skipif(not HAS_BWRAP, reason="bubblewrap is not available on this machine")
def test_the_self_check_proves_the_evidence_channel(tmp_path, evidence_root):
    work = tmp_path / "work"
    work.mkdir()
    out = evidence_root / "run"
    out.mkdir()
    verify_sandbox(BwrapSandbox(), str(work), writable=[str(out)])
    assert list(out.iterdir()) == []   # the probe cleans up after itself


@pytest.mark.skipif(not HAS_BWRAP, reason="bubblewrap is not available on this machine")
def test_bubblewrap_cannot_write_host_files_or_git_metadata(project, tmp_path_factory):
    outside = tmp_path_factory.mktemp("host") / "sentinel"
    outside.write_text("host data")
    sandbox = BwrapSandbox()
    read = run_command(sandbox.wrap(f"cat {shlex.quote(str(outside))}", str(project)),
                       cwd=project)
    assert read.ok and read.output.strip() == "host data"
    for target in (outside, project / ".git" / "config"):
        before = target.read_bytes()
        write = run_command(sandbox.wrap(f"echo changed > {shlex.quote(str(target))}",
                                         str(project)), cwd=project)
        assert not write.ok
        assert target.read_bytes() == before


@pytest.mark.skipif(not HAS_BWRAP, reason="bubblewrap is not available on this machine")
def test_bubblewrap_uses_a_private_network_namespace(tmp_path):
    host = os.readlink("/proc/self/ns/net")
    result = run_command(BwrapSandbox().wrap("readlink /proc/self/ns/net", str(tmp_path)),
                         cwd=tmp_path)
    assert result.ok
    assert result.output.strip() != host


@pytest.mark.skipif(not HAS_BWRAP, reason="bubblewrap is not available on this machine")
def test_bubblewrap_drops_capabilities_and_has_no_controlling_terminal(tmp_path):
    code = '''import os
from pathlib import Path
status = dict(line.split(":", 1) for line in Path("/proc/self/status").read_text().splitlines())
for field in ("CapEff", "CapPrm", "CapBnd"):
    assert int(status[field].strip(), 16) == 0, (field, status[field])
try:
    fd = os.open("/dev/tty", os.O_RDWR)
except OSError:
    pass
else:
    os.close(fd)
    raise AssertionError("sandbox has a controlling terminal")
'''
    command = f"{shlex.quote(sys.executable)} -c {shlex.quote(code)}"
    result = run_command(BwrapSandbox().wrap(command, str(tmp_path)), cwd=tmp_path)
    assert result.ok, result.output


@pytest.mark.skipif(not HAS_BWRAP, reason="bubblewrap is not available on this machine")
def test_a_detached_sandbox_child_cannot_write_after_the_proposal(tmp_path):
    marker = tmp_path / "late"
    ready = tmp_path / "ready"
    code = (f"import time,pathlib; pathlib.Path({str(ready)!r}).touch(); "
            f"time.sleep(1); pathlib.Path({str(marker)!r}).touch()")
    command = f"setsid {shlex.quote(sys.executable)} -c {shlex.quote(code)} >/dev/null 2>&1 &"
    command += f" while [ ! -e {shlex.quote(str(ready))} ]; do sleep 0.01; done"
    result = run_command(BwrapSandbox().wrap(command, str(tmp_path)), cwd=tmp_path, timeout=5)
    assert result.ok
    assert ready.exists()
    time.sleep(1.5)
    assert not marker.exists()


@pytest.mark.skipif(not HAS_BWRAP, reason="bubblewrap is not available on this machine")
def test_evidence_survives_both_kept_and_reverted_trials(project, evidence_root):
    from labloop import Ledger, Outcome

    evidence = evidence_root / "run"
    evidence.mkdir()
    assert main(["baseline", "--run", "python train.py", "--metric", "val_loss"]) == 0
    for metric, outcome in ((1, Outcome.KEPT), (3, Outcome.REVERTED)):
        code = shlex.quote(f'print("val_loss = {metric}")\n')
        note = evidence / str(metric)
        proposal = f"printf %s {code} > train.py && echo evidence > {shlex.quote(str(note))}"
        assert main(["run", "--run", "python train.py", "--metric", "val_loss",
                     "--propose", proposal, "--sandbox", "bwrap", "--sandbox-write",
                     str(evidence), "--trials", "1"]) == 0
        assert Ledger(project / "labloop.jsonl").trials()[-1].outcome is outcome
        assert note.read_text().strip() == "evidence"


# --- wiring through the CLI --------------------------------------------------

def test_run_refuses_when_bubblewrap_is_unavailable(project, monkeypatch, capsys):
    monkeypatch.setattr("labloop.sandbox._which", lambda name: False)
    rc = main([
        "run", "--run", "python train.py", "--metric", "val_loss",
        "--propose", "true", "--sandbox", "auto", "--trials", "1",
    ])
    assert rc == 2
    assert "bubblewrap" in capsys.readouterr().err


def test_cli_refuses_arbitrary_writable_directories(project, monkeypatch, capsys):
    monkeypatch.setattr("labloop.sandbox._which", lambda name: True)
    monkeypatch.setattr("labloop.sandbox.user_namespaces_work", lambda: True)
    rc = main(["run", "--run", "python train.py", "--metric", "val_loss",
               "--propose", "true", "--sandbox", "bwrap", "--sandbox-write",
               str(project.parent), "--trials", "1"])
    assert rc == 2
    assert ".local/state/labloop/evidence" in capsys.readouterr().err


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


def test_a_dedicated_evidence_dir_is_allowed(tmp_path, evidence_root):
    from labloop.sandbox import _validate_writable
    evidence = evidence_root / "run"
    evidence.mkdir()
    try:
        assert _validate_writable(str(evidence), _real(tmp_path / "work")) == _real(evidence)
    finally:
        evidence.rmdir()


def test_writable_inside_the_worktree_is_refused(evidence_root):
    from labloop.sandbox import _validate_writable
    work = evidence_root / "work"
    inside = work / "inside"
    inside.mkdir(parents=True)
    with pytest.raises(SandboxError, match="inside the worktree"):
        _validate_writable(str(inside), _real(work))


def test_writable_that_contains_the_worktree_is_refused(evidence_root):
    from labloop.sandbox import _validate_writable
    evidence = evidence_root / "run"
    work = evidence / "work"
    work.mkdir(parents=True)
    with pytest.raises(SandboxError, match="ancestor of the worktree"):
        _validate_writable(str(evidence), _real(work))


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
