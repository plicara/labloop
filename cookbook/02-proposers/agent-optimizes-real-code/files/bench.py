"""The measurement: correctness first, then speed. Protected.

The agent may rewrite `index.py` however it likes. It may not touch this
file, and this file is what decides whether the rewrite still works.

Correctness is checked against a **reference implementation kept here**, not
against a recorded hash. The first version of this file did use a recorded
hash, and it was wrong in a way worth keeping a note about: the corpus is the
running Python's own standard library, so the fingerprint differs on every
Python version and every machine. A golden constant was only ever valid where
it was computed, and CI caught it on five versions at once.

The reference below is slow and obviously correct. `index.py` has to agree
with it about what the index *contains*; how it gets there is the agent's
business. An index that is fast because it is wrong fails here and is recorded
as `failed`, not as a good score.
"""

import hashlib
import json
import os
import re
import time

import corpus
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

TOKEN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def reference_index():
    """What the index should contain. Deliberately the dullest way to say it."""
    idx: dict[str, set[str]] = {}
    for path in corpus.files():
        with open(path, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
        name = os.path.basename(path)
        for token in set(TOKEN.findall(text)):
            idx.setdefault(token, set()).add(name)
    return {token: sorted(files) for token, files in idx.items()}


def reference_search(idx, query):
    """Files containing every term in the query."""
    results = None
    for term in query:
        hits = set(idx.get(term, []))
        results = hits if results is None else results & hits
    return sorted(results or [])


def fingerprint(idx, search):
    """A hash of what the index contains, independent of how it was built."""
    h = hashlib.sha256()
    h.update(str(len(idx)).encode())
    # A deterministic sample of the index itself, not just the query answers,
    # so an index that is only correct for the ten queries below is caught.
    for token in sorted(idx)[::97]:
        h.update(token.encode())
        h.update(",".join(sorted(idx[token])).encode())
    for q in QUERIES:
        h.update(json.dumps(search(idx, q)).encode())
    return h.hexdigest()


def main():
    start = time.perf_counter()
    idx = index.build_index()
    for q in QUERIES:
        index.search(idx, q)
    elapsed = time.perf_counter() - start

    # Outside the timed region: the reference is not what is being measured.
    expected = fingerprint(reference_index(), reference_search)
    got = fingerprint(idx, index.search)
    if got != expected:
        raise SystemExit(f"index changed meaning: fingerprint {got} != {expected}")

    print(f"seconds = {elapsed:.4f}")


if __name__ == "__main__":
    main()
