# Contributing

## Setup

```bash
git clone https://github.com/foothills-labs/labloop
cd labloop
pip install -e ".[dev]"
```

Stdlib only at runtime — the package has zero dependencies, and keeping it
that way is a feature. `pytest`, `ruff` and `mypy` are dev-only.

## The checks

Everything CI runs, runnable locally:

```bash
pytest -q            # the suite; ~230 tests, under 30 seconds
ruff check .         # lint
mypy                 # strict, src only; the package ships py.typed
```

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

## Commit messages

Explain *why*, in prose, the way the existing history does. The subject
line states what changed; the body states what was wrong, how it was found,
and what now holds. "Fixed bug" is not a commit message.
