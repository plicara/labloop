"""The append-only trial record.

The ledger is the source of truth for the incumbent and the artifact the whole
tool exists to produce, so what it does with a half-written line, an unknown
outcome, or a metric nothing can be compared against all matter.
"""

from __future__ import annotations

import json

import pytest

from labloop import Goal, Ledger, Outcome, Trial


def trial(index, outcome=Outcome.KEPT, metric=1.0, **kw):
    return Trial(
        index=index, outcome=outcome, metric=metric, incumbent=None, duration_seconds=1.0, **kw
    )


def test_an_absent_ledger_reads_as_empty(tmp_path):
    ledger = Ledger(tmp_path / "nothing.jsonl")
    assert ledger.trials() == []
    assert ledger.next_index() == 0
    assert ledger.best(Goal.MINIMIZE) is None
    assert not any(ledger.summary().values())


def test_appending_creates_missing_directories(tmp_path):
    ledger = Ledger(tmp_path / "deep" / "nested" / "l.jsonl")
    ledger.append(trial(0))
    assert ledger.trials()[0].index == 0


def test_a_trial_survives_the_round_trip(tmp_path):
    ledger = Ledger(tmp_path / "l.jsonl")
    original = trial(
        3, Outcome.REVERTED, metric=2.5, commit="abc1234", note="why", stdout_tail="tail"
    )
    ledger.append(original)
    assert ledger.trials() == [original]


def test_one_line_per_trial(tmp_path):
    ledger = Ledger(tmp_path / "l.jsonl")
    for i in range(3):
        ledger.append(trial(i))
    assert len((tmp_path / "l.jsonl").read_text().strip().splitlines()) == 3


def test_a_half_written_final_line_is_skipped_not_fatal(tmp_path):
    # What a hard kill during a write leaves behind. The rest of the record
    # has to stay readable, or one bad exit costs the whole run.
    path = tmp_path / "l.jsonl"
    ledger = Ledger(path)
    ledger.append(trial(0, metric=2.0))
    ledger.append(trial(1, metric=1.0))
    with path.open("a") as fh:
        fh.write('{"index": 2, "outcome": "ke')

    assert [t.index for t in ledger.trials()] == [0, 1]
    assert ledger.next_index() == 2


def test_blank_lines_are_ignored(tmp_path):
    path = tmp_path / "l.jsonl"
    Ledger(path).append(trial(0))
    with path.open("a") as fh:
        fh.write("\n\n")
    assert len(Ledger(path).trials()) == 1


def test_an_outcome_from_a_newer_version_is_skipped(tmp_path):
    path = tmp_path / "l.jsonl"
    Ledger(path).append(trial(0, metric=2.0))
    with path.open("a") as fh:
        fh.write(json.dumps({"index": 1, "outcome": "invented_later", "metric": 1.0}) + "\n")

    assert [t.index for t in Ledger(path).trials()] == [0]


def test_unknown_fields_are_ignored_rather_than_fatal(tmp_path):
    path = tmp_path / "l.jsonl"
    with path.open("w") as fh:
        fh.write(
            json.dumps(
                {
                    "index": 0,
                    "outcome": "kept",
                    "metric": 1.0,
                    "incumbent": None,
                    "duration_seconds": 1.0,
                    "invented_later": "ignored",
                }
            )
            + "\n"
        )
    assert Ledger(path).trials()[0].metric == 1.0


def test_best_ignores_trials_that_were_not_kept(tmp_path):
    ledger = Ledger(tmp_path / "l.jsonl")
    ledger.append(trial(0, Outcome.KEPT, metric=2.0))
    ledger.append(trial(1, Outcome.REVERTED, metric=0.1))
    assert ledger.best(Goal.MINIMIZE).metric == 2.0, "a reverted score is not the incumbent"


def test_best_follows_the_goal(tmp_path):
    ledger = Ledger(tmp_path / "l.jsonl")
    ledger.append(trial(0, metric=2.0))
    ledger.append(trial(1, metric=5.0))
    assert ledger.best(Goal.MINIMIZE).metric == 2.0
    assert ledger.best(Goal.MAXIMIZE).metric == 5.0


def test_best_skips_a_metric_nothing_compares_to(tmp_path):
    # Nothing is better than nan, so an incumbent holding one reverts every
    # later trial forever. Ledgers written before the loop refused to keep one
    # still exist.
    path = tmp_path / "l.jsonl"
    with path.open("w") as fh:
        fh.write(
            '{"index": 0, "outcome": "kept", "metric": NaN, "incumbent": null, '
            '"duration_seconds": 1.0}\n'
            '{"index": 1, "outcome": "kept", "metric": 3.0, "incumbent": null, '
            '"duration_seconds": 1.0}\n'
        )
    assert Ledger(path).best(Goal.MINIMIZE).metric == 3.0


def test_next_index_follows_the_highest_seen(tmp_path):
    ledger = Ledger(tmp_path / "l.jsonl")
    ledger.append(trial(0))
    ledger.append(trial(7))
    ledger.append(trial(3))
    assert ledger.next_index() == 8, "indices must never be reused, even out of order"


def test_summary_counts_every_outcome(tmp_path):
    ledger = Ledger(tmp_path / "l.jsonl")
    ledger.append(trial(0, Outcome.KEPT))
    ledger.append(trial(1, Outcome.REVERTED))
    ledger.append(trial(2, Outcome.REVERTED))
    ledger.append(trial(3, Outcome.HARNESS_CHANGED, metric=None))

    counts = ledger.summary()
    assert counts["kept"] == 1
    assert counts["reverted"] == 2
    assert counts["harness_changed"] == 1
    assert counts["timed_out"] == 0
    assert set(counts) == {o.value for o in Outcome}, "every outcome has a slot"


def test_it_is_readable_while_a_run_is_still_going(tmp_path):
    ledger = Ledger(tmp_path / "l.jsonl")
    ledger.append(trial(0, metric=2.0))
    assert len(ledger.trials()) == 1
    ledger.append(trial(1, metric=1.0))
    assert len(ledger.trials()) == 2, "the same object re-reads rather than caching"


@pytest.mark.parametrize("goal", list(Goal))
def test_best_is_none_when_nothing_was_kept(tmp_path, goal):
    ledger = Ledger(tmp_path / "l.jsonl")
    ledger.append(trial(0, Outcome.FAILED, metric=None))
    assert ledger.best(goal) is None
