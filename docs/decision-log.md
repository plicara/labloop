# Decision log

## DEC-001: Constrain writable evidence to a fixed home-state subtree

- **Date:** 2026-09-14
- **Status:** decided
- **Context:** The follow-up audit of 1.0.2 found that rejecting broad filesystem roots still allowed grants to credential and configuration directories. The user explicitly preferred constraining allowable locations. An explicit bind is caller-granted permission, not by itself a sandbox escape; the goal here is preventing accidental excessive grants.
- **Options considered:** Expand the denylist (continual maintenance and omissions); accept a configurable arbitrary evidence root (moves the same permission problem to another setting); use a fixed evidence subtree (simple, inspectable policy with a migration cost).
- **Decision:** Permit only existing strict descendants of the real home directory's `.local/state/labloop/evidence` subtree. Refuse the root itself, worktree overlap in either direction, and redirects of the evidence root or evidence paths outside that subtree. Resolve the home directory before applying the fixed suffix so a normal symlinked home is supported.
- **Consequences:** Users create dedicated evidence directories and update existing `run`/`resume` configurations that granted arbitrary paths. No arbitrary runtime/config-directory writes are supported. Evidence remains untrusted proposer output and must not contain credentials. This constrains the proposer only; measurement isolation remains outside the current design.

## DEC-002: Check completed measurements and harden the existing backend

- **Date:** 2026-09-14
- **Status:** decided
- **Context:** A follow-up sandbox-integrity audit showed that proposed code could defer a protected-file or ledger edit until measurement, after the original proposal-only check. The user approved closing this gap and selectively borrowing hardening ideas rather than integrating another sandbox runtime.
- **Options considered:** Proposal-only checks (miss run-time changes); post-measurement checks (small, compatible detection improvement); wrap the existing measurement command (does not separate candidate code from metric authority); separate candidate and evaluator workers (stronger boundary with a new workload contract).
- **Decision:** Check the protected set and ledger after each completed ordinary, confirmation, baseline, and noise measurement before accepting its metric. Recover detected ledger changes, discard compromised metrics, preserve preexisting baseline work, and serialize noise calibration under the ledger lock. Add explicit Bubblewrap capability dropping and session detachment. Keep the current backend and defer runtime integration and network proxies.
- **Consequences:** Evaluators must keep caches and logs outside protected paths. Snapshot checks still miss transient changes restored before exit, and interrupted commands do not reach post-command checks. Measurement still runs on the host. The next architectural direction is separate candidate execution and evaluator-owned scoring, described in [Evaluation isolation](evaluation-isolation.md); that mode is not implemented or promised by the current interface.
