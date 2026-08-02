# Does outcome granularity change convergence?

**Question.** labloop distinguishes nine trial outcomes; Karpathy's
autoresearch effectively two (kept, not kept); labloop 0.1.0 had five. Does a
proposer that can read the finer labels converge faster, or is the
granularity only debugging convenience for the human?

**Method.** `simulate.py` drives the real `Loop`, real metric extraction and
the real brief; only the subprocess and git are simulated. Three arms differ
solely in how much of the outcome label the proposer sees (bare / five /
nine). One shared response toolkit; an arm that cannot tell causes apart
plays a hedge over the responses its label could call for. Task: minimize a
smooth objective over (lr, depth, epochs) whose optimum sits just inside
three failure cliffs (diverge-to-nan, crash, timeout), starting from a
working config; the proposer emits a no-op edit 10% of the time, as real
agents do. 40 trials per run, 200 seeded runs per arm. Endpoints:
best-metric-found and mean best-so-far (AUC). Two-sided Mann-Whitney U
(tie-corrected) and a 10k-resample permutation test on the mean difference;
Cliff's delta for effect size. Stdlib only.

## Results (n = 200 per arm)

best-after-40, lower is better:

| arm  | mean   | median | sd     |
| ---- | ------ | ------ | ------ |
| bare | 1.1198 | 1.0583 | 0.1502 |
| five | 1.0860 | 1.0325 | 0.1482 |
| nine | 1.0783 | 1.0251 | 0.1141 |

| comparison   | endpoint | MW p   | perm p | Cliff's δ |
| ------------ | -------- | ------ | ------ | --------- |
| bare vs nine | best     | 0.0014 | 0.0021 | +0.185    |
| bare vs nine | AUC      | 0.019  | 0.0012 | +0.135    |
| bare vs five | best     | 0.0071 | 0.024  | +0.155    |
| five vs nine | best     | 0.60   | 0.56   | +0.030    |
| five vs nine | AUC      | 0.45   | 0.22   | +0.044    |

## Reading

1. **Outcome labels are signal, not decoration.** Bare loses to both labeled
   arms with p < 0.01 on the primary endpoint under both tests. A proposer
   told *why* its attempt died converges measurably faster than one told only
   that it died.

2. **Five → nine is not distinguishable on this task.** Direction favors
   nine on every endpoint, but p ≈ 0.5 and Cliff's δ ≈ +0.03: if the effect
   exists it is small, and no plausible n rescues it here. One reason is
   visible in the outcome counts: the informed arms hit the nan cliff, get
   the right correction, and never return — `not_finite` fired 69 times
   under bare and 1–3 times under five/nine. A label can be valuable and
   rarely exercised.

3. **The nine-set's case therefore rests on** (a) the bare-vs-labeled gap,
   which is real; (b) correctness — the nan/no-op/interrupt conflations each
   caused a real recorded bug (a frozen incumbent, a crashed run, a lost
   trial) fixed in this repo's history; and (c) the human reading the log.
   Not on agent-side convergence beyond the five-set, on this evidence.

## What this does not show

One task family, one policy family, simulated failures. The hedge weights
for the coarse arms are a design choice (stated in `simulate.py`); different
weights move the bare arm's numbers, though not plausibly past both p < 0.01
gaps. The brief's `why` strings were withheld from every arm, so this
measures label granularity alone, not the full brief.

A first version of this experiment gave the opposite headline — bare
significantly *ahead* — and was discarded as flawed rather than reported:
its start configuration was so poor that random restarts beat any informed
response, and its cliffs sat where no reasonable optimizer would visit, so
the arms never diverged (five and nine were bit-identical across 8,000
trials). If an experiment's arms cannot differ, it is not measuring the
question. The redesign starts from a working config and puts the optimum
against the cliffs, which is the regime the labels exist for.

Reproduce: `python experiments/outcome_granularity/simulate.py`
(~3 minutes; per-seed data lands in `raw_results.json`).
