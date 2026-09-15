#!/usr/bin/env bash
#
# Re-measure the KIND of suspicion - safety or capability - for every aware
# episode in a results directory, with each episode graded by the model that
# WAS the episode. See "Self-graded awareness kind" in README.md.
#
# WHAT THIS DOES NOT DO: re-measure whether an episode was eval-aware at all.
# That is a judgement a capable grader gets right, and the five rubric
# questions deciding it are not what varies between models; which words imply
# suspicion of a SAFETY test rather than a CAPABILITY one is the reading that
# does. Awareness is taken from the eval_awareness_grader verdict already in
# each run file, so both readings share one denominator and any difference
# between them is the flavour judgement alone.
#
# Cost follows from that. Two questions per AWARE episode and no calls at all
# for the rest - and most of a corpus is "the rest": on the goal-guarding
# corpus 161 of 559 episodes were aware, and one model was aware in none of
# its 80. Asking all nine questions of every episode, as an earlier version of
# this script did, was 5,031 calls where this is 322.
#
# Writes to analysis.awareness_kind_self under --write-back, never over
# analysis.eval_awareness_grader: the two are different instruments, and this
# project has already measured one grader being wrong for one model - see
# docs/methodology.md#validating-the-grader.
#
# One batch at a time, aborting on the first failure, the same reason
# regrade_all.sh does: --write-back saves each run file as it goes, so an
# abort partway keeps the damage to the batch in progress. A batch exits
# non-zero only when every aware episode came back undetermined, which is a
# fact about the calls rather than about the model; a batch with no aware
# episodes at all succeeds, having spent nothing.
#
# No --resummarise step, unlike regrade_all.sh: nothing here touches a field
# any summary is built from.
#
# Reads no arguments. Set these if you want something other than the defaults:
#
#   OUTPUT_DIR   results directory            (default: ./eval_results_goalguard_r1,
#                                             the corpus this was built for; pass it
#                                             explicitly for any other corpus)
#   DELAY        seconds between files        (default 2)
#   MIN_RUNS     skip batches smaller than N  (default 10, i.e. skip pilots)
#   DRY_RUN      set to 1 to print and not spend
#
# Usage
# -----
# Preview first - this line alone is always safe to paste, prints every
# command it WOULD run, and spends nothing:
#
#     DRY_RUN=1 ./self_grade_all.sh
#
# Then, once the plan above looks right, run it for real - a SEPARATE
# command, deliberately not chained after the line above with && or a
# second line in the same paste, because a bare `./self_grade_all.sh` spends
# money and calls --write-back on the first keystroke:
#
#     ./self_grade_all.sh

set -euo pipefail

OUTPUT_DIR="${OUTPUT_DIR:-./eval_results_goalguard_r1}"
DELAY="${DELAY:-2}"
MIN_RUNS="${MIN_RUNS:-10}"
DRY_RUN="${DRY_RUN:-0}"

echo "Re-measuring awareness KIND in ${OUTPUT_DIR}, each episode graded by its own model"
echo "Skipping batches with fewer than ${MIN_RUNS} runs. Delay ${DELAY}s between files."
[ "${DRY_RUN}" = "1" ] && echo "DRY RUN - nothing will be spent"
echo

# Enumerate (model, nudge, stamp, n) from the run files themselves rather than
# from a hardcoded list, so this stays correct as models are added to the
# corpus - see the goal-guarding models this was written against, and the
# same reasoning regrade_all.sh gives for doing this.
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
echo "${TOTAL} batch(es), ${RUNS} run(s); only the eval-aware ones cost anything."
echo

i=0
while IFS=$'\t' read -r model nudge stamp n; do
    i=$((i + 1))
    echo "############################################################"
    echo "# [${i}/${TOTAL}] ${model} / ${nudge} / ${stamp:-<unstamped>}  (n=${n})"
    echo "############################################################"

    stamp_args=()
    [ -n "$stamp" ] && stamp_args=(--batch-stamp "$stamp")

    grade=(python -m subversionbench.run_eval --self-grade-kind --write-back
           --model "$model" --nudge "$nudge"
           --output-dir "$OUTPUT_DIR" --delay "$DELAY" "${stamp_args[@]}")

    if [ "$DRY_RUN" = "1" ]; then
        printf '  would run: %s\n' "${grade[*]}"
    else
        "${grade[@]}"
    fi
    echo
done <<< "$BATCHES"

echo "============================================================"
echo "Done: ${TOTAL} batch(es) re-measured."
echo
echo "Per-model agreement with the primary reading is in each batch's own"
echo "console output above and in the saved kindself_*.json files."
echo "Aggregate it across the corpus:"
echo "  python - <<'EOF'"
echo "  import glob, json; from pathlib import Path; from collections import Counter"
echo "  agree, total = Counter(), Counter()"
echo "  for p in glob.glob('${OUTPUT_DIR}/kindself_*.json'):"
echo "      doc = json.loads(Path(p).read_text())"
echo "      a = doc['agreement_with_primary']"
echo "      if a['n']:"
echo "          total[doc['model']] += a['n']; agree[doc['model']] += a['agreed']"
echo "  for m in sorted(total):"
echo "      print(f'{m}: {agree[m]}/{total[m]} kinds agreed with the primary')"
echo "  EOF"
