---
name: labloop-setup
description: "Use this skill when setting up a labloop experiment in a repository — choosing the metric, wiring --run, deciding what to --protect, and checking the metric holds still before any trials are spent. Triggers on requests to 'set up labloop', 'run an experiment loop', 'have an agent optimize this against a metric', or when a repo has labloop installed but no baseline yet. Do NOT use when a loop is already configured and running; that is labloop-triage."
---

# Setting up a labloop experiment

Four decisions, in this order. Getting the order wrong is how people waste a
night of compute.

## 1. Pick a metric that is a number

The experiment command must print it on stdout, in one of two formats. Last
occurrence wins, so printing every epoch is fine.

```
val_loss = 1.234
{"step": 40, "val_loss": 1.234}
```

If the code writes JSON to a file instead, do not restructure the project —
add one line to the end of the run command:

```bash
--run "python train.py && python -c \"import json;print('val_loss =', json.load(open('metrics.json'))['val_loss'])\""
```

**Choose the metric so that better is unambiguous.** If you find yourself
wanting to optimise two things, put one in the metric and enforce the other as
a hard failure in the harness (exit non-zero below the floor). A loop cannot
break a tie between two goals.

**Prefer continuous over coarse.** A metric with few possible values (error
rate on 20 examples, a pass count) produces exact ties, and a tie reverts —
so real improvements get discarded for landing on the same value.

## 2. Decide what `--run` covers

It must cover **everything that produces the number**, and nothing expensive
that does not.

The common mistake is training inside `--run` and evaluating outside it. The
loop then scores whatever the last evaluation happened to leave behind, which
is a stale number from a previous trial.

## 3. Choose the protect set

`--protect` names the files that define the measurement. labloop digests them
with SHA-256 before and after each proposal, and a trial that moves them is
recorded as `harness_changed` rather than scored.

Protect:

- the evaluator or test that computes the metric
- the holdout data, including the split that defines it
- any golden/expected output the check compares against

Do not protect:

- the file the agent is meant to edit
- anything written during a run — caches, logs, checkpoints

**Protect the measurement, not the directory it lives in.** If the evaluator
writes a cache inside a protected path, the digest moves every run and the
loop will refuse to compare its own trials. Move the cache out, or protect the
files rather than the directory.

A pattern matching nothing is an error, not a silent pass — that is deliberate,
because a typo there would quietly disable the whole check.

**This detects, it does not prevent.** A shell command can do anything. What
you get is that such a trial is recorded, and that every trial carries the
digest of how it was measured.

## 4. Measure the noise before you trust anything

This is the step people skip, and it is the one that decides whether the run
means anything.

```bash
labloop noise --run "python train.py" --metric val_loss --repeat 6
```

Nothing changes between those runs, so whatever spread you see is what the
experiment produces on its own. Any "improvement" smaller than that is the
loop selecting lucky runs — and it will look exactly like progress.

**Removing the variance is the real fix**: fix the seed, hold the split still,
average over more data, pin the benchmark to a core. Do that first.

When you cannot:

- `--min-delta D` — the metric must improve by more than `D`. Cheap, and
  attacks how *often* a fluke is kept.
- `--confirm` — re-run before keeping, keep only if it wins twice. Costs one
  extra run per candidate win, and attacks how *far* a fluke drifts.

They are cheaper together than `--confirm` alone, because `--min-delta`
rejects most candidates before they earn a second run.

**Which number for `--min-delta`?** `noise` prints both a spread and a
standard deviation. The spread widens with every extra run; the sd is stable.
Using the spread is conservative and will discard real improvements — in one
recorded run it threw away three genuine speedups of 31%, 27% and 15%. Using
the sd lets more flukes through. Pick deliberately and write down which you
picked and why.

## Then, in order

```bash
labloop init                      # gitignore, stub experiment, next commands
labloop noise --run ... --repeat 6
labloop baseline --run ... --protect ...
labloop run --run ... --propose ... --trials N
```

Two things that will stop you before trial 1:

- **The tree must be clean.** The loop reverts by discarding, so it refuses to
  start with uncommitted changes. Keep run logs and scratch files outside the
  repository — redirecting a log into the tree is enough to trip it.
- **Give the proposer its own budget.** `--budget` is for the experiment;
  `--propose-budget` is for the agent, which normally thinks for far longer
  than the experiment runs. Sharing one number means either killing the agent
  mid-thought or handing the experiment minutes it cannot use.
