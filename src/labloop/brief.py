"""What the proposer is told before it makes its next attempt.

A proposal command that gets no feedback is guessing. It cannot see that its
last three attempts died on the same import error, that a change tied the
incumbent, or that the metric it needs was never printed. The ledger already
holds all of that; this turns it into something a program can read.

The brief is written by labloop, from the ledger, and handed to the proposal
as a path. That direction matters. Agents given a memory file they can author
have been observed leaving notes for their future selves, which turns
persistent memory into a channel for working around the harness rather than a
record of it. Here the agent reads and does not write: it learns what happened
without getting to decide what happened.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from .types import Experiment, Goal, Outcome, Trial

__all__ = ["build", "dumps", "environment"]

RECENT = 20
"""Trials included. Enough to show a pattern, bounded so a long run still fits
in a context window."""

_TAIL = 800


def build(
    experiment: Experiment,
    history: Sequence[Trial],
    index: int,
    incumbent: float | None,
    recent: int = RECENT,
) -> dict[str, Any]:
    """Assemble the brief for the trial about to be proposed."""
    recent_trials = list(history)[-recent:] if recent > 0 else []
    return {
        "trial": index,
        "metric": experiment.metric,
        "goal": experiment.goal.value,
        "incumbent": incumbent,
        "protected": list(experiment.protect),
        "budget_seconds": experiment.budget_seconds,
        "counts": _counts(history),
        "history": [_entry(t, experiment) for t in recent_trials],
    }


def environment(brief_path: str, brief: dict[str, Any]) -> dict[str, str]:
    """Variables set for the proposal command.

    The path is the whole brief. The scalars beside it are there so a proposal
    written as a one-line shell command can read the essentials without a JSON
    parser.
    """
    incumbent = brief["incumbent"]
    return {
        "LABLOOP_BRIEF": brief_path,
        "LABLOOP_TRIAL": str(brief["trial"]),
        "LABLOOP_METRIC": brief["metric"],
        "LABLOOP_GOAL": brief["goal"],
        # Empty rather than absent: the first trial has nothing to beat, and
        # an unset variable is easy to mistake for a broken invocation.
        "LABLOOP_INCUMBENT": "" if incumbent is None else repr(incumbent),
    }


def _counts(history: Sequence[Trial]) -> dict[str, int]:
    counts = {outcome.value: 0 for outcome in Outcome}
    for trial in history:
        counts[trial.outcome.value] += 1
    return {name: n for name, n in counts.items() if n}


def _entry(trial: Trial, experiment: Experiment) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "index": trial.index,
        "outcome": trial.outcome.value,
        "metric": trial.metric,
        "why": _why(trial, experiment),
    }
    if trial.commit:
        entry["commit"] = trial.commit
    # Output only where it explains something. A trial that produced a number
    # is explained by the number.
    if trial.outcome in (
        Outcome.FAILED,
        Outcome.TIMED_OUT,
        Outcome.NO_METRIC,
        Outcome.NOT_FINITE,
    ):
        entry["output_tail"] = trial.stdout_tail[-_TAIL:]
    return entry


def _why(trial: Trial, experiment: Experiment) -> str:
    """One sentence on why the trial ended as it did.

    This is the part the proposer cannot reconstruct for itself. "reverted" is
    a label; "tied the incumbent, and a tie is not an improvement" is
    something to act on.
    """
    metric, goal = experiment.metric, experiment.goal
    if trial.outcome is Outcome.KEPT:
        if trial.incumbent is None:
            return f"kept: first measurement of {metric}, nothing to beat yet"
        return f"kept: {metric} {trial.metric:.6g} beat {trial.incumbent:.6g}"

    if trial.outcome is Outcome.REVERTED:
        if trial.metric == trial.incumbent:
            return (
                f"reverted: {metric} {trial.metric:.6g} tied the incumbent, and a "
                "tie is not an improvement"
            )
        direction = "lower" if goal is Goal.MINIMIZE else "higher"
        return (
            f"reverted: {metric} {trial.metric:.6g} did not beat "
            f"{trial.incumbent:.6g}; {direction} is better"
        )

    if trial.outcome is Outcome.TIMED_OUT:
        return f"reverted: exceeded the {experiment.budget_seconds:g}s budget and was killed"

    if trial.outcome is Outcome.NO_METRIC:
        return (
            f"reverted: ran clean but never printed {metric!r}; print it as "
            f"'{metric}=<number>' or as a JSON object on its own line"
        )

    if trial.outcome is Outcome.INTERRUPTED:
        return "not measured: the run was stopped by hand partway through"

    if trial.outcome is Outcome.NO_CHANGE:
        return (
            "not measured: the proposal edited nothing, so the tree is still the "
            "incumbent's. Make a change to the code under study"
        )

    if trial.outcome is Outcome.NOT_FINITE:
        return (
            f"reverted: {trial.note}. The run finished, so this is a diverged "
            "configuration rather than a broken one"
        )

    if trial.outcome is Outcome.HARNESS_CHANGED:
        return (
            f"reverted: {trial.note}. The protected files define the measurement "
            "and must not be edited; change what is being measured instead"
        )

    return f"reverted: {trial.note or 'the command exited non-zero'}"


def dumps(brief: dict[str, Any]) -> str:
    return json.dumps(brief, indent=2, sort_keys=True)
