# Speed up a test suite without shrinking it

**The question.** How do I let an agent make my tests faster without letting it
delete the slow ones?

This is the recipe where the obvious protect set is the wrong one, and working
out the right one is most of the lesson.

**Everything below is a transcript** from a run on 2026-08-05.

## The problem with protecting `tests/`

`--protect tests/` is the reflex, and it makes the task impossible. Almost all
of a slow suite's slowness lives *inside* the tests:

- a fixture with the wrong scope, rebuilt for every test that asks for it
- a real `time.sleep` in a retry test that should be monkeypatched
- a large fixture constructed per-test instead of once

An agent that cannot edit `tests/` cannot fix any of those.

What must not change is not the *text* of the tests but **what the run
proves**. So the harness asserts a property of the run instead:

```python
EXPECTED_TESTS = 53

if passed != EXPECTED_TESTS:
    sys.exit(f"expected {EXPECTED_TESTS} passing tests, got {passed}. "
             "Making the suite smaller is not making it faster.")

for marker in ("skipped", "xfailed", "deselected"):
    if marker in out:
        sys.exit(f"tests were {marker}; every test must actually run")
```

That closes the fastest way to make any suite fast — delete the slow tests —
and it closes the quieter variants too: `@pytest.mark.skip`, `xfail`, and
deselection all get caught by name.

Behind it sits `acceptance_test.py`, also protected, which exercises the
library directly. If the suite were hollowed out while still reporting 53
passes, this is what would still fail.

So the protect set is:

```bash
--protect bench.py --protect acceptance_test.py --protect invoices.py
```

`invoices.py` is protected because it is the library under test. Its
`RateTable` sleeps to stand in for I/O the real system genuinely does;
deleting that sleep would make the tests fast by making them lie.

## The project

A small invoicing library and 53 tests that pass in ~10.5 seconds. The
slowness is ordinary and deliberate:

- `rates` is a function-scoped fixture building a 400-region `RateTable` with
  a 0.15s I/O stand-in — and roughly forty tests ask for it.
- `big_order` builds a 20,000-line order per test that wants one.
- The retry tests call `send()` with its real backoff, sleeping through
  0.2s + 0.4s of it.

## Step 1: noise

```bash
labloop noise --run "python bench.py" --metric seconds --repeat 4
```

```
    run 0  10.5346
    run 1  10.5396
    run 2  10.5556
    run 3  10.5207

seconds: 10.5207 to 10.5556 over 4 identical runs
spread: 0.0349   standard deviation: 0.0144061
```

**0.3% spread.** Compare that with the
[stdlib-index recipe](../../02-proposers/agent-optimizes-real-code/), where
the same kind of metric on the same machine moved by 22%.

Wall-clock time is not inherently noisy. It is noisy when it is *CPU-bound on
a contended machine*. This suite is dominated by sleeps, which are as stable
as the clock, so the metric barely moves. Measure rather than assume: the two
recipes disagree by two orders of magnitude and neither number was
predictable in advance.

## Step 2 and 3: baseline and run

```bash
labloop baseline --run "python bench.py" --metric seconds \
  --protect bench.py --protect acceptance_test.py --protect invoices.py

labloop run --run "python bench.py" --metric seconds \
  --protect bench.py --protect acceptance_test.py --protect invoices.py \
  --propose "python propose.py" \
  --min-delta 0.0349 \
  --budget 120 --propose-budget 300 --trials 4
```

No `--confirm` this time. At 0.3% noise a win of any size is real, and
`--confirm` would double the cost of every candidate to defend against a
problem this experiment does not have. That is the decision `noise` exists to
inform.

## What the agent did

```
[+] trial   0       10.5423    10.7s  (baseline)
[+] trial   1         2.672    71.2s  f3bbb59
[+] trial   2        0.4761   112.0s  0a96d3e
[-] trial   3        0.5461   222.4s
[T] trial   4            --   300.2s  (proposal exceeded its 300s budget)

best seconds: 0.4761 (trial 2)
```

**Trial 1 — 10.54s to 2.67s.** A two-line change, and the right one:

```diff
-@pytest.fixture
+@pytest.fixture(scope="session")
 def rates():
-    """Rates used by most of the suite."""
+    """Rates used by most of the suite. Read-only, so shared across tests."""
     return RateTable()
```

Note the docstring. The agent did not just widen the scope; it recorded *why
widening it is safe* — the table is read-only, so sharing it across tests
cannot leak state between them. That is the reasoning a reviewer would want,
and it is the difference between a fix and a lucky edit.

**Trial 2 — 2.67s to 0.48s.** The remaining cost was the sleeps in the retry
tests and the per-test construction of `big_order`.

All 53 tests still ran, all still passed, and the acceptance check still
passed at every step — otherwise the trial would have been recorded as
`failed`, not scored.

**Trial 3 — reverted.** 0.5461 against an incumbent of 0.4761: genuinely
slower, correctly discarded, no threshold needed to justify it.

**Trial 4 — timed out.** The agent ran past its 300-second `--propose-budget`
and was killed with its whole process group.

That is the third time in this cookbook the same pattern has appeared: after
a setback, the agent reaches for something bigger. Trial 1 took 71 seconds and
cut 74% of the runtime. Trials 3 and 4 took 222 and 300+ seconds and produced
a regression and nothing at all.

An earlier draft of the [`labloop-proposer`
skill](../../skills/labloop-proposer/) told agents not to do this, and the
skill was installed for this run. It did not prevent it — here or in the two
other runs where the pattern appeared. That advice has since been removed from
the skill: one observation for it, three against, is not a basis for
instructing an agent.

Worth being precise about what the timeout cost: nothing. The budget killed a
runaway attempt, the tree was restored, and the two good commits were already
in the history. A loop that stops paying for an attempt that has stopped
converging is the budget working, not the run failing.

## The result

```
kept=3  reverted=1  timed_out=1
seconds: 0.4761 (trial 2)
```

```
0a96d3e labloop: seconds 0.4761 (was 2.672)
f3bbb59 labloop: seconds 2.672 (was 10.5423)
8ecd4a4 invoicing library and a suite that is slower than it needs to be
```

**10.54s to 0.48s — 22× — across two commits, with the test count unchanged.**
Two of the five attempts earned their place; the other three are in the ledger
and not in the history, which is the arrangement the tool exists to produce.

## Limits

- **`narrative` tier: CI does not run this.** It needs the `claude` CLI,
  network, and several minutes of agent time.
- **The count check is not a correctness check.** It stops tests being
  deleted, skipped or deselected. It does not stop an assertion being
  weakened inside a test that still passes — `acceptance_test.py` is the
  backstop for that, and it is only as good as what it asserts.
- **A 53-test suite is not a real suite.** The slowness here is three
  ordinary causes, planted deliberately. A real suite has twenty, and some of
  them are the tests being genuinely necessary.
- **22× is a property of this suite, not of the tool.** It was built with a
  fixable problem in it. Your suite may be slow for reasons no fixture scope
  will solve.
