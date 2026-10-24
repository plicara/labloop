"""Core value types for the experiment loop."""

from __future__ import annotations

import enum
import os
from dataclasses import asdict, dataclass, field
from typing import Any


class UsageError(ValueError):
    """What was asked for cannot work, and the fix is in the request.

    Separate from ValueError so the command line can report bad input as bad
    input while a ValueError raised anywhere else still surfaces as the bug it
    is. It subclasses ValueError so callers of the Python API can keep
    catching that.
    """


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
    direction: str = "main"
    """Which research direction this trial belongs to.

    Directions are parallel lines of inquiry over one shared ledger, each
    advancing its own incumbent. Every pre-existing ledger is one direction
    named main, which is also the default when nobody asks for more.
    """
    change: list[dict[str, Any]] | None = None
    """What the proposal changed, as labloop read it from git before measuring.

    One entry per file: `path`, `status`, `added` and `removed` line counts
    (None for binary), and `where`, the enclosing definitions git names in its
    hunk headers. Derived from the tree, not from anything the proposer said,
    so it can go in the brief: a reverted idea is otherwise invisible to the
    next attempt, which then proposes it again. None when no change reached
    measurement.
    """
    confirmation: float | None = None
    """The confirmation run's metric, when `confirm` asked for one."""
    proposal_tail: str = ""
    """The end of the proposal command's own output, for the human reading the
    ledger. Never put in the brief: it is the proposer's free text, and the
    brief is labloop's account, not a channel between attempts."""
    remeasured: float | None = None
    """The incumbent's tree measured again just before this trial's proposal,
    under `paired`. `incumbent` stays the number the ledger holds."""

    @property
    def bar(self) -> float | None:
        """The number this trial had to beat: re-measured when paired."""
        return self.remeasured if self.remeasured is not None else self.incumbent

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
    They are digested before and after each proposal and after each completed
    measurement, including baselines, confirmation, and noise calibration.
    A changed protected set invalidates the metric; matching snapshots cannot
    detect a transient change restored before the command exits.

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
    strict_metric: bool = False
    """Fail a trial whose output repeats the metric key.

    Off by default: an experiment that streams a metric (a loss per epoch)
    wants last-wins, and that is the documented contract. On, one repeat is
    enough to fail the trial — the loop cannot tell a line printed *after*
    the real value (by the code under measurement, which may be forging it)
    from an honest progress line, so it stops guessing. Recorded in the
    manifest.
    """
    guard_imports: bool = False
    """Treat a planted stdlib shadow as tampering, not a proposal.

    Off by default. On, a new untracked file whose name is a Python
    standard-library module name — ``json.py``, ``hashlib/`` — anywhere in
    the worktree during a phase fails it: planted where the run's Python
    imports from, it replaces the standard library for the measurement
    itself. Python puts the run script's directory on `sys.path` unprompted.
    A stdlib-named file tracked since the baseline is vendored source the
    proposer may edit, so only *new* untracked paths count. A legitimate
    new module named like a stdlib one fails loudly — rename it or turn the
    guard off. Recorded in the manifest.
    """
    give_up_after: int = 10
    paired: bool = False
    """Re-measure the incumbent's tree before each proposal and judge the
    candidate against that, not against the number in the ledger.

    The ledger's number was measured earlier, sometimes hours earlier, and a
    machine that speeds up or slows down in between turns drift into progress
    or regression. Dogfooding labloop on itself, the ledger credited one run
    with four times the gain an interleaved check found. Paired, the two
    numbers being compared are minutes apart. Costs one run per trial.
    """
    propose_budget: float | None = None
    label: str | None = None
    """Who or what proposed these trials, e.g. a model name.

    Recorded in the manifest so the ledger says which setup produced each
    trial. Free text, not identity: it claims nothing and proves nothing.
    """
    sandbox: str = field(default_factory=lambda: os.environ.get("LABLOOP_SANDBOX", "auto"))
    """OS isolation for the propose step: `none`, `auto`, or `bwrap`.

    Defaults to `auto` (overridable with the `LABLOOP_SANDBOX` environment
    variable), so the library is confined by default just like the CLI — a
    `Loop(Experiment(...))` built with no arguments must not silently run the
    proposer unconfined. bubblewrap is the only backend; `auto` picks it and
    refuses when it cannot run. Recorded in the manifest. `none` restores the
    pre-sandbox behaviour.
    """
    sandbox_network: bool = False
    """Whether the sandboxed propose step may reach the network. Off by default.

    A proposer that calls a hosted model needs this on; a local or scripted one
    does not. Off blocks IP traffic; filesystem Unix sockets remain reachable.
    """
    sandbox_writes: tuple[str, ...] = ()
    """Out-of-tree directories the sandboxed propose step may write to.

    Empty by default: the proposer can write only the worktree. A proposer that
    must leave evidence (transcripts, reasoning) needs one writable dir outside
    both the worktree and the digested measurement — inside either, it would be
    committed, reverted, or digested with the trial instead of surviving it.
    Each must exist beneath ~/.local/state/labloop/evidence; the root itself
    and redirects outside it are refused. Recorded in the manifest.
    """

    @property
    def propose_timeout(self) -> float:
        """How long the proposal may take, falling back to the run's budget.

        An agent thinking and a training run training are different jobs with
        different natural lengths, and one number for both means tightening
        the experiment's budget silently starts killing the agent.
        """
        return self.budget_seconds if self.propose_budget is None else self.propose_budget

    def spec(self) -> dict[str, Any]:
        """The experiment as a manifest record.

        `env` is deliberately absent: it is where credentials live, and the
        ledger is a file that gets shared. A resumed run takes its
        environment from the shell it resumes in, like every other run.
        """
        return {
            "run": self.run,
            "metric": self.metric,
            "goal": self.goal.value,
            "budget_seconds": self.budget_seconds,
            "propose": self.propose,
            "protect": list(self.protect),
            "brief": self.brief,
            "confirm": self.confirm,
            "min_delta": self.min_delta,
            "strict_metric": self.strict_metric,
            "guard_imports": self.guard_imports,
            "give_up_after": self.give_up_after,
            "paired": self.paired,
            "propose_budget": self.propose_budget,
            "label": self.label,
            "sandbox": self.sandbox,
            "sandbox_network": self.sandbox_network,
            "sandbox_writes": list(self.sandbox_writes),
        }

    @classmethod
    def from_spec(cls, spec: dict[str, Any]) -> Experiment:
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in spec.items() if k in known})

    def __post_init__(self) -> None:
        if self.budget_seconds <= 0:
            raise UsageError("budget_seconds must be positive")
        if self.min_delta < 0:
            raise UsageError("min_delta must not be negative")
        if self.give_up_after < 0:
            raise UsageError("give_up_after must not be negative")
        if self.propose_budget is not None and self.propose_budget <= 0:
            raise UsageError("propose_budget must be positive")
        if not self.run.strip():
            raise UsageError("run command must not be empty")
        if self.label is not None:
            if not isinstance(self.label, str) or not self.label.strip():
                raise UsageError("label must be a non-empty string")
            if len(self.label) > 128:
                raise UsageError("label must be at most 128 characters")
            if "\n" in self.label or "\r" in self.label:
                raise UsageError("label must be a single line")
            self.label = self.label.strip()
        if self.sandbox not in ("none", "auto", "bwrap"):
            raise UsageError("sandbox must be one of: none, auto, bwrap")
        if isinstance(self.goal, str):
            self.goal = Goal(self.goal)
        if isinstance(self.protect, str):
            # A bare string is iterable, and would otherwise protect one
            # pattern per character.
            self.protect = (self.protect,)
        else:
            self.protect = tuple(self.protect)
        if isinstance(self.sandbox_writes, str):
            self.sandbox_writes = (self.sandbox_writes,)
        else:
            self.sandbox_writes = tuple(self.sandbox_writes)
