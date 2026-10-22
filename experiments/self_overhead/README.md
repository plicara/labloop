# Dogfooding labloop on itself

**Question.** Does labloop work end to end when a real agent uses it on real code, and what breaks when it does?

**Setup (2026-10-22).** labloop optimized its own per-trial overhead. [`bench.py`](bench.py) is the protected `--run`: it gates on the full test suite, then drives an inner labloop on a fixture project (500 source and data files plus a 4 MiB holdout) through a fixed schedule of twelve proposals with the default bubblewrap sandbox, and fails unless every inner trial reaches its scheduled outcome. The metric is `trial_overhead_ms`, wall-clock milliseconds per inner trial.

The proposer was headless Claude Code (`claude -p`) inside labloop's default sandbox with `--sandbox-network`, restricted to Read, Edit, Write, Glob and Grep, and given a cProfile of the baseline inner loop. The judge was a separately installed copy of labloop from the pre-run commit, so the agent could not edit the code that scored it. Two research directions forked from one baseline: Sonnet 5.5 (10 trials) and Haiku 5.5 (15 trials), run one after the other on one machine. Settings: `--confirm --min-delta 13.94 --strict-metric --guard-imports`, with `tests/`, this directory, `pyproject.toml` and `uv.lock` protected.

## Results

`labloop noise` over six runs: 166.12 to 207.74 ms, standard deviation 13.94 ms (7%). `--min-delta` was set to the standard deviation, not the 41.62 ms spread, with `--confirm` as the second guard.

| Direction | Attempts | Kept | Best | Proposer cost |
| --- | --- | --- | --- | --- |
| baseline | | | 219.53 ms | |
| Sonnet 5.5 | 10 (+3 voided) | 2 | 171.76 ms (−22%) | $1.46, ~$0.11 per trial |
| Haiku 5.5 | 15 | 2 | 176.71 ms (−20%) | $0.45, ~$0.03 per trial |

The two directions differ by 5 ms, inside one standard deviation; this run does not separate the models on quality. It does separate them on cost, by about 3.7×.

Both directions independently found the same two improvements, in the same order:

1. Walk protected directories with `os.scandir` instead of `Path.rglob` plus a `relative_to` per file (Sonnet trial 4, Haiku trial 16; −7% and −8%). Checked against `rglob` on Python 3.10, 3.12 and 3.13, symlinked directories included: same file set.
2. Digest the protected set once per trial instead of twice, sharing the snapshot between the incumbent check and the pre-proposal check (Sonnet trial 9 via a cached attribute, Haiku trial 17 via an explicit parameter; −16% and −12%). Haiku's form is safe by construction; Sonnet's needed a caller analysis to show it was.

Neither change is merged; the kept commits live on the local `labloop/sonnet` and `labloop/haiku` branches of the run.

Of 21 reverted trials, roughly two thirds retried an idea already reverted: Haiku proposed removing a redundant `is_dirty()` call six times and string paths in the digest loop six times; Sonnet retried unbuffered or `file_digest` hashing seven times. Many of those measured 163 to 168 ms, a plausible real gain of about 10 ms that never clears a 13.94 ms threshold alone.

## What dogfooding found

Fixed on this branch:

- **Root sandbox kept a full capability bounding set.** Run as real root (containers, CI, cloud agents), bubblewrap skips the user namespace, so `--cap-drop ALL` left the bounding set full in the host namespace. CI runs the sandbox job unprivileged and never saw it. Now `--unshare-user` is explicit.
- **labloop's suite failed when labloop ran it.** Three tests read `PYTHONPYCACHEPREFIX` or `LABLOOP_BRIEF` from the enclosing loop. An autouse fixture now clears them and disables bytecode writes, which an enclosing `--guard-imports` would otherwise reject.
- **`labloop noise` hid why a run failed.** It raised a bare traceback without the command's output; an existing test asserted the traceback. It now exits 2 with the output tail.

Open, needing a decision:

- **The brief does not say what a trial changed.** It reports "the direction worked, the margin was too small" without naming the direction, and the ledger keeps the run's output, not the proposal's. Repeated attempts above are the cost. A diffstat and the proposer's closing lines per history entry would address it.
- **`--guard-imports` over-matches.** It flags stdlib-named paths at any depth among all ignored files, pre-existing ones included, so an in-tree `.venv` (`_pytest/doctest.py`) or the bytecode of a tracked submodule (`mypkg/types.py`) fails every trial. Flagging only paths absent at run start would keep the 1.0.5 `.gitignore` bypass closed.
- **A flagged shadow wedges the run.** The guard rejects the trial but never removes the ignored file it flagged, so every later trial fails until `--give-up-after`. Here an operator-written `.pyc` voided Sonnet trials 5 to 7; the guard blamed the proposal because it cannot tell who wrote it.
- **`labloop baseline` exits 0 when the baseline is not kept**, so a script cannot tell from the exit status.
- **Small gains cannot stack.** With noise at 7%, a real 5% improvement is reverted every time it is proposed. Reducing the benchmark's variance is the real fix here; a loop-level answer would be a separate design.
- **The ledger's `note` is empty on reverts.** The reason exists only in the brief.

Operating labloop with Claude Code as the proposer:

- Self-hosting needs a judge the agent cannot edit; a `uv tool install` of the pre-run commit worked.
- Claude Code denies reads outside its working directory, and the brief lives outside the worktree by design: pass `--add-dir "$(dirname "$LABLOOP_BRIEF")"`.
- In this environment Claude Code's Bash tool cannot run inside the sandbox: it creates a cgroup under the read-only `/sys/fs/cgroup`. The proposer ran without a shell, which the `labloop-proposer` skill does not anticipate (`cat "$LABLOOP_BRIEF"`, "run the experiment yourself").
- `acceptEdits` permits `rm` regardless of a Bash allowlist.
- A nested `claude -p` inherits the parent session's environment, including its session id.
- Never run code in a live worktree during a run: anything it writes is attributed to the trial in progress.

## Reproducing

The bench needs bubblewrap and runs in about 70 s:

```bash
uv run --locked --extra dev python experiments/self_overhead/bench.py
```

The driver scripts, proposer wrapper and prompt were operator files outside the repository, as were the ledger and transcripts.
