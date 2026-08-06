---
name: labloop-proposer
description: "Use this skill when acting as the proposal step inside a labloop experiment loop — when $LABLOOP_BRIEF or $LABLOOP_INCUMBENT is set in the environment, when invoked by a `--propose` command, or when asked to make a change that will be judged by a metric and kept or reverted automatically. Covers reading the brief, choosing one change, avoiding the protected harness, and interpreting each of labloop's nine trial outcomes. Do NOT use for ordinary code changes that no loop is measuring."
---

# Proposing a change inside a labloop loop

You are one attempt inside a keep-or-revert loop. Something ran before you and
something will measure you. Your change is committed only if the metric
improves; otherwise it is discarded and the next attempt starts from the tree
as it was.

Two consequences that change how you should work:

- **Your change is cheap to lose and expensive to fake.** You do not need to
  be conservative to protect the codebase — a bad change is reverted
  automatically. You *do* need to be honest, because the loop rewards anything
  that moves the number.
- **You will not remember this attempt.** The next proposal is a fresh
  invocation. The brief is the only continuity, and you cannot write to it.

## First: read the brief

`$LABLOOP_BRIEF` holds a path to JSON describing every trial so far.

```bash
cat "$LABLOOP_BRIEF"
```

```json
{
  "trial": 6, "metric": "val_loss", "goal": "minimize",
  "incumbent": 0.2651, "protected": ["eval.py"],
  "counts": {"kept": 3, "reverted": 2, "failed": 1},
  "history": [
    {"index": 2, "outcome": "reverted", "metric": 0.4424,
     "why": "reverted: val_loss 0.442413 did not beat 0.434422; lower is better"},
    {"index": 5, "outcome": "failed", "metric": null,
     "why": "reverted: the command exited non-zero",
     "output_tail": "NameError: name 'this' is not defined\n"}
  ]
}
```

Read three things before you touch anything:

1. **`incumbent` and `goal`** — the number to beat and which direction is
   better. There is no partial credit and **a tie reverts**.
2. **`history[].why`** — why each previous attempt was judged as it was. This
   is the field you cannot reconstruct yourself.
3. **`history[].output_tail`** — on failures, the actual traceback. Read it
   before re-attempting anything near that code.

If `$LABLOOP_BRIEF` is unset, fall back to `$LABLOOP_METRIC`, `$LABLOOP_GOAL`,
`$LABLOOP_INCUMBENT` (empty when nothing has been measured yet) and
`$LABLOOP_TRIAL`.

## Make one change

One focused change per trial, always. This is not stylistic advice — it is
what the loop can actually resolve:

- The loop measures the trial, not the edit. Five changes in one trial score
  as one number, and you learn nothing about which of the five helped.
- A reverted trial throws away all five. A kept trial commits all five,
  including the four that hurt and were masked by the one that helped.
- Large rewrites fail the harness check more often, and a `failed` trial
  teaches the loop nothing about the idea.

**Observed failure mode:** after three reverts, an agent spent seven times its
usual thinking budget on a sweeping rewrite and produced its worst result of
the run. Escalating scope after a revert is the wrong instinct. Escalate
*specificity* instead.

## Do not touch the harness

`protected` in the brief lists files that define the measurement — evaluators,
holdout data, test fixtures, benchmarks. labloop digests them before and after
you run.

Editing one is recorded as `harness_changed` and scored as nothing. It is not
a clever shortcut; it is the one move the tool is built to catch, and it wastes
a trial.

This includes the subtle versions:

- Adding a file inside a protected directory (memorising answers).
- Making the metric easier to print rather than easier to achieve.
- Weakening an assertion "temporarily".
- Writing a cache into a protected path, which breaks the digest for every
  later trial.

If the harness genuinely looks wrong, **say so in your output and change
nothing**. A human decides that, not this trial.

## Verify before you finish

Run the experiment command yourself before ending the attempt. A trial that
crashes produces `failed` — no metric, no information, one trial gone.

If you cannot run it (no permission, too slow), re-read your diff for the
things that produce `failed`: syntax, imports, a renamed symbol used elsewhere.

## Reading the outcome of your last attempt

Each label sends you somewhere different. This is why there are nine of them.

| Outcome | What happened | What to do next |
| --- | --- | --- |
| `kept` | Improved. Committed. | Continue in the same direction; the incumbent moved. |
| `reverted` | Measured, did not win. | Change idea, not scale. See the trap below. |
| `failed` | Non-zero exit. | Read `output_tail`. Fix the crash before re-trying the idea. |
| `timed_out` | Exceeded budget, killed with its process group. | Make it cheaper, or the idea is unaffordable. |
| `no_metric` | Ran clean, printed nothing parseable. | You probably broke the line that prints the metric. |
| `not_finite` | `nan` or `inf`. | Numerical instability — usually a rate, a divide, or a log. |
| `no_change` | Your edit changed nothing. | Your patch did not apply. Check paths and that you saved. |
| `harness_changed` | You edited a protected file. | Revert that instinct entirely; see above. |
| `interrupted` | A human stopped it. | Nothing to learn. |

### The `reverted` trap

A change can move the metric the *right* way and still be reverted, when the
gain is inside the band `--min-delta` treats as noise. Current labloop says so
outright:

```
reverted: seconds 0.155 beat 0.2245 by 0.0695, but --min-delta needs more
than 0.0727; the direction worked, the margin was too small to trust
```

When you see that, **push further in the same direction.** The change worked;
it was too small to be believed over the experiment's noise. Do not abandon
it, and do not switch strategy.

On labloop 0.1.0 and earlier the same trial read *"did not beat 0.2245; lower
is better"*, which is false and points the wrong way. If you are on an older
version, check the arithmetic yourself: compare `history[-1].metric` against
the `incumbent` at the time, and if your number was better, treat it as the
message above.

## Do not leave notes for yourself

The brief is written by labloop and read by you, never the reverse. Do not
create scratch files, memory files, or comments addressed to future attempts.
Persistent side-channels turn a measured loop into an unmeasured one, and
files you leave behind either dirty the tree or get committed with a win.

Everything you need is in the brief. If it is not, that is a gap in the brief,
and the fix belongs in labloop.

## Report what you did

Your stdout is not scored, but a human reads it when a run goes wrong. One or
two lines: what you changed, and the reasoning that would not be obvious from
the diff.
