# Confirm on a fresh pair, estimate on a third

- **Date:** 2026-10-24
- **Status:** decided
- **Resolves:** [Paired confirmation reuses its reference](2026-10-24-paired-confirmation-reuses-its-reference.md)

## Context

Under `--paired --confirm` one incumbent measurement judged both of a candidate's runs, so keeps concentrated on trials whose incumbent drew slow, and dogfood run 3 credited its keeps with five to seven times their real gain. A first fix, measuring the incumbent again for the confirmation, was simulated before it shipped (see [the results](../../experiments/paired_confirmation/RESULTS.md)). It cut false keeps fourfold but credited 2.4 times the true gain: the confirming pair had to clear the threshold, so the pairs that cleared it skewed lucky.

## Decision

Under `--paired --confirm`:

1. A trial that wins its first comparison is set aside with `git stash` under the label `labloop trial N`; the incumbent is measured; the proposal is restored and measured again. It is kept only if this pair wins too.
2. A kept trial is measured on a third pair, candidate first and then the incumbent with the proposal set aside. The ledger records that pair as `metric` and `estimate_reference`. The estimate never reverses the keep, because a veto would make it one more threshold that only lucky pairs pass.

The stash, not a copy held by labloop, so a crashed trial's proposal stays recoverable in `git stash list`. `set_aside` fails rather than create an empty stash, and `restore` pops only an entry carrying its own label, so a stash the user made is never applied. Every failure path restores the proposal or names its stash entry in the trial's note. A workspace without `set_aside` keeps the earlier behavior.

## Consequences

In simulation the third pair credits 4.28 against a true 5.00 and −2.92 against a true 0, both within one standard error; false keeps stay at a quarter of the reused-draw design. A trial that wins the first comparison costs two more runs, and two more again if kept. The estimate of a single keep is as noisy as one paired difference; it is right on average, not per trial. Drift between the pairs of one trial is not corrected. The loop writes to the user's stash list during a trial, which `git stash list` shows while it runs.
