"""Drive Claude Code as the proposer for the retrieval task."""

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
        "Improve retrieval quality in `retrieve.py`. It searches a corpus of",
        "Python standard-library module documentation, and the queries are",
        "phrased the way people ask questions rather than the way docs are",
        "written.",
        "",
        "Rules:",
        "  - Edit ONLY retrieve.py. Do not touch evaluate.py, queries.py or",
        "    corpus.py -- those are the measurement.",
        "  - Standard library only. No new dependencies.",
        "  - Run `python evaluate.py` to check your work, and",
        "    `python evaluate.py --detail` to see which queries score worst.",
        "",
        f"The metric is `{brief.get('metric', 'ndcg')}` (nDCG@10) and higher is better.",
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
        tail = history[-1].get("output_tail")
        if tail:
            lines += ["", "The last attempt's output ended with:"]
            lines += ["```", tail.strip()[-1200:], "```"]

    lines += [
        "",
        "Make one focused change. A smaller change that measurably scores",
        "better is worth more than a rewrite that does not.",
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
