#!/usr/bin/env bash
#
# Cut a release: check everything that can be checked, then tag.
#
#   scripts/publish.sh --dry-run     # rehearse; touches nothing
#   scripts/publish.sh               # date the changelog, commit, tag, push
#   scripts/publish.sh --rehearse    # ...and upload to TestPyPI first
#
# What it does NOT do is publish to PyPI. `publish.yml` does that, triggered by
# a GitHub Release being published — so this script ends by handing you the
# release to create. That split is deliberate: PyPI version numbers are
# permanent, and the last step before one becomes permanent should be a human
# looking at the release notes.
#
# Everything before the tag is reversible. Everything after it is not, so all
# the refusals live up front.

set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

REPO="foothills-labs/labloop"
PACKAGE="labloop"
BRANCH="main"
VERSION_FILE="src/labloop/__init__.py"

DRY_RUN=0
REHEARSE=0
ASSUME_YES=0
for arg in "$@"; do
  case "$arg" in
    --dry-run)  DRY_RUN=1 ;;
    --rehearse) REHEARSE=1 ;;
    --yes|-y)   ASSUME_YES=1 ;;
    --help|-h)  awk 'NR>1 && !/^#/ {exit} NR>1 {sub(/^# ?/, ""); print}' \
                  "${BASH_SOURCE[0]}"; exit 0 ;;
    *) echo "unknown option: $arg (try --help)" >&2; exit 2 ;;
  esac
done

say()  { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
ok()   { printf '    ✓ %s\n' "$*"; }
die()  { printf '\n\033[1;31mstopped:\033[0m %s\n' "$*" >&2; exit 1; }

run() {  # echo in dry-run, execute otherwise
  if [ "$DRY_RUN" = 1 ]; then printf '    would run: %s\n' "$*"; else "$@"; fi
}

confirm() {
  [ "$ASSUME_YES" = 1 ] && return 0
  [ "$DRY_RUN" = 1 ] && return 0
  printf '\n%s [y/N] ' "$1"
  read -r reply
  case "$reply" in [yY]*) return 0 ;; *) die "cancelled" ;; esac
}

# ---------------------------------------------------------------- preflight

say "Preflight"

command -v python3 >/dev/null || die "python3 not found"

VERSION=$(python3 - "$VERSION_FILE" <<'PY'
import pathlib, re, sys
text = pathlib.Path(sys.argv[1]).read_text()
match = re.search(r'^__version__ = "([^"]+)"', text, re.M)
if not match:
    sys.exit(f"no __version__ found in {sys.argv[1]}")
print(match.group(1))
PY
)
TAG="v$VERSION"
ok "version $VERSION (tag $TAG)"

current=$(git rev-parse --abbrev-ref HEAD)
[ "$current" = "$BRANCH" ] || die "on branch '$current'; releases are cut from '$BRANCH'"
ok "on $BRANCH"

git diff --quiet && git diff --cached --quiet || die \
  "working tree has uncommitted changes; commit or stash them first"
ok "working tree clean"

git fetch --quiet origin "$BRANCH" --tags
[ "$(git rev-parse HEAD)" = "$(git rev-parse "origin/$BRANCH")" ] || die \
  "local $BRANCH and origin/$BRANCH have diverged; pull or push first"
ok "in step with origin/$BRANCH"

# A tag is cheap to delete locally and expensive to delete once anyone has
# fetched it, so refuse rather than move one.
if git rev-parse -q --verify "refs/tags/$TAG" >/dev/null; then
  die "tag $TAG already exists locally; bump $VERSION_FILE or delete the tag"
fi
if git ls-remote --exit-code --tags origin "refs/tags/$TAG" >/dev/null 2>&1; then
  die "tag $TAG already exists on origin; bump the version in $VERSION_FILE"
fi
ok "$TAG is free"

# The one genuinely permanent check: PyPI never lets a version be reused, even
# after deletion.
if curl -fsS -o /dev/null "https://pypi.org/pypi/$PACKAGE/$VERSION/json" 2>/dev/null; then
  die "$PACKAGE $VERSION is already on PyPI. That number is permanent — bump it."
fi
ok "$PACKAGE $VERSION is not on PyPI"

python3 -c 'import build, twine' 2>/dev/null || die \
  "build and twine are needed: pip install build twine"
for tool in pytest ruff mypy; do
  command -v "$tool" >/dev/null || die \
    "$tool not found; install the dev extras: pip install -e \".[dev]\""
done
# Checked separately so a fresh clone gets this instead of an ImportError
# raised from inside tests/conftest.py.
python3 -c 'import labloop' 2>/dev/null || die \
  "labloop is not importable; install it first: pip install -e \".[dev]\""
ok "build, twine, the dev tools, and labloop itself are present"

# ------------------------------------------------------------------- checks

say "Checks"
run pytest -q
run ruff check .
run mypy
ok "tests, lint and types"

# -------------------------------------------------------------------- build

say "Build"
run rm -rf dist build
run python3 -m build
run python3 -m twine check dist/*

# twine check validates metadata, not that the wheel contains the package. A
# packaging mistake passes it and fails on the user's first command, so drive
# the built artifact end to end the way CI does.
say "Smoke test the built wheel"
if [ "$DRY_RUN" = 1 ]; then
  printf '    would install dist/*.whl into a clean venv and drive it\n'
else
  smoke=$(mktemp -d)
  python3 -m venv "$smoke/venv"
  "$smoke/venv/bin/pip" install --quiet dist/*.whl
  (
    cd "$smoke"
    git init -q . && git config user.email release@test && git config user.name release
    echo 'print("val_loss = 2.0")' > train.py
    echo 'frozen' > eval.py
    printf 'labloop.jsonl\n__pycache__/\n' > .gitignore
    git add -A && git commit -qm init
    export PYTHONDONTWRITEBYTECODE=1
    L="$smoke/venv/bin/labloop"
    installed=$("$L" --version)
    [ "$installed" = "$PACKAGE $VERSION" ] || {
      echo "installed wheel reports '$installed', expected '$PACKAGE $VERSION'"; exit 1; }
    "$L" noise --run "python train.py" --metric val_loss --repeat 2 >/dev/null
    "$L" baseline --run "python train.py" --metric val_loss --protect eval.py >/dev/null
    "$L" run --run "python train.py" --metric val_loss --protect eval.py \
        --propose 'echo "print(\"val_loss = 1.0\")" > train.py' --trials 1 >/dev/null
    "$L" run --run "python train.py" --metric val_loss --protect eval.py \
        --propose 'echo cheat > eval.py' --trials 1 >/dev/null
    grep -q harness_changed labloop.jsonl || { echo "harness check did not fire"; exit 1; }
    [ "$(git log --oneline | wc -l | tr -d ' ')" = "2" ] || {
      echo "expected exactly one kept commit"; exit 1; }
  ) || die "the built wheel failed its smoke test"
  rm -rf "$smoke"
  ok "installed wheel reports $VERSION and drives a real loop"
fi

# ----------------------------------------------------------------- TestPyPI

if [ "$REHEARSE" = 1 ]; then
  say "Rehearse on TestPyPI"
  run python3 -m twine upload --repository testpypi dist/*
  if [ "$DRY_RUN" = 0 ]; then
    rehearsal=$(mktemp -d)
    python3 -m venv "$rehearsal/venv"
    "$rehearsal/venv/bin/pip" install --quiet \
      --index-url https://test.pypi.org/simple/ \
      --extra-index-url https://pypi.org/simple/ "$PACKAGE==$VERSION"
    "$rehearsal/venv/bin/labloop" --version
    rm -rf "$rehearsal"
    ok "installs from TestPyPI"
  fi
fi

# ---------------------------------------------------------------- changelog

say "Changelog"
DATE=$(date +%F)
changelog_state=$(python3 - "$VERSION" "$DATE" <<'PY'
import datetime, pathlib, re, sys
version, date = sys.argv[1], sys.argv[2]
path = pathlib.Path("CHANGELOG.md")
text = path.read_text()

unreleased = f"## {version} — unreleased"
dated = f"## {version} — {date}"

if unreleased in text:
    path.write_text(text.replace(unreleased, dated, 1))
    print("dated")
elif re.search(rf"^## {re.escape(version)} — \d{{4}}-\d{{2}}-\d{{2}}$", text, re.M):
    print("already-dated")
else:
    sys.exit(
        f"CHANGELOG.md has no '## {version} — unreleased' heading and no dated "
        f"one either. Add the section before releasing."
    )
PY
)
NEEDS_CHANGELOG_COMMIT=0
case "$changelog_state" in
  dated)
    ok "dated the $VERSION heading $DATE"
    NEEDS_CHANGELOG_COMMIT=1
    if [ "$DRY_RUN" = 1 ]; then
      git checkout -- CHANGELOG.md   # leave no trace in a rehearsal
      printf '    (reverted, this is a dry run)\n'
    fi
    ;;
  already-dated) ok "$VERSION heading already dated" ;;
esac

# Release notes are the changelog section, so the two cannot disagree.
NOTES=$(python3 - "$VERSION" <<'PY'
import pathlib, re, sys
version = sys.argv[1]
text = pathlib.Path("CHANGELOG.md").read_text()
match = re.search(rf"^## {re.escape(version)} — .*?$(.*?)(?=^## |\Z)", text, re.M | re.S)
print(match.group(1).strip() if match else "")
PY
)

# ------------------------------------------------------------------ release

say "Ready to release $PACKAGE $TAG"
printf '    This will commit the changelog, push %s, and push the tag.\n' "$BRANCH"
printf '    Publishing to PyPI happens when you create the GitHub Release.\n'
confirm "Tag and push $TAG?"

if [ "$NEEDS_CHANGELOG_COMMIT" = 1 ]; then
  run git commit -q -m "Date the $VERSION release" CHANGELOG.md
  run git push origin "$BRANCH"
  ok "changelog dated and pushed"
fi

run git tag -a "$TAG" -m "$PACKAGE $VERSION"
run git push origin "$TAG"
ok "tagged $TAG"

say "Last step: create the GitHub Release"
if command -v gh >/dev/null 2>&1; then
  printf '    gh is installed. Creating the release publishes to PyPI.\n'
  confirm "Create the GitHub Release for $TAG now?"
  if [ "$DRY_RUN" = 1 ]; then
    printf '    would run: gh release create %s --title "%s %s" --notes ...\n' \
      "$TAG" "$PACKAGE" "$VERSION"
  else
    printf '%s\n' "$NOTES" | gh release create "$TAG" \
      --repo "$REPO" --title "$PACKAGE $VERSION" --notes-file -
    ok "release published — watch the run: gh run watch"
  fi
else
  cat <<EOF

    gh is not installed, so create it in the browser:

      https://github.com/$REPO/releases/new?tag=$TAG

    Title:  $PACKAGE $VERSION
    Notes:  the $VERSION section of CHANGELOG.md

    Publishing the release triggers publish.yml, which builds and uploads to
    PyPI via trusted publishing. Then verify what actually shipped:

      python3 -m venv /tmp/verify
      /tmp/verify/bin/pip install $PACKAGE==$VERSION
      /tmp/verify/bin/labloop --version

EOF
fi
