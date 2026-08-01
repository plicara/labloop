# labloop

**Keep a change only if it measurably helps.**

An experiment loop for agent-driven research. Point it at a command that runs
your experiment and a command that changes your code, and it will run trials
under a wall-clock budget — keeping the changes that improve your metric and
reverting everything else.

Every trial is recorded, including the failures. `git log` only remembers what
was kept, and the reverted attempts are most of the information.

```bash
pip install labloop
```

## Use

Establish a baseline, then let an agent iterate against it:

```bash
labloop baseline --run "python train.py" --metric val_loss

labloop run \
  --run "python train.py" \
  --metric val_loss \
  --propose "my-agent --edit train.py" \
  --budget 300 \
  --trials 50
```

```
[+] trial   0        2.431    41.2s          (baseline)
[+] trial   1        2.298    38.9s  a1f4c02
[-] trial   2        2.355    39.4s
[T] trial   3           --   300.0s
[+] trial   4        2.201    40.1s  7bd9e13

best val_loss: 2.201 (trial 4)
```

`+` kept, `-` reverted, `T` timed out, `!` crashed, `?` no metric found,
`~` the metric was `nan` or `inf`, `=` the proposal changed nothing,
`H` the proposal changed the harness, `^` interrupted.

Or from Python:

```python
from labloop import Experiment, Goal, Loop

exp = Experiment(
    run="python train.py",
    metric="val_loss",
    goal=Goal.MINIMIZE,
    budget_seconds=300,
    propose="my-agent --edit train.py",
    protect=("eval.py", "data/holdout"),
)

loop = Loop(exp)
loop.baseline()
loop.run(trials=50)
```

## How it decides

Each trial runs your `propose` command, then your `run` command, then reads the
metric from the output. The change is committed only if the metric beat the
incumbent. Anything else is discarded:

| Outcome | Meaning |
| --- | --- |
| `kept` | Metric improved. Committed. |
| `reverted` | Metric was worse, or tied. |
| `failed` | The command exited non-zero. |
| `timed_out` | Exceeded the budget. Process group killed. |
| `no_metric` | Ran clean but printed no metric. |
| `not_finite` | The metric was `nan` or `inf`. Nothing compares to it. |
| `no_change` | The proposal edited nothing, so there was nothing to measure. |
| `harness_changed` | The proposal edited the thing doing the measuring. |
| `interrupted` | Stopped by hand partway through. |

Four details that matter:

- **A tie is not an improvement.** Equal scores revert, so the loop never
  accumulates neutral churn.
- **A missing metric is not a bad score.** A broken experiment and a poor
  result are different events and are recorded differently. So are a crash, a
  diverged run that printed `nan`, and a proposal that edited nothing — each
  sends you somewhere different, so each gets its own outcome.
- **The loop refuses to start on a dirty tree.** It reverts by discarding, so
  uncommitted work would be destroyed.
- **A metric from a changed harness is not a result.** See below.

It also stops when it stops learning. Ten trials in a row that produce no metric
at all — a mistyped `propose` command, an agent that never applies its edit —
end the run rather than spend the rest of an overnight budget failing
identically. Occasional failures don't count; only an unbroken run of them does.
Change it with `--give-up-after N`, or `0` to run regardless.

## Check your metric holds still

Keep-or-revert assumes that a change in the metric means a change in the code.
If your experiment scores differently run to run, that assumption is false, and
the loop will commit the luckier draws and report them as progress.

Find out before you start:

```bash
labloop noise --run "python train.py" --metric val_loss --repeat 6
```

```
val_loss: 0.857473 to 1.11126 over 6 identical runs
spread: 0.253788

An improvement smaller than 0.253788 is within what this experiment does on its
own, so the loop would be selecting lucky runs. Best is to remove the variance —
fix the seed, average more, hold the data still. Failing that:

    labloop run --min-delta 0.253788 --confirm ...
```

Nothing changed between those runs. Any "improvement" below the spread is the
loop picking a good roll of the dice.

**Removing the variance is the real fix.** Fix the seed, average over more
data, hold the split still. Two settings help when you can't:

- `--min-delta D` — the metric must improve by more than `D` to count. Attacks
  how *often* a fluke is kept, and costs nothing.
- `--confirm` — re-run before keeping, and keep only if it wins twice. The
  incumbent then advances to the weaker of the two measurements, so a lucky
  draw doesn't set a bar only luck can clear. Attacks how *far* the fluke
  drifts, and costs one extra run per candidate win.

Measured on a metric that is pure noise, where every kept trial is false by
construction — 60 trials, averaged over 400 runs:

| Setting | Improvement claimed | False keeps | Experiment runs |
| --- | --- | --- | --- |
| default | 23.5% | 4.8 | 60 |
| `--min-delta` (1 sd) | 20.7% | 2.4 | 60 |
| `--confirm` | 12.9% | 4.8 | 72.7 |
| both | **9.9%** | **2.1** | 66 |

They work on different halves of the problem, and are cheaper together than
`--confirm` alone — `--min-delta` rejects most candidates before they earn a
second run. Neither makes a noisy metric safe. They make it less wrong.

## Protecting the measurement

A keep-or-revert loop rewards whatever moves the metric, and your `propose`
command can reach the evaluator. Agents take that route: published runs have
seen them overwrite test cases and memorize evaluation answers rather than
improve anything.

Name the files that define the measurement and labloop digests them with
SHA-256 before and after each proposal:

```bash
labloop run \
  --run "python eval.py" \
  --metric val_err \
  --protect eval.py \
  --protect data/holdout \
  --propose "my-agent --edit train.py"
```

```
[+] trial   0             1     0.0s  (baseline)
[H] trial   1            --     0.0s  (proposal modified the harness: eval.py)
[+] trial   2        0.3333     0.0s  7c599cd
```

A pattern may name a file, a glob, or a directory — a directory covers the
whole subtree, which is usually what frozen evaluation data needs. Renames,
deletions, and added files all move the digest, because memorizing answers
means adding files and not only editing them.

**This detects, it does not prevent.** A shell command can do anything, and
claiming otherwise would be a promise this design can't keep. What labloop
gives you is that such a trial is recorded as `harness_changed` instead of
scored, and that every trial carries the digest of how it was measured — so
two trials with the same digest are comparable, and you can prove it after the
fact. The ledger itself is checked the same way on every trial, without being
declared: it holds the incumbent, and an agent that can rewrite it doesn't need
to beat it.

If the incumbent in your ledger was measured under a different digest, the loop
stops rather than compare two numbers that came from different measurements.

Patterns matching nothing are an error, not a silent pass — a typo there would
quietly disable the whole check. When something does move, the trial names the
file, so `proposal modified the harness: data/holdout.csv` tells you where to
look.

**Protect the measurement, not the directory it lives in.** If your evaluator
writes a cache or a log inside a protected path, that path stops being stable
and the loop will refuse to compare against its own earlier trials. Caches are
artifacts; keep them somewhere you are not protecting.

## Reading the metric

Two formats, no configuration. The last occurrence wins, so printing every
epoch is fine.

```
val_loss = 1.234        # key=value or key: value
{"step": 40, "val_loss": 1.234}    # a JSON object on its own line
```

## What the proposer is told

A proposal command that gets no feedback is guessing. Before each attempt
labloop writes the trial history to a JSON file and puts its path in
`$LABLOOP_BRIEF`:

```json
{
  "trial": 5,
  "metric": "val_loss",
  "goal": "minimize",
  "incumbent": 1.5,
  "protected": ["eval.py"],
  "counts": { "kept": 2, "reverted": 2, "failed": 1 },
  "history": [
    {
      "index": 1, "outcome": "reverted", "metric": 2.0,
      "why": "reverted: val_loss 2 tied the incumbent, and a tie is not an improvement"
    },
    {
      "index": 3, "outcome": "reverted", "metric": 3.0,
      "why": "reverted: val_loss 3 did not beat 1.5; lower is better"
    }
  ]
}
```

The `why` is the part the proposer can't work out for itself. `reverted` is a
label; *tied the incumbent, and a tie is not an improvement* is something to
act on. Failures carry the tail of their output, so an agent can see the stack
trace that killed its last three attempts.

For a one-line proposal command that doesn't want to parse JSON, the same
essentials are in `$LABLOOP_METRIC`, `$LABLOOP_GOAL`, `$LABLOOP_INCUMBENT`
(empty when there is nothing to beat yet) and `$LABLOOP_TRIAL`.

The brief is written by labloop and read by the proposal, never the reverse.
Agents handed a memory file they can write have been seen leaving notes for
their future selves, which turns persistent memory into a way around the
harness rather than a record of it. The agent learns what happened without
getting to decide what happened.

Pass `--no-brief` to turn it off. The file is written outside the working tree
either way, so it never dirties the tree or lands in a commit.

## Keep artifacts out of git

A kept trial is committed with `git add -A`, so anything your experiment leaves
behind is committed too. A checkpoint written every trial is a checkpoint in
every commit, and the commit stops meaning "the change that improved the
metric".

Put artifacts in `.gitignore` — checkpoints, logs, `__pycache__`, whatever your
run writes. You will hit this anyway: the loop refuses to start on a dirty tree,
and an untracked artifact makes the tree dirty.

## The ledger

Trials append to `labloop.jsonl` — one JSON object per line, readable while the
run is still going.

```bash
labloop log --metric val_loss
```

```python
from labloop import Goal, Ledger

ledger = Ledger("labloop.jsonl")
ledger.summary()        # {'kept': 7, 'reverted': 31, 'timed_out': 2, ...}
ledger.best(Goal.MINIMIZE)
```

## Prior art

The keep-or-revert loop is the idea behind
[Karpathy's autoresearch](https://github.com/karpathy/autoresearch), which
wires it directly into single-GPU nanochat training. `labloop` is not that
project and is not affiliated with it. It generalizes the loop: any command,
any metric, no GPU assumption, with the trial history as a queryable artifact
rather than scrollback.

## Status

Alpha. The API will change. Stdlib only, no dependencies.

## License

Apache-2.0.
