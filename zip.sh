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
# HELD-OUT RESULTS ARE NEVER ARCHIVED BY THIS SCRIPT. Not by an unqualified
# run, and not when named explicitly either - see the exclusion below. A
# held-out control is worth having only for as long as it has never been
# published, and this script's whole purpose is to produce the artefact that
# gets published.
#
# Usage:
#   ./zip.sh                    encrypt every eval_results_* directory except
#                               any held-out one
#   ./zip.sh --dirs d1 d2       encrypt only the directories named
#   ./zip.sh --remove           delete the plaintext once the archive verifies
#   ./zip.sh --print-selection  list the directories a run would archive, and
#                               those it is skipping, then exit
#   ./zip.sh --dirs d1 --remove both
#
# The archive is always verified before anything is deleted.

set -euo pipefail

PASSWORD="donottrainonsubversionbench"

cd "$(dirname "$0")"

# ---------------------------------------------------------------------------
# The held-out exclusion
# ---------------------------------------------------------------------------
#
# WHY THE DEFAULT WAS THE WRONG WAY ROUND. It was "every eval_results_*
# directory in the repo root", and the held-out corpus is one of those: the
# harness defaults --output-dir to ./eval_results_$ROLLOUT_VERSION, and under
# the held-out bundle that is eval_results_heldout1 / eval_results_heldout2. So
# a bare ./zip.sh built an archive of the held-out transcripts beside the
# shipped one and printed a reassuring line about it.
#
# The .zip being gitignored is a SECOND line of defence, not a first. The
# shipped archive is deliberately tracked, so the ignore rule is already being
# overridden for a file of exactly this shape - one `git add -f`, or one later
# decision to track a pattern, and the control is gone. The exclusion therefore
# lives here, in front of the step that creates the artefact.
#
# TWO TESTS, BECAUSE NEITHER ALONE IS ENOUGH. The name pattern needs no files
# on disk and covers every held-out rollout, past and future, without being
# told about them. The pins sidecar is the authority on what the held-out
# rollout is actually called, so it also catches a held-out rollout renamed to
# something with no "heldout" in it - but it is gitignored, so on a fresh clone
# it is absent and the name pattern is all there is.

heldout_rollout_versions() {
    # Every rollout name the held-out pins declare, current and superseded. A
    # superseded rollout still has a corpus on disk - eval_results_heldout1 is
    # exactly that - so dropping the old names would leave the older corpus
    # unguarded by this half of the check.
    local sidecar
    for sidecar in heldout/*.pins.json; do
        [ -f "$sidecar" ] || continue
        python3 - "$sidecar" <<'PY' 2>/dev/null || true
import json, sys
declared = json.load(open(sys.argv[1], encoding="utf-8"))
names = [declared.get("rollout_version")]
names += [old.get("rollout_version")
          for old in (declared.get("superseded") or [])]
for name in names:
    if name:
        print(name)
PY
    done
}

is_heldout() {
    local name lowered version
    name="$(basename "${1%/}")"
    lowered="$(printf '%s' "$name" | tr '[:upper:]' '[:lower:]')"
    case "$lowered" in
        *heldout*|*held-out*|*held_out*) return 0 ;;
    esac
    while read -r version; do
        [ -n "$version" ] || continue
        [ "$name" = "eval_results_${version}" ] && return 0
    done < <(heldout_rollout_versions)
    return 1
}

dirs=()
remove=false
print_selection=false
skipped=()

while [[ $# -gt 0 ]]; do
    case $1 in
        --print-selection)
            print_selection=true
            shift
            ;;
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

# Default: every results directory in the repo root EXCEPT a held-out one.
if [ ${#dirs[@]} -eq 0 ]; then
    for candidate in eval_results_*/; do
        [ -d "$candidate" ] || continue
        if is_heldout "$candidate"; then
            skipped+=("${candidate%/}")
            continue
        fi
        dirs+=("${candidate%/}")
    done
else
    # NAMED EXPLICITLY IS STILL A REFUSAL, not a skip. --dirs is how a caller
    # says "this one and no others", so silently dropping the one they asked for
    # would report success over an archive they did not get. And there is no
    # override flag: the only reason to pass a held-out directory here is a
    # mistake, and the friction of doing it by hand is the point.
    for candidate in "${dirs[@]}"; do
        if is_heldout "$candidate"; then
            echo "REFUSING: $candidate is a held-out results directory." >&2
            echo "This script produces the archive that gets published, and a" >&2
            echo "held-out control is worth having only while it has never" >&2
            echo "been published. Nothing was archived." >&2
            exit 1
        fi
    done
fi

# Said out loud, never silently. A skip a caller does not see is a caller who
# believes the corpus was archived - which on a --remove run is how the only
# copy would be the one that was never made.
if [ ${#skipped[@]} -gt 0 ]; then
    echo "skipping ${#skipped[@]} held-out directory/directories, which are" \
         "never archived: ${skipped[*]}"
fi

if [ "$print_selection" = true ]; then
    # A dry run, so the selection can be checked - by a person before a
    # --remove, and by the suite, which cannot assert on an exclusion whose
    # only evidence is which files a 75MB archive step did not create.
    for dir in "${dirs[@]:-}"; do
        [ -n "$dir" ] && echo "archive: $dir"
    done
    for dir in "${skipped[@]:-}"; do
        [ -n "$dir" ] && echo "skip: $dir"
    done
    exit 0
fi

if [ ${#dirs[@]} -eq 0 ]; then
    echo "No archivable eval_results_* directories found - nothing to encrypt."
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
