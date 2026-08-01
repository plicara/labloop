"""Core value types for the experiment loop."""

from __future__ import annotations

import enum
from dataclasses import asdict, dataclass, field
from typing import Any


class Goal(enum.Enum):
    """Whether a lower or higher metric is better."""

    MINIMIZE = "minimize"
    MAXIMIZE = "maximize"

    def is_better(self, candidate: float, incumbent: float, min_delta: float = 0.0) -> bool:
        """Return True if `candidate` beats `incumbent` under this goal.

        Ties are not improvements. A change that does not move the metric is
        reverted, so the loop never accumulates neutral churn.

        `min_delta` widens that from an exact tie to a band: an experiment
        whose metric moves on its own has to be beaten by more than it moves
        on its own, or the loop is only selecting lucky runs.
        """
        if self is Goal.MINIMIZE:
            return candidate < incumbent - min_delta
        return candidate > incumbent + min_delta


class Outcome(enum.Enum):
    """What the loop decided to do with a trial."""

    KEPT = "kept"
    REVERTED = "reverted"
    NO_CHANGE = "no_change"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    NO_METRIC = "no_metric"
    NOT_FINITE = "not_finite"
    HARNESS_CHANGED = "harness_changed"
    INTERRUPTED = "interrupted"


@dataclass(frozen=True)
class Trial:
    """One pass through the loop: a proposed change, run and judged."""

    index: int
    outcome: Outcome
    metric: float | None
    incumbent: float | None
    duration_seconds: float
    commit: str | None = None
    note: str = ""
    stdout_tail: str = ""
    harness: str | None = None
    """Digest of the files that produced this metric, if any were declared.

    Two trials carrying the same digest were measured the same way. None means
    no claim was made, which is not the same as nothing having changed.
    """

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["outcome"] = self.outcome.value
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Trial:
        d = dict(d)
        d["outcome"] = Outcome(d["outcome"])
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})


@dataclass
class Experiment:
    """What to run, how to score it, and how long it may take.

    `run` is a shell command. `propose` is an optional shell command that
    mutates the working tree before each trial — typically an agent
    invocation. With no `propose`, the loop measures the tree as it stands,
    which is how you establish a baseline.

    `protect` names the files that define the measurement — the evaluation
    script, the held-out data, whatever `run` reads to arrive at a number.
    They are digested before and after each proposal, and a trial that moved
    them is recorded as such instead of scored.

    `brief` controls whether each proposal is handed the trial history to read.

    `confirm` re-runs the experiment before keeping a change, and keeps it only
    if it wins twice. Worth the extra run whenever the metric moves on its own
    between identical runs.

    `min_delta` is how much better a metric has to be to count. Set it to the
    spread `labloop noise` reports; the two settings work on different halves
    of the problem, and cost little together.

    `give_up_after` stops the run once that many trials in a row have produced
    no measurement at all — a mistyped proposal command will otherwise fail
    identically for as many trials as you gave it. 0 runs regardless.
    """

    run: str
    metric: str
    goal: Goal = Goal.MINIMIZE
    budget_seconds: float = 300.0
    propose: str | None = None
    env: dict[str, str] = field(default_factory=dict)
    protect: tuple[str, ...] = ()
    brief: bool = True
    confirm: bool = False
    min_delta: float = 0.0
    give_up_after: int = 10
    propose_budget: float | None = None

    @property
    def propose_timeout(self) -> float:
        """How long the proposal may take, falling back to the run's budget.

        An agent thinking and a training run training are different jobs with
        different natural lengths, and one number for both means tightening
        the experiment's budget silently starts killing the agent.
        """
        return self.budget_seconds if self.propose_budget is None else self.propose_budget

    def __post_init__(self) -> None:
        if self.budget_seconds <= 0:
            raise ValueError("budget_seconds must be positive")
        if self.min_delta < 0:
            raise ValueError("min_delta must not be negative")
        if self.give_up_after < 0:
            raise ValueError("give_up_after must not be negative")
        if self.propose_budget is not None and self.propose_budget <= 0:
            raise ValueError("propose_budget must be positive")
        if not self.run.strip():
            raise ValueError("run command must not be empty")
        if isinstance(self.goal, str):
            self.goal = Goal(self.goal)
        if isinstance(self.protect, str):
            # A bare string is iterable, and would otherwise protect one
            # pattern per character.
            self.protect = (self.protect,)
        else:
            self.protect = tuple(self.protect)
