"""Drive Claude Code as the proposer for the prompt-optimization task.

Note what the agent is *not* told: what is in the eval set. It sees the score
and the history, never the cases. That asymmetry is the whole point -- an
optimiser that can read the answer key optimises the answer key.
"""

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
        "Improve `prompt.txt`. It is the system prompt for a support-triage",
        "task: given a customer message, the model must return a category",
        "(billing, shipping, technical, account, refund, other), an urgency",
        "(low, normal, high), and the order id if the message mentions one.",
        "",
        "Rules:",
        "  - Edit ONLY prompt.txt. Do not touch evaluate.py or eval_set.py --",
        "    those are the measurement, and reading them would be cheating",
        "    rather than solving.",
        "  - The scorer is forgiving about format: it accepts a JSON object",
        "    anywhere in the reply, or `field: value` lines.",
        "  - Run `python evaluate.py` to score your prompt. It takes about a",
        "    minute.",
        "",
        f"The metric is `{brief.get('metric', 'accuracy')}` (mean field accuracy",
        "over held-out cases) and higher is better.",
    ]

    if brief.get("incumbent") is not None:
        lines.append(f"The score to beat is {brief['incumbent']:.6f}.")
    else:
        lines.append("This is the first attempt; there is no score to beat yet.")

    history = brief.get("history", [])
    if history:
        lines += ["", "What has already been tried, most recent last:"]
        for h in history[-8:]:
            lines.append(f"  - trial {h['index']}: {h['why']}")

    lines += [
        "",
        "Make one focused change. Think about what the model is most likely",
        "getting wrong given the score, not about rewriting everything.",
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
