import pytest


@pytest.mark.parametrize("region_n", range(10))
def test_tax_in_range(rates, region_n):
    assert 0 < rates.tax(f"R{region_n:04d}") < 1


@pytest.mark.parametrize("region_n", range(10))
def test_discount_in_range(rates, region_n):
    assert 0 <= rates.discount(f"R{region_n:04d}") < 1


def test_unknown_region_raises(rates):
    with pytest.raises(KeyError):
        rates.tax("NOPE")


def test_table_covers_all_regions(rates):
    assert len(rates.rates) == 400
