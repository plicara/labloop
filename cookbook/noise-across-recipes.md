# Four experiments, four noise levels, one machine

Every recipe in this cookbook starts with `labloop noise`, and between them
they make an argument no single recipe can: **you cannot guess how noisy your
metric is.**

All four ran on the same container, on the same afternoon.

| Recipe | Metric | Spread | Relative | What that implied |
| --- | --- | --- | --- | --- |
| [stdlib index](02-proposers/agent-optimizes-real-code/) | wall-clock seconds | 0.0727 on 0.33 | **22%** | `--min-delta` *and* `--confirm`, and it still discarded three real wins |
| [prompt eval](03-real-tasks/optimize-a-prompt/) | accuracy over 30 cases | 0.0889 on 0.29 | **8.9%** | a threshold was needed; I ran without one and got away with it |
| [test suite](03-real-tasks/speed-up-a-test-suite/) | wall-clock seconds | 0.0349 on 10.54 | **0.3%** | no `--confirm` — it would have doubled the cost of every candidate for nothing |
| [retrieval](03-real-tasks/improve-rag-retrieval/) | nDCG@10 | none | **0%** | believe every improvement immediately |

## The two that should be the same, and aren't

The stdlib-index recipe and the test-suite recipe both measure **wall-clock
seconds of a Python program on the same machine**. They differ by a factor of
seventy.

Wall-clock time is not inherently noisy. It is noisy when it is **CPU-bound on
a contended machine**, because you are measuring your share of the processor
as much as your program. The stdlib index is 0.33 seconds of solid computation
and its measurement moves with whatever else the box is doing. The test suite
is 10.5 seconds dominated by `time.sleep`, and a sleep is as stable as the
clock — so a metric seventy times noisier lives in the *smaller, simpler*
program.

Nobody would have predicted that ordering in advance. I did not.

## What each level costs you

Noise is not just a risk of false keeps. It is a tax on real ones:

- **22%** — the stdlib run set `--min-delta` to the spread and then reverted
  three genuine speedups of 31%, 27% and 15%, one of them short by three
  milliseconds. The best measurement anyone saw is not in that repository.
- **8.9%** — large enough that trials 2 and 3 of the prompt run cannot be
  distinguished from the incumbent. The run converged after trial 1 and the
  remaining trials could not have told anyone anything.
- **0.3%** — `--confirm` would have doubled the cost of every candidate win to
  defend against a problem that experiment does not have.
- **0%** — no threshold, no confirmation, no doubt. Every improvement is the
  change.

## The trap: a clean measurement can mean a broken harness

The prompt recipe first measured `spread: none` — three identical runs from a
system whose central component is a language model.

That was not a stable metric. [The parser was
broken](03-real-tasks/optimize-a-prompt/), extracting nothing from every reply,
so every run failed in exactly the same way. **A metric that fails identically
is indistinguishable from a metric that is stable.** Fixing the parser revealed
the 8.9% that had been there all along.

So `spread: none` is good news only when you can say *why* it is zero. The
retrieval recipe can: same corpus, same queries, same arithmetic, no clock and
no model anywhere in the measurement. The prompt recipe could not, and the
reason was a bug.

## What to do with this

1. **Run `labloop noise` on your experiment.** Not on one like it. The two
   timing recipes here differ by 70×.
2. **If the spread surprises you, find out why before you tune anything.**
   Both surprises in this cookbook — 22% on a tiny program, 0% on a model —
   were telling you something about the harness.
3. **Removing the variance beats thresholding it.** Pin the seed, hold the
   split, run the benchmark best-of-N, use more eval cases. Every threshold is
   a tax you pay on every real improvement for the rest of the run.
4. **When you must threshold, choose deliberately.** `noise` prints a
   conservative and a permissive option with what each costs. The conservative
   one is not the safe one; it is the one that throws away real work.
