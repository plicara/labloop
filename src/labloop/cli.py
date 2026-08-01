"""Command line interface."""

from __future__ import annotations

import argparse
import sys

from . import __version__
from .integrity import HarnessMismatchError, NoProtectedFilesError
from .ledger import Ledger
from .loop import Loop
from .types import Experiment, Goal, Outcome, Trial
from .workspace import DirtyTreeError

_MARKS = {
    Outcome.KEPT: "+",
    Outcome.REVERTED: "-",
    Outcome.FAILED: "!",
    Outcome.TIMED_OUT: "T",
    Outcome.NO_METRIC: "?",
    Outcome.HARNESS_CHANGED: "H",
}


def _report(trial: Trial) -> None:
    metric = f"{trial.metric:.6g}" if trial.metric is not None else "--"
    line = (
        f"[{_MARKS[trial.outcome]}] trial {trial.index:>3}  "
        f"{metric:>12}  {trial.duration_seconds:6.1f}s"
    )
    if trial.commit:
        line += f"  {trial.commit}"
    if trial.note:
        line += f"  ({trial.note})"
    print(line, flush=True)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="labloop",
        description="Keep a change only if it measurably helps.",
    )
    parser.add_argument("--version", action="version", version=f"labloop {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    def add_common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--run", required=True, help="command that runs one experiment")
        p.add_argument("--metric", required=True, help="metric key to read from output")
        p.add_argument("--goal", choices=[g.value for g in Goal], default=Goal.MINIMIZE.value)
        p.add_argument("--budget", type=float, default=300.0, help="seconds per command")
        p.add_argument("--workdir", default=".")
        p.add_argument("--ledger", default="labloop.jsonl")
        p.add_argument(
            "--protect",
            action="append",
            default=None,
            metavar="PATH",
            help=(
                "file, directory, or glob that defines the measurement; a trial "
                "that changes it is recorded, not scored (repeatable)"
            ),
        )

    baseline = sub.add_parser("baseline", help="measure the tree as it stands")
    add_common(baseline)

    run = sub.add_parser("run", help="run proposal-and-judge cycles")
    add_common(run)
    run.add_argument("--propose", required=True, help="command that changes the code")
    run.add_argument("--trials", type=int, default=1)

    log = sub.add_parser("log", help="summarize the ledger")
    log.add_argument("--ledger", default="labloop.jsonl")
    log.add_argument("--goal", choices=[g.value for g in Goal], default=Goal.MINIMIZE.value)
    log.add_argument("--metric", default=None, help="metric name, for labelling only")

    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    if args.command == "log":
        return _log(args)

    experiment = Experiment(
        run=args.run,
        metric=args.metric,
        goal=Goal(args.goal),
        budget_seconds=args.budget,
        propose=getattr(args, "propose", None),
        protect=tuple(args.protect or ()),
    )
    loop = Loop(experiment, workdir=args.workdir, ledger=args.ledger, reporter=_report)

    try:
        if args.command == "baseline":
            loop.baseline()
        else:
            loop.run(trials=args.trials)
    except (DirtyTreeError, HarnessMismatchError, NoProtectedFilesError) as exc:
        print(f"labloop: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\nlabloop: interrupted", file=sys.stderr)
        return 130

    best = loop.ledger.best(experiment.goal)
    if best and best.metric is not None:
        print(f"\nbest {experiment.metric}: {best.metric:.6g} (trial {best.index})")
    return 0


def _log(args) -> int:
    ledger = Ledger(args.ledger)
    trials = ledger.trials()
    if not trials:
        print(f"no trials recorded in {args.ledger}")
        return 0

    for trial in trials:
        _report(trial)

    counts = ledger.summary()
    print("\n" + "  ".join(f"{name}={n}" for name, n in counts.items() if n))
    best = ledger.best(Goal(args.goal))
    if best and best.metric is not None:
        # The ledger records metric values, not the name they were read under.
        label = args.metric or "best"
        print(f"{label}: {best.metric:.6g} (trial {best.index})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
