"""Pulling a single number out of an experiment's output.

Two formats are supported, tried in this order:

1. A ``key=value`` or ``key: value`` pair anywhere in the output.
2. A JSON object on its own line containing ``key``.

The *last* occurrence wins. Training loops print the same key every epoch, and
the final one is the result.
"""

from __future__ import annotations

import json
import re

__all__ = ["extract_metric", "MetricNotFound"]


class MetricNotFound(LookupError):
    """The named metric did not appear in the output."""


_NUMBER = r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?"


def extract_metric(output: str, key: str) -> float:
    """Return the last value of `key` in `output`.

    Raises MetricNotFound if the key never appears, rather than returning a
    sentinel. A missing metric is a broken experiment, not a bad score, and
    the loop treats the two differently.
    """
    value = _from_key_value(output, key)
    if value is not None:
        return value

    value = _from_json_lines(output, key)
    if value is not None:
        return value

    raise MetricNotFound(f"metric {key!r} not found in output")


def _from_key_value(output: str, key: str) -> float | None:
    pattern = re.compile(
        rf"\b{re.escape(key)}\b\s*[=:]\s*({_NUMBER})",
        re.IGNORECASE,
    )
    matches = pattern.findall(output)
    if not matches:
        return None
    return float(matches[-1])


def _from_json_lines(output: str, key: str) -> float | None:
    found: float | None = None
    for line in output.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and key in obj:
            try:
                found = float(obj[key])
            except (TypeError, ValueError):
                continue
    return found
