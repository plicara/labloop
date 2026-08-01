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


# nan and inf are matched because experiments print them: a diverged training
# run says `loss = nan`, and reporting that as "no metric" would send you to
# check your print statement instead of your learning rate. Deciding what such
# a value means is the loop's job, not the parser's. The trailing boundary
# keeps `status = info` from reading as infinity.
_NUMBER = (
    r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?"
    r"|[-+]?(?:nan|inf(?:inity)?)\b"
)


def extract_metric(output: str, key: str) -> float:
    """Return the last value of `key` in `output`.

    Raises MetricNotFound if the key never appears, rather than returning a
    sentinel. A missing metric is a broken experiment, not a bad score, and
    the loop treats the two differently.

    The result may be nan or inf. Those are values the experiment printed, so
    reporting them is honest; refusing to compare them is the loop's job.
    """
    value = _from_key_value(output, key)
    if value is not None:
        return value

    value = _from_json_lines(output, key)
    if value is not None:
        return value

    raise MetricNotFound(f"metric {key!r} not found in output")


def _word_edge(char: str) -> str:
    r"""A `\b` only where one can match.

    `\b` sits between a word character and a non-word one, so appending it to
    a key ending in `)` or `%` demands a word character that is never there —
    `loss(train) = 1.5` would not be found, though the JSON form finds it. The
    boundary still guards keys that end in a word character, which is where it
    earns its keep: `val_loss` must not match `total_val_loss_scaled`.
    """
    return r"\b" if char.isalnum() or char == "_" else ""


def _from_key_value(output: str, key: str) -> float | None:
    pattern = re.compile(
        rf"{_word_edge(key[:1])}{re.escape(key)}{_word_edge(key[-1:])}"
        rf"\s*[=:]\s*({_NUMBER})",
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
