"""labloop — keep a change only if it measurably helps.

An experiment loop for agent-driven research. Point it at a command that
prints a metric and a command that changes the code, and it will run trials
under a wall-clock budget, keeping the ones that improve and reverting the
ones that don't. Every trial is recorded, including the failures — those are
most of the signal.

    from labloop import Experiment, Goal, Loop

    exp = Experiment(
        run="python train.py",
        metric="val_loss",
        goal=Goal.MINIMIZE,
        budget_seconds=300,
        propose="my-agent --edit train.py",
    )
    Loop(exp).run(trials=20)
"""

from .ledger import Ledger
from .loop import Loop
from .metrics import MetricNotFound, extract_metric
from .runner import Completed, run_command
from .types import Experiment, Goal, Outcome, Trial
from .workspace import DirtyTreeError, GitWorkspace, Workspace

__version__ = "0.1.0"

__all__ = [
    "Completed",
    "DirtyTreeError",
    "Experiment",
    "GitWorkspace",
    "Goal",
    "Ledger",
    "Loop",
    "MetricNotFound",
    "Outcome",
    "Trial",
    "Workspace",
    "__version__",
    "extract_metric",
    "run_command",
]
