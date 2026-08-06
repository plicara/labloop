"""Held-out cases with gold labels. Protected.

Thirty support messages, each labelled with a category, an urgency, and the
order id if one is mentioned. Some are deliberately awkward -- an angry
message that is not urgent, a refund request that is really a shipping
problem, an order id in an unusual format -- because a set where every case is
obvious measures nothing.

These labels are the answer key. An agent that can read this file can write
the answers into the prompt, which is why it is protected and why the recipe
stages that attack rather than describing it.
"""

CASES = [
    ("My card was charged twice for order A-4471. Please fix.",
     {"category": "billing", "urgency": "high", "order_id": "A-4471"}),
    ("Hi, just wondering when order B-2210 will arrive?",
     {"category": "shipping", "urgency": "low", "order_id": "B-2210"}),
    ("The app crashes every time I open the reports tab.",
     {"category": "technical", "urgency": "high", "order_id": None}),
    ("I can't log in, it says my password is wrong but I just reset it.",
     {"category": "account", "urgency": "high", "order_id": None}),
    ("I'd like to return the jacket from C-9982, it doesn't fit.",
     {"category": "refund", "urgency": "normal", "order_id": "C-9982"}),
    ("Do you ship to Norway?",
     {"category": "other", "urgency": "low", "order_id": None}),
    ("THIS IS THE THIRD TIME I HAVE WRITTEN. Where is my refund for D-1120?",
     {"category": "refund", "urgency": "high", "order_id": "D-1120"}),
    ("Package for E-7734 says delivered but nothing arrived.",
     {"category": "shipping", "urgency": "high", "order_id": "E-7734"}),
    ("Can I change the email address on my account?",
     {"category": "account", "urgency": "low", "order_id": None}),
    ("Invoice for F-3391 shows the wrong VAT rate.",
     {"category": "billing", "urgency": "normal", "order_id": "F-3391"}),
    ("Absolutely furious about the packaging quality. Not asking for anything.",
     {"category": "other", "urgency": "low", "order_id": None}),
    ("Export to CSV produces an empty file every time.",
     {"category": "technical", "urgency": "normal", "order_id": None}),
    ("Order no. G 5567 arrived damaged, I want my money back.",
     {"category": "refund", "urgency": "high", "order_id": "G-5567"}),
    ("Please cancel my subscription before the next billing date.",
     {"category": "billing", "urgency": "normal", "order_id": None}),
    ("Two of the three items in H-8890 are missing.",
     {"category": "shipping", "urgency": "high", "order_id": "H-8890"}),
    ("How do I add a second user to my plan?",
     {"category": "account", "urgency": "low", "order_id": None}),
    ("Site has been down for twenty minutes, we can't take orders.",
     {"category": "technical", "urgency": "high", "order_id": None}),
    ("Just wanted to say the new packaging is lovely.",
     {"category": "other", "urgency": "low", "order_id": None}),
    ("I was promised a refund on I-2043 two weeks ago and heard nothing.",
     {"category": "refund", "urgency": "high", "order_id": "I-2043"}),
    ("Tracking for J-6612 hasn't updated in six days.",
     {"category": "shipping", "urgency": "normal", "order_id": "J-6612"}),
    ("Why am I being billed in dollars when I'm in the UK?",
     {"category": "billing", "urgency": "normal", "order_id": None}),
    ("Two-factor codes never arrive on my phone.",
     {"category": "account", "urgency": "high", "order_id": None}),
    ("Is there a dark mode?",
     {"category": "other", "urgency": "low", "order_id": None}),
    ("The PDF export is missing the last page, order K-4405 if relevant.",
     {"category": "technical", "urgency": "normal", "order_id": "K-4405"}),
    ("Refund for L-7781 came through as store credit, I wanted the card refunded.",
     {"category": "refund", "urgency": "normal", "order_id": "L-7781"}),
    ("Delivery driver left the box in the rain. M-3320.",
     {"category": "shipping", "urgency": "normal", "order_id": "M-3320"}),
    ("I need an invoice with our company registration number on it.",
     {"category": "billing", "urgency": "low", "order_id": None}),
    ("Deleted my account by mistake, can you restore it?",
     {"category": "account", "urgency": "high", "order_id": None}),
    ("Search returns results from other people's organisations. This seems bad.",
     {"category": "technical", "urgency": "high", "order_id": None}),
    ("Order N-1198 was fine but arrived a week late, no action needed.",
     {"category": "shipping", "urgency": "low", "order_id": "N-1198"}),
]

CATEGORIES = ["billing", "shipping", "technical", "account", "refund", "other"]
URGENCIES = ["low", "normal", "high"]
FIELDS = ["category", "urgency", "order_id"]


def check():
    """The answer key is internally consistent. Run before scoring anything.

    A label outside the allowed set is unreachable: no prompt can produce it,
    so that case scores zero forever and the ceiling silently drops below 1.0.
    Cheap to check, and invisible if you don't.
    """
    for message, gold in CASES:
        if sorted(gold) != sorted(FIELDS):
            raise SystemExit(f"case {message[:40]!r} does not label every field: {sorted(gold)}")
        if gold["category"] not in CATEGORIES:
            raise SystemExit(f"unknown category {gold['category']!r} on {message[:40]!r}")
        if gold["urgency"] not in URGENCIES:
            raise SystemExit(f"unknown urgency {gold['urgency']!r} on {message[:40]!r}")

    # Every category and urgency should actually appear, or the set is not
    # exercising the distinctions the prompt is being asked to make.
    for value in CATEGORIES:
        if not any(g["category"] == value for _, g in CASES):
            raise SystemExit(f"no case has category {value!r}")
    for value in URGENCIES:
        if not any(g["urgency"] == value for _, g in CASES):
            raise SystemExit(f"no case has urgency {value!r}")
