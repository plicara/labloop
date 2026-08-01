"""The experiment loop: propose, run, measure, keep or revert."""

from __future__ import annotations

import tempfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

from . import brief as _brief
from .integrity import (
    HarnessMismatchError,
    NoProtectedFilesError,
    file_digest,
    harness_digest,
)
from .ledger import Ledger
from .metrics import MetricNotFound, extract_metric
from .runner import run_command
from .types import Experiment, Outcome, Trial
from .workspace import GitWorkspace, Workspace

__all__ = ["Loop"]

Reporter = Callable[[Trial], None]


class Loop:
    """Drive an experiment toward a better metric, one reversible step at a time.

    Each trial mutates the working tree, runs the experiment under a wall-clock
    budget, and keeps the change only if the metric improved on the incumbent.
    Anything else — a worse score, a crash, a timeout, a missing metric — is
    reverted. Every trial is recorded either way.
    """

    def __init__(
        self,
        experiment: Experiment,
        workdir: str | Path = ".",
        ledger: str | Path = "labloop.jsonl",
        workspace: Workspace | None = None,
        reporter: Reporter | None = None,
    ) -> None:
        self.experiment = experiment
        self.workdir = Path(workdir)
        self.ledger = Ledger(ledger)
        self.workspace = workspace or GitWorkspace(self.workdir)
        self.reporter = reporter

    def baseline(self) -> Trial:
        """Measure the tree as it stands, without proposing a change.

        Establishes the incumbent. Recorded as KEPT because it is the state
        the working tree is actually in — there is nothing to revert to.
        """
        # Digested before the run, so it describes the tree that was measured.
        harness = self._harness()
        completed = run_command(
            self.experiment.run,
            cwd=self.workdir,
            timeout=self.experiment.budget_seconds,
            env=self.experiment.env,
        )
        metric = self._read_metric(completed.output)
        succeeded = metric is not None and completed.ok
        outcome = Outcome.KEPT if succeeded else self._failure(completed, metric)

        trial = Trial(
            index=self.ledger.next_index(),
            outcome=outcome,
            metric=metric,
            incumbent=None,
            duration_seconds=completed.duration_seconds,
            note="baseline",
            stdout_tail=completed.tail,
            harness=harness,
        )
        self._record(trial)
        return trial

    def run(self, trials: int = 1) -> list[Trial]:
        """Run `trials` proposal-and-judge cycles."""
        if self.experiment.propose is None:
            raise ValueError(
                "experiment has no `propose` command; use baseline() to measure "
                "the tree as-is, or set propose to an agent invocation"
            )
        if isinstance(self.workspace, GitWorkspace):
            self.workspace.require_clean()

        incumbent = self._incumbent()
        results: list[Trial] = []

        for _ in range(trials):
            trial = self._one_trial(incumbent)
            results.append(trial)
            if trial.outcome is Outcome.KEPT and trial.metric is not None:
                incumbent = trial.metric
        return results

    def _one_trial(self, incumbent: float | None) -> Trial:
        index = self.ledger.next_index()
        harness = self._harness()
        ledger_before = file_digest(self.ledger.path)

        with self._proposal_env(index, incumbent) as env:
            proposal = run_command(
                self.experiment.propose or "",
                cwd=self.workdir,
                timeout=self.experiment.budget_seconds,
                env=env,
            )

        # Checked before the exit status, and before spending the budget on a
        # run whose number would mean nothing anyway. A proposal that moved
        # the measurement is a more serious event than one that crashed.
        tampering = self._tampering(harness, ledger_before)
        if tampering:
            self.workspace.revert()
            return self._record(
                Trial(
                    index=index,
                    outcome=Outcome.HARNESS_CHANGED,
                    metric=None,
                    incumbent=incumbent,
                    duration_seconds=proposal.duration_seconds,
                    note=tampering,
                    stdout_tail=proposal.tail,
                    harness=harness,
                )
            )

        if not proposal.ok:
            self.workspace.revert()
            return self._record(
                Trial(
                    index=index,
                    outcome=Outcome.FAILED,
                    metric=None,
                    incumbent=incumbent,
                    duration_seconds=proposal.duration_seconds,
                    note="propose command failed",
                    stdout_tail=proposal.tail,
                    harness=harness,
                )
            )

        completed = run_command(
            self.experiment.run,
            cwd=self.workdir,
            timeout=self.experiment.budget_seconds,
            env=self.experiment.env,
        )
        metric = self._read_metric(completed.output)
        duration = proposal.duration_seconds + completed.duration_seconds

        if metric is None or not completed.ok:
            self.workspace.revert()
            return self._record(
                Trial(
                    index=index,
                    outcome=self._failure(completed, metric),
                    metric=metric,
                    incumbent=incumbent,
                    duration_seconds=duration,
                    stdout_tail=completed.tail,
                    harness=harness,
                )
            )

        improved = incumbent is None or self.experiment.goal.is_better(metric, incumbent)
        if not improved:
            self.workspace.revert()
            return self._record(
                Trial(
                    index=index,
                    outcome=Outcome.REVERTED,
                    metric=metric,
                    incumbent=incumbent,
                    duration_seconds=duration,
                    stdout_tail=completed.tail,
                    harness=harness,
                )
            )

        message = f"labloop: {self.experiment.metric} {metric:.6g}"
        if incumbent is not None:
            message += f" (was {incumbent:.6g})"
        commit = self.workspace.commit(message)

        return self._record(
            Trial(
                index=index,
                outcome=Outcome.KEPT,
                metric=metric,
                incumbent=incumbent,
                duration_seconds=duration,
                commit=commit,
                stdout_tail=completed.tail,
                harness=harness,
            )
        )

    @contextmanager
    def _proposal_env(self, index: int, incumbent: float | None) -> Iterator[dict[str, str]]:
        """Write the brief, point the proposal at it, then take it away again.

        The file is written outside the working tree deliberately. Dropping it
        in the workdir would dirty the tree the loop just insisted was clean,
        and `git add -A` would sweep it into the next commit.
        """
        if not self.experiment.brief:
            yield dict(self.experiment.env)
            return

        payload = _brief.build(self.experiment, self.ledger.trials(), index, incumbent)
        handle = tempfile.NamedTemporaryFile(
            "w",
            prefix=f"labloop-brief-{index}-",
            suffix=".json",
            delete=False,
            encoding="utf-8",
        )
        try:
            with handle as fh:
                fh.write(_brief.dumps(payload))
            yield {**self.experiment.env, **_brief.environment(handle.name, payload)}
        finally:
            Path(handle.name).unlink(missing_ok=True)

    def _harness(self) -> str | None:
        return harness_digest(self.workdir, self.experiment.protect)

    def _tampering(self, harness: str | None, ledger_before: str | None) -> str | None:
        """Name what the proposal changed that it had no business changing.

        The ledger is checked unconditionally. It is the source of truth for
        the incumbent, so an agent that can rewrite it can lower the bar it is
        being judged against — and it usually sits in the working tree, where
        a revert may not reach it.
        """
        if file_digest(self.ledger.path) != ledger_before:
            return "proposal modified the ledger"
        if harness is None:
            return None
        try:
            after = self._harness()
        except NoProtectedFilesError:
            return "proposal deleted the protected files"
        return "proposal modified the harness" if after != harness else None

    def _incumbent(self) -> float | None:
        """The metric to beat, read from the ledger rather than memory.

        Refuses an incumbent that a different harness produced: those two
        numbers came from different measurements, and comparing them would
        manufacture an improvement out of nothing. Trials recorded before any
        harness was declared carry no digest and cannot be checked either way,
        so they are accepted — the check can only speak for what it measured.
        """
        best = self.ledger.best(self.experiment.goal)
        if best is None:
            return None

        current = self._harness()
        if current is not None and best.harness is not None and best.harness != current:
            raise HarnessMismatchError(
                f"trial {best.index} was measured by a different harness "
                f"({best.harness[:12]} vs {current[:12]}); its {self.experiment.metric} "
                "is not comparable to what this loop would measure — start a new ledger"
            )
        return best.metric

    def _read_metric(self, output: str) -> float | None:
        try:
            return extract_metric(output, self.experiment.metric)
        except MetricNotFound:
            return None

    @staticmethod
    def _failure(completed, metric: float | None) -> Outcome:
        if completed.timed_out:
            return Outcome.TIMED_OUT
        if metric is None:
            return Outcome.NO_METRIC
        return Outcome.FAILED

    def _record(self, trial: Trial) -> Trial:
        self.ledger.append(trial)
        if self.reporter:
            self.reporter(trial)
        return trial
