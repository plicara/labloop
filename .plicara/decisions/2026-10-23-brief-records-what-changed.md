# The brief records what each attempt changed

- **Date:** 2026-10-23
- **Status:** decided

## Context

Dogfooding labloop on its own per-trial overhead with two Claude Code directions (see [the write-up](../../experiments/self_overhead/README.md)) showed that the brief named each earlier trial's outcome and reason but never its change. Of 21 reverted trials, roughly two thirds re-proposed an idea already reverted; one proposer tried the same `is_dirty()` removal six times. The README's premise that reverted attempts are most of the information held only for a human reading transcripts outside labloop.

The brief has a standing rule: labloop writes it and the proposer only reads it, because agents given writable memory leave notes for later attempts. Any record of what an attempt changed is, at some level, the attempt's own output.

## Options considered

1. Put the proposer's own summary in the brief. Most informative, and exactly the notes channel the rule exists to close.
2. Put the reverted diff in the brief. Informative, but comments, strings and prose files carry free text forward.
3. Put a summary derived by labloop from git: paths, status, line counts, and the enclosing definitions as bare identifiers, for source files only.
4. Change nothing and rely on the proposer's own exploration.

## Decision

Option 3. Each trial that reaches measurement records `change`, read with one `git diff -U0` before the measurement runs, with external diff and textconv drivers off and git's builtin function-name rules applied by extension. `where` keeps only identifiers, so a comment or a line of a notes file never reaches the brief. The brief carries `change` per history entry and `tried`, an aggregate by file and definition over the whole direction. The proposer's output is kept in the ledger as `proposal_tail` for humans and never placed in the brief.

## Consequences

Identifier names remain a narrow channel: a proposer can name a function after its plan. Kept code already carries names forward, so closing it in the brief alone would buy nothing. The summary costs one git process per measured trial, about 4 ms in the dogfood benchmark, within its noise. A workspace without `describe_change` records no summary and otherwise behaves as before. Whether this reduces repeated attempts is to be measured by re-running the same dogfood experiment.
