#!/usr/bin/env bash
# Exactly the commands the README shows. CI runs this file, so the two cannot
# drift: a command in the prose that is not here is a build failure.
set -euo pipefail

cp "$(dirname "$0")"/files/*.py .
git init -q .
git config user.email recipe@example.com
git config user.name recipe
printf 'labloop.jsonl\n__pycache__/\n' > .gitignore
git add -A
git commit -qm "spam classifier, before any tuning"

export PYTHONDONTWRITEBYTECODE=1

labloop noise --run "python train.py" --metric val_loss --repeat 3

labloop baseline --run "python train.py" --metric val_loss \
  --protect evaluate.py --protect data.py

labloop run --run "python train.py" --metric val_loss \
  --protect evaluate.py --protect data.py \
  --propose "python propose.py" --trials 6

labloop log --metric val_loss
