"""A small invoicing library. The agent does not edit this -- only its tests."""

import time


class RateTable:
    """Tax and discount rates by region. Expensive to construct, cheap to use."""

    def __init__(self, regions=400):
        self.rates = {}
        for i in range(regions):
            region = f"R{i:04d}"
            # Stands in for the real thing: parsing a rate file, or a lookup
            # over a schedule that has to be built before anything can use it.
            self.rates[region] = {
                "tax": 0.05 + (i % 17) / 100,
                "discount": (i % 7) / 100,
            }
        time.sleep(0.15)  # the I/O this stands in for

    def tax(self, region):
        return self.rates[region]["tax"]

    def discount(self, region):
        return self.rates[region]["discount"]


class Invoice:
    def __init__(self, region, lines):
        self.region = region
        self.lines = list(lines)

    def subtotal(self):
        return sum(qty * price for qty, price in self.lines)

    def total(self, rates):
        sub = self.subtotal()
        sub -= sub * rates.discount(self.region)
        return round(sub * (1 + rates.tax(self.region)), 2)


def send(invoice, transport, retries=3, backoff=0.2):
    """Send an invoice, retrying on failure with a backoff."""
    last = None
    for attempt in range(retries):
        try:
            return transport(invoice)
        except OSError as exc:
            last = exc
            time.sleep(backoff * (2**attempt))
    raise last
