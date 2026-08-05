# Let Claude Code optimize real code against a real benchmark

**The question.** How do I point an actual coding agent at my code and only
keep the speedups that are real?

Not a toy. The code is a real identifier index over **4.7 MB of CPython
standard library source** — 170 files that are already on your machine. The
proposer is the real `claude` CLI, running headless, making its own decisions.
The metric is wall-clock seconds, which is noisy, which is the entire
difficulty.

**Everything below is a transcript.** These are the numbers this run produced
on 2026-08-05, not numbers chosen to make a point.

## The task

Three files:

- `index.py` — builds a map from identifier to the files containing it, and
  answers multi-term queries. **This is what the agent edits.** It works, and
  it is slow in the way code is slow when it was written once and never
  revisited: a list-membership check inside the hot loop.
- `bench.py` — times the build and the queries, then checks a SHA-256
  fingerprint of the index's *contents* against a golden value. **Protected.**
- `corpus.py` — locates the stdlib source. **Protected.**

The fingerprint is the part that makes this a real optimization task rather
than a benchmark game. An index that is fast because it is wrong fails the
check, exits non-zero, and is recorded as `failed` — not as a good score. And
because the fingerprint samples the index itself and not just the ten query
answers, an index that special-cases the queries is caught too.

## Step 1: find out what the metric is worth

```bash
labloop noise --run "python bench.py" --metric seconds --repeat 6
```

```
    run 0  0.3372
    run 1  0.3296
    run 2  0.3266
    run 3  0.3993
    run 4  0.348
    run 5  0.3375

seconds: 0.3266 to 0.3993 over 6 identical runs
spread: 0.0727   standard deviation: 0.0269781

An improvement smaller than 0.0727 is a difference this experiment has already
produced without any change to the code, so the loop would be selecting lucky
runs.

    labloop run --min-delta 0.0727 --confirm ...
```

**Twenty-two percent noise on an unchanged program.** Nothing was edited
between those six runs; the machine simply is not a stopwatch. Any speedup
under ~0.07s is indistinguishable from a busy neighbour on the same host.

This is why the recipe exists. If you skip this step and let an agent run
overnight against wall-clock time, you will wake up to a commit history of
lucky runs — and it will look exactly like progress.

## Step 2: baseline, with the correctness check protected

```bash
labloop baseline --run "python bench.py" --metric seconds \
  --protect bench.py --protect corpus.py
```

```
[+] trial   0        0.3342     0.4s  (baseline)
```

## Step 3: hand it to the agent

The `--min-delta` is taken from step 1's output. That is the whole point of
step 1 — the threshold is a measurement, not a preference.

```bash
labloop run --run "python bench.py" --metric seconds \
  --protect bench.py --protect corpus.py \
  --propose "python propose.py" \
  --min-delta 0.0727 --confirm \
  --budget 120 --propose-budget 300 --trials 5
```

`--propose-budget 300` is separate from `--budget 120` because the agent
thinks for far longer than the benchmark runs. Sharing one budget would mean
either killing the agent mid-thought or giving the benchmark five minutes it
cannot use.

## What the agent actually did

```
[+] trial   1        0.2245    32.3s  059657a
[-] trial   2         0.155    38.5s
[-] trial   3        0.1628    49.5s
[-] trial   4        0.1906   220.2s
[-] trial   5        0.2838    69.8s

best seconds: 0.2245 (trial 1)
```

**Trial 1 — kept.** A 33% cut, and a change a good engineer would make:

```diff
-        for token in tokenize(text):
-            if token not in index:
-                index[token] = []
-            # Keep the file list unique.
-            if name not in index[token]:
-                index[token].append(name)
+        # Dedupe tokens within the file first so repeats (e.g. "self") only
+        # cost one set insertion per file instead of one per occurrence.
+        for token in set(tokenize(text)):
+            bucket = index.get(token)
+            if bucket is None:
+                index[token] = bucket = set()
+            bucket.add(name)
```

It found the O(n) list-membership check in the hot loop, replaced the buckets
with sets, and deduplicated tokens per file so common identifiers cost one
insertion instead of thousands. It also wrote the comment explaining why.
That is real work, and it cleared 0.0727 comfortably: 0.3342 → 0.2245 is a
gain of 0.1097.

**Trials 2, 3 and 4 — reverted, and this is the recipe's real finding.**

Every one of them was *faster than the incumbent*, and every one was thrown
away:

| Trial | Time | Incumbent | Gain | Needed | Verdict |
| --- | --- | --- | --- | --- | --- |
| 2 | 0.1550 | 0.2245 | 0.0695 | 0.0727 | reverted, short by **0.0032s** |
| 3 | 0.1628 | 0.2245 | 0.0617 | 0.0727 | reverted, short by 0.0110s |
| 4 | 0.1906 | 0.2245 | 0.0339 | 0.0727 | reverted, short by 0.0388s |

Trial 2 was a genuine ~31% improvement on top of an already-optimized
version, and the loop threw it away because it missed the noise floor by
three milliseconds.

Trial 4 also took **220 seconds** of agent time — nearly seven times trial 1 —
to produce a worse result than either of the two attempts before it. An agent
that is told its last three changes "did not beat" the incumbent is an agent
being pushed toward bigger and wilder rewrites, which is the opposite of what
you want when the changes were in fact working. See the `why` problem below.

**This is the honest cost of `--min-delta`, and it is worth understanding
before you set one.** The threshold cannot distinguish "real but small" from
"lucky"; that is precisely why it works against flukes, and precisely why it
discards real gains of the same size. The loop is not being stupid here — on
the evidence available to it, a 0.0695s gain is inside the range this
experiment produces with no change at all.

**Trial 5 — reverted, and correctly.** At 0.2838 it was genuinely slower than
the incumbent. This is the one revert in the run that needed no threshold to
justify it, and it is worth noticing that it looks identical in the output to
the three that were actually improvements.

## What the run cost

```
kept=2  reverted=4
seconds: 0.2245 (trial 1)
```

The loop kept a real 33% speedup and it is in the history:

```
059657a labloop: seconds 0.2245 (was 0.3342)
4f4c652 identifier index over the stdlib, written once and never revisited
```

But the best measurement anyone saw was **trial 2's 0.155s** — a 54% cut from
baseline — and it is not in the repository. The threshold that protected the
run from flukes also cost it the two best results it found.

There is a subtlety in which number to use. `noise` suggests the **spread**
(0.0727), and the README notes that the spread widens with every extra run
while the **standard deviation** (0.0270) is the stable one. On this run that
choice decided three trials: with `--min-delta 0.0270`, trials 2, 3 and 4
would all have been kept, and the run would have ended at 0.155 instead of
0.2245.

Neither choice is wrong, and this is the trade the README describes — but
seeing it cost three real wins on one short run is more instructive than the
paragraph. **Spread is conservative and expensive; sd is permissive and lets
more flukes through.** On a metric this noisy, consider fixing the noise
instead: pin the process to a core, run the benchmark best-of-N inside
`bench.py`, and the whole dilemma goes away. `--min-delta` is what you use
when you cannot.

## What this recipe does not prove

- **It is `narrative` tier and CI does not run it.** It needs the `claude`
  CLI, network, and several minutes of agent time. The numbers are dated and
  the hardware named for exactly that reason.
- **An agent is not reproducible.** Run this yourself and the agent will make
  different choices. What reproduces is the *shape*: some proposals clear the
  bar, some do not, and the ones that do not are still recorded.
- **A shared container is a bad stopwatch.** 22% noise is worse than you would
  see on a quiet machine. That makes it a good teaching environment and a bad
  benchmarking one.
- **`--protect` detects, it does not prevent.** The agent could have rewritten
  `bench.py`; it would have been recorded as `harness_changed` rather than
  stopped.

## The wiring, which is the reusable part

Everything above is the experiment. This is the integration, and it is small
enough to paste:

```python
def read_brief():
    path = os.environ.get("LABLOOP_BRIEF")
    if not path or not os.path.exists(path):
        return {}
    return json.loads(pathlib.Path(path).read_text())

# ... build a prompt from brief["incumbent"], brief["history"], and each
# entry's "why" — the field the agent cannot reconstruct for itself ...

subprocess.run(["claude", "-p", prompt, "--permission-mode", "acceptEdits"],
               timeout=240, capture_output=True, text=True)
```

The `why` strings are what stop the agent repeating itself — and building this
recipe turned up a case where the `why` is actively misleading. After trial 2,
the prompt for trial 3 contained:

```
  - trial 2: reverted: seconds 0.155 did not beat 0.2245; lower is better
```

**That is false.** 0.155 did beat 0.2245 — by 31%. It was reverted because the
gain missed `--min-delta`, not because it was slower. An agent reading that
line learns the wrong lesson: it will abandon a direction that was working.

The cause is in `brief.py:_why_verdict`, which explains a revert by comparing
metric to incumbent and never mentions `min_delta`:

```python
return (
    f"reverted: {metric} {trial.metric:.6g} did not beat "
    f"{trial.incumbent:.6g}; {direction} is better"
)
```

The README says the `why` exists because it is "the part the proposer can't
work out for itself". Here it tells the proposer something untrue, and the
proposer has no way to detect that. A min-delta revert wants its own sentence
— *beat 0.2245 but only by 0.0695, and 0.0727 is required* — which is both
true and actionable, where the current message is neither.

The recipe records it because it is what the run actually produced. A fix is
small — `_why_verdict` has `experiment.min_delta` in hand already:

```python
if experiment.min_delta and _improved(trial.metric, trial.incumbent, goal):
    gain = abs(trial.incumbent - trial.metric)
    return (
        f"reverted: {metric} {trial.metric:.6g} beat {trial.incumbent:.6g} "
        f"by {gain:.6g}, but {experiment.min_delta:.6g} is required because "
        "the experiment is that noisy"
    )
```

That sentence is true, and it tells the agent to push harder in the same
direction rather than to abandon it.

Swap `claude` for `aider`, `codex`, or a script that calls an API, and nothing
else in this recipe changes. That is the contract the roadmap means when it
says `propose` stays any command.

## A gotcha that cost me a run

The first attempt at this recipe died immediately:

```
labloop: working tree has uncommitted changes, and the loop reverts by
discarding, so it would destroy them.
```

I had redirected the run log into the repository with `> run.log`. Keep run
logs, notes, and scratch files outside the tree — the loop reverts by
discarding, and the interlock is what stops it discarding your work.
