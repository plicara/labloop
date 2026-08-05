"""Retrieve documents for a query. This is the file the agent edits.

It works, and it is mediocre: whitespace tokenisation, raw term frequency, no
length normalisation, and every field weighted the same. All of the usual
levers are missing, which is the point -- there is real headroom here, and it
is the kind an agent can reason about rather than guess at.
"""

import math
from collections import Counter


def tokenize(text):
    """Split text into terms."""
    return text.lower().split()


def document_text(doc):
    """Flatten a document into the text that gets indexed."""
    parts = [doc["title"], doc["summary"]]
    parts.extend(doc["names"])
    parts.extend(doc.get("submodules", []))
    return " ".join(parts)


def build(docs):
    """Index the corpus."""
    postings = {}
    lengths = {}
    for doc in docs:
        terms = Counter(tokenize(document_text(doc)))
        lengths[doc["id"]] = sum(terms.values())
        for term, count in terms.items():
            postings.setdefault(term, {})[doc["id"]] = count
    return {"postings": postings, "lengths": lengths, "n": len(docs)}


def score(index, query):
    """Score every document that shares a term with the query."""
    scores = {}
    for term in tokenize(query):
        posting = index["postings"].get(term)
        if not posting:
            continue
        idf = math.log(index["n"] / len(posting))
        for doc_id, count in posting.items():
            scores[doc_id] = scores.get(doc_id, 0.0) + count * idf
    return scores


def search(index, query, k=10):
    """The top k document ids for a query, best first."""
    scores = score(index, query)
    ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
    return [doc_id for doc_id, _ in ranked[:k]]
