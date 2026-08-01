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
`H` the proposal changed the harness.

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
| `harness_changed` | The proposal edited the thing doing the measuring. |

Four details that matter:

- **A tie is not an improvement.** Equal scores revert, so the loop never
  accumulates neutral churn.
- **A missing metric is not a bad score.** A broken experiment and a poor
  result are different events and are recorded differently.
- **The loop refuses to start on a dirty tree.** It reverts by discarding, so
  uncommitted work would be destroyed.
- **A metric from a changed harness is not a result.** See below.

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
[H] trial   1            --     0.0s  (proposal modified the harness)
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
quietly disable the whole check.

## Reading the metric

Two formats, no configuration. The last occurrence wins, so printing every
epoch is fine.

```
val_loss = 1.234        # key=value or key: value
{"step": 40, "val_loss": 1.234}    # a JSON object on its own line
```

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
