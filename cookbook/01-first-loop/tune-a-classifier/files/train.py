"""A bag-of-words spam classifier. This is the file the proposer edits.

It prints one line in the format labloop reads:

    val_loss = 0.3
"""

import re
from collections import Counter

from data import TRAIN
from evaluate import score

# --- knobs ------------------------------------------------------------
ALPHA = 1.0  # Laplace smoothing added to every count
MIN_COUNT = 1  # drop tokens seen fewer times than this
LOWERCASE = False  # fold case before counting
STRIP_PUNCT = False  # drop punctuation from tokens
# ----------------------------------------------------------------------


def tokenize(text):
    if LOWERCASE:
        text = text.lower()
    if STRIP_PUNCT:
        text = re.sub(r"[^\w\s]", " ", text)
    return text.split()


def train():
    counts = {"spam": Counter(), "ham": Counter()}
    for text, label in TRAIN:
        counts[label].update(tokenize(text))

    seen = counts["spam"] + counts["ham"]
    vocab = {tok for tok, n in seen.items() if n >= MIN_COUNT}

    priors, likelihood = {}, {}
    for cls, c in counts.items():
        priors[cls] = sum(1 for _, label in TRAIN if label == cls) / len(TRAIN)
        total = sum(n for tok, n in c.items() if tok in vocab)
        denom = total + ALPHA * (len(vocab) + 1)
        likelihood[cls] = {tok: (c[tok] + ALPHA) / denom for tok in vocab}
        likelihood[cls]["<unk>"] = ALPHA / denom
    return priors, likelihood, vocab


if __name__ == "__main__":
    print(f"val_loss = {score(train(), tokenize)}")
