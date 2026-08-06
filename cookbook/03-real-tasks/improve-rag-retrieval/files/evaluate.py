"""Score the retriever. Protected.

The metric is nDCG@10, not recall@10, and that choice is the recipe's first
lesson. Recall over forty queries with one or two relevant documents each can
only take a few dozen distinct values, so most genuine improvements land on an
exact tie -- and a tie reverts. nDCG moves whenever a relevant document moves
up the ranking, which is what the agent is actually changing.
"""

import math
import sys

import corpus
import queries
import retrieve

K = 10


def dcg(gains):
    return sum(g / math.log2(i + 2) for i, g in enumerate(gains))


def ndcg_at_k(ranked, relevance, k=K):
    gains = [relevance.get(doc_id, 0) for doc_id in ranked[:k]]
    ideal = sorted(relevance.values(), reverse=True)[:k]
    best = dcg(ideal)
    return dcg(gains) / best if best else 0.0


def main():
    docs = corpus.documents()
    queries.check([d["id"] for d in docs])

    index = retrieve.build(docs)

    total = 0.0
    per_query = []
    for query, relevance in queries.QUERIES:
        ranked = retrieve.search(index, query, k=K)
        if len(ranked) > K:
            sys.exit(f"search returned {len(ranked)} results for k={K}")
        s = ndcg_at_k(ranked, relevance)
        per_query.append((s, query))
        total += s

    mean = total / len(queries.QUERIES)

    if "--detail" in sys.argv:
        for s, query in sorted(per_query):
            print(f"  {s:.3f}  {query}")

    print(f"ndcg = {mean:.6f}")


if __name__ == "__main__":
    main()
