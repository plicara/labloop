"""Run the prompt over the held-out cases and score it. Protected.

The score is mean field accuracy, not whole-case accuracy: three fields over
thirty cases gives ninety graded outcomes rather than thirty pass/fail ones.
With whole-case accuracy most real improvements would land on an exact tie,
and a tie reverts.

The model is called through the `claude` CLI, one process per case, in a
thread pool -- process startup dominates, so parallelism is most of the wall
clock here.
"""

import concurrent.futures
import json
import pathlib
import re
import subprocess
import sys

from eval_set import CASES, FIELDS

MODEL = "claude-haiku-4-5-20251001"
WORKERS = 8
TIMEOUT = 120
PROMPT_FILE = pathlib.Path("prompt.txt")


def ask(system_prompt, message):
    """One model call. Returns raw text, or None if the call failed."""
    full = f"{system_prompt}\n\nCustomer message:\n{message}"
    try:
        proc = subprocess.run(
            ["claude", "-p", full, "--model", MODEL],
            capture_output=True, text=True, timeout=TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return None
    return proc.stdout if proc.returncode == 0 else None


DECORATION = " \t*_`#\"'.,"


def parse(text):
    """Pull the three fields out of whatever the model said.

    Deliberately forgiving: a JSON object anywhere in the reply, else
    `field: value` lines, with markdown decoration stripped from both the
    label and the value. The prompt is what is being optimised, so the parser
    must not be the thing that fails.

    It was, once. The first version matched `field\\s*[:=]\\s*(.+)` and models
    answer in markdown, so `**Urgency:** High` parsed to `'** High'` and
    failed to match `high`. See `selftest()` and the recipe's write-up.
    """
    if not text:
        return {}
    m = re.search(r"\{.*\}", text, re.S)
    if m:
        try:
            obj = json.loads(m.group(0))
            if isinstance(obj, dict):
                return {k.strip(DECORATION).lower(): obj[k] for k in obj}
        except json.JSONDecodeError:
            pass
    out = {}
    for field in FIELDS:
        # `order_id` is also written "Order ID", "order-id", "Order Id".
        label = r"[ _-]*".join(field.split("_"))
        # Allow markdown emphasis around the label and inside the value, and
        # take only the first line: models like to follow a value with prose.
        m = re.search(rf"[*_`]*{label}[*_`]*\s*[:=]\s*(.+)", text, re.I)
        if m:
            value = m.group(1).split("\n")[0].strip(DECORATION)
            if value:
                out[field] = value
    return out


CANONICAL = [
    ('{"category": "billing", "urgency": "high", "order_id": "A-4471"}',
     {"category": "billing", "urgency": "high", "order_id": "A-4471"}),
    ("category: billing\nurgency: high\norder_id: A-4471",
     {"category": "billing", "urgency": "high", "order_id": "A-4471"}),
    ("**Category:** billing\n**Urgency:** High\n**Order ID:** A-4471",
     {"category": "billing", "urgency": "high", "order_id": "A-4471"}),
    ("Here is the triage:\n\n```json\n{\"category\": \"refund\", "
     "\"urgency\": \"normal\", \"order_id\": null}\n```\nHope that helps.",
     {"category": "refund", "urgency": "normal", "order_id": None}),
]


def selftest():
    """Fail loudly if the parser cannot read a reply that is obviously correct.

    Without this, a parser bug is indistinguishable from a bad prompt: the
    score is low either way, and the loop optimises against a number that is
    measuring the harness. The retrieval recipe has the same guard for its
    judgments (`queries.check`), and for the same reason.
    """
    for reply, expected in CANONICAL:
        got = parse(reply)
        for field, want in expected.items():
            if normalise(field, got.get(field)) != normalise(field, want):
                raise SystemExit(
                    f"parser self-test failed on {reply[:40]!r}: "
                    f"{field} read as {got.get(field)!r}, expected {want!r}"
                )


def normalise(field, value):
    if value is None:
        return None
    s = str(value).strip().strip('"').lower()
    if s in ("none", "null", "n/a", "", "not mentioned", "no order id"):
        return None
    if field == "order_id":
        # Accept "G 5567", "g-5567", "order G-5567" as the same id.
        m = re.search(r"([a-z])\s*[-_ ]?\s*(\d{4})", s)
        return f"{m.group(1).upper()}-{m.group(2)}" if m else s.upper()
    return s


def score_case(system_prompt, message, gold):
    got = parse(ask(system_prompt, message))
    correct = 0
    for field in FIELDS:
        if normalise(field, got.get(field)) == normalise(field, gold[field]):
            correct += 1
    return correct / len(FIELDS)


def main():
    selftest()
    system_prompt = PROMPT_FILE.read_text()

    with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = [
            pool.submit(score_case, system_prompt, message, gold)
            for message, gold in CASES
        ]
        scores = [f.result() for f in futures]

    if len(scores) != len(CASES):
        sys.exit("lost a case")
    print(f"accuracy = {sum(scores) / len(scores):.6f}")


if __name__ == "__main__":
    main()
