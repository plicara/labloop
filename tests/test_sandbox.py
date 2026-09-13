"""Opt-in OS isolation for the propose step (scaffold).

The pure tests pin the template contract; the CLI test proves the propose
command is actually wrapped, which is the whole point of the feature.
"""

from __future__ import annotations

import shlex
import shutil
import sys

import pytest

from labloop import Experiment, Goal, TemplateSandbox, UsageError, resolve_sandbox
from labloop.cli import main


def test_wrap_substitutes_command_and_workdir():
    sandbox = TemplateSandbox("t", "run --at {workdir} -- {command}")
    assert sandbox.wrap("do thing", "/work") == "run --at /work -- do thing"


def test_a_template_without_the_placeholder_is_rejected():
    with pytest.raises(UsageError):
        TemplateSandbox("t", "bwrap --ro-bind / /")


def test_no_choice_is_no_isolation():
    assert resolve_sandbox(None, None) is None
    assert resolve_sandbox("none", None) is None


def test_a_custom_template_is_used_verbatim():
    resolved = resolve_sandbox(None, "echo {command}")
    assert resolved is not None and resolved.wrap("x", "/w") == "echo x"


def test_auto_fails_loudly_when_no_backend_exists(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name: None)
    with pytest.raises(UsageError):
        resolve_sandbox("auto", None)


def test_naming_a_backend_that_is_absent_is_an_error(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name: None)
    with pytest.raises(UsageError):
        resolve_sandbox("bwrap", None)


def test_bwrap_is_used_when_present(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/bwrap")
    resolved = resolve_sandbox("bwrap", None)
    assert resolved is not None and resolved.template.startswith("bwrap ")


def test_an_experiment_rejects_a_sandbox_without_the_placeholder():
    with pytest.raises(UsageError):
        Experiment(run="true", metric="m", goal=Goal.MAXIMIZE, sandbox="bwrap /")


def test_the_propose_command_is_actually_wrapped(project, capsys):
    # The sandbox template sets an env var; the proposer writes it to disk. If
    # the propose step were not wrapped, the file would be empty.
    inner = (
        f"{shlex.quote(sys.executable)} -c "
        + shlex.quote(
            "import os,pathlib;"
            "pathlib.Path('probe.txt').write_text(os.environ.get('LABLOOP_SANDBOX_PROBE',''))"
        )
    )
    assert (
        main(
            [
                "run",
                "--run",
                "python train.py",
                "--metric",
                "val_loss",
                "--propose",
                inner,
                "--sandbox-exec",
                "LABLOOP_SANDBOX_PROBE=yes {command}",
                "--trials",
                "1",
            ]
        )
        == 0
    )
    capsys.readouterr()
    assert (project / "probe.txt").read_text().strip() == "yes"
