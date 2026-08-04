"""The measurement. This file is protected: the proposer must not touch it.

It holds the holdout messages and the scoring function. If a proposal could
edit this, "improving the metric" and "improving the classifier" would stop
being the same thing.

The metric is mean cross-entropy on the holdout, not error rate. Ten messages
give error rate only eleven possible values, so most real improvements would
show up as an exact tie -- and a tie reverts. A continuous metric grades them.
"""

import math

HOLDOUT = [
    # Plainly spam.
    ("FREE entry to win a prize, click now!!!", "spam"),
    ("Your account needs URGENT verification, click here", "spam"),
    ("Claim your CASH bonus today, no fees", "spam"),
    ("Congratulations, you have won free tickets!", "spam"),
    ("Order cheap meds now, no prescription", "spam"),
    # Spam that reads calmly.
    ("Following up on the rates we discussed. Refinance available.", "spam"),
    ("Your delivery is on hold pending a small fee.", "spam"),
    ("A gift card is reserved in your name until Friday.", "spam"),
    # Plainly ham.
    ("Can we move the standup to 10am?", "ham"),
    ("I left the keys with reception, thanks.", "ham"),
    ("Great work on the release yesterday.", "ham"),
    ("Are you joining the call or dialing in?", "ham"),
    ("Lunch at the usual place on Friday?", "ham"),
    # Ham using words the spam set also uses.
    ("The free tier is enough for our usage, no need to pay.", "ham"),
    ("Congratulations on the promotion! Well deserved.", "ham"),
    ("Urgent: the build is broken on main, can you look?", "ham"),
    ("Click the second link in the doc, that's the right one.", "ham"),
    ("I won the raffle at the office party, of all things.", "ham"),
    ("Please claim your expenses before the end of the month.", "ham"),
    ("The prize for finishing early is more work, apparently.", "ham"),
]


def score(model, tokenize):
    """Mean cross-entropy on the holdout. Lower is better."""
    priors, likelihood, vocab = model
    total = 0.0
    for text, label in HOLDOUT:
        toks = [t for t in tokenize(text) if t in vocab]
        logp = {}
        for cls in priors:
            lp = math.log(priors[cls])
            for tok in toks:
                lp += math.log(likelihood[cls].get(tok, likelihood[cls]["<unk>"]))
            # Length-normalise so long messages don't dominate the average.
            logp[cls] = lp / (len(toks) + 1)
        m = max(logp.values())
        denom = sum(math.exp(v - m) for v in logp.values())
        p_true = math.exp(logp[label] - m) / denom
        total += -math.log(max(p_true, 1e-12))
    return total / len(HOLDOUT)
