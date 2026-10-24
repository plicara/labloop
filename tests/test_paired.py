"""Paired measurement: judge a candidate against its incumbent measured now.

Found by dogfooding: the ledger's incumbent was measured up to an hour before
the candidate it judged, and slow drift on the machine turned into credited
gains four times the size an interleaved check found.
"""

from __future__ import annotations

from labloop import Experiment, Outcome, Trial


def test_a_trial_is_judged_against_its_remeasured_incumbent_when_there_is_one():
    plain = Trial(index=1, outcome=Outcome.REVERTED, metric=2.0, incumbent=1.0,
                  duration_seconds=1.0)
    paired = Trial(index=1, outcome=Outcome.REVERTED, metric=2.0, incumbent=1.0,
                   duration_seconds=1.0, remeasured=1.7)
    assert plain.bar == 1.0
    assert paired.bar == 1.7


def test_remeasured_survives_the_ledger_round_trip():
    trial = Trial(index=1, outcome=Outcome.KEPT, metric=1.5, incumbent=2.0,
                  duration_seconds=1.0, remeasured=1.8)
    restored = Trial.from_dict(trial.to_dict())
    assert restored == trial
    assert "bar" not in trial.to_dict(), "derived, so not stored"


def test_paired_is_off_by_default_and_recorded_in_the_manifest():
    assert Experiment(run="x", metric="m").paired is False
    spec = Experiment(run="x", metric="m", paired=True).spec()
    assert spec["paired"] is True
    assert Experiment.from_spec(spec).paired is True
