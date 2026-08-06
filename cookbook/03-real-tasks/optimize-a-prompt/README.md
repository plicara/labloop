# Optimize a prompt against a held-out eval set

**The question.** How do I let an agent rewrite a prompt without it learning
the answer key?

This is the recipe where the cheat is not hypothetical. Everywhere else in the
cookbook, "the agent could edit the evaluator" is a risk worth guarding
against. Here the answer key is a text file, the optimiser is a coding agent
with file access, and copying thirty labels into a prompt would score
perfectly while learning nothing.

**Everything below is a transcript** from a run on 2026-08-05.

## The task

Support triage. Given a customer message, return three fields:

| Field | Values |
| --- | --- |
| `category` | billing, shipping, technical, account, refund, other |
| `urgency` | low, normal, high |
| `order_id` | the id if the message mentions one, else nothing |

- `prompt.txt` — the system prompt. **This is what the agent edits.**
- `eval_set.py` — thirty held-out messages with gold labels. **Protected.**
- `evaluate.py` — runs the prompt over every case and scores it. **Protected.**

The cases are not all obvious, on purpose:

```python
("THIS IS THE THIRD TIME I HAVE WRITTEN. Where is my refund for D-1120?",
 {"category": "refund", "urgency": "high", "order_id": "D-1120"}),

("Absolutely furious about the packaging quality. Not asking for anything.",
 {"category": "other", "urgency": "low", "order_id": None}),

("Order no. G 5567 arrived damaged, I want my money back.",
 {"category": "refund", "urgency": "high", "order_id": "G-5567"}),
```

Shouting is not urgency; the second case is angrier than the first and needs
nothing. `G 5567` is the same id as `G-5567`. A set where every case is
obvious measures nothing.

## Mean field accuracy, not whole-case accuracy

Thirty cases scored pass/fail gives thirty-one possible values, and most real
prompt improvements would land on an **exact tie** — which reverts. Scoring
each of the three fields separately gives ninety graded outcomes, so a prompt
that fixes urgency while leaving category alone is visibly better rather than
invisibly equal.

Same lesson as the [retrieval recipe](../improve-rag-retrieval/)'s choice of
nDCG over recall@10: **pick a metric fine enough to see the change you are
making.**

## The parser must not be the thing that fails

`evaluate.py` accepts a JSON object anywhere in the reply, or `field: value`
lines, and normalises `G 5567`, `g-5567` and `order G-5567` to the same id.

That forgiveness is deliberate. The prompt is what is being optimised; if the
parser were strict, the loop would mostly be measuring whether the model
guessed the output format, and the agent's first win would be formatting
rather than triage. A brittle harness optimises for the harness.

## The starting prompt

Deliberately vague — no format, no category list, no guidance:

```
You are a support triage assistant. Read the customer message and work out
what kind of request it is, how urgent it is, and which order it refers to.

Reply with your answer.
```

It scores **0.1778**. There is a great deal of room.

## What the agent is not told

`propose.py` passes the score and the history. It never passes the cases. The
agent knows it is getting 17.8% and can see labloop's verdict on each previous
attempt, but it cannot see a single message or a single gold label.

That asymmetry is the design. `--protect eval_set.py` means an agent that
reads and copies the answers is recorded as `harness_changed` rather than
scored — but detection is the backstop, not the plan. The plan is that the
information never reaches it.

## The harness bug that nearly produced a fake recipe

The first run of this recipe measured noise like this:

```
accuracy: 0.177778 to 0.177778 over 3 identical runs
spread: none — every run agreed, so any change in the metric is the change
```

A perfectly deterministic metric, from a system whose central component is a
language model. That is not impossible, but it is surprising enough to check —
and `0.177778 × 90 = 16` exactly, which is suspiciously round.

Sixteen is the number of cases whose gold `order_id` is `None`. The parser was
extracting **nothing at all**, so those sixteen scored a third each for `None`
matching `None`, and every other field was wrong on every case. The model was
answering correctly and scoring zero:

```
Model said:  **Request Type:** Billing/Payment Issue — Duplicate Charge
             **Urgency:** High     **Order Reference:** A-4471
Gold:        billing / high / A-4471
Parsed:      {'urgency': '** High'}     →  0 of 3
```

Models reply in markdown. `**Urgency:** High` matched `urgency\s*[:=]\s*(.+)`
starting after the colon, giving `'** High'`, which normalises to nothing. The
section above this one says *the parser must not be the thing that fails*, and
the parser was the thing that failed.

**The fix is not the lesson.** The lesson is that a harness bug and a bad
prompt produce the same low number, so the loop would have optimised against a
measurement of itself for as long as it was allowed to — and `spread: none`
would have made the numbers look trustworthy the whole way.

So `evaluate.py` now checks itself before it scores anything:

```python
CANONICAL = [
    ('{"category": "billing", "urgency": "high", "order_id": "A-4471"}', {...}),
    ("category: billing\nurgency: high\norder_id: A-4471",               {...}),
    ("**Category:** billing\n**Urgency:** High\n**Order ID:** A-4471",   {...}),
    ("Here is the triage:\n\n```json\n{...}\n```\nHope that helps.",     {...}),
]
```

If the parser cannot read a reply that is obviously correct, the run dies
instead of reporting a number. The [retrieval
recipe](../improve-rag-retrieval/) has the same guard on its judgments, and it
is what caught that corpus silently missing every C module.

The self-test earned itself immediately: the first fix handled markdown bold
and still failed on `**Order ID:** A-4471`, a label variant I had not
considered.

**And fixing it changed what the noise measurement said.**

## Step 1: noise, honestly this time

```bash
labloop noise --run "python evaluate.py" --metric accuracy --repeat 3
```

```
    run 0  0.266667
    run 1  0.3
    run 2  0.211111

accuracy: 0.211111 to 0.3 over 3 identical runs
spread: 0.088889   standard deviation: 0.0449051
```

**The metric was noisy all along.** The broken parser had been hiding it, by
failing in exactly the same way every time. A metric that fails identically
looks identical to a metric that is stable.

That is the sharpest form of the lesson in this cookbook: *a suspiciously
clean noise measurement can be a symptom of a broken harness, not a
well-behaved experiment.* `spread: none` is good news only if you can say why.

## What the agent did

```
[+] trial   0      0.288889    58.5s  (baseline)
[+] trial   1      0.888889   100.6s  d4afe22
[-] trial   2      0.888889   183.8s
[-] trial   3      0.877778   192.3s

kept=2  reverted=2
accuracy: 0.888889 (trial 1)
```

**Trial 1 — 0.2889 to 0.8889.** The agent replaced the vague instruction with
a schema and field guidance:

```diff
-Reply with your answer.
+Reply with exactly three lines, in this format:
+
+category: <billing|shipping|technical|account|refund|other>
+urgency: <low|normal|high>
+order_id: <the order id mentioned in the message, or none>
+
+Field guidance:
+- category: pick the single best fit.
+  - refund: the customer explicitly asks for a refund, return, or money back
+  - account: login/password/profile issues not about a technical bug
+- urgency: how quickly this needs a response.
+  - high: customer is blocked, angry, mentions money at risk, urgent deadline
```

Three things at once, and all three were needed: the output format (so the
parser can read it), the closed value sets (so `billing` rather than
`Billing/Payment Issue`), and the boundary rules for the categories that
overlap — refund versus shipping, account versus technical.

**Trial 2 — an exact tie, reverted.** 0.888889 against an incumbent of
0.888889. [A tie is not an improvement](../../../README.md#how-it-decides), so
it reverted, and this is what that rule looks like when it fires on real data
rather than in a design note.

**Trial 3 — 0.8778, reverted.** Slightly worse.

## What this run cannot tell you

Trials 2 and 3 are **inside the noise**. The spread is 0.0889 and the standard
deviation 0.0449; trial 3 differs from the incumbent by 0.011. On this
evidence, trials 1, 2 and 3 may all be the same prompt quality measured three
times.

I ran this without `--min-delta`, and that was a mistake I got away with.
Trial 1's improvement was 0.6 — seven times the spread, so no threshold was
needed to believe it. But had the agent made a genuine 0.05 improvement, this
run could not have told it from a lucky draw, and would have committed it
either way. The correct invocation, given what step 1 measured:

```bash
labloop run ... --min-delta 0.0449 --confirm
```

Better still: **make the metric less noisy.** Thirty cases at three fields is
ninety binary outcomes, and the sampling noise on ninety outcomes is large.
Three hundred cases would cut it by roughly a third, and cost three hundred
model calls per trial instead of thirty.

## Limits

- **`narrative` tier: CI does not run this.** It needs the `claude` CLI,
  network, and a few minutes of model time per trial.
- **Thirty cases is a demonstration, not an evaluation.** A prompt that scores
  0.89 here has not been shown to be good; it has been shown to be better than
  one that scored 0.29 on the same thirty cases.
- **The labels are one author's judgement**, written before any system was
  tuned. "Shouting is not urgency" is a defensible rule and not the only one.
- **Nothing here proves the agent could not have cheated** — only that it did
  not need to. `--protect` would have recorded it if it had read the answer
  key, and the run shows no `harness_changed` trial.
