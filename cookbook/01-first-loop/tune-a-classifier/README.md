# Tune a classifier and watch the loop throw most of it away

**The question.** I have a script and a metric. What does a real labloop run
actually look like, start to finish — and what does it feel like when it
works?

Six trials. Two survive. That ratio is the point.

Everything below is executed by `run.sh`, which CI runs on every push. The
output is pasted from a real run, not from memory.

## What you're tuning

A bag-of-words spam classifier in three files, stdlib only:

- `train.py` — the model and four knobs. **This is the file the proposer edits.**
- `evaluate.py` — the holdout messages and the scoring function. **Protected.**
- `data.py` — the training messages. **Protected.**

The metric is mean cross-entropy on the holdout, not error rate. That choice
matters more than it looks: twenty holdout messages give error rate only
twenty-one possible values, so most genuine improvements would land on an
exact tie — and [a tie is not an improvement](../../../README.md#how-it-decides),
so the loop would revert them. A continuous metric grades what a coarse one
rounds away.

Copy the directory and run it:

```bash
cp cookbook/01-first-loop/tune-a-classifier/files/*.py .
git init -q . && git add -A && git commit -qm "before any tuning"
```

## Step 1: find out whether the metric holds still

Before measuring anything, measure the measurement:

```bash
labloop noise --run "python train.py" --metric val_loss --repeat 3
```

```
    run 0  0.464869
    run 1  0.464869
    run 2  0.464869

val_loss: 0.464869 to 0.464869 over 3 identical runs
spread: none — every run agreed, so any change in the metric is the change
```

This experiment is deterministic, so every improvement the loop reports is
real. That is the easy case, and you should confirm you're in it rather than
assume it. A model with a random seed, a shuffled split, or a GPU
reduction order would print a spread here, and every number after this point
would need [`--min-delta` and `--confirm`](../../../README.md#check-your-metric-holds-still)
to mean anything.

**Do this first, every time.** It costs three runs and it is the difference
between a research record and a list of lucky dice rolls.

## Step 2: take a baseline

```bash
labloop baseline --run "python train.py" --metric val_loss \
  --protect evaluate.py --protect data.py
```

```
[+] trial   0      0.464869     0.0s  (baseline)
```

`--protect` names the files that define the measurement. labloop digests them
with SHA-256 before and after every proposal. Note that `data.py` is protected
too: an agent that can edit the training set can make the holdout easy instead
of making the model good.

## Step 3: let it run

```bash
labloop run --run "python train.py" --metric val_loss \
  --protect evaluate.py --protect data.py \
  --propose "python propose.py" --trials 6
```

```
[+] trial   1      0.434422     0.1s  d898535
[-] trial   2      0.442413     0.0s
[-] trial   3       0.57752     0.0s
[+] trial   4      0.265123     0.0s  dc00be4
[!] trial   5            --     0.0s
      NameError: name 'this' is not defined
[H] trial   6            --     0.0s  (proposal modified the harness: evaluate.py)

best val_loss: 0.265123 (trial 4)
```

Six attempts, and the loop's judgement on each:

| Trial | The proposal | Verdict |
| --- | --- | --- |
| 1 | `LOWERCASE = True` | 0.4344 beat 0.4649. **Kept**, committed as `d898535`. |
| 2 | `STRIP_PUNCT = True` | 0.4424 lost to 0.4344. **Reverted** — plausible, and wrong. |
| 3 | `ALPHA = 5.0` | 0.5776, clearly worse. **Reverted.** |
| 4 | `ALPHA = 0.1` | 0.2651. **Kept** — a 43% cut, the run's real result. |
| 5 | syntax error | **Failed.** Not scored as a bad result, because a crash isn't one. |
| 6 | rewrote `evaluate.py` | **Harness changed.** Caught, not scored. |

Trial 2 is the one worth sitting with. Stripping punctuation is a reasonable
thing to try — `!!!` looks like spam signal, and removing noise usually helps.
It made the model worse. Without the loop you'd have kept it, because it
sounds right, and you'd have carried it into every experiment after.

Trial 6 is the other one. The proposer, having crashed on trial 5, rewrote the
file that grades it. Real agents do this — the README is blunt that
[published runs have seen it](../../../README.md#protecting-the-measurement).
labloop recorded it as `harness_changed` and scored nothing.

**What this does not prove:** that labloop *prevented* the cheat. It detected
it. A shell command can do anything; what you get is that the trial is
recorded rather than scored, and that every trial carries the digest of how it
was measured.

## Step 4: read what happened

```bash
labloop log --metric val_loss
```

```
kept=3  reverted=2  failed=1  harness_changed=1
val_loss: 0.265123 (trial 4)
```

And the repository holds only the wins:

```
dc00be4 labloop: val_loss 0.265123 (was 0.434422)
d898535 labloop: val_loss 0.434422 (was 0.464869)
ec30a12 spam classifier, before any tuning
```

Two commits from six attempts. `train.py` ends with exactly the two changes
that earned their place:

```python
ALPHA = 0.1        # kept, trial 4
MIN_COUNT = 1      # never changed
LOWERCASE = True   # kept, trial 1
STRIP_PUNCT = False  # tried at trial 2, reverted
```

The four failures are not in `git log`, and that is the whole argument for the
ledger: they are most of the information. Trial 2 is a result — *punctuation
stripping hurts this classifier* — and it is a result you only have because
something wrote it down.

## What the proposer was told

Before each attempt labloop writes the history to a JSON file and puts the
path in `$LABLOOP_BRIEF`. Here is the real brief, after trial 5:

```json
{
  "trial": 6,
  "metric": "val_loss",
  "goal": "minimize",
  "incumbent": 0.2651227330068643,
  "counts": { "kept": 3, "reverted": 2, "failed": 1 },
  "history": [
    { "index": 2, "outcome": "reverted", "metric": 0.4424,
      "why": "reverted: val_loss 0.442413 did not beat 0.434422; lower is better" },
    { "index": 5, "outcome": "failed", "metric": null,
      "why": "reverted: the command exited non-zero",
      "output_tail": "NameError: name 'this' is not defined\n" }
  ]
}
```

The `why` is the part that earns its place. `reverted` is a label; *did not
beat 0.434422, lower is better* is something to act on. And trial 5's
`output_tail` carries the traceback, so an agent can see what killed its last
attempt instead of guessing.

`propose.py` in this recipe reads that file in about ten lines:

```python
def read_brief():
    path = os.environ.get("LABLOOP_BRIEF")
    if not path or not os.path.exists(path):
        return {}
    return json.loads(pathlib.Path(path).read_text())
```

That is the whole integration surface. Swap the scripted edits for a call to
a coding agent and this recipe becomes a real research loop — which is
[the next recipe](../../02-proposers/).

## Limits of this recipe

- **The proposer is scripted, not intelligent.** Its six edits are a fixed
  list, so the ledger is identical on every run and CI can check that the
  output above is still true. It demonstrates what labloop does with
  proposals, not how good an agent's proposals are.
- **The experiment is deterministic and instant.** Real ones are neither.
  A noisy metric is a different recipe, and a harder problem.
- **Twenty holdout messages is not an evaluation.** It is small enough to
  read, which is the only reason it is this size. A win of 0.43 → 0.27 on
  twenty examples would not survive contact with a real test set.
