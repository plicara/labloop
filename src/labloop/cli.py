"""Command line interface."""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

from . import __version__
from .integrity import HarnessMismatchError, NoProtectedFilesError
from .ledger import Ledger
from .lock import LedgerLockedError
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
    if trial.direction != "main":
        line += f"  [{trial.direction}]"
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
            "--direction",
            default="main",
            help="research direction to advance (see `labloop branch`)",
        )
        p.add_argument(
            "--wait",
            action="store_true",
            help="if another run holds this ledger, queue behind it instead of failing",
        )
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

    init = sub.add_parser("init", help="set a repository up for labloop")
    init.add_argument("--workdir", default=".")

    branch = sub.add_parser(
        "branch", help="fork a new research direction from a kept trial"
    )
    branch.add_argument("name", help="name for the new direction")
    branch.add_argument(
        "--from-trial",
        type=int,
        required=True,
        metavar="N",
        help="kept trial to fork from; its metric becomes the number to beat",
    )
    branch.add_argument("--workdir", default=".")
    branch.add_argument("--ledger", default="labloop.jsonl")

    resume = sub.add_parser(
        "resume", help="continue a run under the spec recorded in the ledger"
    )
    resume.add_argument("--workdir", default=".")
    resume.add_argument("--ledger", default="labloop.jsonl")
    resume.add_argument("--trials", type=_positive, default=1)
    resume.add_argument(
        "--wait",
        action="store_true",
        help="if another run holds this ledger, queue behind it instead of failing",
    )

    log = sub.add_parser("log", help="summarize or query the ledger")
    log.add_argument("--ledger", default="labloop.jsonl")
    log.add_argument("--goal", choices=[g.value for g in Goal], default=Goal.MINIMIZE.value)
    log.add_argument("--metric", default=None, help="metric name, for labelling only")
    log.add_argument(
        "--json",
        action="store_true",
        help="one JSON object per trial, for jq and friends",
    )
    log.add_argument(
        "--outcome",
        choices=[o.value for o in Outcome],
        default=None,
        help="only trials that ended this way",
    )
    log.add_argument("--direction", default=None, help="only this direction's trials")
    log.add_argument(
        "--since-trial", type=int, default=None, metavar="N", help="only trials with index >= N"
    )
    log.add_argument(
        "--compare",
        nargs=2,
        metavar=("A", "B"),
        default=None,
        help="compare two directions' bests; refuses when their harnesses differ",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    try:
        if args.command == "log":
            return _log(args)
        if args.command == "init":
            return _init(args)
        if args.command == "branch":
            return _branch(args)
        if args.command == "resume":
            return _resume(args)
        return _experiment_command(args)
    except (
        DirtyTreeError,
        HarnessMismatchError,
        LedgerLockedError,
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


def _resume(args) -> int:
    """Continue under the manifest, not under whatever was retyped.

    After a crash the alternative is re-typing the invocation and hoping it
    matches; if the metric or the protect set drifted, the guards fire and
    the advice is to start a new ledger — for a run that was fine. The
    manifest is the spec that was actually in force, so resume cannot drift.
    """
    workdir, ledger_path = _paths(args)
    manifests = Ledger(ledger_path).manifests()
    if not manifests:
        raise UsageError(
            f"{ledger_path} has no recorded spec to resume — it predates manifests "
            "or no run has started here. Run `labloop run` with the full arguments once."
        )
    # The last spec that can actually run. A baseline re-measurement after
    # the crash should not cost the user their run spec.
    spec = next((m for m in reversed(manifests) if m.get("propose")), None)
    if spec is None:
        raise UsageError(
            "every recorded spec is a baseline (no propose command); "
            "there is nothing to resume"
        )
    experiment = Experiment.from_spec(spec)

    loop = Loop(
        experiment,
        workdir=workdir,
        ledger=ledger_path,
        reporter=_report,
        wait_for_lock=args.wait,
        direction=spec.get("direction", "main"),
    )
    loop.run(trials=args.trials)

    best = loop.ledger.best(experiment.goal)
    if best and best.metric is not None:
        print(f"\nbest {experiment.metric}: {best.metric:.6g} (trial {best.index})")
    return 0


_EXAMPLE = """\
# labloop example: delete me once you have a real experiment.
# The loop keeps a change only if the printed metric improves.
LR = 0.5
print(f"val_loss = {abs(LR - 0.03):.4f}")
"""

_IGNORES = ("labloop.jsonl", "__pycache__/")


def _init(args) -> int:
    """Set a repository up: gitignore the ledger, show the first commands.

    Writes as little as possible. The one thing every project needs is the
    ledger kept out of git; the example experiment appears only when there is
    no Python file it could shadow, and everything printed at the end is
    copy-paste runnable.
    """
    import subprocess

    workdir = Path(args.workdir)
    if not workdir.is_dir():
        raise UsageError(f"--workdir {args.workdir!r} is not a directory")
    probe = subprocess.run(
        ["git", "rev-parse", "--git-dir"], cwd=workdir, capture_output=True
    )
    if probe.returncode != 0:
        raise UsageError(
            "not a git repository — the loop keeps and reverts through git, so run "
            "`git init` first"
        )

    gitignore = workdir / ".gitignore"
    existing = gitignore.read_text().splitlines() if gitignore.exists() else []
    missing = [entry for entry in _IGNORES if entry not in existing]
    if missing:
        text = "\n".join([*existing, *missing]) + "\n"
        gitignore.write_text(text)
        print(f"added to .gitignore: {', '.join(missing)}")
    else:
        print(".gitignore already covers labloop")

    run_cmd = None
    if not list(workdir.glob("*.py")):
        example = workdir / "labloop-example.py"
        example.write_text(_EXAMPLE)
        run_cmd = f"python {example.name}"
        print(f"wrote {example.name} — a stand-in experiment that prints val_loss")

    print(
        "\nNext, in order:\n"
        "    git add -A && git commit -m 'labloop setup'\n"
        f"    labloop noise --run {run_cmd or '<your command>'!r} --metric val_loss\n"
        f"    labloop baseline --run {run_cmd or '<your command>'!r} --metric val_loss\n"
        "\nThe noise check is not ceremony: keep-or-revert is only as good as the\n"
        "metric holding still."
    )
    return 0


def _paths(args) -> tuple[Path, Path]:
    """Resolve --workdir and --ledger the same way everywhere.

    The ledger is relative to the project, not the shell — three commands
    each doing this by hand is how one of them ends up not doing it.
    """
    workdir = Path(args.workdir)
    if not workdir.is_dir():
        raise UsageError(f"--workdir {args.workdir!r} is not a directory")
    ledger_path = Path(args.ledger)
    if not ledger_path.is_absolute():
        ledger_path = workdir / ledger_path
    return workdir, ledger_path


def _branch(args) -> int:
    """Fork a direction: record it in the ledger, create its git branch.

    The fork point must be a kept trial — it is the incumbent the new
    direction starts from, and a reverted trial's tree no longer exists.
    """
    _, ledger_path = _paths(args)
    ledger = Ledger(ledger_path)
    name = args.name.strip()
    if not name or "/" in name or name in ledger.directions():
        raise UsageError(
            f"direction name {args.name!r} is empty, contains '/', or already exists"
        )
    fork_from = _fork_point(ledger, args.from_trial, ledger_path)
    ledger.append_fork(name, args.from_trial)
    print(
        f"direction {name!r} forks from trial {fork_from.index} "
        f"({fork_from.metric:.6g}, commit {fork_from.commit or 'baseline HEAD'})"
    )
    if fork_from.commit:
        print(
            "\nRun it in its own worktree so directions don't fight over one tree:\n"
            f"    git worktree add ../{name} -b labloop/{name} {fork_from.commit}\n"
            f"    cd ../{name}\n"
            f"    labloop run --direction {name} --ledger {ledger_path.resolve()} ..."
        )
    return 0


def _fork_point(ledger: Ledger, index: int, ledger_path: Path) -> Trial:
    """The trial a new direction starts from — kept, with a real metric."""
    trial = next((t for t in ledger if t.index == index), None)
    if trial is None:
        raise UsageError(f"trial {index} is not in {ledger_path}")
    if trial.outcome is not Outcome.KEPT or trial.metric is None:
        raise UsageError(
            f"trial {index} was {trial.outcome.value}; a direction can only fork "
            "from a kept trial, whose tree exists and whose metric is real"
        )
    return trial


def _experiment_command(args) -> int:
    workdir, _ = _paths(args)

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
    loop = Loop(
        experiment,
        workdir=args.workdir,
        ledger=args.ledger,
        reporter=_report,
        wait_for_lock=getattr(args, "wait", False),
        direction=getattr(args, "direction", "main"),
    )

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


def _compare(ledger: Ledger, args) -> int:
    """Two directions' bests, side by side — only if they measured alike.

    Numbers from different harness digests are not comparable, and a
    comparison that quietly ignored that would be the tool doing the exact
    thing it exists to catch.
    """
    goal, label = Goal(args.goal), args.metric or "best"
    known = ledger.directions()
    for name in args.compare:
        if name not in known:
            raise UsageError(f"direction {name!r} is not in {args.ledger}")
    bests = {name: ledger.best(goal, direction=name) for name in args.compare}

    digests = {b.harness for b in bests.values() if b is not None and b.harness}
    if len(digests) > 1:
        raise UsageError(
            f"directions {args.compare[0]!r} and {args.compare[1]!r} were measured "
            "by different harnesses; their metrics are not comparable"
        )

    for name, best in bests.items():
        if best is None or best.metric is None:
            print(f"{name}: nothing kept yet")
        else:
            print(f"{name}: {label} {best.metric:.6g} (trial {best.index})")
    return 0


def _log(args) -> int:
    ledger = Ledger(args.ledger)
    if args.compare:
        return _compare(ledger, args)

    trials = ledger.trials()
    if not trials:
        print(f"no trials recorded in {args.ledger}")
        return 0
    trials = _filtered(trials, args)
    if not trials:
        print("no trials match the filters")
        return 0

    if args.json:
        for trial in trials:
            print(json.dumps(trial.to_dict(), sort_keys=True))
        return 0

    for trial in trials:
        _report(trial)
    counts = ledger.summary()
    print("\n" + "  ".join(f"{name}={n}" for name, n in counts.items() if n))
    _print_bests(ledger, args)
    return 0


def _filtered(trials: list[Trial], args) -> list[Trial]:
    if args.direction is not None:
        trials = [t for t in trials if t.direction == args.direction]
    if args.outcome is not None:
        trials = [t for t in trials if t.outcome.value == args.outcome]
    if args.since_trial is not None:
        trials = [t for t in trials if t.index >= args.since_trial]
    return trials


def _print_bests(ledger: Ledger, args) -> None:
    label = args.metric or "best"
    directions = ledger.directions()
    if len(directions) <= 1:
        best = ledger.best(Goal(args.goal))
        if best and best.metric is not None:
            # The ledger records metric values, not the name they were read
            # under.
            print(f"{label}: {best.metric:.6g} (trial {best.index})")
        return

    # More than one line of inquiry: report each direction's own best,
    # because comparing them is exactly what the reader is here to do.
    forks = ledger.forks()
    for direction in directions:
        best = ledger.best(Goal(args.goal), direction=direction)
        forked = f" (forked from trial {forks[direction]})" if direction in forks else ""
        if best and best.metric is not None:
            print(f"{direction}: best {label} {best.metric:.6g} (trial {best.index}){forked}")
        else:
            print(f"{direction}: nothing kept yet{forked}")


if __name__ == "__main__":
    raise SystemExit(main())
