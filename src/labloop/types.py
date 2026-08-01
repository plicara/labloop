"""Core value types for the experiment loop."""

from __future__ import annotations

import enum
from dataclasses import asdict, dataclass, field
from typing import Any


class Goal(enum.Enum):
    """Whether a lower or higher metric is better."""

    MINIMIZE = "minimize"
    MAXIMIZE = "maximize"

    def is_better(self, candidate: float, incumbent: float) -> bool:
        """Return True if `candidate` beats `incumbent` under this goal.

        Ties are not improvements. A change that does not move the metric is
        reverted, so the loop never accumulates neutral churn.
        """
        if self is Goal.MINIMIZE:
            return candidate < incumbent
        return candidate > incumbent


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

    @property
    def is_improvement(self) -> bool:
        return self is Outcome.KEPT


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
    """

    run: str
    metric: str
    goal: Goal = Goal.MINIMIZE
    budget_seconds: float = 300.0
    propose: str | None = None
    env: dict[str, str] = field(default_factory=dict)
    protect: tuple[str, ...] = ()
    brief: bool = True

    def __post_init__(self) -> None:
        if self.budget_seconds <= 0:
            raise ValueError("budget_seconds must be positive")
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
