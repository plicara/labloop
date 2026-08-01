"""The experiment loop: propose, run, measure, keep or revert."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

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

        proposal = run_command(
            self.experiment.propose or "",
            cwd=self.workdir,
            timeout=self.experiment.budget_seconds,
            env=self.experiment.env,
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
            )
        )

    def _incumbent(self) -> float | None:
        best = self.ledger.best(self.experiment.goal)
        return best.metric if best else None

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
