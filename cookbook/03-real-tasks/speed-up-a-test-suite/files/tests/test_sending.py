import pytest
from invoices import Invoice, send


def transport_ok(invoice):
    return f"sent {invoice.region}"


def flaky(n_failures):
    calls = {"n": 0}

    def transport(invoice):
        calls["n"] += 1
        if calls["n"] <= n_failures:
            raise OSError("temporary")
        return f"sent {invoice.region} after {calls['n']}"

    return transport


@pytest.fixture
def invoice(rates):
    return Invoice("R0007", [(1, 10.0)])


def test_send_succeeds(invoice):
    assert send(invoice, transport_ok).startswith("sent")


def test_send_retries_once(invoice):
    assert "after 2" in send(invoice, flaky(1))


def test_send_retries_twice(invoice):
    assert "after 3" in send(invoice, flaky(2))


def test_send_gives_up(invoice):
    with pytest.raises(OSError):
        send(invoice, flaky(99))


@pytest.mark.parametrize("region_n", range(6))
def test_send_any_region(rates, region_n):
    inv = Invoice(f"R{region_n:04d}", [(1, 1.0)])
    assert send(inv, transport_ok).startswith("sent")
