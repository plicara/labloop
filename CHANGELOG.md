# Changelog

## Unreleased

- Check protected files and the ledger after completed measurements, including baselines, confirmation runs, and noise calibration, before accepting metrics. Discard tampered scores, restore altered ledgers, and identify the violating phase. Preserve preexisting uncommitted baseline work and stop noise calibration without publishing statistics.
- Explicitly drop all capabilities and detach the controlling terminal in Bubblewrap. Document the snapshot checks' transient-tampering blind spot and a separate, unimplemented evaluator-isolation design; retain the current single backend.
- Constrain `--sandbox-write` to existing directories below `~/.local/state/labloop/evidence`, excluding the root, the worktree, its ancestors, and symlink redirects outside the allowed area. Existing arbitrary writable paths need migration.
- Use exclusively owned temporary sandbox probes so startup checks cannot delete preexisting work or evidence files.
- Restore a proposer-modified ledger before recording `harness_changed`, so forged incumbents do not affect subsequent trials.
- Kill the original POSIX process group on timeout or interruption, even if its shell has exited; bound output draining when an unconfined detached child retains a pipe.
- Capture individual untracked proposal files so evaluator artifacts created later in a new directory are not swept into a kept commit.
- Refresh the active manifest under each trial's lock so interleaved waiting runs retain their own labels and resume specification.
- Require a working Bubblewrap self-check in sandbox CI and release publishing. Add kernel-facing tests for host and Git writes, network namespaces, detached processes, and evidence surviving keeps and reverts.
- Make release dry runs read-only, reject untracked files and unverifiable remote state, verify editable source provenance, fix cross-platform wheel smoke setup, and require explicit final publication confirmation. Remove direct workflow-dispatch publishing.
- Refresh setup, security scope, evidence migration, cookbook network flags, release instructions, and roadmap status; include scripts and audit documentation in source distributions.

## 1.0.2 — 2026-09-14

### Hardening the 1.0 sandbox after an independent audit

- **`--sandbox-write` is validated.** It accepted any existing directory —
  including `/tmp` (which re-exposes the bytecode mirror the sandbox exists to
  keep unreachable) and `/` (which disables the sandbox). A writable path that is
  an ancestor of the worktree, or a shared/temporary root, is now refused, and
  both the worktree and the path are canonicalised so a symlink cannot point the
  bind back inside the worktree.
- **The Python API is confined by default**, matching the CLI:
  `Experiment.sandbox` defaults to `auto` (override with `LABLOOP_SANDBOX`), so a
  library caller no longer runs the proposer unconfined.
- **The docs no longer overstate "network off".** The network namespace blocks IP
  traffic; Unix-domain sockets are filesystem objects and stay reachable, so a
  same-user local relay can still receive data.
- **The 1.0.0 notes below are corrected**: one backend (bubblewrap), Linux only;
  the removed alternatives are not promised, and the README now says run needs
  bubblewrap by default.
- **CI adds a sandbox job** that installs Bubblewrap and runs its tests. The availability-based skips still allowed that job to pass without a working backend; the mandatory capability gate is in the unreleased follow-up above.

## 1.0.1 — 2026-09-14

### A writable evidence channel for the sandboxed proposer

- `--sandbox-write PATH` (repeatable) bind-mounts an out-of-tree directory
  read-write into the sandbox. A sandboxed proposer could otherwise leave no
  record of what it tried — anything it wrote in-tree would be committed,
  reverted, or digested with the trial — so an audit trail that only exists
  for kept trials is no audit trail at all.
- Refused when inside the worktree or missing, so a typo fails loudly at
  startup instead of silently losing the evidence. The startup self-check
  proves the channel too: a write there must work, or the loop refuses.
- Recorded in the manifest alongside the rest of the sandbox spec.

## 1.0.0 — 2026-09-13

### Sandboxing on by default, with the network off

- The propose step runs sandboxed by default, with **bubblewrap** (Linux only);
  the loop refuses to start when it cannot run rather than running unconfined.
  `--sandbox none` restores the old behaviour.
- **IP networking is off by default** (`--sandbox-network` turns it on). Unix-domain sockets remain reachable. A proposing agent that calls a hosted model needs the flag or an explicit sandbox opt-out.
- A startup self-check proves the boundary on the machine before trial 0: a write
  inside the worktree works and a write outside it is denied. This catches a
  "best effort" backend silently running unsandboxed.
- Bubblewrap is the only supported backend. `--sandbox-exec` is not a released option.

### A protected file can no longer be shadowed

`import x` prefers a package `x/` over a module `x.py`. Protecting `x.py` alone
missed a proposal that creates `x/__init__.py` — the watched file is byte-identical
while its behaviour is replaced. The digest now covers the would-be package too, so
creating one is a harness change.

## 0.3.0 — 2026-09-13

### Running where the project actually lives, and keeping the record straight

Found by consuming 0.2.0 in a real project — a prompt-optimization chase whose
workspace sat in a subdirectory of its repository.

- **A `--workdir` below the repository root can keep changes.** `git status`
  reports paths relative to the repo root while `git add` ran from the workdir,
  so a keep in a subdirectory failed with a pathspec error: the loop measured an
  improvement it could never commit. `GitWorkspace` now resolves the toplevel
  once and runs every git command there, translating paths at the boundary.
- **Child commands no longer write bytecode into the protected tree.** A propose
  step that imported or compiled a protected module wrote `__pycache__` inside
  it, moved the harness digest, and made *every* trial read as `harness_changed`.
  The runner points `PYTHONPYCACHEPREFIX` at a fresh, removed-after directory.
  This is a raised bar, not a boundary: a same-user process can still race the
  mirror, and labloop remains a detector, not a sandbox. The integrity docstring
  now says so, and names the real fix (run adversarial proposers under OS
  isolation).
- **`--wait` runs share the ledger per trial, not per run.** The lock held the
  whole multi-trial run, so a second direction waited hours while the first
  finished and the documented round-robin never happened. The incumbent is also
  re-read per trial, so a peer's kept trial is not judged against a stale bar.
- **`--label` on `baseline` and `run` records who or what proposed a trial** in
  the manifest and in `log --json`, instead of abusing the propose command
  string to carry it. `log --json` attributes each trial to the label in force
  when it was recorded; ledgers written before the field still load.
- **A staged rename can be committed.** `changed_paths()` reports both sides of
  a rename, and the vanished side is in neither the worktree nor the index, so
  `git add` failed on it.

286 tests (was 256).

## 0.2.0 — 2026-08-05

### Trusting the number

- `labloop noise` suggests two thresholds, not one. It used to name the
  spread alone, which is the safe-looking number and silently expensive: on
  a recorded run `--min-delta <spread>` discarded three genuine speedups of
  31%, 27% and 15%. It now prints the spread and the deviation with what
  each costs — conservative discards real work, permissive lets flukes
  through — because only the user knows which mistake is cheaper. The README
  already reasoned with the deviation; the tool now agrees with it.
- A `--min-delta` revert says so. It used to tell the proposer
  `seconds 0.155 did not beat 0.2245` about a change that beat it by 31%,
  because the explanation compared metric to incumbent and never mentioned
  the threshold. Found by dogfooding: the agent that read it abandoned a
  direction that was working and spent its next trial on a wilder rewrite
  that scored worse. It now reads `beat 0.2245 by 0.0695, but --min-delta
  needs more than 0.0727; the direction worked, the margin was too small to
  trust`. Real regressions and exact ties are unchanged.

### The cookbook

- `cookbook/` — worked examples, each a real task with a real agent and the
  run's real output, including the trials that were thrown away. Five
  recipes: a spam classifier, an identifier index over the CPython source, a
  slow pytest suite, a retrieval system, and a prompt scored against a
  held-out eval set. Every recipe declares how far it is verified, and
  `tests/test_cookbook.py` runs each one's harness on every supported Python
  — a narrative recipe's agent trajectory cannot be re-run, but the
  scaffolding it documents is deterministic and is the half that rots.
- `cookbook/skills/` — three agent skills (`labloop-setup`,
  `labloop-proposer`, `labloop-triage`) covering the moments a user has an
  agent in the room. Reference, not coaching: an earlier draft gave
  behavioural advice that three recorded runs contradicted, and it was
  removed rather than caveated.
- `cookbook/noise-across-recipes.md` — four experiments on one machine
  measured 22%, 8.9%, 0.3% and 0% noise, including two wall-clock benchmarks
  that differ by 70×. Nothing about that ordering was predictable in advance,
  which is the argument for measuring rather than assuming.
- The sdist ships `cookbook/` alongside `experiments/` and `tests/`.

## 0.1.0 — 2026-08-02

First release, published to PyPI as `labloop` and tagged `v0.1.0`.
Everything below was built and then used in anger before
shipping: the loop was pointed at real experiment shapes — a regression
task, a timing benchmark, a checkpoint-heavy training script, a pure-noise
metric — and every bug that surfaced is listed here with the behavior that
replaced it.

### The loop

- Keep-or-revert over any command and any metric: `propose` mutates the
  tree, `run` prints a number, an improvement is committed and anything
  else reverted. Ties revert — a tie is not an improvement.
- Nine trial outcomes, each a distinct event that sends you somewhere
  different: `kept`, `reverted`, `no_change`, `failed`, `timed_out`,
  `no_metric`, `not_finite`, `harness_changed`, `interrupted`. Measured
  (`experiments/outcome_granularity/`): outcome labels beat kept/not-kept
  on convergence with p < 0.01; the five-to-nine refinement is not
  statistically distinguishable and the set stays for the bugs its
  distinctions fixed.
- Separate proposal budget (`--propose-budget`): an agent thinking longer
  than the experiment runs is ordinary. Timeouts kill the whole process
  group either way.
- A run stops after ten consecutive trials with no verdict
  (`--give-up-after`), instead of failing identically all night.

### Trusting the number

- `labloop noise` measures whether the metric holds still before anything
  is optimized; reports spread and standard deviation with the exact
  follow-up command.
- `--min-delta` and `--confirm` for metrics that move on their own —
  measured on pure noise over 400 replicated runs: fabricated improvement
  falls from 23.5% to 9.9% with both, for 10% more compute. Neither makes
  a noisy metric safe, and the docs say so.
- Non-finite metrics never become the incumbent: one `nan` used to freeze
  the loop permanently, reverting every later improvement while `best`
  reported nan.
- `--protect` digests the files that define the measurement (SHA-256,
  per-file); a proposal that edits the evaluator or the held-out data is
  recorded as `harness_changed` and named, not scored. The ledger itself
  is checked on every trial without being declared. Detection, not
  prevention — a claim the design can keep.
- An incumbent measured under a different harness digest stops the loop
  instead of being compared against; metric or goal drift against an
  existing ledger is refused with the field named.

### The record

- Append-only JSONL ledger; half-written lines, unknown outcomes and
  unknown fields are skipped, not fatal. Valid strict JSON always.
- A kept trial commits exactly the proposed change plus a sparse decision
  log (`labloop-history.jsonl`, reverted trials included); run artifacts
  are discarded, so a checkpoint-per-trial training run does not become a
  repository of hundreds of gigabytes.
- Every run records its spec as a manifest line; `labloop resume`
  continues under the last spec that can actually run — a baseline
  re-measurement after the crash does not cost you the run spec. Same
  incumbent, same numbering, nothing retyped. The environment is never
  recorded.
- One loop per ledger, enforced by an OS-released lock; a second run is
  refused with the holder's pid, `--wait` queues. A crashed run cannot
  leave a stale lock.
- Research directions: fork from any kept trial (`labloop branch`), run
  each in its own worktree against the shared ledger, per-direction
  incumbents seeded from the fork point. `log --compare` refuses across
  differing harnesses. A direction the ledger has never heard of is
  refused with a did-you-mean — a typo'd `--direction` used to create a
  phantom direction whose first trial, however bad, was kept.
- Querying without jq: `log --json`, `--outcome`, `--direction`,
  `--since-trial`.

### Feedback to the proposer

- Each proposal receives `$LABLOOP_BRIEF`: its direction's history with a
  one-sentence `why` per trial, failures carrying their output tail;
  scalars in `$LABLOOP_METRIC`, `$LABLOOP_GOAL`, `$LABLOOP_INCUMBENT`,
  `$LABLOOP_TRIAL`. Written by labloop and read by the agent, never the
  reverse.

### Fixed before anyone else could hit them

Eleven bugs found by dogfooding, each now a regression test: the nan
freeze; a crash that printed nothing reported as `no_metric`; `nan` read
differently by the two output parsers; metric names ending in punctuation
missed in key=value form; a no-op proposal crashing the run on git's
empty-commit refusal; an interrupted trial vanishing from the ledger (and
recovery advice that would have committed an unmeasured change); a commit
refused by a pre-commit hook taking the run down with an empty ledger;
`revert` unable to undo staged changes (`git checkout -- .` restores from
the index), wedging the tree permanently; a relative `--ledger` resolving
against the shell's cwd and silently splitting the record; one budget
covering both the agent and the experiment; and a proposal killed at the
budget reported as failed rather than timed out. Plus two found after the
changelog was first written: a typo'd `--direction` silently creating a
phantom direction, and `resume` refused when the newest manifest was a
baseline. And from release review: `labloop run` outside a git repository
now names the fix instead of tracebacking.
