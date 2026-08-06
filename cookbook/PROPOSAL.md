# Proposal: a labloop cookbook

**Status: five recipes built, catalog below is what is not.**
Start with [`02-proposers/agent-optimizes-real-code/`](02-proposers/agent-optimizes-real-code/)
— a real agent on real code — then the three in
[`03-real-tasks/`](03-real-tasks/). [`cookbook/README.md`](README.md) is the
generated index. The rest of this document is the argument and the backlog.

## What a recipe is here

A worked example: a real scenario, the real commands, the real output, and
the judgement calls in between. Not a feature tour.

The one that exists tunes a spam classifier over six trials. Two survive.
The proposer tries something plausible and is wrong (stripping punctuation
makes the model worse), crashes once, and then — after crashing — rewrites
the file that grades it and gets caught. Every number and every line of
terminal output in that recipe came from running it, and CI reruns it.

That is the shape: **a user watches the loop do its job on something real,
including the parts where the loop says no.**

## Why the repo needs a shelf of them

The README teaches the loop and is nearly full. What it cannot do is answer
the questions users actually arrive with, which are never about concepts:

- *I have a `train.py` that prints nothing. Where do I start?*
- *How do I make Claude Code the proposer?*
- *My metric moves ±0.25 between identical runs. Is labloop useless to me?*
- *I have two ideas and one baseline. How do I run both without fooling myself?*

Those are how-to questions — [Diátaxis](https://diataxis.fr/tutorials-how-to/)
calls this the user *at work* rather than *at study* — and a worked example is
the canonical form. Answering them in the README means doubling its length or
thinning what it already does well.

One gap is already reserved. From `ROADMAP.md`, under *Not doing, and why*:

> **A bundled agent.** `propose` stays any command. The brief/env contract is
> the integration surface; adapters belong in examples, not the core.

"Examples" is a directory that does not exist. Everyone wiring up an agent is
rediscovering the same ten lines of brief-reading glue in private. The
cookbook is where that decision lands.

## The catalog

Organised by **the job the reader is doing**, not by which flag it exercises.
Each entry is a real task on real inputs, driven by a real agent, and each
names the metric it optimises — because "what is the number" is the first
thing a reader has to decide and the thing they get wrong.

### 1. Making code faster

The most common real use of a keep-or-revert loop, and the one where the
metric is treacherous: wall-clock time is noisy, so most "speedups" are dice.

- **Let Claude Code optimize real code against a real benchmark** — *built.*
  An identifier index over 4.7 MB of CPython stdlib source. Metric: seconds.
  Real agent, real 22% measurement noise, `--min-delta` and `--confirm`
  chosen from the measurement rather than from taste.
- **Speed up a test suite without shrinking it** — *built*
  ([03-real-tasks](03-real-tasks/speed-up-a-test-suite/)). 10.54s to 0.48s.
  The protect set is a property of the run, not a file hash.
- **Cut memory, not time** — same loop, metric from `tracemalloc` peak. Shows
  that "the metric" need not be time or loss, and what changes when the metric
  is perfectly deterministic (spoiler: you can drop `--confirm`).

Also built, and honestly labelled:
[`01-first-loop/tune-a-classifier/`](01-first-loop/tune-a-classifier/) is a
toy — twenty spam messages and a scripted proposer replaying fixed edits. It
is not a use case and is not presented as one. Its job is to be the
deterministic fixture the CI harness is tested against, since a `narrative`
recipe like the one above can never play that role. Every cookbook needs one
of these; it should not be the front door.

### 2. Improving a model

- **Beat a baseline on a real tabular dataset** — a real CSV, a real
  train/test split, metric: held-out AUC. The agent does feature engineering.
  The holdout and the split are protected, which is the whole ballgame.
- **Tune a training script you did not write** — someone else's `train.py`,
  seeded and un-seeded, showing what `noise` says about each and why the
  un-seeded one needs fixing before the loop is worth running.
- **Reproduce the autoresearch loop** — the original use case (nanochat-style
  `val_bpb` on one GPU) run under labloop, as the honest comparison to the
  project this generalises. `narrative` tier; nobody's CI has a GPU.

### 3. Improving an LLM pipeline

Real 2026 work, and a place where the metric is an eval score rather than a
number a program computes about itself.

- **Optimize a prompt against a real eval set** — *built*
  ([03-real-tasks](03-real-tasks/optimize-a-prompt/)). 0.29 to 0.89, and the
  recipe leads with the harness bug that was scoring nothing.
- **Improve retrieval quality on a real corpus** — *built*
  ([03-real-tasks](03-real-tasks/improve-rag-retrieval/)). nDCG 0.25 to 0.54,
  including a diagnosis of mine that the data disproved.
- **Cut token cost at fixed quality** — two numbers, one loop: cost is the
  metric, and a quality floor lives in the harness as a hard failure. The
  worked answer to "labloop only optimises one thing".

### 4. Running more than one idea

- **Two ideas, one baseline** — fork two directions into worktrees over a
  shared ledger, run both, read `log --compare`. The differentiator, worked
  on the section-1 benchmark so the reader already knows the task.
- **Comparing directions that aren't comparable** — drift one direction's
  harness on purpose, watch `--compare` refuse, fix it.
- **An overnight run you'll close the laptop on** — tmux, budgets,
  `--give-up-after`, and what the morning looks like.
- **Your run died at trial 34** — kill it mid-trial, `resume`, verify the
  ledger is contiguous. Then change `--metric` and watch the refusal name the
  field.

### 5. Reading the result

- **Turn a ledger into a report** — stdlib-only script over `log --json`:
  convergence plot, table of what was tried and rejected.
- **Write up what the agent tried and why it failed** — mining reverted trials
  for the negative results, in the shape `experiments/` already publishes.
- **The research record that ships with the repo** — `labloop-history.jsonl`
  read in review, months later, by someone who wasn't there.

### 6. Problems you will hit in the first hour

Short troubleshooting entries, not full worked examples. These exist because
every one of them cost someone an afternoon.

- **Your script prints nothing, or prints the wrong thing** — bridging a
  `metrics.json` writer; why last-occurrence means per-epoch printing is fine.
- **`--run` covers the wrong thing** — putting eval outside `--run` scores a
  stale number.
- **The loop refuses to start** — the dirty-tree interlock, including the way
  I tripped it building this cookbook: redirecting a log into the repo.
- **Your proposer thinks for longer than your experiment runs** — why
  `--propose-budget` is separate, and what the process-group kill saves you
  from.

### 7. Loops not worth running

Anti-recipes. Each names the tool that is actually right instead.

- **A metric that takes six hours** — the arithmetic on how many trials an
  overnight budget buys, and when to build a proxy metric first.
- **Two things you care about** — when the section-3 trick (one metric, one
  floor) does *not* rescue you, and what to use instead.
- **A hyperparameter sweep** — this wants a sweeper, not an agent.
- **A metric too noisy for any setting to save** — the honest exit.

## Skills

*Built: [`cookbook/skills/`](skills/). Candidate recipes to choose from:
[`CANDIDATES.md`](CANDIDATES.md).*

Three agent skills, one for each moment where a labloop user has an agent in
the room:

| Skill | Who loads it | The moment |
| --- | --- | --- |
| `labloop-setup` | the user's assistant | wiring an experiment before a trial is spent |
| `labloop-proposer` | **the agent inside `--propose`** | one attempt, judged and probably reverted |
| `labloop-triage` | the user's assistant | a run that produced nothing, or too much |

`labloop-proposer` is the one that matters. The roadmap declines to bundle an
agent — `propose` stays any command — which leaves every user re-deriving the
same prompt knowledge privately. A skill fills that gap without closing the
door: it is text, it ships in the cookbook rather than the package, it adds no
dependency, and swapping `claude` for `aider` costs nothing.

Its content is evidence, not advice. Each rule traces to something a recorded
run did:

- **What a trial can resolve** — the loop scores a trial, not an edit, so it
  cannot attribute a result to one change among several. Mechanism, not
  advice: an earlier draft gave the advice too, and three later runs
  contradicted it.
- **The `reverted` trap** — when `--min-delta` caused the revert, the brief
  said *"did not beat 0.2245"* about a change that beat it by 31%. Found by
  writing the recipe, and now fixed in `brief.py` with tests; the skill
  teaches the current message and the older-version workaround.
- **The nine outcomes as a routing table** — measured, not asserted
  (`experiments/outcome_granularity/`, p < 0.01 against no labels).

Skills are instructions, not enforcement. One cannot stop an agent editing the
harness; `--protect` detects that and nothing prevents it. What a skill does is
make the good path clear and name the bad one.

## Keeping them true

This is the supporting machinery, and the reason it matters is empirical:
four of the five cookbooks surveyed below do not execute their recipes, and
their recipes have drifted.

**Layout.** `cookbook/` at the root, beside `experiments/` — not `docs/`,
because there is no docs site and starting one at alpha is a second project.
One directory per recipe, self-contained, because labloop recipes are
multi-file by nature: an experiment, a proposer, a protect set, and prose.

```
cookbook/01-first-loop/tune-a-classifier/
  recipe.json      # metadata and expected outcomes
  README.md        # the recipe
  run.sh           # exactly the commands the README shows
  files/           # train.py, evaluate.py, data.py, propose.py
```

`recipe.json`, not YAML frontmatter: the package is stdlib-only and means to
stay that way, `tomllib` is 3.11+ while we support 3.10, and JSON Lines is
already the house format.

**The ledger is the test oracle.** `recipe.json` declares what the run should
produce, and CI checks the ledger against it:

```json
"expect": { "kept": 3, "reverted": 2, "failed": 1,
            "harness_changed": 1, "best_metric": 0.2651227330068643 }
```

This already works. Running the built recipe's `run.sh` in a clean directory
and diffing against its `expect` block matches exactly. A recipe claiming to
demonstrate a caught cheat has to actually produce one.

**Three tiers, because honesty beats coverage.** The best recipes need a real
agent or a real GPU and cannot run in CI. Rather than a dishonest badge or a
cookbook missing its best material, every recipe declares one:

- `verified` — runs end-to-end in CI in seconds, no network. Most recipes,
  and the bar is: if it can be, it must be.
- `structural` — the real agent is swapped for a stub honouring the same
  contract. CI proves the wiring — flags, quoting, protect set, brief path.
  It proves nothing about whether the agent is any good, and the recipe says
  so in those words. This is how section 2 gets tested without an API key.
- `narrative` — a real run on real hardware, reported not re-run. Carries the
  date, version, model and hardware, and a visible not-run-in-CI line. The
  standard `experiments/` already holds itself to.

`tier` is required and has no default, so a recipe cannot quietly skip it.

**No drift between prose and commands.** The README shows commands; `run.sh`
contains them; CI executes `run.sh` and asserts every ```` ```bash ```` block
in the README appears in it. A command shown to a reader that is not the
command CI ran is a build failure.

**A generated index.** CI regenerates `cookbook/README.md` from the
`recipe.json` files and fails if it differs from what is committed — no
hand-maintained table of contents to forget, which is how the Hugging Face
cookbook's TOC drifts from its directory.

## What the good ones do

| Cookbook | Worth taking | Worth avoiding |
| --- | --- | --- |
| [Rust Cookbook](https://github.com/rust-lang-nursery/rust-cookbook) | Every snippet executed in CI via [skeptic](https://github.com/budziq/rust-skeptic). A written rubric naming what a *bad* recipe looks like. | Prose drifts from code if an include is dropped. |
| [Modal examples](https://github.com/modal-labs/modal-examples) | Runnable files with frontmatter driving CI. "Continuously tested for correctness" is earned. | Needs an account and cloud spend, so readers can't verify locally. |
| [OpenAI Cookbook](https://github.com/openai/openai-cookbook) | `registry.yaml` — the index is data, the site generated from it. | Reviewed "best-effort", nothing executed, recipes rot. |
| [Claude Cookbooks](https://github.com/anthropics/claude-cookbooks) | ~15 categories keyed to what you're trying to do. | Notebook-shaped, which suits an API, not a tool whose unit of work is a commit. |
| [HF Cookbook](https://github.com/huggingface/cookbook) | Low-friction contribution; authors credited inline. | Hand-maintained TOC drifts from the directory. |

## Rules for a recipe

For `cookbook/CONTRIBUTING.md`, in the shape the root one already uses:

- **One question, asked by a person.** The title is the goal, not the feature:
  "Two ideas, one baseline", never "Using `--direction`".
- **Show the run.** Real commands, real output, pasted from an execution. A
  recipe with no terminal output in it is an essay.
- **Show the loop saying no.** The reverts are the product. A recipe where
  everything works teaches nothing about a tool whose job is rejection.
- **The README explains; the cookbook does.** Link to the concept, don't
  restate it. A cookbook that restates the README is a second README that will
  disagree with the first by winter.
- **Prose says why, code says what.** Inline comments are not explanation.
- **End with limits.** Every recipe says what it did not prove. The built one
  says outright that its proposer is scripted and its holdout is too small.
- **Measured or dated.** A number is either produced by the `run.sh` CI
  executes, or it carries the date and hardware it came from.

## Build order

- **Wave 0 — the harness.** `build_index.py`, `tests/test_cookbook.py`, the CI
  job, `CONTRIBUTING.md`. One recipe exists to test it against; add a
  `structural` and a `narrative` one so all three paths are exercised.
  Deliverable: `pytest -q` fails if a recipe lies. ~1 day.
- **Wave 1 — proposers (section 2).** The reserved gap, the most-asked
  question, and the reason people bounce off the tool.
- **Wave 2 — trusting the number (section 3).**
- **Wave 3 — directions, ledger reporting, anti-recipes.**

CI cost stays under a few seconds per recipe; anything slower is `narrative`
by definition.

## Deliberately not doing

- **Notebooks.** Wrong medium for a tool whose unit of work is a git commit.
- **A documentation site.** Premature. The metadata is there to generate one
  from if the cookbook earns it.
- **Open contribution before wave 0.** Every rotted cookbook above rotted
  because recipes arrived faster than verification.
- **Shipping recipes in the wheel.** `cookbook/` belongs in the sdist beside
  `experiments/`, since that is the archival artifact. Nothing in it is
  importable.
