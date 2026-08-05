"""Build a searchable index of identifiers across a corpus of Python source.

This is the file the agent optimizes. It works, and it is slow, in the
specific way code is slow when it was written once and never revisited.
"""

import re

import corpus


def tokenize(text):
    """Pull identifier-like tokens out of source text."""
    return re.findall(r"[A-Za-z_][A-Za-z0-9_]*", text)


def build_index():
    """Map each identifier to the sorted list of files that contain it."""
    index = {}
    for path in corpus.files():
        with open(path, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
        name = path.split("/")[-1]
        for token in tokenize(text):
            if token not in index:
                index[token] = []
            # Keep the file list unique.
            if name not in index[token]:
                index[token].append(name)
    for token in index:
        index[token] = sorted(index[token])
    return index


def search(index, query):
    """Files containing every identifier in the query."""
    results = None
    for term in query:
        hits = index.get(term, [])
        if results is None:
            results = list(hits)
        else:
            results = [r for r in results if r in hits]
    return sorted(results or [])
