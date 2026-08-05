# Ten candidate recipes

Pick a couple. Each is a real task with a real metric, in the shape of
[`agent-optimizes-real-code`](02-proposers/agent-optimizes-real-code/): real
inputs, a real agent, and the run's actual numbers reported including the
parts that went badly.

Every entry names the **cheat it invites**, because that is what decides the
protect set, and it is the thing a reader most needs to see before it happens
to them.

Cost is my estimate of build time including the real run.

---

## 1. Speed up a test suite without breaking it

**Task.** A real repo's `pytest` suite, slow for ordinary reasons — no
parallelism, module-scope fixtures rebuilt per test, a sleep in a retry test.
The agent makes it faster.

**Metric.** Wall-clock seconds for the full suite. **Protected.** The tests
themselves, and a collected-count assertion.

**The cheat it invites.** Deleting or skipping slow tests. This is the single
most natural way to make a suite fast, which is what makes it the recipe's
centrepiece: the protect set has to cover *how many tests ran*, not just the
files.

**Teaches.** That the harness sometimes has to assert a property of the run
(count, coverage floor) rather than just hash files. Universal — everyone has
a slow test suite.

**Tier.** `narrative`. **Cost.** ~half a day.

**My take:** the strongest candidate on relevance. Every reader has this
problem this week.

---

## 2. Cut memory instead of time

**Task.** A script that loads and transforms a large CSV wastefully. The agent
reduces peak memory.

**Metric.** `tracemalloc` peak bytes — **exactly deterministic**.
**Protected.** The output correctness check.

**Teaches.** The deliberate contrast with the built recipe. Same loop, same
agent, but `labloop noise` prints *spread: none*, so `--min-delta` and
`--confirm` are unnecessary and every improvement is believed immediately.
The clearest possible demonstration that noise is a property of your
experiment, not a fact of life — and worth engineering away.

**Tier.** `verified` (the agent step is `structural`). **Cost.** ~half a day.

**My take:** cheap, and it makes the noise lesson land by contrast. Good
second pick alongside a noisy one.

---

## 3. Optimize a prompt against a held-out eval set

**Task.** A classification or extraction prompt in `prompt.txt`, scored over
~100 held-out cases. The agent rewrites the prompt.

**Metric.** Accuracy on the holdout. **Protected.** The eval set, the grader,
and the split.

**The cheat it invites.** The live one. An agent that can read the eval set can
write the answers into the prompt — and a prompt that names the expected
outputs scores perfectly while learning nothing. This is not a hypothetical
here the way it is in a classifier recipe.

**Teaches.** That "the thing being optimized" need not be code. Also the
strongest argument for `--protect` in the whole cookbook.

**Tier.** `narrative` (needs API access). **Cost.** ~a day, plus eval-set
construction.

**My take:** the most 2026-relevant recipe on the list, and the one where
labloop's safety story is most obviously load-bearing.

---

## 4. Cut token cost at fixed quality

**Task.** A working LLM pipeline that is more expensive than it needs to be.
The agent reduces cost — shorter prompts, cheaper model for sub-steps, fewer
round-trips.

**Metric.** Dollars (or tokens) per task. **Protected.** The eval set and a
**quality floor enforced as a hard failure**: score below threshold, exit
non-zero, trial recorded as `failed`.

**Teaches.** The worked answer to the most common objection — *labloop only
optimises one number*. One metric, one floor, and the two-objective problem
dissolves. That pattern generalises far beyond LLM work.

**Tier.** `narrative`. **Cost.** ~a day.

**My take:** high value because it answers an objection rather than
demonstrating a feature. Pairs naturally with #3.

---

## 5. Two directions from one baseline

**Task.** Fork the built stdlib-index benchmark into two directions —
"better data structures" and "less work per file" — run both, compare.

**Metric.** Seconds, same as the parent. **Protected.** Same.

**Teaches.** The roadmap's headline differentiator, worked: worktrees, a
shared ledger, per-direction incumbents seeded from the fork point,
`log --compare`, and its refusal when harness digests differ. Reuses a task
the reader already understands, so all the new material is the branching.

**Tier.** `narrative`. **Cost.** ~half a day (the task already exists).

**My take:** the cheapest way to document stage 3 of the roadmap, and it is
currently undocumented outside the README.

---

## 6. Improve retrieval in a RAG pipeline

**Task.** A small corpus, a real query set with relevance judgments. The agent
tunes chunking, embedding choice, and reranking.

**Metric.** recall@10. **Protected.** Queries, judgments, and the scorer.

**Teaches.** A metric that is a fraction over a fixed set — coarse enough that
ties are common, which makes it a natural home for the "choose a continuous
metric" lesson (recall@k with graded gain rather than a hit count).

**Tier.** `narrative`. **Cost.** ~a day and a half; the query set is the work.

**My take:** valuable but expensive, and overlaps #3 on the "protect the eval"
lesson. Pick it only if RAG is a target audience.

---

## 7. Shrink a container image

**Task.** A real `Dockerfile` at ~1 GB. The agent applies the ordinary moves —
smaller base, multi-stage, layer ordering, cache cleanup.

**Metric.** Image bytes. **Protected.** A smoke test that the image still
runs and the app answers.

**Teaches.** That labloop is not a Python tool. Nothing in the loop knows what
language this is — `--run` is `docker build && docker run`, and the metric is
a number printed by a shell command.

**Tier.** `narrative` (needs a Docker daemon). **Cost.** ~half a day.

**My take:** the best "this is not an ML tool" demonstration. Worth one slot
if the audience is broader than researchers.

---

## 8. Improve a compression ratio

**Task.** A domain-specific encoder for a real corpus (say, the ledger's own
JSONL). The agent improves the ratio.

**Metric.** Compressed bytes — **deterministic**. **Protected.** A round-trip
fidelity check: decompress must equal the original, byte for byte.

**Teaches.** The cleanest protect set in the cookbook — correctness is a
property, not a file — plus a genuinely interesting search space where an
agent can make real algorithmic progress over many trials.

**Tier.** `verified` end to end. **Cost.** ~half a day.

**My take:** the best candidate for a long CI-verified run, and a good
showcase for a 50-trial overnight loop where progress is real and visible.

---

## 9. Reduce p99 latency of a small service

**Task.** A local HTTP service with an N+1 query and a synchronous call in the
handler. A load generator drives it; the agent optimizes.

**Metric.** p99 latency. **Protected.** Response-correctness assertions in the
load generator.

**Teaches.** The noisiest metric in the cookbook — worse than wall-clock,
because it is a tail statistic. The honest recipe here may well conclude
*measure more requests before you loop at all*, which is a result worth
publishing.

**Tier.** `narrative`. **Cost.** ~a day.

**My take:** high realism, high risk of an inconclusive run. That could be a
feature — an anti-recipe with data — but say so up front.

---

## 10. Reproduce the autoresearch loop

**Task.** The original use case: a nanochat-style training run on one GPU,
minimising `val_bpb`, driven by an agent.

**Metric.** `val_bpb`. **Protected.** The eval split and the tokenizer.

**Teaches.** The honest comparison against the project labloop generalises.
Same loop, same task, plus the things labloop adds — a queryable ledger,
resumability, directions.

**Tier.** `narrative`, and unusually so: hours of GPU time.

**My take:** the most credible recipe for the README's "prior art" section and
the least likely to get written, because none of this runs here. Worth
scheduling only if someone has the hardware.

---

## If you want a recommendation

**#1 (test suite)** and **#3 (prompt eval)**. Between them they cover the two
audiences — engineers who have never trained a model, and people doing LLM
work in 2026 — and both centre on a cheat that is real rather than staged. If
you want a third that is cheap and CI-verifiable, **#8 (compression)**.

**#2** is the cheapest thing on the list and makes an existing lesson land
harder, so it is a good filler regardless of what else is picked.
