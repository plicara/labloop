"""The measurement: correctness first, then speed. Protected.

The agent may rewrite `index.py` however it likes. It may not touch this
file, and this file is what decides whether the rewrite still works.

Correctness is checked against a fingerprint computed once from the original
implementation. An index that is fast because it is wrong fails here and is
recorded as `failed`, not as a good score.
"""

import hashlib
import json
import time

import index

QUERIES = [
    ["def", "return"],
    ["class", "self", "__init__"],
    ["import", "os", "sys"],
    ["yield", "generator"],
    ["asyncio", "await"],
    ["socket", "bind", "listen"],
    ["threading", "Lock"],
    ["json", "dumps", "loads"],
    ["warnings", "deprecated"],
    ["typing", "Optional"],
]

# Computed from the original index.py. Any change to what the index *means*
# moves this; a change to how fast it is built does not.
GOLDEN = "8f06a9b67a96129b65bf9f1c09666fae6dbeb29d7e50ec018b930d32ae0be163"


def fingerprint(idx):
    """A hash of what the index contains, independent of how it was built."""
    h = hashlib.sha256()
    h.update(str(len(idx)).encode())
    # A deterministic sample of the index itself, not just the query answers,
    # so an index that is only correct for the ten queries below is caught.
    for token in sorted(idx)[::97]:
        h.update(token.encode())
        h.update(",".join(sorted(idx[token])).encode())
    for q in QUERIES:
        h.update(json.dumps(index.search(idx, q)).encode())
    return h.hexdigest()


def main():
    start = time.perf_counter()
    idx = index.build_index()
    for q in QUERIES:
        index.search(idx, q)
    elapsed = time.perf_counter() - start

    got = fingerprint(idx)
    if got != GOLDEN:
        raise SystemExit(f"index changed meaning: fingerprint {got} != {GOLDEN}")

    print(f"seconds = {elapsed:.4f}")


if __name__ == "__main__":
    main()
