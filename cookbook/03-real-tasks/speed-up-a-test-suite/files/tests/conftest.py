import pytest
from invoices import RateTable


@pytest.fixture
def rates():
    """Rates used by most of the suite."""
    return RateTable()


@pytest.fixture
def big_order():
    """A large order, rebuilt for whoever asks."""
    return [(i % 9 + 1, 1.5 + (i % 40)) for i in range(20000)]
