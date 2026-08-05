import pytest
from invoices import Invoice


@pytest.mark.parametrize("region_n", range(12))
def test_total_is_positive(rates, region_n):
    inv = Invoice(f"R{region_n:04d}", [(2, 10.0), (1, 5.5)])
    assert inv.total(rates) > 0


@pytest.mark.parametrize("qty,price", [(1, 1.0), (3, 2.5), (10, 0.99), (7, 12.25)])
def test_subtotal_multiplies(rates, qty, price):
    inv = Invoice("R0001", [(qty, price)])
    assert inv.subtotal() == pytest.approx(qty * price)
    assert inv.total(rates) > 0


def test_discount_reduces_total(rates):
    lines = [(5, 20.0)]
    plain = Invoice("R0000", lines).total(rates)
    discounted = Invoice("R0003", lines).total(rates)
    assert discounted != plain


def test_empty_invoice_totals_zero(rates):
    assert Invoice("R0002", []).total(rates) == 0


def test_large_order_subtotal(rates, big_order):
    inv = Invoice("R0005", big_order)
    assert inv.subtotal() > 0
    assert inv.total(rates) > 0


def test_large_order_is_stable(rates, big_order):
    a = Invoice("R0006", big_order).total(rates)
    b = Invoice("R0006", big_order).total(rates)
    assert a == b


def test_rounding_to_two_places(rates):
    total = Invoice("R0004", [(3, 1.0 / 3)]).total(rates)
    assert round(total, 2) == total
