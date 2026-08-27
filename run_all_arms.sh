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
# Matches run_eval.py's own default exactly, sourced rather than duplicated
# as a literal - a mismatched default here is not cosmetic. This script's
# own existing-file check reads OUTPUT_DIR directly; run_eval.py falls back
# to ITS default whenever --output-dir is not passed to it. Before this, the
# two defaults were different strings ("." here, "./eval_results_r9" there),
# so a run with no --output-dir flag checked an empty current directory,
# found nothing, and silently re-collected every arm while run_eval.py went
# on writing into eval_results_r9 as it always had - the skip/resume logic
# never engaged at all. A real batch was re-run this way before it was caught.
OUTPUT_DIR="./eval_results_$(python3 -c \
    'from subversionbench.config import ROLLOUT_VERSION; print(ROLLOUT_VERSION)')"
DRY_RUN="${DRY_RUN:-0}"
PASSTHROUGH=()
FAILED_ARMS=()

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
        --output-dir) OUTPUT_DIR="$2"; shift 2 ;;
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

# STOPPING THE BATCH IS NOT THE SAME AS ONE ARM FAILING
#
# The `if ! "${cmd[@]}"` guard in the loop below deliberately keeps a single bad
# arm from ending the batch, so that a model having a rough patch on one arm
# does not silently skip the eleven after it. An operator asking to stop is the
# opposite intent and must not be absorbed by that guard.
#
# Measured rather than assumed, because bash's signal handling here is not
# obvious (see test_run_all_arms.py, which pins the trappable cases):
#
#   Ctrl-C (SIGINT) reaches the whole foreground process group and did already
#   stop the loop before this trap existed - the arm dies, and bash's own
#   default action ends the script. That case was never broken.
#
#   A signal delivered to THIS SCRIPT alone was swallowed: the arm kept running
#   to completion, the guard saw an ordinary non-zero exit, and the next arm
#   started. That is what this trap fixes.
#
#   A plain SIGTERM ended the script mid-arm saying nothing about what had been
#   collected or how to resume.
#
# CTRL-Z DOES NOT STOP THIS BATCH, and on a long paid run that is the expensive
# mistake. Ctrl-Z sends SIGTSTP, which SUSPENDS: the arm in flight stops, the
# script makes no further progress, and nothing is spent while it sits there -
# so it looks stopped. It is not. The moment anything continues it - `fg`, `bg`,
# or SIGCONT - every remaining arm runs to completion and the script exits 0, as
# though the interruption never happened. Measured, not inferred.
#
# So SIGTSTP is deliberately NOT trapped here. Trapping it to exit would take
# away a legitimate pause, and trapping it to warn-then-suspend depends on a
# disposition this script inherits rather than controls: a signal ignored on
# entry to a shell cannot be trapped or reset, and job control is off in a
# non-interactive script. Documented instead, because a warning that fires on
# some invocations and not others is worse than a comment that always applies.
#
# To actually stop a batch: Ctrl-C, or `kill -INT <pid>`, or `kill <pid>`.
#
# A SIGNAL THAT REACHES ONLY THE ARM is the case this trap cannot see, and it is
# the common one: when SIGINT is ignored on entry (below), Ctrl-C never reaches
# this script at all. run_eval.py used to return 0 or 1 whether it was
# interrupted or merely failed, so the guard read an ordinary failed arm and
# started the next. It now returns EXIT_INTERRUPTED (130) for an interrupt
# specifically, and the arm guard in the loop stops the batch on it.
stop_batch() {
    echo
    echo "============================================================"
    echo "Stopped by $1. The arm in progress was not completed."
    echo "Everything already written is reusable: re-run this script with no"
    echo "--resume to pick up wherever it left off."
    echo "============================================================"
    exit "$2"
}
trap 'stop_batch SIGINT 130' INT
trap 'stop_batch SIGTERM 143' TERM

# SAY SO WHEN CTRL-C CANNOT WORK, RATHER THAN LETTING IT BE DISCOVERED
#
# A signal ignored on entry to a shell may not be trapped or reset, and that is
# the disposition a background job of a NON-INTERACTIVE shell inherits. When it
# applies, the trap above silently does not install: Ctrl-C then reaches only
# the arm's own process, run_eval.py obeys it, and the guard below starts the
# next arm - which is indistinguishable, from the terminal, from the interrupt
# having been ignored.
#
# Detected by asking whether the trap READBACK NAMES OUR HANDLER, which is the
# only form of the question both shells answer the same way. Measured on each,
# because the two report an inherited-ignored SIGINT differently and a check
# written against either one alone is wrong on the other:
#
#                              trap -p INT, after installing a handler
#   bash 3.2 (macOS)   ignored: <empty>              installed: trap -- 'h' SIGINT
#   bash 5.2 (Linux)   ignored: trap -- '' SIGINT    installed: trap -- 'h' SIGINT
#
# Neither shell FIRES the trap when the signal was ignored on entry, so the
# behaviour is the same and only the spelling differs. Testing for an empty
# readback - which is what this did first - reported the state correctly on
# macOS and silently never warned on Linux.
case "$(trap -p INT)" in
    *stop_batch*) ;;                 # installed, and will actually fire
    *)
        echo "NOTE: SIGINT was already ignored when this script started, so Ctrl-C"
        echo "      cannot stop it - bash may not trap a signal it inherited as"
        echo "      ignored. Ctrl-C will kill the ARM in progress, and this"
        echo "      script will carry on to the next one."
        echo "      To stop the whole batch:  kill $$"
        echo
        ;;
esac

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

            # --output-dir is always explicit here, never left to run_eval.py's
            # own default - that default and this script's are sourced from the
            # same place above, but a subprocess falling back to its own copy
            # is exactly the split that let the two drift apart before.
            cmd=(python3 -m subversionbench.run_eval
                 --model "$MODEL" --runs "$RUNS"
                 --nudge "$nudge" --oversight "$oversight" --lure "$lure"
                 --output-dir "$OUTPUT_DIR"
                 "${interrogation_args[@]+"${interrogation_args[@]}"}"
                 "${resume_args[@]+"${resume_args[@]}"}" "${PASSTHROUGH[@]+"${PASSTHROUGH[@]}"}")

            if [ "$DRY_RUN" = "1" ]; then
                printf '  would run: %s\n' "${cmd[*]}"
            else
                # set -e makes an unguarded "${cmd[@]}" fatal to this WHOLE
                # script the moment one arm exits non-zero - which run_eval.py
                # does deliberately on its own abort (--max-consecutive-
                # failures, an auth failure). A model having a rough patch on
                # one arm used to silently end the batch there: every arm
                # after it in the loop, however unrelated, was never even
                # attempted. This script's own header says "SAFE TO RE-RUN" -
                # that has to be true of one arm failing mid-batch too, not
                # just of re-invoking the script from a clean start.
                arm_rc=0
                "${cmd[@]}" || arm_rc=$?
                if [ "$arm_rc" -eq 130 ]; then
                    # run_eval.py's EXIT_INTERRUPTED: a human asked it to stop.
                    # This is the case no trap here can catch - when SIGINT is
                    # ignored on entry, only the child ever sees the signal - so
                    # the exit code is the only evidence, and continuing to the
                    # next arm is the one thing that must not happen.
                    stop_batch "an interrupt in the arm in progress" 130
                elif [ "$arm_rc" -ne 0 ]; then
                    echo "  [!] this arm did not complete - continuing to the next one."
                    echo "      Re-running this script (no --resume needed) will pick up"
                    echo "      wherever it left off, the same as any other partial arm."
                    FAILED_ARMS+=("nudge=${nudge} oversight=${oversight} lure=${lure}")
                fi
            fi
            echo
        done
    done
done

if [ "${#FAILED_ARMS[@]}" -gt 0 ]; then
    echo "============================================================"
    echo "${#FAILED_ARMS[@]} arm(s) did not complete:"
    for arm in "${FAILED_ARMS[@]}"; do
        echo "  - ${arm}"
    done
    echo "Re-run this script (no --resume needed) to pick them back up."
fi

echo "============================================================"
echo "Done: ${TOTAL_ARMS} arm(s) for ${MODEL}, ${RUNS} run(s) each requested."

# Free - reads saved summaries and run files, calls no API - so this runs
# even after a DRY_RUN, skipping only when there is nothing on disk to
# summarise yet (a fresh --output-dir with everything still to collect).
if [ "$DRY_RUN" != "1" ]; then
    python3 -m subversionbench.run_eval --model "$MODEL" --summarise-arms \
        --output-dir "$OUTPUT_DIR"
fi
