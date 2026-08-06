# Skills

Three agent skills covering the three moments where a labloop user has an
agent in the room. They are written for Claude Code's skill format
(`SKILL.md` with `name`/`description` frontmatter) and contain no
Claude-specific machinery, so the body is useful to any agent that can read
instructions.

| Skill | Who loads it | The moment |
| --- | --- | --- |
| `labloop-setup` | the user's assistant | wiring an experiment before any trial is spent |
| `labloop-proposer` | **the agent inside `--propose`** | making one attempt, judged and probably reverted |
| `labloop-triage` | the user's assistant | a run that produced nothing, or too much |

## Install

Copy into the project where you run experiments — not into labloop's own
checkout:

```bash
mkdir -p .claude/skills
cp -r /path/to/labloop/cookbook/skills/labloop-* .claude/skills/
```

`labloop-setup` and `labloop-triage` then load themselves when the
conversation calls for them. `labloop-proposer` is different: it is for the
agent labloop invokes, so the proposer command has to be one that can load
skills from the project.

```bash
labloop run --propose "claude -p 'Improve train.py' --permission-mode acceptEdits" ...
```

## Why `labloop-proposer` is the interesting one

The roadmap declines to bundle an agent: `propose` stays any command, and the
brief/env contract is the integration surface. That leaves a real gap — every
user wires up the same brief-reading glue and the same hard-won prompt
knowledge in private.

A skill fills the gap without closing the door. It is text, it ships in the
cookbook rather than the package, it adds no dependency, and swapping `claude`
for `aider` or `codex` costs nothing.

Its content is not invented. It encodes what a recorded run actually did:

- **One focused change per trial.** After three reverts, an agent escalated to
  a sweeping rewrite, spent seven times its usual thinking budget, and produced
  its worst result of the run. The skill names that instinct and redirects it.
- **The `reverted` trap.** A change can move the metric the right way and still
  be reverted for missing `--min-delta`. On labloop 0.1.0 the brief said
  *"did not beat 0.2245"* about a change that beat it by 31%; that is
  [now fixed](../../src/labloop/brief.py), and the skill teaches both the
  current message and the check to run on older versions.
- **The nine outcomes as a routing table.** Each label sends you somewhere
  different; that is measured, not asserted
  (`experiments/outcome_granularity/`, p < 0.01 against no labels).

## What was actually tested

`labloop-proposer` was installed into a scratch project and driven through a
real loop on the stdlib-index benchmark:

```
[+] trial   0        0.3613     0.4s  (baseline)
[+] trial   1        0.2163    27.3s  daccf1d
[-] trial   2         0.271   167.6s
```

**What this establishes:** the skill loads, the agent works under it, and the
loop keeps its result. Trial 1 was a clean focused change — sets for the
buckets, dedupe per file, and `search` reduced to set intersection.

**What it does not establish, and the part worth reading:** trial 2 spent
**167.6 seconds** — six times trial 1 — and came back *worse* than the
incumbent. That is the same failure mode the skill's "one focused change per
trial" rule was written to prevent, appearing on the second trial after the
rule was installed. One data point is not a refutation, but it is certainly
not a confirmation, and it would be dishonest to show trial 1 alone.

The obvious comparison — 0.2163 here against 0.2245 in the recipe — is not a
comparison at all: different baselines (0.3613 vs 0.3342) on a shared machine
whose load moved between runs, n=1 on each side, and a non-deterministic agent.
Reading a win into that would be exactly the mistake `labloop noise` exists to
prevent, in the repository that built the tool.

Measuring whether these skills help means many paired runs with and without
them, which is an `experiments/` job with statistics, not a cookbook claim.
Until someone does that, they are reasoned from recorded failures and
**not demonstrated to improve anything** — including the failure mode above,
which they have now been observed not to prevent once.

## Limits

These are instructions, not enforcement. A skill cannot stop an agent editing
the harness — `--protect` detects that, and nothing prevents it. The skill
makes the good path clear and the bad path explicitly named, which is what
instructions can do and all they can do.
