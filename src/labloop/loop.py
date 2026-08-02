"""The experiment loop: propose, run, measure, keep or revert."""

from __future__ import annotations

import json
import math
import tempfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

from . import brief as _brief
from .integrity import (
    HarnessMismatchError,
    NoProtectedFilesError,
    changed_files,
    combine,
    file_digest,
    harness_digest,
    harness_files,
)
from .ledger import Ledger
from .lock import LedgerLock
from .metrics import MetricNotFound, extract_metric
from .runner import run_command
from .types import Experiment, Goal, Outcome, Trial, UsageError
from .workspace import GitWorkspace, Workspace

__all__ = ["Loop", "StalledError"]

Reporter = Callable[[Trial], None]


class StalledError(RuntimeError):
    """Trial after trial produced no measurement, so the run was stopped."""


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
        wait_for_lock: bool = False,
    ) -> None:
        self.experiment = experiment
        self.workdir = Path(workdir)
        # Relative to the project, not to wherever the command was typed. The
        # ledger is the project's research record, and resolving it against
        # the shell's cwd meant running the same project from two directories
        # silently produced two ledgers — the second starting from no
        # incumbent and renumbering from zero.
        ledger = Path(ledger)
        self.ledger = Ledger(ledger if ledger.is_absolute() else self.workdir / ledger)
        self.workspace = workspace or GitWorkspace(self.workdir)
        self.reporter = reporter
        self.lock = LedgerLock(self.ledger.path, wait=wait_for_lock)

    def baseline(self) -> Trial:
        """Measure the tree as it stands, without proposing a change.

        Establishes the incumbent. Recorded as KEPT because it is the state
        the working tree is actually in — there is nothing to revert to.
        """
        with self.lock:
            return self._baseline()

    def _baseline(self) -> Trial:
        # Digested before the run, so it describes the tree that was measured.
        harness = self._harness()
        clean_before = not self.workspace.is_dirty()
        completed = run_command(
            self.experiment.run,
            cwd=self.workdir,
            timeout=self.experiment.budget_seconds,
            env=self.experiment.env,
        )
        metric = self._read_metric(completed.output)
        note = "baseline"
        if metric is None or not completed.ok:
            outcome, metric = self._failure(completed), None
        elif not math.isfinite(metric):
            outcome, note, metric = Outcome.NOT_FINITE, self._not_finite(metric), None
        else:
            outcome = Outcome.KEPT

        trial = Trial(
            index=self.ledger.next_index(),
            outcome=outcome,
            metric=metric,
            incumbent=None,
            duration_seconds=completed.duration_seconds,
            note=note,
            stdout_tail=completed.tail,
            harness=harness,
        )
        self._record(trial)

        # A run that spews artifacts onto a clean tree would block the next
        # `run` on the dirty-tree interlock. Sweeping is only safe when the
        # tree was clean going in: on a dirty tree everything present might
        # be the user's work, and baseline measures the tree as it stands —
        # it has no business deleting any of it.
        if clean_before and self.workspace.is_dirty():
            self.workspace.revert()
        return trial

    def measure_noise(self, repeats: int = 5) -> list[float]:
        """Run the experiment repeatedly without changing anything.

        Keep-or-revert assumes a difference in the metric means a difference
        in the code. If the same tree scores differently run to run, the loop
        will happily commit the luckier draws and report them as progress —
        the spread this returns is the size of improvement below which that is
        all it can be doing. Nothing is written to the ledger: these are not
        trials, and treating them as an incumbent would bias it.
        """
        if repeats < 2:
            raise UsageError("measuring spread needs at least 2 runs")

        values: list[float] = []
        for _ in range(repeats):
            completed = run_command(
                self.experiment.run,
                cwd=self.workdir,
                timeout=self.experiment.budget_seconds,
                env=self.experiment.env,
            )
            metric = self._read_metric(completed.output)
            if metric is None or not completed.ok or not math.isfinite(metric):
                raise RuntimeError(
                    f"the run command did not produce a usable {self.experiment.metric} "
                    f"(exit {completed.returncode}); fix that before measuring its spread"
                )
            values.append(metric)
        return values

    def run(self, trials: int = 1) -> list[Trial]:
        """Run `trials` proposal-and-judge cycles.

        Holds the ledger lock throughout: two loops over one ledger would
        interleave trial indices and each advance its own incumbent.
        """
        if self.experiment.propose is None:
            raise UsageError(
                "experiment has no `propose` command; use baseline() to measure "
                "the tree as-is, or set propose to an agent invocation"
            )
        with self.lock:
            return self._run(trials)

    def _run(self, trials: int) -> list[Trial]:
        if isinstance(self.workspace, GitWorkspace):
            self.workspace.require_clean()

        incumbent = self._incumbent()
        results: list[Trial] = []
        stalled = 0

        for _ in range(trials):
            try:
                trial = self._one_trial(incumbent)
            except KeyboardInterrupt:
                # An overnight run stopped by hand is still a trial that
                # happened. Recording it before re-raising keeps the ledger's
                # promise; the tree is left as it is, because discarding a
                # change nobody has looked at is the user's call, not ours.
                self._record(
                    Trial(
                        index=self.ledger.next_index(),
                        outcome=Outcome.INTERRUPTED,
                        metric=None,
                        incumbent=incumbent,
                        duration_seconds=0.0,
                        note="stopped by hand; the tree may hold an unjudged change",
                    )
                )
                raise
            results.append(trial)
            if trial.outcome is Outcome.KEPT and trial.metric is not None:
                incumbent = trial.metric

            # Keeping and reverting are the loop working; a verdict on merit
            # was reached either way. Everything else is machinery that did
            # not do its job, and a mistyped proposal command will otherwise
            # fail identically for every trial in an overnight budget while
            # looking busy. One is ordinary, so the count resets on any real
            # verdict; only an unbroken run of them ends the run.
            judged = trial.outcome in (Outcome.KEPT, Outcome.REVERTED)
            stalled = 0 if judged else stalled + 1
            if self.experiment.give_up_after and stalled >= self.experiment.give_up_after:
                raise StalledError(
                    f"stopping: {stalled} trials in a row reached no verdict on the "
                    f"{self.experiment.metric}. The last one was {trial.outcome.value}"
                    f"{f' ({trial.note})' if trial.note else ''}. "
                    "Every trial is in the ledger, so nothing is lost — fix the setup and "
                    "run again, or pass --give-up-after 0 if this is expected."
                )
        return results

    def _one_trial(self, incumbent: float | None) -> Trial:
        index = self.ledger.next_index()
        files_before = harness_files(self.workdir, self.experiment.protect)
        harness = combine(files_before)
        ledger_before = file_digest(self.ledger.path)

        def record(outcome: Outcome, duration: float, **fields: object) -> Trial:
            """Every branch below shares these; only the verdict differs."""
            return self._record(
                Trial(
                    index=index,
                    outcome=outcome,
                    incumbent=incumbent,
                    duration_seconds=duration,
                    harness=harness,
                    **{"metric": None, **fields},  # type: ignore[arg-type]
                )
            )

        def reject(outcome: Outcome, duration: float, **fields: object) -> Trial:
            self.workspace.revert()
            return record(outcome, duration, **fields)

        with self._proposal_env(index, incumbent) as env:
            proposal = run_command(
                self.experiment.propose or "",
                cwd=self.workdir,
                timeout=self.experiment.propose_timeout,
                env=env,
            )
        spent = proposal.duration_seconds

        # Checked before the exit status, and before spending the budget on a
        # run whose number would mean nothing anyway. A proposal that moved
        # the measurement is a more serious event than one that crashed.
        tampering = self._tampering(harness, ledger_before, files_before)
        if tampering:
            return reject(
                Outcome.HARNESS_CHANGED, spent, note=tampering, stdout_tail=proposal.tail
            )

        if not proposal.ok:
            # A proposal killed at the budget did not fail, it ran out of
            # time. Told it "failed", you go looking for a crash in an agent
            # that was only thinking.
            timed_out = proposal.timed_out
            return reject(
                Outcome.TIMED_OUT if timed_out else Outcome.FAILED,
                spent,
                note=(
                    f"proposal exceeded its {self.experiment.propose_timeout:g}s budget"
                    if timed_out
                    else "propose command failed"
                ),
                stdout_tail=proposal.tail,
            )

        if not self.workspace.is_dirty():
            # Nothing to judge: the tree is the incumbent's tree, so running
            # the experiment would spend the budget re-measuring what the
            # ledger already holds, and any difference would be noise recorded
            # as progress. Committing is not an option either — git refuses an
            # empty commit, which used to end the run with a traceback and no
            # record of the trial. Nothing to revert, so this one does not.
            return record(
                Outcome.NO_CHANGE,
                spent,
                note="proposal left the tree unchanged",
                stdout_tail=proposal.tail,
            )

        # What the proposal touched, captured before the experiment runs so
        # a kept commit records the change and not the artifacts. A training
        # run can leave checkpoints of hundreds of megabytes per trial;
        # committing them turns an overnight run into a repository of
        # hundreds of gigabytes, and the commit stops meaning "the change
        # that improved the metric".
        proposed_paths = self.workspace.changed_paths()

        completed = run_command(
            self.experiment.run,
            cwd=self.workdir,
            timeout=self.experiment.budget_seconds,
            env=self.experiment.env,
        )
        metric = self._read_metric(completed.output)
        spent += completed.duration_seconds

        if metric is None or not completed.ok:
            return reject(self._failure(completed), spent, stdout_tail=completed.tail)

        if not math.isfinite(metric):
            # Never stored as a number. Nothing compares better than nan, so an
            # incumbent holding one reverts every later trial forever, and NaN
            # is not valid JSON for whatever reads the ledger next.
            return reject(
                Outcome.NOT_FINITE,
                spent,
                note=self._not_finite(metric),
                stdout_tail=completed.tail,
            )

        if not self._beats(metric, incumbent):
            return reject(
                Outcome.REVERTED, spent, metric=metric, stdout_tail=completed.tail
            )

        if self.experiment.confirm:
            again = run_command(
                self.experiment.run,
                cwd=self.workdir,
                timeout=self.experiment.budget_seconds,
                env=self.experiment.env,
            )
            second = self._read_metric(again.output)
            spent += again.duration_seconds
            usable = second is not None and again.ok and math.isfinite(second)

            if not (usable and self._beats(second, incumbent)):
                shown = f"{second:.6g}" if second is not None else "--"
                return reject(
                    Outcome.REVERTED,
                    spent,
                    metric=second if usable else None,
                    note=f"won at {metric:.6g} but measured {shown} on a second run",
                    stdout_tail=again.tail,
                )

            # The incumbent advances to the weaker of the two. A lucky draw
            # would otherwise set a bar that only luck can clear, which is the
            # mechanism that walks a noisy metric downwards.
            pick = max if self.experiment.goal is Goal.MINIMIZE else min
            metric = pick(metric, second)

        message = f"labloop: {self.experiment.metric} {metric:.6g}"
        if incumbent is not None:
            message += f" (was {incumbent:.6g})"

        try:
            history = self._write_history(index, metric, incumbent)
            commit = self.workspace.commit(message, [*proposed_paths, history])
        except RuntimeError as exc:
            # A pre-commit hook that rejects the change, or any other reason
            # git declines. The measurement was real, so it is recorded, but a
            # change that cannot be committed cannot be the incumbent — the
            # next trial has to start from a tree that matches the ledger.
            return reject(
                Outcome.FAILED,
                spent,
                metric=metric,
                note=f"improved but could not be committed: {exc}",
                stdout_tail=completed.tail,
            )

        if self.workspace.is_dirty():
            # Whatever the run produced beyond the proposed change —
            # checkpoints, logs, caches not covered by .gitignore. The same
            # sweep every reverted trial already gets; a kept trial's
            # artifacts are no more part of the change than a reverted one's.
            self.workspace.revert()

        return record(
            Outcome.KEPT,
            spent,
            metric=metric,
            commit=commit,
            stdout_tail=completed.tail,
        )

    HISTORY_FILE = "labloop-history.jsonl"

    def _write_history(self, index: int, metric: float, incumbent: float | None) -> str:
        """Refresh the decision log that travels with the repository.

        The ledger stays out of git — it carries output tails and can grow
        without bound. This is the sparse version: one compact line per
        trial, reverted ones included, because the attempts that were thrown
        away are most of the information and `git log` only remembers what
        was kept. Rewritten in full each time, but earlier lines never
        change, so every commit's diff is only the lines since the last keep.
        """
        entries = [
            {
                "index": t.index,
                "outcome": t.outcome.value,
                "metric": t.metric,
                "incumbent": t.incumbent,
                "note": t.note,
            }
            for t in self.ledger
        ]
        entries.append(
            {
                "index": index,
                "outcome": Outcome.KEPT.value,
                "metric": metric,
                "incumbent": incumbent,
                "note": "",
            }
        )
        path = self.workdir / self.HISTORY_FILE
        path.write_text(
            "".join(json.dumps(e, sort_keys=True) + "\n" for e in entries),
            encoding="utf-8",
        )
        return self.HISTORY_FILE

    def _beats(self, candidate: float, incumbent: float | None) -> bool:
        if incumbent is None:
            return True
        return self.experiment.goal.is_better(candidate, incumbent, self.experiment.min_delta)

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

    def _tampering(
        self,
        harness: str | None,
        ledger_before: str | None,
        files_before: dict[str, str] | None = None,
    ) -> str | None:
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
            after = harness_files(self.workdir, self.experiment.protect)
        except NoProtectedFilesError:
            return "proposal deleted the protected files"
        if after == files_before:
            return None
        moved = changed_files(files_before, after)
        if moved:
            return f"proposal modified the harness: {moved}"
        return "proposal modified the harness"

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
                f"({best.harness[:12]} vs {current[:12]}), so its "
                f"{self.experiment.metric} is not comparable to what this loop would "
                "measure. If a protected file changed on purpose, start a new ledger. "
                "If your experiment writes a cache or log into a protected path, that "
                "path is an artifact rather than part of the measurement — stop "
                "protecting it, or move it out."
            )
        return best.metric

    def _not_finite(self, value: float) -> str:
        return f"{self.experiment.metric} was {value}, which cannot be compared"

    def _read_metric(self, output: str) -> float | None:
        try:
            return extract_metric(output, self.experiment.metric)
        except MetricNotFound:
            return None

    @staticmethod
    def _failure(completed) -> Outcome:
        """Why a trial produced nothing usable.

        Exit status is read before the metric. A crashed run that printed
        nothing crashed — calling it "no metric" would send you to check your
        print statement instead of the stack trace. NO_METRIC is reserved for
        what it says: a run that finished cleanly and stayed quiet.
        """
        if completed.timed_out:
            return Outcome.TIMED_OUT
        if not completed.ok:
            return Outcome.FAILED
        return Outcome.NO_METRIC

    def _record(self, trial: Trial) -> Trial:
        self.ledger.append(trial)
        if self.reporter:
            self.reporter(trial)
        return trial
