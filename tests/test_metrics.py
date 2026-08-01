import math

import pytest

from labloop import MetricNotFound, extract_metric


def test_reads_key_value_pair():
    assert extract_metric("val_loss = 1.25", "val_loss") == 1.25


def test_reads_colon_form():
    assert extract_metric("step 10 val_loss: 0.5", "val_loss") == 0.5


def test_last_occurrence_wins():
    output = "val_loss=3.0\nval_loss=2.0\nval_loss=1.5\n"
    assert extract_metric(output, "val_loss") == 1.5


def test_scientific_notation_and_negatives():
    assert extract_metric("score = -1.5e-3", "score") == pytest.approx(-0.0015)


def test_reads_json_lines():
    output = '{"step": 1, "val_bpb": 2.0}\n{"step": 2, "val_bpb": 1.75}\n'
    assert extract_metric(output, "val_bpb") == 1.75


def test_ignores_non_json_noise_around_json():
    output = 'loading...\n{"val_bpb": 1.1}\ndone\n'
    assert extract_metric(output, "val_bpb") == 1.1


def test_does_not_match_a_longer_key():
    with pytest.raises(MetricNotFound):
        extract_metric("total_val_loss_scaled = 1.0", "val_loss")


def test_missing_metric_raises():
    with pytest.raises(MetricNotFound):
        extract_metric("nothing here", "val_loss")


def test_reads_nan_because_a_diverged_run_prints_it():
    assert math.isnan(extract_metric("val_loss = nan", "val_loss"))


def test_reads_infinity_in_both_spellings():
    assert extract_metric("val_loss = inf", "val_loss") == math.inf
    assert extract_metric("val_loss = -Infinity", "val_loss") == -math.inf


def test_both_output_formats_agree_about_nan():
    # The JSON path has always accepted NaN; the key=value path used to reject
    # it, so the same event was reported two different ways.
    assert math.isnan(extract_metric("val_loss = nan", "val_loss"))
    assert math.isnan(extract_metric('{"val_loss": NaN}', "val_loss"))


def test_a_word_beginning_with_inf_is_not_a_number():
    with pytest.raises(MetricNotFound):
        extract_metric("status = info", "status")
    with pytest.raises(MetricNotFound):
        extract_metric("units = nanoseconds", "units")
