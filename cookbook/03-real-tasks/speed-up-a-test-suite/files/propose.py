"""Drive Claude Code as the proposer for the test-suite task."""

import json
import os
import pathlib
import subprocess
import sys

AGENT_BUDGET_SECONDS = 300


def read_brief():
    path = os.environ.get("LABLOOP_BRIEF")
    if not path or not os.path.exists(path):
        return {}
    return json.loads(pathlib.Path(path).read_text())


def prompt_from(brief):
    lines = [
        "Make this project's pytest suite run faster.",
        "",
        "Rules:",
        "  - Edit ONLY files under tests/. Do not touch bench.py,",
        "    acceptance_test.py, or invoices.py.",
        "  - All 53 tests must still run and pass. Deleting, skipping,",
        "    deselecting or xfailing a test is a failure, not a speedup:",
        "    bench.py checks the count.",
        "  - The tests must still prove what they prove now. invoices.py is",
        "    the real library and its costs are real; make the *tests* stop",
        "    paying them unnecessarily.",
        "  - Run `python bench.py` to check your work before finishing.",
        "",
        f"The metric is `{brief.get('metric', 'seconds')}` and lower is better.",
    ]

    if brief.get("incumbent") is not None:
        lines.append(f"The time to beat is {brief['incumbent']:.4f} seconds.")
    else:
        lines.append("This is the first attempt; there is no time to beat yet.")

    history = brief.get("history", [])
    if history:
        lines += ["", "What has already been tried, most recent last:"]
        for h in history[-8:]:
            lines.append(f"  - trial {h['index']}: {h['why']}")
        tail = history[-1].get("output_tail")
        if tail:
            lines += ["", "The last attempt's output ended with:"]
            lines += ["```", tail.strip()[-1200:], "```"]

    lines += [
        "",
        "Make one focused change. A smaller change that is measurably faster",
        "is worth more than a large one that fails the checks.",
    ]
    return "\n".join(lines)


def main():
    brief = read_brief()
    prompt = prompt_from(brief)
    print(f"--- trial {brief.get('trial', '?')} ---\n{prompt}\n", file=sys.stderr)

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
