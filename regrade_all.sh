#!/usr/bin/env bash
#
# Re-grade every saved batch with the current --grader-model, then rebuild its
# summary.
#
# Needed because the awareness rate is only comparable across models if every
# model was graded by the same grader. Changing the default from
# claude-haiku-4-5 to claude-opus-5 makes every batch graded before that change
# incomparable with every batch graded after it, so this is not optional
# housekeeping - a half-regraded results directory is worse than an un-regraded
# one, because the inconsistency is invisible in the summaries.
#
# One batch at a time, aborting on the first failure. --write-back saves each
# run file as it goes, so a batch interrupted midway leaves that model split
# across two graders; the abort keeps the damage to one batch, and re-running
# the script redoes it from the start.
#
# Reads no arguments. Set these if you want something other than the defaults:
#
#   OUTPUT_DIR   results directory            (default: the current version's,
#                                             so pass it explicitly to regrade
#                                             batches collected under an older one)
#   GRADER       --grader-model to grade with (default: the package default)
#   DELAY        seconds between files        (default 2)
#   MIN_RUNS     skip batches smaller than N  (default 10, i.e. skip pilots)
#   DRY_RUN      set to 1 to print and not spend
#
# Cost, for reference: about $24 for 550 runs at Opus rates, $15 at Sonnet 5,
# $5 at Haiku. Seven rubric questions per episode, with the transcript cached
# across them.

set -euo pipefail

OUTPUT_DIR="${OUTPUT_DIR:-./eval_results_$(python -c "from subversionbench.config import VERSION; print(VERSION)")}"
DELAY="${DELAY:-2}"
MIN_RUNS="${MIN_RUNS:-10}"
DRY_RUN="${DRY_RUN:-0}"
GRADER="${GRADER:-$(python -c 'from subversionbench.config import DEFAULT_GRADER_MODEL as m; print(m)')}"

echo "Re-grading batches in ${OUTPUT_DIR} with ${GRADER}"
echo "Skipping batches with fewer than ${MIN_RUNS} runs. Delay ${DELAY}s between files."
[ "${DRY_RUN}" = "1" ] && echo "DRY RUN - nothing will be spent"
echo

# Enumerate (model, nudge, stamp, n) from the run files themselves rather than
# from a hardcoded list, so this stays correct as batches are added.
BATCHES=$(python - "$OUTPUT_DIR" "$MIN_RUNS" <<'PY'
import glob, json, re, sys
from pathlib import Path
from collections import defaultdict

output_dir, min_runs = sys.argv[1], int(sys.argv[2])
found = defaultdict(int)
for path in glob.glob(f"{output_dir}/run_*.json"):
    data = json.loads(Path(path).read_text())
    stamp = (re.search(r"_(\d{8}T\d{6})\.json$", path) or [None, ""])[1]
    found[(data.get("model", ""), data.get("nudge", ""), stamp)] += 1

for (model, nudge, stamp), n in sorted(found.items()):
    if n >= min_runs and model and nudge:
        print(f"{model}\t{nudge}\t{stamp}\t{n}")
PY
)

if [ -z "$BATCHES" ]; then
    echo "No batches with >= ${MIN_RUNS} runs found in ${OUTPUT_DIR}." >&2
    exit 1
fi

TOTAL=$(printf '%s\n' "$BATCHES" | wc -l | tr -d ' ')
RUNS=$(printf '%s\n' "$BATCHES" | awk -F'\t' '{s+=$4} END {print s}')
echo "${TOTAL} batch(es), ${RUNS} run(s) to re-grade."
echo

i=0
while IFS=$'\t' read -r model nudge stamp n; do
    i=$((i + 1))
    echo "############################################################"
    echo "# [${i}/${TOTAL}] ${model} / ${nudge} / ${stamp:-<unstamped>}  (n=${n})"
    echo "############################################################"

    stamp_args=()
    [ -n "$stamp" ] && stamp_args=(--batch-stamp "$stamp")

    grade=(python -m subversionbench.run_eval --grade-existing --write-back
           --grader-model "$GRADER" --model "$model" --nudge "$nudge"
           --output-dir "$OUTPUT_DIR" --delay "$DELAY" "${stamp_args[@]}")
    summarise=(python -m subversionbench.run_eval --resummarise
               --model "$model" --nudge "$nudge"
               --output-dir "$OUTPUT_DIR" "${stamp_args[@]}")

    if [ "$DRY_RUN" = "1" ]; then
        printf '  would run: %s\n' "${grade[*]}"
        printf '  would run: %s\n' "${summarise[*]}"
    else
        "${grade[@]}"
        # Summaries are derived from the run files, so they are stale the moment
        # the verdicts change. Rebuilt per batch rather than at the end, so an
        # abort never leaves regraded runs described by pre-regrade summaries.
        "${summarise[@]}"
    fi
    echo
done <<< "$BATCHES"

echo "============================================================"
echo "Done: ${TOTAL} batch(es) re-graded with ${GRADER} and resummarised."
echo
echo "Verify a single grader across everything you report:"
echo "  python - <<'EOF'"
echo "  import glob, json; from pathlib import Path; from collections import Counter"
echo "  c = Counter()"
echo "  for p in glob.glob('${OUTPUT_DIR}/run_*.json'):"
echo "      g = json.loads(Path(p).read_text())['analysis'].get('eval_awareness_grader') or {}"
echo "      c[g.get('grader_model')] += 1"
echo "  print(dict(c))"
echo "  EOF"
