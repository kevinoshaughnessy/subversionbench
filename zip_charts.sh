#!/bin/bash
#
# Encrypt the charts/ directory, the same way zip.sh encrypts eval_results_*.
#
# charts/ carries no scenario text and no model transcript - see the
# .gitignore comment on it - so it does not need zip.sh's redaction step
# (subversionbench/export.py exists to strip host-identifying content out of
# saved JSON, and there is no JSON here to strip it from) or its held-out
# exclusion (a chart directory is never a held-out corpus). What it still
# needs is the same password gate: the images are pictures of rates this
# benchmark would rather a training crawl not index either, for the same
# crawler-friction reason zip.sh gives.
#
# A separate script rather than a branch in zip.sh, because the two directory
# shapes do not share a selection rule - zip.sh discovers every eval_results_*
# sibling and excludes held-out ones by name; this one has exactly one target.
# Forcing them through one argument parser would mean teaching zip.sh's
# is_heldout and the JSON redaction step to no-op for a chart directory,
# which is more surface than a second small script costs.
#
# Usage:
#   ./zip_charts.sh            encrypt charts/ -> charts.zip
#   ./zip_charts.sh --remove   delete the plaintext once the archive verifies

set -euo pipefail

cd "$(dirname "$0")"

# shellcheck source=zip_password.sh
source ./zip_password.sh

DIR="charts"
ARCHIVE="${DIR}.zip"
remove=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --remove)
            remove=true
            shift
            ;;
        -h|--help)
            sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'
            exit 0
            ;;
        *)
            echo "Unknown option: $1" >&2
            echo "Usage: $0 [--remove]" >&2
            exit 1
            ;;
    esac
done

if ! command -v zip >/dev/null 2>&1; then
    echo "zip is not installed." >&2
    exit 1
fi

if [ ! -d "$DIR" ]; then
    echo "No $DIR/ directory - nothing to encrypt. Run report/trends first." >&2
    exit 1
fi

count=$(find "$DIR" -name '*.png' | wc -l | tr -d ' ')
if [ "$count" -eq 0 ]; then
    echo "No .png files under $DIR/ - nothing to encrypt." >&2
    exit 1
fi

rm -f "$ARCHIVE"
zip -r -q --password "$PASSWORD" "$ARCHIVE" "$DIR" \
    -x '*.DS_Store' -x '__MACOSX/*'

# Verify before trusting it, the same discipline zip.sh applies - an archive
# that fails to open is worse than no archive, because it looks published.
if ! unzip -qq -P "$PASSWORD" -t "$ARCHIVE" >/dev/null 2>&1; then
    echo "FAILED: $ARCHIVE did not verify; plaintext left in place." >&2
    exit 1
fi

size=$(du -h "$ARCHIVE" | cut -f1 | tr -d ' ')
echo "encrypted $count chart(s) from $DIR/ -> $ARCHIVE ($size)"

if [ "$remove" = true ]; then
    rm -rf "$DIR"
    echo "  removed plaintext $DIR/"
fi
