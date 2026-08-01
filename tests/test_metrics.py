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
