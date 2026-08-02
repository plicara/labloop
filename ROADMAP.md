# Roadmap to 0.1.0

What has to exist before this ships as a package rather than a concept.
Ordered: each stage builds on the one before it, and release is last on
purpose. PyPI version numbers are permanent and the name is claimed on first
publish, so nothing goes out until the list above it is done.

The positioning this serves: autoresearch proved the keep-or-revert loop on
one task (nanochat, `val_bpb`, one GPU, one thread of commits). labloop
generalizes it — any command, any metric, the trial history as a queryable
artifact — and its author has named the next step himself: "not to emulate a
single PhD student, it's to emulate a research community of them." The
differentiators below are, in order: trust the number, don't lose the work,
run more than one thread, and be easy to start.

## 1. Concurrency safety — ledger locking · **done**

Two loops over one ledger interleave silently today: interleaved trial
indices, two incumbents, a corrupted record. The dirty-tree interlock
catches same-tree collisions by accident, but two worktrees sharing a ledger
have no guard at all — and worktrees are exactly how parallel directions
(stage 3) will run.

- Advisory lock (`fcntl`/`msvcrt`) on the ledger for the duration of a run;
  a second loop fails fast with a message naming the holder's pid.
- `--wait` to queue instead of fail.
- Acceptance: the concurrent-loops probe from the test suite ends with one
  winner, one clean refusal, zero interleaved lines. Windows lock path
  covered in CI or explicitly documented as unsupported.
- Shipped: flock on a temp-dir sidecar keyed by the ledger's resolved path
  (never in the working tree, where it would trip the dirty-tree
  interlock), re-entrant, released by the OS on process death. The race is
  a test: two real processes, one winner, one exit-2 refusal, contiguous
  indices. Windows uses msvcrt best-effort and is not exercised by CI.

## 2. Resumability — `labloop resume` and run manifests · **done**

An overnight run dies (OOM, reboot, closed laptop). The ledger survives by
design, but what the user then does is re-type the whole invocation and hope
it matches; if the metric name or protect set drifted, the harness-mismatch
guard fires and tells them to start a new ledger.

- Record the full experiment spec (run, metric, goal, budgets, protect,
  min-delta, confirm) in the ledger as a manifest line on every start.
- `labloop resume` re-reads it and continues under the same spec; a spec
  that differs from the manifest is an error naming the field that moved.
- Acceptance: kill a run at trial N, `labloop resume`, ledger shows
  N+1 onward with the same incumbent and harness digest; changing
  `--metric` between the two is refused with the field named.
- Shipped: manifest lines live in the ledger itself (invisible to older
  readers, which skip them like any unparseable line), deduplicated so an
  unchanged spec is one line however many runs start under it. `env` is
  never recorded — that is where credentials live. Identity drift (metric,
  goal) is refused by name on any run, not only resume; schedule drift
  (budgets, propose, trials) is recorded and allowed.

## 3. Branching research directions — the named gap · **core done**

One linear thread of commits today. The differentiator worth the most and
the one to design most carefully:

- `trial.parent` (commit of the incumbent it beat) already implicit — make
  it explicit in the schema; add a `direction` field.
- `labloop branch <name>` forks a direction from any kept trial: its own git
  branch, its own incumbent line in the shared ledger.
- Directions run concurrently in separate worktrees (stage 1 makes the
  shared ledger safe; stage 2's manifests keep each direction honest).
- `labloop log --tree` renders the directions and their best metrics;
  cross-direction comparison only where harness digests match.
- Explicitly out of scope for 0.1.0: automatic merging of directions.
  Choosing what to merge is research judgment; the tool's job is to keep the
  candidates comparable.
- Acceptance: two directions from one baseline, run in parallel, each
  advancing its own incumbent; `log --tree` shows both; the losing
  direction's trials remain queryable.
- Shipped: `direction` on every trial (old ledgers read as one direction,
  `main`), fork records in the ledger, per-direction incumbents seeded
  from the fork point and blind to the parent's later progress,
  `labloop branch` with worktree instructions, `--direction` on runs,
  per-direction bests in `log`, resume returns to the direction in force.
- Remaining, deliberately: simultaneous runs still serialize on the
  per-run ledger lock (`--wait` queues them). True simultaneity needs
  per-append locking with index coordination — a smaller, separate change
  now that the semantics exist.

## 4. `labloop init` — the first five minutes

The README teaches concepts; nothing scaffolds a project. `init` writes the
pieces a new project needs and nothing else: a `.gitignore` covering ledger
and caches, a stub eval script that prints the metric in the accepted
format, a suggested `--protect` set, and — when the tree already has an
obvious experiment — a filled-in first command to run. Ends by running
`labloop noise` so the first thing a user learns is whether their metric
holds still.

- Acceptance: `labloop init && labloop baseline ...` works in an empty git
  repo without editing anything by hand.

## 5. Ledger tooling — the artifact half of the pitch

"Trial history as a queryable artifact" currently means "it's JSONL, bring
jq". Minimum honest version:

- `labloop log --json` (machine-readable, stable field names).
- Filters: `--outcome`, `--since-trial`, `--direction`.
- `labloop log --compare A B` for two directions or two ledgers, refusing
  where harness digests differ.
- Acceptance: every README claim about querying the ledger is a copy-paste
  command that works.

## 6. Release engineering

- Rehearse on TestPyPI: build, upload, `pip install` into a clean venv on
  3.10 and 3.13, run the CI smoke script against the installed wheel.
- Fill `CHANGELOG.md` from the commit history (the bug-fix story is the
  honest marketing: eleven bugs found by dogfooding, each with a test).
- Configure PyPI trusted publishing exactly as `publish.yml`'s header
  documents; tag `v0.1.0`; verify the published wheel with the same smoke
  script. A pending publisher does not reserve the name — publish claims it.

## Not doing, and why

- **The `autoresearch` PyPI name** stays unclaimed. It would read as the
  official package of a 90k-star project that isn't ours; that confusion is
  what PEP 541 exists to reverse.
- **Automatic direction merging** — see stage 3.
- **A bundled agent.** `propose` stays any command. The brief/env contract
  is the integration surface; adapters belong in examples, not the core.
- **Outcome consolidation.** Measured (see
  `experiments/outcome_granularity/`): labels beat no labels with p < 0.01;
  five vs nine is not distinguishable on convergence, and the nine-set's
  extra distinctions each trace to a recorded bug their absence caused. They
  stay.
