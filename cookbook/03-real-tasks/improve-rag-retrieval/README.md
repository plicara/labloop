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

## Step 3: run

```bash
labloop run --run "python evaluate.py" --metric ndcg --goal maximize \
  --protect evaluate.py --protect queries.py --protect corpus.py \
  --propose "python propose.py" \
  --budget 120 --propose-budget 300 --trials 4
```

## What the agent did

```
[+] trial   0       0.25272     0.2s  (baseline)
[+] trial   1      0.519855   110.1s  b4c45bf
[-] trial   2       0.51081   285.6s
```

**Trial 1 — 0.2527 to 0.5199. The score doubled.** The agent implemented BM25:

```diff
-        idf = math.log(index["n"] / len(posting))
+        df = len(posting)
+        idf = math.log((n - df + 0.5) / (df + 0.5) + 1)
         for doc_id, count in posting.items():
-            scores[doc_id] = scores.get(doc_id, 0.0) + count * idf
+            dl = lengths[doc_id]
+            denom = count + K1 * (1 - B + B * dl / avgdl)
+            scores[doc_id] = scores.get(doc_id, 0.0) + idf * (count * (K1 + 1)) / denom
```

Smoothed idf, term-frequency saturation, and document-length normalisation,
with a docstring naming the diagnosis:

> Raw term frequency lets long documents (modules with hundreds of public
> names) win purely by being long. BM25's saturation and length normalization
> keep a short, on-topic summary competitive with a bloated names list.

That is the correct reading of this corpus. `os` and `sys` export hundreds of
names; under raw term frequency they surfaced for almost anything.

**Trial 2 — reverted.** 0.5109 against 0.5199, on a metric where higher is
better. It also took 285 seconds against trial 1's 110.

**Trial 3 — 0.5199 to 0.5355.** The agent fixed the tokenizer:

```diff
-    return text.lower().split()
+    return _TOKEN_RE.findall(text.lower())   # r"[a-z0-9]+"
```

> Plain whitespace splitting leaves stdlib identifiers like `lru_cache`,
> `make_archive`, or `ZIP_DEFLATED` as single opaque tokens, so they never
> match a query word like "cache" or "archive".

**Trial 4 — `no_change`.** The agent finished without editing anything, so
there was nothing to measure. Not a failure and not a result: the loop
recorded it as its own outcome and moved on.

```
kept=3  reverted=1  no_change=1
ndcg: 0.535526 (trial 3)
```

**0.2527 to 0.5355 — 2.1× — over two kept commits.**

## The wrong diagnosis, and the right one

While trial 3 was still running, I wrote in this file that the ten
zero-scoring queries were candidate-set failures — that `functools` never
surfaced for *"cache the result of an expensive function call"* because
whitespace tokenisation could not match `cache` against `lru_cache`, and that
splitting identifiers was therefore the next lever.

The agent then made exactly that change, and **it fixed none of them.** Still
ten zeros, the same ten. So the diagnosis was wrong, and the data says why:

```
query terms: ['cache', 'the', 'result', 'of', 'an', 'expensive', 'function', 'call']
functools has 'cache'? True | doc length: 41
functools score: 5.505
rank of functools: 32
top10: ['shelve', 'ast', 'sys', 'rlcompleter', 'platform', 'pdb', ...]
```

`functools` **is** in the candidate set, and does score. It ranks 32nd. The
top ten are documents matching *"the"*, *"of"*, *"an"*, *"function"*,
*"call"* — six near-meaningless terms outvoting the one that carries the
query. This was never a tokenisation problem. It is a **term-weighting**
problem, and the fix is stopword handling or a floor on idf, not more
aggressive splitting.

Two things worth taking from that:

- **The improvement was real and the explanation was wrong.** Trial 3 earned
  its keep — the tokenizer change did help other queries — but not for the
  reason predicted. A metric that goes up is not evidence that your story
  about it is correct.
- **The loop did not care.** It measured the change and kept it. Being right
  about *why* is a human problem, which is what `--detail`, the ledger, and
  five minutes of poking at the index are for.
