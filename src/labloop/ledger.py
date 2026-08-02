"""Append-only record of every trial the loop has run.

The ledger is the point of the tool. A run that improves a metric but leaves
no account of what was tried is not research, and `git log` only records the
changes that were kept — the reverted ones are most of the information.

Stored as JSON Lines so a partial run is still readable and an interrupted
write costs at most one trial.
"""

from __future__ import annotations

import json
import math
from collections.abc import Iterator
from pathlib import Path

from .types import Goal, Outcome, Trial

__all__ = ["Ledger"]


class Ledger:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def append(self, trial: Trial) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(trial.to_dict(), sort_keys=True) + "\n")

    def append_manifest(self, spec: dict) -> None:
        """Record the experiment spec a run started under.

        Manifest lines sit in the same file as trials — the ledger is the
        record of the run, and the spec is part of the record. They are
        invisible to the trial iterator (no `outcome` field, so `from_dict`
        rejects them), which is also what makes them backward compatible:
        an older labloop reading this ledger skips them the same way it
        skips a half-written line.
        """
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"manifest": 1, **spec}, sort_keys=True) + "\n")

    def last_manifest(self) -> dict | None:
        """The most recent spec recorded, or None on a pre-manifest ledger."""
        found = None
        if not self.path.exists():
            return None
        with self.path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(record, dict) and record.get("manifest") == 1:
                    found = {k: v for k, v in record.items() if k != "manifest"}
        return found

    def __iter__(self) -> Iterator[Trial]:
        if not self.path.exists():
            return
        with self.path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield Trial.from_dict(json.loads(line))
                except (json.JSONDecodeError, KeyError, ValueError):
                    # A truncated final line is expected after a hard kill.
                    continue

    def trials(self) -> list[Trial]:
        return list(self)

    def best(self, goal: Goal, direction: str | None = None) -> Trial | None:
        """Return the kept trial with the strongest metric, if any.

        With `direction`, only that direction's trials compete — plus its
        fork point, if it has one: a direction forked from trial N starts
        with N's metric as the number to beat, or the fork would begin by
        "improving on" nothing and keep a change worse than its parent.

        Non-finite metrics are skipped. Nothing compares better than nan, so
        an incumbent holding one would revert every later trial forever — and
        ledgers written before the loop refused to keep such a value still
        exist.
        """
        scored = [
            t
            for t in self
            if t.outcome is Outcome.KEPT and t.metric is not None and math.isfinite(t.metric)
        ]
        if direction is not None:
            fork_from = self.forks().get(direction)
            scored = [
                t
                for t in scored
                if t.direction == direction or (fork_from is not None and t.index == fork_from)
            ]
        if not scored:
            return None
        pick = min if goal is Goal.MINIMIZE else max
        return pick(scored, key=lambda t: t.metric)  # type: ignore[arg-type]

    def directions(self) -> list[str]:
        """Every direction the ledger has seen, forked-but-unstarted included."""
        seen = dict.fromkeys(t.direction for t in self)
        seen.update(dict.fromkeys(self.forks()))
        return list(seen)

    def append_fork(self, direction: str, from_index: int) -> None:
        """Record that `direction` starts from trial `from_index`."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(
                json.dumps(
                    {"fork": 1, "direction": direction, "from_index": from_index},
                    sort_keys=True,
                )
                + "\n"
            )

    def forks(self) -> dict[str, int]:
        """direction -> the trial index it forked from."""
        found: dict[str, int] = {}
        if not self.path.exists():
            return found
        with self.path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(record, dict) and record.get("fork") == 1:
                    found[record["direction"]] = record["from_index"]
        return found

    def next_index(self) -> int:
        last = -1
        for trial in self:
            last = max(last, trial.index)
        return last + 1

    def summary(self) -> dict[str, int]:
        counts = {outcome.value: 0 for outcome in Outcome}
        for trial in self:
            counts[trial.outcome.value] += 1
        return counts
