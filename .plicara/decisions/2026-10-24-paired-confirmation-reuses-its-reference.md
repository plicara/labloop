# Paired confirmation reuses its reference

- **Date:** 2026-10-24
- **Status:** open
- **Follows:** [Paired measurement against drift](2026-10-24-paired-measurement.md)

## Context

Dogfood run 3 tested `--paired` with `--confirm` (see [the write-up](../../experiments/self_overhead/README.md)). Of 21 trials, the two keeps were judged against the two slowest of the 21 incumbent re-measurements: 220.3 and 215.6 ms, against a median of 203.9. The ledger credited them with 7.2% and 11.3%; interleaved outside the loop they were 1.0% and 2.1%. If keeps were unrelated to the reference draw, both landing on the two highest ranks would happen about once in 150 runs.

The cause is in the design recorded earlier: the incumbent is measured once per trial, and that measurement is the bar for both the candidate's first run and its confirmation. A slow draw lets both candidate runs pass, so the confirmation is not independent of the decision it confirms, and the loop selects for unlucky references.

## Options

1. Re-measure the incumbent for the confirmation too, after the candidate's runs. Independent, but it needs the proposal set aside while the incumbent's tree is measured, which is the stash-and-restore fragility rejected before.
2. Measure the incumbent several times before the proposal and use the median. Cheap to build; shrinks the reference's noise by the square root of the count but still reuses it.
3. Decide on one set of measurements and record the gain from another: keep the verdict as now, then measure candidate and incumbent once more each, interleaved, and record that difference as the trial's gain.
4. Leave the loop as is and document that ledger totals are an upper bound, verified by an interleaved check outside the loop.

## Current state

Option 4 is in place: the README and changelog say what `--paired` does not fix and recommend the interleaved check. No change to the loop is decided. Options 1 and 3 address the cause; either needs measuring the incumbent's tree after a proposal exists, which is a design decision of its own.
