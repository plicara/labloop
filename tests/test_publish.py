"""Release preflight without network access, tags, uploads, or real Git writes."""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.fixture
def release_checkout(tmp_path):
    root = tmp_path / "checkout"
    (root / "scripts").mkdir(parents=True)
    shutil.copyfile(Path(__file__).parents[1] / "scripts" / "publish.sh",
                    root / "scripts" / "publish.sh")
    package = root / "src" / "labloop"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text('__version__ = "99.0.0"\n')
    (root / "CHANGELOG.md").write_text("# Changelog\n\n## 99.0.0 — unreleased\n\nTest notes.\n")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    python = bin_dir / "python3"
    python.write_text('#!/bin/sh\n[ "$1" = -c ] && [ "$2" = "import build, twine" ] && exit 0\n'
                      f'exec {shlex.quote(sys.executable)} "$@"\n')
    python.chmod(0o755)
    git = bin_dir / "git"
    git.write_text('''#!/bin/sh
printf '%s\\n' "$*" >> "$LABLOOP_RELEASE_CALLS"
case "$*" in
  'status --porcelain'*) printf '%s' "$LABLOOP_TEST_DIRTY" ;;
  'rev-parse --abbrev-ref HEAD') echo main ;;
  'rev-parse -q --verify'*) exit 1 ;;
  'rev-parse'*) echo abc123 ;;
  'ls-remote --exit-code --tags'*) exit 2 ;;
  'ls-remote --exit-code --heads'*) printf 'abc123\\trefs/heads/main\\n' ;;
esac
''')
    git.chmod(0o755)
    curl = bin_dir / "curl"
    curl.write_text('#!/bin/sh\n[ "$LABLOOP_TEST_CURL_FAIL" = 1 ] && exit 7\nprintf 404\n')
    curl.chmod(0o755)
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}",
           "PYTHONPATH": str(root / "src"),
           "LABLOOP_RELEASE_CALLS": str(tmp_path / "calls"),
           "LABLOOP_TEST_DIRTY": "", "LABLOOP_TEST_CURL_FAIL": "0"}
    env.pop("PYTHONDONTWRITEBYTECODE", None)
    return root, env


def run_preflight(root, env):
    return subprocess.run(["bash", "scripts/publish.sh", "--dry-run"], cwd=root,
                          env=env, capture_output=True, text=True, timeout=30)


def test_release_dry_run_does_not_mutate_git_or_the_changelog(release_checkout):
    root, env = release_checkout
    before = (root / "CHANGELOG.md").read_bytes()
    result = run_preflight(root, env)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (root / "CHANGELOG.md").read_bytes() == before
    assert not list(root.rglob("__pycache__"))
    calls = Path(env["LABLOOP_RELEASE_CALLS"]).read_text().splitlines()
    assert not any(call.startswith(("fetch ", "checkout ", "commit ", "push ", "tag "))
                   for call in calls)


def test_release_preflight_refuses_untracked_files(release_checkout):
    root, env = release_checkout
    env["LABLOOP_TEST_DIRTY"] = "?? scratch.py\n"
    result = run_preflight(root, env)
    assert result.returncode != 0
    assert "uncommitted" in result.stderr


def test_release_preflight_does_not_treat_network_failure_as_an_available_version(release_checkout):
    root, env = release_checkout
    env["LABLOOP_TEST_CURL_FAIL"] = "1"
    result = run_preflight(root, env)
    assert result.returncode != 0
    assert "could not check PyPI" in result.stderr
