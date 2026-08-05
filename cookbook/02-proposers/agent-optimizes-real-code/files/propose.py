"""Drive Claude Code as the proposer.

This is the whole integration: read the brief labloop wrote, turn it into a
prompt, run the agent headless, let it edit the file. Everything else in this
recipe is the experiment, not the wiring.
"""

import json
import os
import pathlib
import subprocess
import sys

TARGET = "index.py"
AGENT_BUDGET_SECONDS = 240


def read_brief():
    """The trial history labloop wrote for this attempt."""
    path = os.environ.get("LABLOOP_BRIEF")
    if not path or not os.path.exists(path):
        return {}
    return json.loads(pathlib.Path(path).read_text())


def prompt_from(brief):
    """Turn the brief into something an agent can act on."""
    lines = [
        f"Make `{TARGET}` faster. It builds an identifier index over the Python",
        "standard library's source and answers queries against it.",
        "",
        "Rules:",
        f"  - Edit ONLY {TARGET}. Do not touch bench.py or corpus.py.",
        "  - bench.py checks a fingerprint of the index contents. The index must",
        "    keep meaning exactly the same thing, or the trial fails.",
        "  - Run `python bench.py` to check your work before finishing.",
        "",
        f"The metric is `{brief.get('metric', 'seconds')}` and lower is better.",
    ]

    if brief.get("incumbent") is not None:
        lines.append(f"The time to beat is {brief['incumbent']:.4f} seconds.")
    else:
        lines.append("This is the first attempt; there is no time to beat yet.")

    # The history is the part that stops the agent repeating itself. `why`
    # explains labloop's verdict, which the agent cannot work out alone.
    history = brief.get("history", [])
    if history:
        lines += ["", "What has already been tried, most recent last:"]
        for h in history[-8:]:
            lines.append(f"  - trial {h['index']}: {h['why']}")
        tail = history[-1].get("output_tail")
        if tail:
            lines += ["", "The last attempt's output ended with:", "```", tail.strip(), "```"]

    lines += [
        "",
        "Make one focused change. Do not rewrite everything at once:",
        "a smaller change that is measurably faster is worth more than a",
        "large one that fails the fingerprint check.",
    ]
    return "\n".join(lines)


def main():
    brief = read_brief()
    prompt = prompt_from(brief)
    print(f"--- prompt for trial {brief.get('trial', '?')} ---\n{prompt}\n", file=sys.stderr)

    result = subprocess.run(
        ["claude", "-p", prompt, "--permission-mode", "acceptEdits"],
        capture_output=True,
        text=True,
        timeout=AGENT_BUDGET_SECONDS,
    )
    print(result.stdout[-2000:], file=sys.stderr)
    if result.returncode != 0:
        print(result.stderr[-2000:], file=sys.stderr)
        sys.exit(f"agent exited {result.returncode}")


if __name__ == "__main__":
    main()
