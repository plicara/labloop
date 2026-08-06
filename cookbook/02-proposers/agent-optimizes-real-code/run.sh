#!/usr/bin/env bash
# The commands this recipe shows. Not run by CI: it needs the `claude` CLI,
# network, and a few minutes of an agent's time. See recipe.json ("tier":
# "narrative") and the "What this recipe does not prove" section.
set -euo pipefail

cp "$(dirname "$0")"/files/*.py .
git init -q .
git config user.email recipe@example.com
git config user.name recipe
printf 'labloop.jsonl\n__pycache__/\n' > .gitignore
git add -A
git commit -qm "identifier index over the stdlib, written once and never revisited"

export PYTHONDONTWRITEBYTECODE=1

# 1. How much does the metric move when nothing changes?
labloop noise --run "python bench.py" --metric seconds --repeat 6

# 2. Where are we starting from?
labloop baseline --run "python bench.py" --metric seconds \
  --protect bench.py --protect corpus.py

# 3. Let the agent work. The --min-delta comes from step 1, not from taste.
#    Note: keep run logs OUTSIDE the tree; a stray file trips the dirty-tree
#    interlock before the first trial starts.
labloop run --run "python bench.py" --metric seconds \
  --protect bench.py --protect corpus.py \
  --propose "python propose.py" \
  --min-delta 0.0727 --confirm \
  --budget 120 --propose-budget 300 --trials 5

labloop log --metric seconds
