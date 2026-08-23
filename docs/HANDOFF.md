# Handoff — labloop

> **Historical document.** Written 2026-08-01, when the lab traded as
> Foothills Labs (renamed Plicara Labs 2026-08-20; this repo is now
> `plicara/labloop`). Moved here from `foundation_lab/docs/handoffs/` on
> 2026-08-23 — a project's handoff lives in its own repository. Kept as the
> record of the handoff, not as guidance: verify anything below against this
> repo's README, CHANGELOG and ROADMAP before relying on it.

Context for a fresh session working on `foothills-labs/labloop`.
Written 2026-08-01. Everything below is verified unless marked otherwise.

---

## 1. What it is

`labloop` is an experiment loop for agent-driven research: **keep a change only
if it measurably helps.** You give it a command that runs an experiment and
prints a metric, and a command that changes the code. It runs trials under a
wall-clock budget, commits the ones that improve the metric, and reverts
everything else. Every trial is recorded — including the failures, which are
most of the signal.

It ships under Foothills Labs, a foundation model lab whose sequencing is
benchmarks → fine-tuning small models → scaling up. `labloop` is
infrastructure for the first two.

## 2. State

| Fact | Value |
| --- | --- |
| Repo | `foothills-labs/labloop`, public |
| Branch | `main` |
| Head | `789d6cd` — "Initial commit: labloop 0.1.0" |
| CI | **Green.** Lint + tests on Python 3.10/3.11/3.12/3.13, plus a build job running `twine check` |
| Published | **No.** Nothing on PyPI yet |
| PyPI name | `labloop` — verified free 2026-08-01 with controls |
| License | Apache-2.0, real `LICENSE` file, `license`/`license-files` set in `pyproject.toml` |
| Dependencies | **None.** Stdlib only. `pytest` and `ruff` are dev-only |
| Tests | 20, all passing |

## 3. Layout

```
src/labloop/
  types.py      Goal, Outcome, Trial, Experiment — the value types
  metrics.py    pulling a number out of stdout (key=value or JSON lines)
  ledger.py     append-only JSONL trial record; best(), summary(), next_index()
  runner.py     run a command under a timeout, kill the whole process group
  workspace.py  git operations behind a Protocol: is_dirty / revert / commit
  loop.py       the keep-or-revert loop itself
  cli.py        labloop baseline | run | log
tests/
  test_metrics.py   metric extraction
  test_loop.py      loop behaviour via a FakeWorkspace
```

`Workspace` is a `Protocol` specifically so tests can substitute an in-memory
double and the loop never shells out to git directly. Keep that seam.

## 4. Design decisions — settled, don't relitigate

These are deliberate and tested. Changing any of them is a real decision, not
a cleanup.

- **A tie is not an improvement.** Equal metric reverts. Otherwise the loop
  accumulates neutral churn that looks like progress.
- **A missing metric is not a bad score.** `NO_METRIC` is distinct from
  `FAILED` and from a poor number. A broken experiment and a bad result are
  different events and must not be averaged together.
- **The loop refuses to start on a dirty tree** (`DirtyTreeError`). It reverts
  by discarding, so uncommitted work would be destroyed. This is a safety
  interlock, not a convenience check.
- **Timeouts kill the process group**, not just the shell. A training script
  that spawns workers would otherwise leave them alive, contending with the
  next trial for the GPU.
- **The ledger is the source of truth for the incumbent**, not in-memory
  state. A fresh `Loop` over an existing ledger picks up where the last one
  stopped. There is a test for this.
- **Metric extraction takes the last occurrence.** Training loops print the
  same key every epoch; the final one is the result.

## 5. Prior art and the naming decision

The keep-or-revert loop is the idea behind
[`karpathy/autoresearch`](https://github.com/karpathy/autoresearch) (March
2026, 21k+ stars), which wires it directly into single-GPU nanochat training:
three files, a fixed five-minute budget, one metric (`val_bpb`), agent edits
`train.py`.

**`labloop` is not that project and is not affiliated with it.** The README
says so explicitly. Keep that.

The PyPI name `autoresearch` is *free*, and was **deliberately not taken**. It
would read as the official package for a 21k-star project that isn't ours —
exactly the name confusion PEP 541 exists to reverse. Do not claim it.

**Where the value is.** Karpathy has publicly stated the gap himself: the
current code *"synchronously grows a single thread of commits in a particular
research direction,"* and the next step is asynchronous, massively
collaborative agents — *"not to emulate a single PhD student, it's to emulate
a research community of them."* `labloop` generalizes the loop rather than
cloning it:

1. Any command, any metric — not hardwired to nanochat and `val_bpb`.
   (Shopify pointed the same idea at their templating engine and got 53%
   faster rendering from 93 automated commits, so the loop is not ML-specific.)
2. No GPU assumption.
3. The trial history as a queryable artifact, not scrollback.

## 6. What's deliberately not done

The scaffold is real but small. These are open, in rough priority order:

1. **Agent integration.** `propose` is any shell command right now — it works,
   but it's untyped and gives the agent no structured feedback about *why* a
   trial was reverted. Feeding the ledger back to the proposer is the obvious
   next move.
2. **Branching research directions** — the gap named above. One linear commit
   thread today. The ledger schema is already shaped to carry a parent/branch
   field.
3. **Resumability and concurrency.** No locking; two loops over one ledger
   would interleave badly.
4. **`labloop init`** — there's no scaffolding command yet, only
   `baseline`, `run`, `log`.

## 7. Gotchas

- **The session integration cannot create or delete GitHub repos** — both
  return `403 Resource not accessible by integration`. Branch deletion via
  git push and via the REST API are both blocked too. The user must do those
  in the GitHub UI.
- **Publishing setup is not done and is not urgent** — nothing publishes until
  a release is tagged. When you want `0.1.0` out, the exact values are in the
  header comment of `.github/workflows/publish.yml`.
- **A PyPI pending publisher does not reserve the name.** PyPI's own docs say
  so, and it is invalidated if someone else registers first. Do not treat
  configuring it as claiming the name.
- **PyPI version numbers are permanent.** Rehearse on TestPyPI.

## 8. House style

Full brand guide is in `foundation_lab/docs/brand.md`. What matters here:
plain and specific prose, numbers over adjectives, claim only what is
measured, publish negative results. Comments explain *why*, not *what*.
The org is always plural — "Foothills", never "Foothill".
