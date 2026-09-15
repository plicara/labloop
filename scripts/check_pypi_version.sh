#!/usr/bin/env bash
#
# The one genuinely permanent check: PyPI never lets a version be reused,
# even after deletion. A forgotten bump must fail the gate, not the upload.
#
#   scripts/check_pypi_version.sh PACKAGE VERSION
#
# Exit 0: the version is not on PyPI. Exit 1: it is already there, or PyPI
# could not be checked — treat an unverifiable state as unavailable to
# publish, never the reverse.

set -euo pipefail

PACKAGE="${1:?usage: check_pypi_version.sh PACKAGE VERSION}"
VERSION="${2:?usage: check_pypi_version.sh PACKAGE VERSION}"

status=$(curl -sS -o /dev/null -w '%{http_code}' --connect-timeout 10 --max-time 30 \
  "https://pypi.org/pypi/$PACKAGE/$VERSION/json") || {
  echo "could not check PyPI" >&2; exit 1; }
case "$status" in
  200) echo "$PACKAGE $VERSION is already on PyPI. That number is permanent — bump it." >&2; exit 1 ;;
  404) ;;
  *) echo "could not check PyPI (HTTP $status)" >&2; exit 1 ;;
esac
