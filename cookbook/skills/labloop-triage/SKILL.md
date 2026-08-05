---
name: labloop-triage
description: "Use this skill to diagnose a labloop run that is not producing results — nothing is being kept, every trial fails or times out, the loop gave up early, refuses to start, or reports progress that looks too good. Triggers on 'why is nothing being kept', 'the loop gave up', 'labloop refuses to run', 'these results look wrong', or when reading a labloop.jsonl ledger to work out what went wrong. Do NOT use for initial configuration; that is labloop-setup."
---

# Diagnosing a labloop run

Start from the ledger, not from the code. It records every trial including the
discarded ones, which is where the diagnosis lives.

```bash
labloop log --metric <metric>            # replay, with per-direction bests
labloop log --json | head -20            # one strict JSON object per trial
labloop log --outcome reverted --json    # only what was thrown away
```

The outcome distribution is the first thing to look at, because each label
points somewhere different.

```bash
labloop log --json | python -c "
import sys,json,collections
c=collections.Counter(json.loads(l)['outcome'] for l in sys.stdin if l.strip())
print(c.most_common())"
```

## Nothing is being kept

**Mostly `reverted`, metrics close to the incumbent.** The proposals are real
but small. Check whether `--min-delta` is set: a change that beat the incumbent
by less than the threshold is reverted, and the message reads *"did not beat
X"* even though it did. Compare each reverted trial's metric against the
incumbent at the time:

```bash
labloop log --json | python -c "
import sys,json
for l in sys.stdin:
    t=json.loads(l)
    if t.get('outcome')=='reverted' and t.get('metric') is not None and t.get('incumbent') is not None:
        better = t['metric'] < t['incumbent']   # flip for maximize
        if better: print('trial',t['index'],'was BETTER but reverted:',t['metric'],'vs',t['incumbent'])"
```

If that prints anything, the loop is discarding real progress and the threshold
is too aggressive for the noise. Re-run `labloop noise` and consider the
standard deviation rather than the spread.

**Mostly `reverted`, metrics wandering far above and below.** The metric is
noisy and the loop is doing its job. Fix the variance at the source before
spending more compute.

**Everything ties.** The metric is too coarse — a small integer count or an
error rate over few examples. A tie reverts by design. Use a continuous metric.

## Every trial fails

**`failed`** — read the tail:

```bash
labloop log --outcome failed --json | python -c "
import sys,json
for l in sys.stdin: print(json.loads(l).get('stdout_tail','')[-400:])"
```

One repeated traceback means the agent keeps making the same broken edit; the
brief carries `output_tail` so it should see it. If the same error recurs
anyway, the proposer is probably not reading the brief at all.

**`no_metric`** — the command ran clean and printed nothing parseable. Either
the proposal broke the line that prints the metric, or `--metric` names a key
the output does not contain. Run the experiment by hand and look at stdout.

**`no_change`** — the proposal edited nothing. The proposer command is wrong,
the agent is writing to the wrong path, or it is refusing the task. This is
the single most common wiring bug. Run the propose command by hand in a dirty
scratch copy and see whether it touches a file.

**`harness_changed`** — the proposal is editing the measurement. If it is once,
the agent wandered. If it is every trial, the agent believes the harness is the
task; the prompt needs to name the file it may edit and the files it may not.

**`timed_out`** — distinguish the two cases. A timed-out *experiment* means the
change made it too slow (or `--budget` is unrealistic). A timed-out *proposal*
means the agent needs a larger `--propose-budget`, which is separate on
purpose.

## The loop gave up

Ten consecutive trials producing no metric ends the run. That is
`--give-up-after` (set `0` to disable), and it fires on an unbroken run, not on
occasional failures. It almost always means the proposer is broken rather than
unlucky — check `no_change` and `no_metric` above before raising the limit.

## It refuses to start

**Dirty tree.** The loop reverts by discarding, so uncommitted work would be
destroyed. Commit it, stash it, or — if it is an unjudged leftover from an
interrupted run — discard it. Keep logs and scratch files outside the repo.

**Ledger locked.** Another run holds it; the message names the pid. Wait, use
`--wait` to queue, or confirm the other run is gone.

**Harness digest mismatch.** The incumbent in the ledger was measured under a
different harness, so comparing would mix measurements. Either restore the
harness or start a new ledger — do not "fix" it by disabling `--protect`.

**Identity drift.** A run whose `--metric` or `--goal` differs from the
manifest is refused with the field named. Those two define what the recorded
numbers mean. Budgets and trial counts may drift; identity may not.

## The results look too good

Take it seriously — this is the failure mode the tool exists to make visible.

1. **Was noise ever measured?** If not, do it now. If the spread is near the
   claimed improvement, the wins are dice.
2. **Did the harness hold?** Every trial carries its digest; two trials with
   different digests are not comparable.
3. **Read the winning diffs.** `git log` holds only the kept commits, so this
   is short.

```bash
git log --oneline | head -20
git show <commit>
```

Look for the metric being printed rather than earned, an assertion weakened, a
holdout file appearing, or the evaluator learning to answer instead of grade.

4. **Re-run the baseline against the final tree.** If the improvement does not
   reproduce from a cold start, it was never there.
