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

from .integrity import HarnessMismatchError, NoProtectedFilesError, harness_digest
from .ledger import Ledger
from .lock import LedgerLock, LedgerLockedError
from .loop import Loop, StalledError
from .metrics import MetricNotFound, extract_metric
from .runner import Completed, run_command
from .sandbox import (
    BwrapSandbox,
    Sandbox,
    SandboxError,
    available_backends,
    resolve_sandbox,
    verify_sandbox,
)
from .types import Experiment, Goal, Outcome, Trial, UsageError
from .workspace import (
    DirtyTreeError,
    GitIdentityError,
    GitWorkspace,
    NotAGitRepositoryError,
    Workspace,
)

__version__ = "1.0.0"

__all__ = [
    "Completed",
    "DirtyTreeError",
    "Experiment",
    "GitWorkspace",
    "Goal",
    "GitIdentityError",
    "HarnessMismatchError",
    "Ledger",
    "LedgerLock",
    "LedgerLockedError",
    "Loop",
    "MetricNotFound",
    "NotAGitRepositoryError",
    "NoProtectedFilesError",
    "Outcome",
    "StalledError",
    "Trial",
    "UsageError",
    "Workspace",
    "__version__",
    "available_backends",
    "BwrapSandbox",
    "Sandbox",
    "SandboxError",
    "extract_metric",
    "harness_digest",
    "resolve_sandbox",
    "verify_sandbox",
    "run_command",
]
