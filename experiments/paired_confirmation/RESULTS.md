# Does a paired confirmation credit the gain a change really has?

**Question.** Dogfood run 3 kept only the trials judged against the slowest incumbent draws and credited them with five to seven times the gain an interleaved check found. Which confirmation design gives a ledger whose credited gains can be believed?

**Method.** [`simulate.py`](simulate.py) drives the real `Loop` on a real git repository; only the experiment's number is simulated, as quality plus Gaussian noise with σ = 5. In `null` no proposal helps; in `real` every proposal truly helps by 5 (one σ). Ten seeded runs of 40 trials per cell. `--min-delta` follows the README: σ unpaired, σ√2 paired. Credited gain per keep is the recorded bar minus the recorded metric.

## Results

Two-pair design (commit `2b1c790`): the confirmation compared a fresh incumbent measurement with a fresh candidate run, and the gain was credited from that pair. Raw: [`raw_two_pair.json`](raw_two_pair.json).

| Scenario | Confirmation | Keeps per run | Credited per keep | True per keep | Credited / true | Runs per trial |
| --- | --- | --- | --- | --- | --- | --- |
| null | unpaired | 0.80 | 6.74 | 0 | | 1.08 |
| null | reused | 2.40 | 9.48 | 0 | | 2.16 |
| null | fresh pair | 0.60 | 10.14 | 0 | | 2.30 |
| real | unpaired | 2.10 | 7.94 | 5.00 | 1.59 | 1.19 |
| real | reused | 8.80 | 10.59 | 5.00 | 2.12 | 2.40 |
| real | fresh pair | 6.50 | 11.99 | 5.00 | 2.40 | 2.80 |

Three-pair design (commit `f95d82e`, current): kept on two independent wins, gain estimated on a third pair measured after the verdict. Raw: [`raw_three_pair.json`](raw_three_pair.json). The unpaired and reused rows are identical to the table above, as they should be: same seeds, same code paths.

| Scenario | Confirmation | Keeps per run | Credited per keep | True per keep | Credited / true | Runs per trial |
| --- | --- | --- | --- | --- | --- | --- |
| null | fresh pair + estimate | 0.60 | −2.92 | 0 | | 2.33 |
| real | fresh pair + estimate | 7.00 | 4.28 | 5.00 | 0.86 | 3.10 |

## Reading it

- **Reusing the incumbent draw is the worst design.** Under pure noise it keeps 2.4 false changes per 40 trials, three times the unpaired rate, and credits each with 9.5. This is the run-3 failure, reproduced.
- **A fresh pair fixes the decision but not the number.** False keeps fall fourfold, to 0.6 per run. The credited gain gets worse, 2.4× the truth, because a pair that must clear a threshold only survives when it came out lucky. Any number that is both a test and the reported value is biased upward.
- **A third, unselected pair fixes the number.** Credited 4.28 against a true 5.00 over 70 keeps, within one standard error (a single pair's difference has σ√2 ≈ 7.1, so about 0.85 over 70); under pure noise −2.92 over 6 false keeps, within one standard error of zero (about 2.9). The estimate is noisy per keep and honest on average.
- **Cost.** The third pair is two runs, only on kept trials. Here every `real` proposal helps, so 3.1 runs per trial; in the dogfood runs, where under a tenth of trials were kept, it would be close to the 2 that pairing already costs.

## Limitations

Simulated noise is Gaussian and stationary within a trial; drift between the three pairs of one trial is not modeled. The incumbent's quality changes only through keeps. Ten runs per cell bound the precision quoted above.
