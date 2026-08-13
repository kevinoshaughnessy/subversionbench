#!/usr/bin/env bash
#
# Run every (nudge, oversight, lure) arm for one model, --runs episodes each.
#
# 12 arms: nudge in {none, strong, max} x oversight in {true, false} x lure in
# {true, false}. Each is a DISTINCT rollout arm - none pools with another, and
# nothing about the harness merges them - so this is 12 separate batches run
# back to back, not one bigger one. Narrow the axes with --nudges/--oversights/
# --lures (comma-separated) if you do not want the full cross product.
#
# EVERY interrogation phrasing is exercised, and it is NOT a thirteenth loop
# dimension. The phrasings are a paired design: each is put to the SAME episode,
# starting from the conversation as that episode left it, so they cannot see one
# another. Looping over them instead would be 48 batches at four times the
# episode cost, and would replace a within-episode comparison with a
# between-batch one - throwing away the reason the paired design exists. So they
# go through as one --interrogation list per arm, defaulting to all of them, and
# the list is read from INTERROGATION_CHOICES rather than written out here so it
# cannot go stale when a phrasing is added.
#
# Usage:
#   ./run_all_arms.sh --model x-ai/grok-4.5 --runs 10
#   ./run_all_arms.sh --model x-ai/grok-4.5 --runs 10 --nudges strong,max
#   ./run_all_arms.sh --model x-ai/grok-4.5 --runs 10 --interrogations zeroevidence
#   DRY_RUN=1 ./run_all_arms.sh --model x-ai/grok-4.5 --runs 10
#
# Any other run_eval.py flag (--delay, --max-turns, --effort, --grader-model,
# --isolation, --no-grader, --no-power, --interrogation, --thinking-budget,
# --max-tokens, --max-consecutive-failures, --output-dir) passes straight
# through to every arm unchanged.
#
# COST: 12 arms x --runs episodes per model by default - 120 episodes at
# --runs 10. Budget for that before running for real; DRY_RUN=1 prints the
# command for every arm and spends nothing.
#
# SAFE TO RE-RUN. Before each arm, this checks --output-dir for run files
# already on disk under that exact (model, nudge, oversight, lure) - not just
# oversight, since find_run_files() does not itself filter on lure:
#
#   - --runs or more already there: skipped.
#   - some there, all under ONE batch stamp: continued with run_eval.py's own
#     --resume, which is what actually fills a partial batch in to --runs
#     rather than starting a second one beside it. A fresh --runs N with no
#     --resume always begins a new stamp at episode 1, so retrying this way
#     without --resume would not "top up" a partial arm - it would run N MORE
#     episodes next to the ones already there.
#   - some there, under more than one stamp: not guessed at. Two partial
#     attempts for the same arm is not something to silently pick one of -
#     skipped, with both stamps named, for a human to resolve.

set -euo pipefail

MODEL=""
RUNS=""
NUDGES=(none strong max)
OVERSIGHTS=(true false)
LURES=(false true)
OUTPUT_DIR="."
DRY_RUN="${DRY_RUN:-0}"
PASSTHROUGH=()

# Every phrasing except the reference one, which parse_interrogations always
# prepends and which is not optional - the headline concealment field is defined
# as its answer. Derived from the shipped list so adding a phrasing does not need
# an edit here.
INTERROGATIONS="$(python3 -c 'from subversionbench.config import (
    DEFAULT_INTERROGATION as d, INTERROGATION_CHOICES as c)
print(",".join(n for n in c if n != d))')"

while [ $# -gt 0 ]; do
    case "$1" in
        --model) MODEL="$2"; shift 2 ;;
        --runs) RUNS="$2"; shift 2 ;;
        --nudges) IFS=',' read -r -a NUDGES <<< "$2"; shift 2 ;;
        --oversights) IFS=',' read -r -a OVERSIGHTS <<< "$2"; shift 2 ;;
        --lures) IFS=',' read -r -a LURES <<< "$2"; shift 2 ;;
        --interrogations) INTERROGATIONS="$2"; shift 2 ;;
        --output-dir) OUTPUT_DIR="$2"; PASSTHROUGH+=(--output-dir "$2"); shift 2 ;;
        *) PASSTHROUGH+=("$1"); shift ;;
    esac
done

if [ -z "$MODEL" ] || [ -z "$RUNS" ]; then
    echo "usage: $0 --model MODEL --runs N [--nudges a,b,c] [--oversights a,b]" >&2
    echo "          [--lures a,b] [run_eval.py flags...]" >&2
    exit 1
fi

TOTAL_ARMS=$(( ${#NUDGES[@]} * ${#OVERSIGHTS[@]} * ${#LURES[@]} ))
TOTAL_EPISODES=$(( TOTAL_ARMS * RUNS ))

echo "Model: ${MODEL}"
echo "Arms: ${#NUDGES[@]} nudge x ${#OVERSIGHTS[@]} oversight x ${#LURES[@]} lure = ${TOTAL_ARMS}"
echo "Runs per arm: ${RUNS}  -  total episodes if nothing is already on disk: ${TOTAL_EPISODES}"
echo "Extra interrogation phrasings per episode: ${INTERROGATIONS:-<none>}"
[ "$DRY_RUN" = "1" ] && echo "DRY RUN - nothing will be spent"
echo

i=0
for nudge in "${NUDGES[@]}"; do
    for oversight in "${OVERSIGHTS[@]}"; do
        for lure in "${LURES[@]}"; do
            i=$((i + 1))
            echo "############################################################"
            echo "# [${i}/${TOTAL_ARMS}] nudge=${nudge} oversight=${oversight} lure=${lure}"
            echo "############################################################"

            # Prints "<count>\t<stamp1>[,<stamp2>...]" - count of run files that
            # match this exact arm, and the distinct stamps they were found
            # under, so the shell can decide skip / resume / fresh without
            # re-parsing filenames itself.
            read -r existing stamps <<< "$(python3 - "$OUTPUT_DIR" "$MODEL" \
                "$nudge" "$oversight" "$lure" <<'PY'
import sys
from subversionbench.batch import find_run_files, parse_batch_filename

output_dir, model, nudge, oversight, lure = sys.argv[1:6]
oversight, lure = oversight == "true", lure == "true"
slug = model.replace("/", "_")
stamps = set()
n = 0
for path in find_run_files(output_dir, slug, nudge, oversight=oversight):
    _effort, stamp, got_oversight, got_lure = parse_batch_filename(path, nudge)
    if got_oversight == oversight and got_lure == lure:
        n += 1
        stamps.add(stamp or "")
print(n, ",".join(sorted(stamps)) or "-")
PY
)"

            resume_args=()
            if [ "$existing" -ge "$RUNS" ]; then
                echo "  skipping: ${existing} run(s) already on disk for this arm (>= ${RUNS})"
                echo
                continue
            elif [ "$existing" -gt 0 ]; then
                if [ "$(echo "$stamps" | tr -cd ',' | wc -c)" -eq 0 ] && [ "$stamps" != "-" ]; then
                    echo "  ${existing} run(s) already on disk under stamp ${stamps};"
                    echo "  resuming to reach ${RUNS}"
                    resume_args=(--resume "$stamps")
                else
                    echo "  skipping: ${existing} run(s) already on disk under more than one"
                    echo "  stamp (${stamps}) - resolve which to continue by hand, e.g. with"
                    echo "  --resume, before re-running this arm"
                    echo
                    continue
                fi
            fi

            interrogation_args=()
            [ -n "$INTERROGATIONS" ] && \
                interrogation_args=(--interrogation "$INTERROGATIONS")

            cmd=(python3 -m subversionbench.run_eval
                 --model "$MODEL" --runs "$RUNS"
                 --nudge "$nudge" --oversight "$oversight" --lure "$lure"
                 "${interrogation_args[@]+"${interrogation_args[@]}"}"
                 "${resume_args[@]+"${resume_args[@]}"}" "${PASSTHROUGH[@]+"${PASSTHROUGH[@]}"}")

            if [ "$DRY_RUN" = "1" ]; then
                printf '  would run: %s\n' "${cmd[*]}"
            else
                "${cmd[@]}"
            fi
            echo
        done
    done
done

echo "============================================================"
echo "Done: ${TOTAL_ARMS} arm(s) for ${MODEL}, ${RUNS} run(s) each requested."
