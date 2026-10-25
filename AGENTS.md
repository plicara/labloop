# Working in labloop

This repository owns its code, evidence, and lab context. Read `.plicara/README.md` and `.plicara/project.yaml` before substantive work. Use `make setup` and `make check`; the Makefile is authoritative for commands.

## Boundaries

Preserve evaluator protection, sandbox behavior, and the acceptance criteria of the experiment loop. Do not weaken security checks to make a run pass.

Work stays within the requested project. A sibling checkout is not an implicit dependency or an authorized edit target. Project lifecycle status lives only in `.plicara/project.yaml`; finishing ordinary work never requires updating a central lab board or organization profile.

## Tools and records

Use uv for Python: dependencies in the owning `pyproject.toml`, a committed lockfile, and `uv run --locked` for managed project commands. Independent experiments may have separate environments. Use the native locked package manager for other languages. Paid inference, long training, deployment, and publication are explicit operations outside routine checks.

Project procedures belong in `.agents/skills/<name>/SKILL.md`. Add skills when a repeatable procedure exists; do not fill the folder with speculative instructions. Put significant decisions in dated, append-only records under `.plicara/decisions/`. Keep implementation docs beside code and link to them.

## Completion

Run the checks relevant to the change. Report failures, skipped checks, and remaining local changes accurately; a dirty working tree is not synchronized work. Preserve pre-existing edits. Update metadata only when its facts change, and never copy versions, test counts, or CI state into it.

Commit identity: author Adrian Tame <31286933+AdrianTJ@users.noreply.github.com>, committer Claude <noreply@anthropic.com>. End every commit message that Claude wrote or helped write with a `Co-Authored-By: Claude <noreply@anthropic.com>` trailer (a model version may follow the name), and omit it only for commits Claude had no part in. This applies from this change on; existing history is not rewritten. Use conventional branch prefixes and short kebab-case names. Inspect staged changes for secrets before committing. Ask before destructive operations, publishing, or deployment.

Write Markdown with one paragraph or list item per source line and blank lines between blocks.
