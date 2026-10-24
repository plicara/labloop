# Dogfooding labloop on itself

**Question.** Does labloop work end to end when a real agent uses it on real code, and what breaks when it does?

**Setup (2026-10-22).** labloop optimized its own per-trial overhead. [`bench.py`](bench.py) is the protected `--run`: it gates on the full test suite, then drives an inner labloop on a fixture project (500 source and data files plus a 4 MiB holdout) through a fixed schedule of twelve proposals with the default bubblewrap sandbox, and fails unless every inner trial reaches its scheduled outcome. The metric is `trial_overhead_ms`, wall-clock milliseconds per inner trial.

The proposer was headless Claude Code (`claude -p`) inside labloop's default sandbox with `--sandbox-network`, restricted to Read, Edit, Write, Glob and Grep, and given a cProfile of the baseline inner loop. The judge was a separately installed copy of labloop from the pre-run commit, so the agent could not edit the code that scored it. Two research directions forked from one baseline: Sonnet 5.5 (10 trials) and Haiku 5.5 (15 trials), run one after the other on one machine. Settings: `--confirm --min-delta 13.94 --strict-metric --guard-imports`, with `tests/`, this directory, `pyproject.toml` and `uv.lock` protected.

## Results

`labloop noise` over six runs: 166.12 to 207.74 ms, standard deviation 13.94 ms (7%). `--min-delta` was set to the standard deviation, not the 41.62 ms spread, with `--confirm` as the second guard.

| Direction | Attempts | Kept | Best | Proposer cost |
| --- | --- | --- | --- | --- |
| baseline | | | 219.53 ms | |
| Sonnet 5.5 | 10 (+3 voided) | 2 | 171.76 ms (−22%) | $1.46, ~$0.11 per trial |
| Haiku 5.5 | 15 | 2 | 176.71 ms (−20%) | $0.45, ~$0.03 per trial |

The two directions differ by 5 ms, inside one standard deviation; this run does not separate the models on quality. It does separate them on cost, by about 3.7×.

**Independent check.** After the run, the timing half of the bench ran outside labloop on clean checkouts of the baseline and both bests, interleaved round-robin for eight rounds. Both bests were faster than the baseline in 8 of 8 paired rounds: −18.1% (Sonnet) and −17.9% (Haiku), against −22% and −20% claimed in the ledger, and indistinguishable from each other (244.3 against 244.9 ms mean). The keeps are real and slightly overstated. Absolute numbers were about 35% higher than inside the loop (baseline mean 298 ms, sd 8.5), so only interleaved comparisons are meaningful here; labloop's incumbent is a past measurement, not an interleaved one, and slow drift over a long run can bias keeps either way. Whether the threshold discarded real gains could not be checked, because reverted diffs are not recorded.

The loop's bookkeeping held: each direction's branch has exactly its two kept commits, each touching only `src/` and the decision log; both worktrees were clean after every revert, including the three voided trials; each trial was judged against the latest keep of its own direction. The ledger does not record the confirmation run's value, so the documented "incumbent advances to the weaker of the two" could not be audited.

Both directions independently found the same two improvements, in the same order:

1. Walk protected directories with `os.scandir` instead of `Path.rglob` plus a `relative_to` per file (Sonnet trial 4, Haiku trial 16; −7% and −8%). Checked against `rglob` on Python 3.10, 3.12 and 3.13, symlinked directories included: same file set.
2. Digest the protected set once per trial instead of twice, sharing the snapshot between the incumbent check and the pre-proposal check (Sonnet trial 9 via a cached attribute, Haiku trial 17 via an explicit parameter; −16% and −12%). Haiku's form is safe by construction; Sonnet's needed a caller analysis to show it was.

Neither change is merged; the kept commits live on the local `labloop/sonnet` and `labloop/haiku` branches of the run.

Of 21 reverted trials, roughly two thirds retried an idea already reverted: Haiku proposed removing a redundant `is_dirty()` call six times and string paths in the digest loop six times; Sonnet retried unbuffered or `file_digest` hashing seven times. Many of those measured 163 to 168 ms, a plausible real gain of about 10 ms that never clears a 13.94 ms threshold alone.

## What dogfooding found

Fixed on this branch:

- **Root sandbox kept a full capability bounding set.** Run as real root (containers, CI, cloud agents), bubblewrap skips the user namespace, so `--cap-drop ALL` left the bounding set full in the host namespace. CI runs the sandbox job unprivileged and never saw it. Now `--unshare-user` is explicit.
- **labloop's suite failed when labloop ran it.** Three tests read `PYTHONPYCACHEPREFIX` or `LABLOOP_BRIEF` from the enclosing loop. An autouse fixture now clears them and disables bytecode writes, which an enclosing `--guard-imports` would otherwise reject.
- **`labloop noise` hid why a run failed.** It raised a bare traceback without the command's output; an existing test asserted the traceback. It now exits 2 with the output tail.

Open, needing a decision:

- **The brief did not say what a trial changed.** It reported "the direction worked, the margin was too small" without naming the direction, and the ledger kept the run's output, not the proposal's. Addressed in `6788d70` (see [the decision](../../.plicara/decisions/2026-10-23-brief-records-what-changed.md)) and tested in run 2 below.
- **`--guard-imports` over-matches.** It flags stdlib-named paths at any depth among all ignored files, pre-existing ones included, so an in-tree `.venv` (`_pytest/doctest.py`) or the bytecode of a tracked submodule (`mypkg/types.py`) fails every trial. Flagging only paths absent at run start would keep the 1.0.5 `.gitignore` bypass closed.
- **A flagged shadow wedges the run.** The guard rejects the trial but never removes the ignored file it flagged, so every later trial fails until `--give-up-after`. Here an operator-written `.pyc` voided Sonnet trials 5 to 7; the guard blamed the proposal because it cannot tell who wrote it.
- **`labloop baseline` exits 0 when the baseline is not kept**, so a script cannot tell from the exit status.
- **Small gains cannot stack.** With noise at 7%, a real 5% improvement is reverted every time it is proposed. Reducing the benchmark's variance is the real fix here; a loop-level answer would be a separate design.
- **The ledger's `note` is empty on reverts.** The reason exists only in the brief.

Operating labloop with Claude Code as the proposer:

- Self-hosting needs a judge the agent cannot edit; a `uv tool install` of the pre-run commit worked.
- Claude Code denies reads outside its working directory, and the brief lives outside the worktree by design: pass `--add-dir "$(dirname "$LABLOOP_BRIEF")"`.
- In this environment Claude Code's Bash tool cannot run inside the sandbox: it creates a cgroup under the read-only `/sys/fs/cgroup`. The proposer ran without a shell, which the `labloop-proposer` skill does not anticipate (`cat "$LABLOOP_BRIEF"`, "run the experiment yourself").
- `acceptEdits` permits `rm` regardless of a Bash allowlist.
- A nested `claude -p` inherits the parent session's environment, including its session id.
- Never run code in a live worktree during a run: anything it writes is attributed to the trial in progress.

## Run 2: does recording the change reduce repeats?

**Setup (2026-10-23).** The same benchmark, models, trial budgets, prompt, shell-less tool set and threshold procedure as run 1, against labloop `6788d70`: run 1's two verified speedups merged, plus the brief recording each trial's `change` and a `tried` table, and the proposer skill explaining both. The judge was again a pinned install of that commit. Noise over six runs had a standard deviation of 3.22 ms against run 1's 13.94, so `--min-delta` was 3.22: a quieter machine, and a lower bar for keeps.

| Direction | Trials | Kept | Ledger claimed | Interleaved A/B | Proposer cost |
| --- | --- | --- | --- | --- | --- |
| baseline | | | 188.71 ms | | |
| Sonnet 5.5 | 10 | 2 | −8.0% | −4.4%, faster in 7/8 rounds | $1.08 |
| Haiku 5.5 | 9 (+1 killed, +1 interrupted) | 3 | −24.2% | −5.9%, faster in 7/8 rounds | $0.26 |

Repeats, scored two ways with the same method for both runs. Location repeats come from [`repeats.py`](repeats.py), which replays each proposer's edits from its transcript and names the enclosing definition; idea repeats are a hand classification of each attempt's own summary.

| Non-kept attempts repeating an earlier failure | Run 1 | Run 2 |
| --- | --- | --- |
| Sonnet, by location | 5 of 8 | 6 of 8 |
| Sonnet, by idea | 4 or 5 of 8 | 5 of 8 |
| Haiku first 9 trials, by location | 5 of 7 | 1 of 6 |
| Haiku first 9 trials, by idea | 5 of 7 | 1 of 4 edits, plus 2 deliberate no-edits |

**What this shows, and what it does not.**

- Sonnet repeated ideas as often as before. It read `tried`, acknowledged the earlier attempt, and re-proposed the digest I/O idea four more times, reasoning that the earlier gain may have been lost in noise. Location data says where an attempt went, not that its idea was settled.
- That reasoning is sometimes right: Sonnet's concurrent-digest idea was reverted by confirmation in trial 4, repeated in trial 6, and kept in trial 9. Run 1's two most-repeated ideas, string paths in the digest loop and dropping `is_dirty()`, were both kept under run 2's lower threshold, and measured outside the loop they are real but small: 6.2 and 2.6 ms.
- Haiku repeated far less and twice declined to edit rather than repeat, but the comparison is contaminated: Haiku trials 11, 15, 17 and 18 read this write-up, which was committed into the tree they worked in and names run 1's ideas and thresholds. Of Haiku's uncontaminated non-kept edits, one of three repeated an idea. The sample cannot separate the brief's effect from the write-up's.

**The loop overstated its gains.** Measured one step at a time outside the loop, Haiku's three keeps saved 2.3 ms (faster in 5 of 8 rounds), 6.2 ms (7 of 8) and 2.6 ms (5 of 8), where the ledger credited 17.7, 15.0 and 13.0 ms. All three were measured before the container restart, so restart drift does not explain it; the likely cause is the machine speeding up slowly over the hour, so later trials compared well against a baseline measured early. Noise calibrated over seven minutes of back-to-back runs cannot see drift over an hour, and `--confirm` re-measures the candidate, never the incumbent. In run 1 the overstatement was a few points; here it was about four times the real gain.

**Restart drift stopped the run.** A container restart killed Haiku trial 17 mid-proposal; `labloop resume` refused the unjudged tree with the right recovery command and continued. Afterwards the incumbent's own tree measured 164.7 to 169.7 ms against the 143.04 recorded before the restart, about 17% slower, so no remaining trial could keep anything. Re-running a baseline cannot reset the bar, because the incumbent is the best kept metric ever recorded. Haiku was stopped after nine trials; trial 20 is recorded as interrupted.

New findings:

- **Comparisons are unpaired across time.** The candidate is measured now and the incumbent was measured earlier, so drift becomes progress or regression. Measuring the incumbent tree beside each candidate, or re-measuring it on each confirmation, would make the comparison immune to drift at the cost of one more run per trial.
- **The incumbent cannot be re-measured.** After a machine change, the only options are a new ledger or a new direction, which loses the history and `tried`.
- **Results committed to the tree reach the proposer.** Proposers read the whole repository, so a write-up of the last run is in effect a memory file. Keep notes outside the tree under study, or publish them after the run.
- **A killed run leaves no trace.** SIGKILL records nothing, so the next trial reuses the index; a wrapper that names evidence files by `$LABLOOP_TRIAL` overwrites the killed attempt's transcript unless moved first.
- **`resume` cannot choose a direction.** It continues the direction of the newest manifest.
- **`where` attribution is approximate.** git names the definition above a hunk, so an edit at the top of a function is attributed to the one before it.
- **The confirmation note works.** Two lucky draws were caught with both numbers on record (Sonnet trials 4 and 10: 167.82 then 177.38, 156.83 then 170.93).
- One finding withdrawn: run 1's driver logs report `exit 0` for every run because `$?` followed a `$(date)` substitution. labloop itself exits 130 on interrupt.

## Run 3: does paired measurement make the claims true?

**Setup (2026-10-24).** As run 2, against labloop `f6becd9`, with `--paired` added and `--min-delta` set to √2 times the noise standard deviation (7.99 ms, so 11.30), because a paired comparison is a difference of two runs. The run branches carried one local commit removing this write-up and the decision records, so no proposer could read earlier results; a search of the remaining documentation found no optimization idea named in it.

| Direction | Trials | Kept | Paired claim | Interleaved A/B | Proposer cost |
| --- | --- | --- | --- | --- | --- |
| baseline | | | 196.34 ms | | |
| Sonnet 5.5 | 10 | 1 (`git ls-files`, trial 10) | −7.2% | −1.0%, faster in 7/8 rounds | $1.26 |
| Haiku 5.5 | 8 judged (+3 failed) | 1 (string paths, trial 18) | −11.3% | −2.1%, faster in 6/8 rounds | $0.21 |

Pairing did what it was built to do about drift. The incumbent re-measured between 183.9 and 220.3 ms over the run while the ledger held 196.34; Sonnet's keep measured 204.34, worse than the recorded baseline, and could not have been kept against it.

**It did not make the claims true.** The two keeps were judged against the two slowest of 21 incumbent re-measurements (220.3 and 215.6 ms, median 203.9). One incumbent draw is the bar for both the candidate's first run and its confirmation, so a slow draw lets both pass: the confirmation is not independent of the decision, and the loop selects for unlucky references. Both keeps are real, faster in most interleaved rounds, but each was credited with five to seven times its size. See [the follow-up decision](../../.plicara/decisions/2026-10-24-paired-confirmation-reuses-its-reference.md).

**Repeats, with no proposer able to read earlier results.** Sonnet repeated a failed location in 6 of 9 non-kept trials, as in runs 1 and 2; it tried concurrent hashing three times after it regressed by a third each time. Haiku repeated in 3 of 7. Recording the change in the brief does not measurably stop Sonnet repeating itself; for Haiku the uncontaminated effect is at most modest.

**How it ended.** The account's usage limit refused every proposal from Haiku trial 19 on, and `--give-up-after 3` stopped the run after three failed proposals. Under `--paired` each of those still cost a full incumbent measurement first, because the re-measurement precedes the proposal. Haiku trial 13 may have been perturbed: the operator ran the test suite while it measured.

## Across the three runs

| | Run 1 | Run 2 | Run 3 |
| --- | --- | --- | --- |
| labloop | `d45f943` | `6788d70`: brief records changes | `f6becd9`: and `--paired` |
| `--min-delta` | 13.94 (1 sd) | 3.22 (1 sd) | 11.30 (√2 sd) |
| Keeps, both directions | 4 | 5 | 2 |
| Ledger's gain vs interleaved | −22%/−20% vs −18% | −8%/−24% vs −4%/−6% | −7%/−11% vs −1%/−2% |
| Sonnet, non-kept repeating a failed location | 5 of 8 | 6 of 8 | 6 of 9 |
| Haiku, non-kept repeating a failed location | 11 of 13 | 1 of 7 (contaminated) | 3 of 7 |
| Proposer cost | $1.91 | $1.34 | $1.47 |

What holds across all three: keep-or-revert, the git bookkeeping and the tamper checks behaved correctly in every run, and each run's final commit was faster than its baseline when checked outside the loop; individual keeps were sometimes too small to tell from noise. What does not hold: the size the ledger credits a keep with. Every run overstated it, and the two changes meant to help, recording the change and pairing the measurement, did not fix that. Until a confirmation measures the incumbent independently, a run's total is an upper bound to verify, not a result.

## Reproducing

The bench needs bubblewrap and runs in about 70 s:

```bash
uv run --locked --extra dev python experiments/self_overhead/bench.py
```

The driver scripts, proposer wrapper and prompt were operator files outside the repository, as were the ledgers and transcripts. Score repeats with `python3 experiments/self_overhead/repeats.py LEDGER EVIDENCE_ROOT PREFIX . START_COMMIT`.
