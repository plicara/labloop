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
from typing import Any, cast

from .types import Goal, Outcome, Trial

__all__ = ["Ledger"]


class Ledger:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def append(self, trial: Trial) -> None:
        self._append(trial.to_dict())

    def append_manifest(self, spec: dict[str, Any]) -> None:
        """Record the experiment spec a run started under.

        Manifest lines sit in the same file as trials — the ledger is the
        record of the run, and the spec is part of the record. They are
        invisible to the trial iterator (no `outcome` field, so `from_dict`
        rejects them), which is also what makes them backward compatible:
        an older labloop reading this ledger skips them the same way it
        skips a half-written line.
        """
        self._append({"manifest": 1, **spec})

    def _append(self, record: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, sort_keys=True) + "\n")

    def _raw_records(self) -> Iterator[dict[str, Any]]:
        """Every parseable JSON object in the file, in order.

        Blank and half-written lines are skipped, not fatal: a truncated
        final line is what a hard kill leaves behind.
        """
        if not self.path.exists():
            return
        with self.path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(record, dict):
                    yield record

    def _records(self, kind: str) -> Iterator[dict[str, Any]]:
        """Every non-trial record of one kind, in file order.

        Trials, manifests and forks share the file; each non-trial kind is
        marked by its own key so unknown kinds stay skippable both forward
        and backward.
        """
        for record in self._raw_records():
            if record.get(kind) == 1:
                yield {k: v for k, v in record.items() if k != kind}

    def manifests(self) -> list[dict[str, Any]]:
        """Every spec recorded, oldest first."""
        return list(self._records("manifest"))

    def last_manifest(self) -> dict[str, Any] | None:
        """The most recent spec recorded, or None on a pre-manifest ledger."""
        manifests = self.manifests()
        return manifests[-1] if manifests else None

    def __iter__(self) -> Iterator[Trial]:
        for record in self._raw_records():
            try:
                yield Trial.from_dict(record)
            except (KeyError, ValueError):
                # Not a trial: a manifest, a fork, or a kind from a newer
                # version. All deliberately skippable.
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
        # The fork table is read once, not per trial — a 700-trial ledger
        # would otherwise rescan the whole file 700 times.
        fork_from = self.forks().get(direction) if direction is not None else None
        scored = [t for t in self if _scoreable(t, direction, fork_from)]
        if not scored:
            return None
        pick = min if goal is Goal.MINIMIZE else max
        # _scoreable guarantees a real metric on everything in `scored`.
        return pick(scored, key=lambda t: cast(float, t.metric))

    def directions(self) -> list[str]:
        """Every direction the ledger has seen, forked-but-unstarted included."""
        seen = dict.fromkeys(t.direction for t in self)
        seen.update(dict.fromkeys(self.forks()))
        return list(seen)

    def append_fork(self, direction: str, from_index: int) -> None:
        """Record that `direction` starts from trial `from_index`."""
        self._append({"fork": 1, "direction": direction, "from_index": from_index})

    def forks(self) -> dict[str, int]:
        """direction -> the trial index it forked from."""
        return {r["direction"]: r["from_index"] for r in self._records("fork")}

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


def _scoreable(trial: Trial, direction: str | None, fork_from: int | None) -> bool:
    """Can this trial hold the incumbent for `direction`?"""
    if trial.outcome is not Outcome.KEPT or trial.metric is None:
        return False
    if not math.isfinite(trial.metric):
        return False
    if direction is None:
        return True
    return trial.direction == direction or trial.index == fork_from
