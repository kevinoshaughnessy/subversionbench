#!/bin/bash
#
# Encrypt SubversionBench result files.
#
# Run transcripts contain the full scenario text and the models' responses to
# it. If they reach a training corpus the benchmark is burned: a model trained
# on them has seen the memo, the monitoring config and the interrogation
# questions, and its eval-awareness rate stops meaning anything. Password
# protection is not security - the password is published in the README - it is
# there so that crawlers and dataset-scraping pipelines cannot read the
# contents, in the same way SAD and BIG-bench guard their test sets.
#
# Usage:
#   ./zip.sh                    encrypt every eval_results_* directory
#   ./zip.sh --dirs d1 d2       encrypt only the directories named
#   ./zip.sh --remove           delete the plaintext once the archive verifies
#   ./zip.sh --dirs d1 --remove both
#
# The archive is always verified before anything is deleted.

set -euo pipefail

PASSWORD="donottrainonsubversionbench"

cd "$(dirname "$0")"

dirs=()
remove=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --dirs)
            shift
            while [[ $# -gt 0 ]] && [[ $1 != --* ]]; do
                dirs+=("$1")
                shift
            done
            ;;
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
            echo "Usage: $0 [--dirs <dir> ...] [--remove]" >&2
            exit 1
            ;;
    esac
done

# Default: every results directory in the repo root.
if [ ${#dirs[@]} -eq 0 ]; then
    for candidate in eval_results_*/; do
        [ -d "$candidate" ] && dirs+=("${candidate%/}")
    done
fi

if [ ${#dirs[@]} -eq 0 ]; then
    echo "No eval_results_* directories found - nothing to encrypt."
    exit 0
fi

if ! command -v zip >/dev/null 2>&1; then
    echo "zip is not installed." >&2
    exit 1
fi

# Refuse to touch a directory a batch is still writing to. Archiving a live
# results directory captures a partial batch, and --remove would delete
# episodes written after the archive was made.
for dir in "${dirs[@]}"; do
    dir="${dir%/}"
    [ -d "$dir" ] || continue
    if [ -n "$(find "$dir" -name '*.json' -newermt '-2 minutes' 2>/dev/null)" ]; then
        echo "REFUSING: $dir has files written in the last 2 minutes - a batch" >&2
        echo "may still be running. Wait for it to finish, or pass --dirs to" >&2
        echo "archive something else." >&2
        exit 1
    fi
done

for dir in "${dirs[@]}"; do
    dir="${dir%/}"
    if [ ! -d "$dir" ]; then
        echo "skip: $dir is not a directory"
        continue
    fi

    count=$(find "$dir" -name '*.json' | wc -l | tr -d ' ')
    archive="${dir}.zip"

    # Redact into a staging copy, and archive THAT.
    #
    # The corpus keeps its real paths: `messages` holds the conversation an episode
    # ended with, and re-interrogating a saved episode needs the bytes the model
    # actually saw. The archive is the only thing that leaves this machine, so the
    # archive is what gets cleaned. See subversionbench/export.py.
    staging=$(mktemp -d)
    if ! python3 -m subversionbench.export --dir "$dir" --into "$staging"; then
        echo "FAILED: could not redact $dir; nothing archived." >&2
        rm -rf "$staging"
        exit 1
    fi

    rm -f "$archive"
    # From inside the staging dir, so entries are named "$dir/..." and unzip
    # recreates the directory the corpus came from.
    archive_abs="$PWD/$archive"
    ( cd "$staging" && zip -r -q --password "$PASSWORD" "$archive_abs" "$dir" \
        -x '*.DS_Store' -x '__MACOSX/*' )
    rm -rf "$staging"

    # Verify before trusting it with the only copy.
    if ! unzip -qq -P "$PASSWORD" -t "$archive" >/dev/null 2>&1; then
        echo "FAILED: $archive did not verify; plaintext left in place." >&2
        exit 1
    fi

    # And verify it is CLEAN, on the unpacked archive rather than the staging copy,
    # so the check tests what is actually published. A silent leak here would ship:
    # the password is published by design, so nothing in the archive is protected.
    check=$(mktemp -d)
    unzip -qq -P "$PASSWORD" "$archive" -d "$check"
    if ! python3 -m subversionbench.export --verify "$check"; then
        rm -rf "$check"
        rm -f "$archive"
        echo "FAILED: $archive still identified the host; archive deleted." >&2
        exit 1
    fi
    rm -rf "$check"

    size=$(du -h "$archive" | cut -f1 | tr -d ' ')
    echo "encrypted $count JSON file(s) from $dir -> $archive ($size)"

    if [ "$remove" = true ]; then
        rm -rf "$dir"
        echo "  removed plaintext $dir/"
    fi
done

if [ "$remove" = false ]; then
    echo
    echo "Plaintext directories are still present. They are gitignored, but"
    echo "pass --remove once you are happy with the archives if you want them"
    echo "gone from disk."
fi
