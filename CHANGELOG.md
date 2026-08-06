# Changelog

## 0.1.0 — unreleased

First release. Everything below was built and then used in anger before
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
- A `--min-delta` revert says so. It used to tell the proposer
  `seconds 0.155 did not beat 0.2245` about a change that beat it by 31%,
  because the explanation compared metric to incumbent and never mentioned
  the threshold. Found by dogfooding: the agent that read it abandoned a
  direction that was working and spent its next trial on a wilder rewrite
  that scored worse. It now reads `beat 0.2245 by 0.0695, but --min-delta
  needs more than 0.0727; the direction worked, the margin was too small to
  trust`. Real regressions and exact ties are unchanged.
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
budget reported as failed rather than timed out.
