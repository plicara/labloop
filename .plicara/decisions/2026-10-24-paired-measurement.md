# Paired measurement against drift

- **Date:** 2026-10-24
- **Status:** decided

## Context

The loop judged each candidate against the best kept metric in the ledger, measured whenever that trial ran. In dogfood run 2 (see [the write-up](../../experiments/self_overhead/README.md)) the ledger credited Haiku's three keeps with 17.7, 15.0 and 13.0 ms; measured interleaved outside the loop they were 2.3, 6.2 and 2.6 ms. All three were measured before any restart, so the likely cause is the machine speeding up over the hour: later candidates compared well against a baseline measured early. Then a container restart made the machine about 17% slower, and no later trial could beat the incumbent's pre-restart number. `noise` cannot see either effect, because it measures back-to-back runs over minutes, and `--confirm` re-measures the candidate, never the incumbent.

## Options considered

1. Re-measure the incumbent after the candidate, by stashing the proposal, measuring the incumbent commit, and restoring the proposal. Closest in time, but stashing untracked files and restoring them after a measurement that may write artifacts is fragile, and a failed restore loses the proposal.
2. Measure the incumbent in a second worktree beside the candidate. Clean, but ignored inputs such as local datasets are absent from a fresh worktree.
3. Re-measure the incumbent before the proposal, while the tree is still exactly the incumbent's commit. The two measurements are minutes apart, nothing is stashed, and ignored inputs are present.
4. Let a baseline reset the incumbent. Fixes the restart case only, and changes what `best` means for every ledger.

## Decision

Option 3, opt-in as `--paired`. The re-measurement runs under the same tamper checks as any measurement (phase `incumbent run`), its artifacts are swept before the proposal, and an incumbent that no longer measures fails the trial before a proposal is spent. The verdict, the confirmation, the brief and every report use the re-measured number; the ledger keeps both `incumbent` and `remeasured`.

## Consequences

One more run per trial, including trials whose proposal changes nothing. The comparison is a difference of two runs, so its noise is about √2 times one run's, and `--min-delta` should allow for it. Drift within a single trial, between the re-measurement and the candidate's run, is not corrected. The ledger's best kept metric still reflects the machine it was measured on; under `--paired` it is a record, not the bar. Whether this removes the overstatement is to be measured by a third dogfood run with the same interleaved check.
