# Improve retrieval quality on a real corpus

**The question.** How do I tune a retriever against a real query set without
tuning it to the answers?

**Everything below is a transcript** from a run on 2026-08-05.

## The setup

- **Corpus.** 194 documents, one per Python standard-library module: title,
  module docstring, the public names it defines, and its submodules. Real
  documentation text, already on your machine.
- **Queries.** Forty questions with graded relevance judgments, in
  `queries.py`. **Protected.**
- **Scorer.** `evaluate.py`, computing nDCG@10. **Protected.**
- **Retriever.** `retrieve.py` — whitespace tokenisation, raw term frequency,
  no length normalisation, every field weighted the same. **This is what the
  agent edits.**

## Two decisions that shaped the recipe

### The queries are phrased like questions, not like documents

```python
("read and write comma separated spreadsheet files", {"csv": 2}),
("cache the result of an expensive function call",   {"functools": 2}),
("get the smallest few items from a big list efficiently", {"heapq": 2}),
```

Not `"csv module"`. A query set full of module names would make this a
keyword-matching exercise that any system passes; the vocabulary gap between
*"comma separated spreadsheet"* and a docstring reading *"csv.py - read/write
CSV files"* is the actual retrieval problem.

### nDCG@10, not recall@10

Recall over forty queries with one or two relevant documents each takes only a
few dozen distinct values, so most genuine improvements land on an **exact
tie** — and [a tie reverts](../../../README.md#how-it-decides). The loop would
discard real progress for landing on the same number.

nDCG moves whenever a relevant document moves *up the ranking*, which is what
the agent is actually changing. Choosing a metric fine enough to see the
change you are making is a decision to take before the loop starts, not after
it stalls.

## A corpus bug worth repeating

The first version built documents by parsing module source with `ast`. It ran,
produced 163 documents, and was quietly wrong: C modules have no Python
source, so `itertools`, `decimal`, `time`, `zlib` and `binascii` were simply
absent — and five queries pointed at documents that did not exist.

`queries.check()` caught it because it asserts every judged module is in the
corpus:

```
judged modules missing from corpus: ['binascii', 'concurrent', 'decimal',
 'itertools', 'multiprocessing', 'time', 'urllib', 'zlib']
```

Without that assertion the run would have proceeded, scored those queries a
permanent zero, and produced a plausible-looking ndcg that no retriever could
ever improve. **An eval harness should check its own integrity before it
checks anything else** — the same instinct as labloop refusing a `--protect`
pattern that matches nothing.

The fix was to build the corpus by importing rather than parsing, with a
denylist for modules whose import is itself the problem (`antigravity` opens a
browser).

## Step 1: noise

```bash
labloop noise --run "python evaluate.py" --metric ndcg --repeat 3
```

```
spread: none — every run agreed, so any change in the metric is the change
```

Deterministic: same corpus, same queries, same arithmetic. No `--min-delta`,
no `--confirm`, and every improvement is believed immediately. Contrast the
[test-suite recipe](../speed-up-a-test-suite/) at 0.3% and the
[stdlib-index recipe](../../02-proposers/agent-optimizes-real-code/) at 22%.
Three recipes, three answers, all measured rather than assumed.

## Step 2: baseline

```bash
labloop baseline --run "python evaluate.py" --metric ndcg --goal maximize \
  --protect evaluate.py --protect queries.py --protect corpus.py
```

The naive retriever scores **0.2527**, and `--detail` shows why: fourteen of
the forty queries score exactly zero.

```
  0.000  cache the result of an expensive function call
  0.000  compress files into a zip archive
  0.000  count how many times each item appears in a list
  0.000  download a web page from a url
  0.000  find all files matching a wildcard pattern
```

Every one of those is a vocabulary-gap failure: the right document exists and
uses different words.
