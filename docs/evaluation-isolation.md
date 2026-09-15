# Evaluation isolation

Status: design proposal, not implemented. The current release interface still runs `--run` on the host. Post-command integrity checks reject persistent protected-file and ledger changes; they do not make candidate execution or its reported score trustworthy.

## Boundary to build

Separate the controller, candidate, and evaluator into distinct trust domains. Wrapping the existing `--run` command in the proposer sandbox alone would not establish this boundary: candidate code could still share a process with the evaluator or print a forged metric.

| Component | Owns | Must not trust |
| --- | --- | --- |
| Controller | Ledger, Git operations, trial identity, immutable candidate snapshot, acceptance decision | Candidate stdout, writable evidence, candidate-provided paths or Git configuration |
| Candidate worker | Writable scratch and explicitly declared output artifacts | No authority over evaluator code, holdout answers, ledger, controller processes, or Git metadata |
| Evaluator worker | Frozen evaluator code, dependencies, holdout data, and final metric computation | Candidate artifacts are untrusted data, not importable code or executable serialization |

The intended sequence is: capture the candidate snapshot; execute it in an isolated worker; stop all worker descendants; validate and transfer declared outputs; evaluate them in a separate worker; accept only the evaluator's result. The controller retains sole authority to write the ledger and commit the exact candidate snapshot, not files subsequently mutated by measurement.

## First supported workload

Start with artifact-based evaluation: a candidate produces predictions or another bounded, non-executable data format, and a trusted evaluator computes the score. The evaluator never imports candidate Python modules or unpickles candidate objects. A structured JSON result is useful for validation, but is not authentication by itself: the channel must be writable only by the evaluator, and the controller must bind it to the current trial and candidate snapshot.

Many existing experiments use `python eval.py`, import candidate code, need interactive inference, or evaluate performance in-process. Those workloads need a separate adapter or a clearly labeled legacy mode. Do not silently claim the artifact protocol covers them. Holdout confidentiality also needs separate treatment when the candidate must see evaluation inputs.

## Required controls

- Construct read-only evaluator inputs and dependencies outside candidate-writable space. Pin the environment, sanitize import paths and environment variables, and exclude writable package and bytecode caches. A read-only source file is insufficient when imports can resolve elsewhere.
- Give candidate workers only declared inputs, dedicated scratch, and bounded output destinations. Hide the controller's ledger, Git metadata, credentials, process namespace, and local sockets. Keep the existing proposer's broader read policy distinct from this stronger execution policy.
- Transfer artifacts only after worker termination, from an immutable snapshot or controller-owned copies. Reject symlinks, special files, path traversal, oversized outputs, and executable deserialization formats. Avoid validating a path and then reopening attacker-replaceable contents.
- Run the evaluator in a separate constrained process environment. A malicious artifact can exploit a parser; treating the evaluator as trusted does not justify granting it controller write access.
- Bound process lifetime, output, memory, and artifact size; fail closed when required isolation is unavailable. Define timeout and interruption recovery before enabling the mode. Keep rejected data quarantined only through an explicit inspection policy.
- Make network, GPU, device access, and caches explicit compatibility choices. These can expand authority substantially and should not be inferred from the legacy command configuration.

## Delivery gates

Before implementing a public mode, choose the artifact schema, supported workload, isolation substrate, and migration semantics. Linux Bubblewrap may provide parts of the filesystem/process boundary; a disposable VM can provide a stronger host boundary. Neither automatically separates metric authority from candidate execution.

Acceptance tests must attempt persistent and transient evaluator rewrites, forged stdout and result files, import/cache poisoning, artifact path replacement, malicious serialization, ledger/Git modification, and escaped descendants. Tests must also demonstrate legitimate artifact evaluation, interruption recovery, reproducible snapshot commits, and refusal on an unsupported host. Kernel-facing tests must run on the supported execution platform, not only inspect generated command strings.

## What to borrow from sandbox-runtime

Keep the current Bubblewrap backend and the explicit capability/session hardening. Defer adding another runtime dependency, backend abstraction, and network proxies. A future domain-filtered egress policy could improve hosted-agent usability, but needs its own threat model for DNS, redirects, local relays, and credential handling. It does not solve measurement integrity and should not be a prerequisite for evaluator separation.
