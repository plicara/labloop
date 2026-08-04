# Proposal: a labloop cookbook

**Status: proposal, with one recipe built.**
[`01-first-loop/tune-a-classifier/`](01-first-loop/tune-a-classifier/) is
finished and runs — read that first. It is what every entry in the catalog
below should look like. The rest of this document is the catalog and the
argument.

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

Roughly twenty recipes across six sections. Each is a scenario, not a topic.

### 1. The first loop

- **Tune a classifier and watch the loop throw most of it away** — *built.*
  The end-to-end tour: noise check, baseline, six trials, two commits.
- **Your script prints nothing, or prints the wrong thing** — a `train.py`
  that writes `metrics.json` and logs to stderr. Three ways to bridge it
  (a one-line shim, a `--run` that pipes, editing the script), why the
  last-occurrence rule means printing every epoch is fine, and what
  `no_metric` looks like when you get it wrong.
- **Deciding what `--run` covers** — the same experiment wired three ways:
  training only, training plus eval, and a Makefile target. Shows the trap of
  putting the eval outside `--run`, where the loop scores a stale number.
- **Budgets that don't lie** — a proposer that thinks for 90s wrapped around a
  40s experiment. Shows why `--propose-budget` exists, and a training script
  that spawns workers, so the process-group kill is visible in `ps` rather
  than asserted.
- **Running in a repo that isn't fresh** — an existing project with build
  artifacts, a virtualenv, and a warm dataset cache. What to `.gitignore` so
  it survives reverts, and what the dirty-tree refusal is protecting.

### 2. Wiring a proposer

The reserved gap. One recipe per adapter, each ending with the same loop
running for real.

- **Claude Code as the proposer** — headless invocation, the prompt built from
  `$LABLOOP_BRIEF`, keeping the agent scoped to the file it should edit, and
  what its `harness_changed` trials look like when it wanders.
- **aider as the proposer** · **Codex CLI as the proposer** · **A plain API
  script as the proposer** — the same experiment, three wirings, so the
  contract is visibly tool-agnostic.
- **The ten lines that read a brief** — the reference adapter: brief JSON to
  prompt, including `why` and `output_tail`, which are the fields an agent
  cannot reconstruct for itself. Copy-paste sized on purpose.
- **Prove your harness before you spend tokens** — a deterministic stub
  proposer that makes a known-good and a known-bad edit. Run this first; if
  the ledger doesn't show one kept and one reverted, the bug is in your wiring,
  not your agent.

### 3. Trusting the number

- **Your metric is noisy: what the numbers actually cost you** — a training
  script with a real seed, run under `noise`, then the same loop with and
  without `--min-delta` and `--confirm`, showing false keeps in the ledger.
  Reproduces the README's table on a live experiment instead of a simulation.
- **Make a stochastic experiment hold still** — seed, fixed split, averaged
  runs; the before-and-after `noise` output as the evidence.
- **Choosing `--protect` for a real evaluator** — a project where the eval
  writes a cache inside its own directory, which breaks the digest. Shows the
  refusal, then the fix, and why "protect the measurement, not the directory"
  is a rule with teeth.
- **What the classic cheats look like in a ledger** — three staged proposals:
  overwrite the test, memorise the holdout by adding a file, print the metric
  without computing it. The third is the interesting one, because `--protect`
  does not catch it and the recipe says so.

### 4. More than one thread

- **Two ideas, one baseline** — fork two directions into worktrees over a
  shared ledger, run both, read `log --compare`. The differentiator, worked.
- **Comparing directions that aren't comparable** — deliberately drift one
  direction's harness, watch `--compare` refuse, and fix it.
- **An overnight run on a box you'll close the laptop on** — tmux, budgets,
  `--give-up-after`, and what the morning looks like.
- **Your run died at trial 34** — kill it mid-trial, `labloop resume`, verify
  the ledger is contiguous. Then change `--metric` and watch the refusal name
  the field.

### 5. The ledger as an artifact

- **Turn a ledger into a report** — a stdlib-only script over `log --json`
  producing a convergence plot and a table of what was tried.
- **Write up what the agent tried and why it failed** — mining reverted trials
  for the negative results, in the shape `experiments/` already publishes.
- **The research record that ships with the repo** — using
  `labloop-history.jsonl` in review, months later.

### 6. Loops not worth running

Anti-recipes. Each names the tool that is actually right instead.

- **A metric that takes six hours** — the arithmetic on how many trials an
  overnight budget buys, and when to build a proxy metric first.
- **Two things you care about** — keep-or-revert has no defined answer for a
  tie-break between accuracy and latency. What to do instead.
- **A hyperparameter sweep** — this wants a sweeper, not an agent.
- **A metric too noisy for any setting to save** — the honest exit.

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
