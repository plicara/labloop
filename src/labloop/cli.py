"""Command line interface."""

from __future__ import annotations

import argparse
import statistics
import sys
from pathlib import Path

from . import __version__
from .integrity import HarnessMismatchError, NoProtectedFilesError
from .ledger import Ledger
from .loop import Loop, StalledError
from .types import Experiment, Goal, Outcome, Trial, UsageError
from .workspace import DirtyTreeError

_MARKS = {
    Outcome.KEPT: "+",
    Outcome.REVERTED: "-",
    Outcome.NO_CHANGE: "=",
    Outcome.FAILED: "!",
    Outcome.TIMED_OUT: "T",
    Outcome.NO_METRIC: "?",
    Outcome.NOT_FINITE: "~",
    Outcome.HARNESS_CHANGED: "H",
    Outcome.INTERRUPTED: "^",
}


# Outcomes where the output says something the outcome alone doesn't. A
# mistyped propose command otherwise repeats "propose command failed" for
# every trial in the run, with the actual error only in the ledger.
_DIAGNOSE = (Outcome.FAILED, Outcome.TIMED_OUT, Outcome.NO_METRIC)


def _last_line(text: str, limit: int = 100) -> str:
    for line in reversed(text.strip().splitlines()):
        line = line.strip()
        if not line:
            continue
        if len(line) <= limit:
            return line
        # Both ends, not the first N characters. An error names the problem at
        # the front and the thing it happened to at the back; the long path in
        # the middle is the part worth losing.
        half = (limit - 1) // 2
        return f"{line[:half]}…{line[-half:]}"
    return ""


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

    if trial.outcome in _DIAGNOSE and (reason := _last_line(trial.stdout_tail)):
        print(f"      {reason}", flush=True)


def _positive(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError(f"must be 1 or more, got {number}")
    return number


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
        p.add_argument(
            "--min-delta",
            type=float,
            default=0.0,
            help="how much better the metric must be to count; use the spread from `labloop noise`",
        )
        p.add_argument(
            "--budget", type=float, default=300.0, help="seconds the run command may take"
        )
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
    run.add_argument("--trials", type=_positive, default=1)
    run.add_argument(
        "--propose-budget",
        type=float,
        default=None,
        metavar="SECONDS",
        help="seconds the propose command may take (default: same as --budget)",
    )
    run.add_argument(
        "--give-up-after",
        type=int,
        default=10,
        metavar="N",
        help="stop after N trials in a row produce no metric (0 to run regardless)",
    )
    run.add_argument(
        "--confirm",
        action="store_true",
        help="re-run before keeping a change, and keep it only if it wins twice",
    )
    run.add_argument(
        "--no-brief",
        dest="brief",
        action="store_false",
        help="don't hand the proposal the trial history via $LABLOOP_BRIEF",
    )

    noise = sub.add_parser(
        "noise", help="run the experiment repeatedly, unchanged, to measure its spread"
    )
    add_common(noise)
    noise.add_argument(
        "--repeat", type=_positive, default=5, help="how many runs (default 5)"
    )

    log = sub.add_parser("log", help="summarize the ledger")
    log.add_argument("--ledger", default="labloop.jsonl")
    log.add_argument("--goal", choices=[g.value for g in Goal], default=Goal.MINIMIZE.value)
    log.add_argument("--metric", default=None, help="metric name, for labelling only")

    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    if args.command == "log":
        return _log(args)

    try:
        return _experiment_command(args)
    except (
        DirtyTreeError,
        HarnessMismatchError,
        NoProtectedFilesError,
        StalledError,
        UsageError,
    ) as exc:
        # Bad input, not a bug. A traceback here reads as the tool breaking
        # when the user has only mistyped something.
        print(f"labloop: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print(
            "\nlabloop: interrupted. The working tree may hold a change that was "
            "never judged — discard it with `git reset --hard && git clean -fd` "
            "before starting again.",
            file=sys.stderr,
        )
        return 130


def _experiment_command(args) -> int:
    workdir = Path(args.workdir)
    if not workdir.is_dir():
        raise UsageError(f"--workdir {args.workdir!r} is not a directory")

    experiment = Experiment(
        run=args.run,
        metric=args.metric,
        goal=Goal(args.goal),
        budget_seconds=args.budget,
        propose=getattr(args, "propose", None),
        protect=tuple(args.protect or ()),
        brief=getattr(args, "brief", True),
        confirm=getattr(args, "confirm", False),
        min_delta=args.min_delta,
        give_up_after=getattr(args, "give_up_after", 0),
        propose_budget=getattr(args, "propose_budget", None),
    )
    loop = Loop(experiment, workdir=args.workdir, ledger=args.ledger, reporter=_report)

    if args.command == "noise":
        return _noise(loop, args.repeat)
    if args.command == "baseline":
        loop.baseline()
    else:
        loop.run(trials=args.trials)

    best = loop.ledger.best(experiment.goal)
    if best and best.metric is not None:
        print(f"\nbest {experiment.metric}: {best.metric:.6g} (trial {best.index})")
    return 0


def _noise(loop: Loop, repeats: int) -> int:
    values = loop.measure_noise(repeats)
    for i, value in enumerate(values):
        print(f"    run {i}  {value:.6g}", flush=True)

    low, high = min(values), max(values)
    spread = high - low
    metric = loop.experiment.metric
    print(f"\n{metric}: {low:.6g} to {high:.6g} over {len(values)} identical runs")

    if spread == 0:
        print("spread: none — every run agreed, so any change in the metric is the change")
        return 0

    # Both, because they say different things. The range is what was actually
    # observed and is what --min-delta should clear, but it widens with every
    # extra run; the standard deviation does not, so it is the one to compare
    # across experiments or against a later measurement.
    deviation = statistics.stdev(values)
    print(f"spread: {spread:.6g}   standard deviation: {deviation:.6g}")
    print(
        f"\nAn improvement smaller than {spread:.6g} is a difference this experiment has "
        f"already produced without any change to the code, so the loop would be "
        f"selecting lucky runs. Best is to remove the variance — fix the seed, average "
        f"more, hold the data still. Failing that:\n"
        f"\n    labloop run --min-delta {spread:.6g} --confirm ...\n"
    )
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
