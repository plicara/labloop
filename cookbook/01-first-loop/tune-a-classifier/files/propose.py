"""A stand-in proposer: scripted, deterministic, and honest about being both.

A real proposer is a coding agent. This one applies a fixed list of edits so
the recipe produces the same ledger every time it runs -- which is what lets
CI check that the output in the README is still the output you get.

What it does share with a real proposer is the interface. labloop writes the
trial history to a JSON file and puts the path in $LABLOOP_BRIEF; this script
reads it the way an agent should, and prints what it learned before editing.
That reading code is the part worth copying.
"""

import json
import os
import pathlib
import re
import sys

TRAIN = pathlib.Path("train.py")


def read_brief():
    """Load the brief labloop wrote for this trial. Returns {} if disabled."""
    path = os.environ.get("LABLOOP_BRIEF")
    if not path or not os.path.exists(path):
        return {}
    return json.loads(pathlib.Path(path).read_text())


def set_knob(name, value):
    """Rewrite one `NAME = value` line in train.py, preserving its comment."""
    text = TRAIN.read_text()
    new, n = re.subn(rf"^{name} = \S+", f"{name} = {value}", text, count=1, flags=re.M)
    if n != 1:
        sys.exit(f"could not find knob {name}")
    TRAIN.write_text(new)


# Each entry is one attempt, in order. A real agent would decide these from
# the brief; the point of the recipe is what labloop does with them.
ATTEMPTS = [
    lambda: set_knob("LOWERCASE", "True"),
    lambda: set_knob("STRIP_PUNCT", "True"),
    lambda: set_knob("ALPHA", "5.0"),
    lambda: set_knob("ALPHA", "0.1"),
    lambda: TRAIN.write_text(TRAIN.read_text() + "\nthis is not python\n"),
    lambda: pathlib.Path("evaluate.py").write_text("# rewritten by the proposer\n"),
]


def main():
    brief = read_brief()
    trial = brief.get("trial", int(os.environ.get("LABLOOP_TRIAL", 0)))

    # The `why` on the last trial is the part a proposer cannot work out for
    # itself: "reverted" is a label, "did not beat 0.4344" is a reason.
    history = brief.get("history", [])
    if history:
        print(f"last: {history[-1]['why']}", file=sys.stderr)
    if brief.get("incumbent") is not None:
        print(f"to beat: {brief['metric']} {brief['incumbent']}", file=sys.stderr)

    if not 1 <= trial <= len(ATTEMPTS):
        sys.exit(f"no scripted attempt for trial {trial}")
    ATTEMPTS[trial - 1]()


if __name__ == "__main__":
    main()
