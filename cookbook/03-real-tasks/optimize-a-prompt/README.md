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
