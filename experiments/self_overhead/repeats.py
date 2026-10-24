"""Score repeated attempts per direction from proposer transcripts.

Usage: repeats.py LEDGER EVIDENCE_ROOT EVIDENCE_PREFIX REPO START_COMMIT [--skip OUTCOME]

Transcripts are read from EVIDENCE_ROOT/EVIDENCE_PREFIX-<direction>/trial-<n>.jsonl,
the stream-json output of the headless Claude Code proposer used in the
dogfood runs. `--skip harness_changed` leaves out trials voided rather than
judged; run 1 needed it for three trials an operator-written .pyc voided.

For each trial, replay the proposer's Edit/Write calls against the file
contents at that trial's base commit (the direction's latest kept commit, or
its fork point), and name the enclosing def/class of each edit. A trial is a
location repeat if it touches a (file, definition) an earlier non-kept trial
in the same direction touched. Same method for every run, so runs compare.
"""

import json
import re
import subprocess
import sys
from pathlib import Path

ledger_path, evid_root, prefix, repo = sys.argv[1:5]
DEF = re.compile(r"^\s*(?:async\s+)?(?:def|class)\s+(\w+)")


def git_show(commit, path):
    r = subprocess.run(["git", "show", f"{commit}:{path}"], cwd=repo, capture_output=True,
                       text=True)
    return r.stdout if r.returncode == 0 else ""


def enclosing(text, offset):
    line_no = text.count("\n", 0, offset)
    lines = text.splitlines()
    for i in range(min(line_no, len(lines) - 1), -1, -1):
        m = DEF.match(lines[i])
        if m:
            return m.group(1)
    return "<module>"


rows = [json.loads(line) for line in open(ledger_path)]
trials = [r for r in rows if "outcome" in r]
start = sys.argv[5]
skip = set(sys.argv[sys.argv.index("--skip") + 1:]) if "--skip" in sys.argv else set()
trials = [t for t in trials if t["outcome"] not in skip]

results = {}
for direction in sorted({t.get("direction") for t in trials} - {"main", None}):
    mine = [t for t in trials if t.get("direction") == direction]
    base = start
    tried_bad: set = set()
    out = []
    for t in mine:
        f = Path(evid_root) / f"{prefix}-{direction}" / f"trial-{t['index']}.jsonl"
        touched = set()
        files: dict[str, str] = {}
        if f.exists():
            for line in f.open():
                try:
                    e = json.loads(line)
                except ValueError:
                    continue
                if e.get("type") != "assistant":
                    continue
                for c in e["message"]["content"]:
                    if c.get("type") != "tool_use" or c["name"] not in ("Edit", "Write"):
                        continue
                    inp = c["input"]
                    path = inp.get("file_path", "")
                    rel = path.split("/src/", 1)[-1]
                    rel = "src/" + rel if "/src/" in path else Path(path).name
                    if rel not in files:
                        files[rel] = git_show(base, rel)
                    text = files[rel]
                    if c["name"] == "Write":
                        touched.add((rel, "<whole file>"))
                        files[rel] = inp.get("content", "")
                        continue
                    old, new = inp.get("old_string", ""), inp.get("new_string", "")
                    at = text.find(old) if old else -1
                    touched.add((rel, enclosing(text, at) if at >= 0 else "<unlocated>"))
                    if at >= 0:
                        files[rel] = text[:at] + new + text[at + len(old):]
        repeat = bool(touched & tried_bad)
        out.append({"index": t["index"], "outcome": t["outcome"], "metric": t.get("metric"),
                    "touched": sorted(touched), "repeat": repeat})
        if t["outcome"] == "kept":
            base = t.get("commit") or base
        else:
            tried_bad |= touched
    results[direction] = out

for direction, out in results.items():
    rest = out[1:]
    rev = [o for o in out if o["outcome"] != "kept"]
    rep_all = sum(o["repeat"] for o in rest)
    rep_rev = sum(o["repeat"] for o in rev)
    kept = sum(o["outcome"] == "kept" for o in out)
    print(f"== {direction}: {len(out)} trials, {kept} kept; location repeats "
          f"{rep_all}/{len(rest)} of trials after the first, {rep_rev}/{len(rev)} of non-kept")
    for o in out:
        where = ", ".join(f"{p.split('/')[-1]}:{d}" for p, d in o["touched"])
        print(f"  t{o['index']:>2} {o['outcome']:<16} {'R' if o['repeat'] else ' '} {where}")
