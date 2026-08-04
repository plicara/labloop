# Proposal: a labloop cookbook

**Status: proposal.** Nothing here is built yet. This document argues for a
`cookbook/` directory, says what goes in it, and — the part that matters —
says how it stays true.

## Why this repo needs one

The README teaches the loop. It is good at that and it is nearly full. What
it cannot do is answer the questions a user actually arrives with, which are
never about concepts:

- *I have a `train.py` that prints nothing. Where do I start?*
- *How do I make Claude Code the proposer?*
- *My metric moves ±0.25 between identical runs. Is labloop useless to me?*
- *I have two ideas and one baseline. How do I run both and compare them
  without fooling myself?*

Those are how-to questions — [Diátaxis](https://diataxis.fr/tutorials-how-to/)
calls this the user *at work*, as opposed to the user *at study* — and a
recipe is the canonical form for them. Answering them inside the README means
either doubling its length or thinning what it already does well.

There is also a gap the roadmap has already named and reserved. From
`ROADMAP.md`, under *Not doing, and why*:

> **A bundled agent.** `propose` stays any command. The brief/env contract is
> the integration surface; adapters belong in examples, not the core.

"Examples" is a directory that does not exist. Every user wiring up an agent
is rediscovering the same twenty lines of brief-reading glue in private. The
cookbook is where that decision lands.

## What the good ones do

Five that are worth stealing from, and what each one is actually good at:

| Cookbook | The idea worth taking | The failure worth avoiding |
| --- | --- | --- |
| [Rust Cookbook](https://github.com/rust-lang-nursery/rust-cookbook) | **Every snippet is executed in CI** (via [skeptic](https://github.com/budziq/rust-skeptic)), plus link and spell checks. A written rubric names what a *bad* recipe looks like, not only a good one. | Prose can drift from the included code if the include is dropped. |
| [Modal examples](https://github.com/modal-labs/modal-examples) | Each example is a runnable file with **YAML frontmatter that drives CI** — per-example opt-in/opt-out of testing. "Continuously tested for correctness" is a claim they can make. | Requires an account and cloud spend to run, so the reader can't verify locally. |
| [OpenAI Cookbook](https://github.com/openai/openai-cookbook) | A `registry.yaml` giving every recipe a **title, slug, description, date, authors, tags** — the index is data, and the site is generated from it. | Contributions are reviewed "on a best-effort basis" and nothing is executed. Recipes rot silently. |
| [Anthropic Claude Cookbooks](https://github.com/anthropics/claude-cookbooks) | ~15 categories keyed to *capabilities* (tool use, evals, agents, observability), so a reader navigates by what they're trying to do. | Notebook-shaped, which suits an API and not a tool that drives git. |
| [Hugging Face Cookbook](https://github.com/huggingface/cookbook) | Low-friction community authorship: add the notebook, add two lines to `_toctree.yml`, put your name under the first header. | The index is hand-maintained, so it drifts from the directory. |

The pattern across all five: **the index should be generated from per-recipe
metadata, and the recipes should be executed.** The ones that skip the second
half are the ones with rotted recipes.

One thing none of them do, which this repo should: publish the recipes that
say *don't*. `experiments/outcome_granularity/RESULTS.md` exists because a
negative result was worth writing down. The same instinct applies to loops
that shouldn't be run.

## Shape

`cookbook/` at the repo root, sibling to `experiments/` — not `docs/`. There
is no docs site and starting one at alpha is a second project.

One directory per recipe, self-contained, because labloop recipes are
multi-file by nature: an experiment script, a proposer, a protect set, and
prose tying them together. A reader copies the directory and it runs.

```
cookbook/
  README.md                      # generated index — do not hand-edit
  CONTRIBUTING.md                # the rubric
  build_index.py                 # regenerates README.md from recipe.json files
  01-first-loop/
    metric-from-a-script-that-prints-nothing/
      recipe.json                # metadata (below)
      README.md                  # the recipe
      train.py                   # the files it needs
      run.sh                     # exactly the commands the README shows
```

`recipe.json`, not YAML or TOML frontmatter: the package is stdlib-only and
intends to stay that way, `tomllib` is 3.11+ while we support 3.10, and JSON
Lines is already the house data format. No parser to write, nothing to add to
`dev`.

```json
{
  "title": "Read a metric from a script that prints nothing",
  "question": "My train.py writes a JSON file and prints nothing. How do I run it under labloop?",
  "tier": "verified",
  "section": "01-first-loop",
  "runtime_seconds": 3,
  "needs": [],
  "expect": { "kept": 1, "reverted": 1 },
  "labloop": "0.1.0"
}
```

## The part that makes it work: three tiers of verification

Every cookbook that rots, rots because nothing runs it. But labloop's most
valuable recipes involve a real coding agent and a real training run, and
neither belongs in CI — one costs money and needs network, the other needs a
GPU and forty minutes. Pretending otherwise gets you either a dishonest
badge or a cookbook that omits its best material.

So the tier is declared per recipe, in the metadata, and shown in the index:

- **`verified`** — runs end-to-end in CI in a temp git repo, under a few
  seconds, no network. The proposer is a shell command. This is most recipes,
  and the bar is: if it can be `verified`, it must be.

- **`structural`** — runs in CI with the real agent replaced by a stub that
  honors the same contract: reads `$LABLOOP_BRIEF`, edits a file, exits. CI
  proves the wiring — flags, quoting, protect set, file layout, that the
  brief is where the recipe says it is. It proves nothing about whether the
  agent is any good. The recipe says so, in those words. This is how the
  agent-adapter recipes get tested without an API key.

- **`narrative`** — a real run on real hardware, reported and not re-run.
  Must carry the date, the labloop version, the model and hardware, and a
  visible line saying it is not executed in CI. This is the same standard
  `experiments/` already holds itself to.

CI enforces the tiers rather than trusting them: `verified` and `structural`
recipes are executed, and the run's ledger is checked against the `expect`
block in `recipe.json`. That assertion is pleasingly native — **the ledger is
the test oracle.** A recipe claiming it demonstrates a `harness_changed`
trial has to actually produce one.

`narrative` recipes are checked for their required metadata and their banner,
so the one tier that cannot be executed cannot quietly omit the fact.

## Keeping prose and commands from drifting

Rust Cookbook's answer is mdBook `{{#include}}`; ours can be simpler. The
recipe's README shows commands, and `run.sh` contains them. The test executes
`run.sh` and separately asserts that every ```` ```bash ```` block in the
README appears in `run.sh`. A command shown to the reader that is not the
command CI ran is a build failure.

The index is generated the same way `CHANGELOG` discipline works here: CI
regenerates `cookbook/README.md` from the `recipe.json` files and fails if it
differs from what is committed. No hand-maintained table of contents to
forget.

## What goes in it

Six sections. Ordered the way the roadmap is: trust the number, don't lose
the work, run more than one thread, be easy to start — plus the two the
README can't hold.

**1. The first loop.** Turning something you already have into an experiment.
Reading a metric out of a script that prints nothing or prints the wrong
shape. Choosing what `--run` covers and what it must not. Budgets that don't
lie — why `--propose-budget` exists and what the process-group kill saves you
from. Running in a repo that isn't fresh: dirty trees, ignored artifacts,
warm caches that survive a revert.

**2. Wiring a proposer.** The reserved gap, one recipe per adapter. Claude
Code headless as the proposer. aider. Codex CLI. A plain API script. A
twenty-line reference adapter that turns the brief JSON into a prompt —
including the `why` field, which is the part the agent cannot work out for
itself. And a deterministic stub proposer, so you can prove your harness
works before spending a single token on it. Every one of these is
`structural`.

**3. Trusting the number.** `labloop noise` on a real experiment and how to
read spread against standard deviation. Making a stochastic experiment
deterministic — seed, split, averaging — and what to do with `--min-delta`
and `--confirm` when you can't. Choosing a `--protect` set for a real
evaluator, including the trap the README names: a cache written inside a
protected path. And a recipe that stages the classic cheats — overwritten
eval, memorized holdout, a metric printed without being computed — so a
reader can see what each one looks like in the ledger before it happens to
them for real.

**4. More than one thread.** Forking two directions from one baseline in
worktrees over a shared ledger. Comparing them honestly, and what
`--compare` refuses when the harness digests differ. Overnight runs on a
remote box: `--give-up-after`, what survives a reboot, and resuming under the
recorded spec.

**5. The ledger as an artifact.** A stdlib-only script that turns `log
--json` into a report or a plot. Extracting "what was tried and why it
failed" for a write-up. Using `labloop-history.jsonl` as the research record
that travels with the repository.

**6. Loops not worth running.** The anti-recipes, and the section I'd argue
hardest for. A metric that takes six hours to measure. A multi-objective
goal, where keep-or-revert has no defined answer. Hyperparameter sweeps,
which want a sweeper and not an agent. A metric so noisy that no setting
makes it safe. Each one names the tool that is actually right for it. Rust
Cookbook publishes what a bad recipe looks like; the labloop version is
publishing what a bad *loop* looks like, and it fits how this project already
talks about its own limits.

## Rules for a recipe

To go in `cookbook/CONTRIBUTING.md`, in the shape the root one already uses:

- **One question, asked by a person.** The title is the goal, not the
  feature. "Run two ideas from one baseline", not "Using `--direction`."
- **The README explains; the cookbook does.** If a concept is explained in
  the README, link to it. Do not re-explain it. A cookbook that restates the
  README is a second README that will disagree with the first one by winter.
- **Prose says why, code says what.** Inline comments are not explanation —
  the same rule Rust Cookbook enforces.
- **Say what it doesn't do.** Every recipe ends with its limits. A
  `structural` recipe says outright that CI checked the wiring and not the
  agent.
- **Measured or dated.** A number in a recipe is either produced by the
  `run.sh` CI executes, or it carries the date and hardware it came from.
  House style is already numbers over adjectives.
- **Minimal.** No extra files, no framing, nothing the question didn't ask
  for.

## Build order

Not thirty recipes. The harness first, then enough recipes to prove all three
tiers exist, then growth.

- **Wave 0 — the harness.** `cookbook/`, `build_index.py`,
  `tests/test_cookbook.py`, the CI job, the rubric. Three recipes, one per
  tier, chosen to exercise the machinery rather than to be the most useful:
  a `verified` first-loop recipe, a `structural` stub-proposer recipe, a
  `narrative` placeholder. Deliverable: `pytest -q` fails if a recipe lies.
- **Wave 1 — proposers.** The adapter recipes. This is the roadmap's reserved
  gap and the most-asked question; it should ship first among the content.
- **Wave 2 — trusting the number.** Noise, protect sets, staged cheats. The
  differentiator that most needs a worked example rather than a paragraph.
- **Wave 3 — directions, ledger reporting, anti-recipes.**

Cost of wave 0 is roughly a day. CI cost is a few seconds per run: recipes
are small commands against a stub experiment, and anything slower than that
belongs in `narrative` by definition.

## Deliberately not doing

- **Notebooks.** Wrong medium for a tool whose unit of work is a git commit
  and whose output is a ledger. The two AI cookbooks use them because they
  document an API.
- **A documentation site.** Premature. The index is markdown in the repo; if
  the cookbook earns a site later, the metadata is already there to generate
  one from — that is exactly what `registry.yaml` buys OpenAI.
- **Open community contribution before wave 0.** Every rotted cookbook found
  in this search rotted because recipes arrived faster than verification. The
  harness is what makes contributions safe to accept.
- **Shipping recipes in the wheel.** `cookbook/` belongs in the sdist
  alongside `experiments/`, since the sdist is the archival artifact, but
  nothing in it is importable.

## The one risk

Cookbook rot, and it is not hypothetical: it is the failure mode of four of
the five examples above. The mitigation is the whole reason wave 0 is
verification machinery and not content. If the harness ever gets skipped "just
for this recipe," the cookbook has started dying — so `tier` is required, has
no default, and CI rejects a recipe without one.
