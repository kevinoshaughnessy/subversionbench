#!/bin/bash
#
# Decrypt SubversionBench result files encrypted by ./zip.sh.
#
# Usage:
#   ./unzip.sh                    decrypt every eval_results_*.zip
#   ./unzip.sh --dirs a.zip b.zip decrypt only the archives named
#   ./unzip.sh --force            overwrite existing plaintext without asking
#
# Without --force an archive whose plaintext directory already exists is
# skipped, so a decrypt cannot quietly clobber results that have been
# reclassified or otherwise updated since they were archived.

set -euo pipefail

PASSWORD="donottrainonsubversionbench"

cd "$(dirname "$0")"

archives=()
force=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --dirs)
            shift
            while [[ $# -gt 0 ]] && [[ $1 != --* ]]; do
                archives+=("$1")
                shift
            done
            ;;
        --force)
            force=true
            shift
            ;;
        -h|--help)
            sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'
            exit 0
            ;;
        *)
            echo "Unknown option: $1" >&2
            echo "Usage: $0 [--dirs <archive> ...] [--force]" >&2
            exit 1
            ;;
    esac
done

if [ ${#archives[@]} -eq 0 ]; then
    for candidate in eval_results_*.zip; do
        [ -f "$candidate" ] && archives+=("$candidate")
    done
fi

if [ ${#archives[@]} -eq 0 ]; then
    echo "No eval_results_*.zip archives found - nothing to decrypt."
    exit 0
fi

if ! command -v unzip >/dev/null 2>&1; then
    echo "unzip is not installed." >&2
    exit 1
fi

for archive in "${archives[@]}"; do
    if [ ! -f "$archive" ]; then
        echo "skip: $archive not found"
        continue
    fi

    target="${archive%.zip}"
    if [ -d "$target" ] && [ "$force" = false ]; then
        echo "skip: $target/ already exists (pass --force to overwrite)"
        continue
    fi

    if ! unzip -qq -o -P "$PASSWORD" "$archive"; then
        echo "FAILED: could not decrypt $archive - wrong password?" >&2
        exit 1
    fi

    count=$(find "$target" -name '*.json' 2>/dev/null | wc -l | tr -d ' ')
    echo "decrypted $archive -> $target/ ($count JSON file(s))"
done

echo
echo "Plaintext transcripts are now on disk. They are gitignored; re-run"
echo "./zip.sh before sharing this directory anywhere."
