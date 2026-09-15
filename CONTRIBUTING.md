# Contributing

## Setup

```bash
git clone https://github.com/plicara/labloop
cd labloop
pip install -e ".[dev]"
```

The Python runtime is standard-library only. `pytest`, `ruff` and `mypy` are dev-only; install `build` and `twine` too for release preflight. The default proposer sandbox separately requires Linux, Bubblewrap, and working unprivileged user namespaces.

## The checks

Run the portable checks from an environment with the editable package and dev tools installed:

```bash
pytest -q            # portable suite; sandbox integrations skip without Bubblewrap
ruff check .         # lint
mypy                 # strict, src only; the package ships py.typed
```

On Linux, also run `pytest -q --require-sandbox tests/test_sandbox.py`. This first executes the real sandbox self-check and fails if isolation is unavailable; both the sandbox CI job and release publishing require it. Ordinary tests opt out of the default sandbox through a test fixture. That makes portable tests useful, but passing them alone does not verify Linux isolation.

## How changes are made here

**Tests come first.** Write the failing test, watch it fail, then write the
code that makes it pass. A test written after the fact tends to enshrine
whatever the code happens to do; a test written first states what it should
do. This repository's history has a worked example: a failing test for a
typo'd `--direction` flushed out four existing tests that were quietly
pinning behavior nobody wanted.

**Dogfood before you trust.** Most of the bugs fixed here were found by
using the tool on realistic tasks, not by reading the code. If you add a
user-facing behavior, drive it from the command line the way a stranger
would — including the mistakes a stranger would make.

**Measure claims.** House style is numbers over adjectives. If a change is
justified by convergence, noise robustness, or performance, the evidence
belongs in `experiments/` with statistics, not in the commit message as an
assertion. Negative results are published, not discarded — see
`experiments/outcome_granularity/RESULTS.md` for the shape.

**Settled design decisions.** Some behaviors look odd and are load-bearing.
Before "fixing" one, check whether a test asserts it on purpose:

- A tie is not an improvement; equal metrics revert.
- A missing metric is not a bad score; nine outcomes exist because each
  sends the user somewhere different.
- The loop refuses to start on a dirty tree; it reverts by discarding.
- Kept commits contain the proposed change and the decision log, never
  run artifacts.
- The ledger is append-only, valid strict JSON, and the source of truth
  for the incumbent.
- The brief is written by labloop and read by the agent, never the
  reverse.

Changing any of these is a design discussion, not a cleanup.

## Releasing

`scripts/publish.sh` cuts a release. It refuses before it does anything
irreversible — wrong branch, dirty tree, diverged from origin, tag already
taken, version already on PyPI — then runs the suite, builds, and drives the
built wheel end to end in a clean venv, because `twine check` validates
metadata and not that the wheel contains the package.

```bash
scripts/publish.sh --dry-run     # read-only preflight; print later steps
scripts/publish.sh --rehearse    # upload to TestPyPI on the way
scripts/publish.sh               # date the changelog, commit, tag, push
```

The dry run performs read-only local and remote preflight checks; it prints, rather than executes, tests, builds, uploads, commits, and pushes. A normal run tests and builds first. Its wheel smoke test explicitly opts out of proposer isolation to check packaging on platforms without Bubblewrap.

After tagging, the script offers to publish the GitHub Release if `gh` is installed, displays the notes, and requires confirmation even with `--yes`. Otherwise it prints browser instructions. Publishing that release triggers `publish.yml`, which first refuses a version already on PyPI (the same `scripts/check_pypi_version.sh` gate the script uses), then runs portable checks and mandatory Linux sandbox tests before uploading. There is no manual workflow-dispatch publishing shortcut. No local rehearsal proves that external publishing succeeded; verify the installed release afterward.

## Commit messages

Explain *why*, in prose, the way the existing history does. The subject
line states what changed; the body states what was wrong, how it was found,
and what now holds. "Fixed bug" is not a commit message.
