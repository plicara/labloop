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


def parse(text):
    """Pull the three fields out of whatever the model said.

    Deliberately forgiving: a JSON object anywhere in the reply, else
    `field: value` lines. The prompt is what is being optimised, so the parser
    must not be the thing that fails.
    """
    if not text:
        return {}
    m = re.search(r"\{.*\}", text, re.S)
    if m:
        try:
            obj = json.loads(m.group(0))
            if isinstance(obj, dict):
                return {k.lower(): obj[k] for k in obj}
        except json.JSONDecodeError:
            pass
    out = {}
    for field in FIELDS:
        m = re.search(rf"{field}\s*[:=]\s*(.+)", text, re.I)
        if m:
            out[field] = m.group(1).strip().strip('",.')
    return out


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
