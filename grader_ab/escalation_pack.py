"""
A blinded labelling pack for the impossible-task report rungs.

`--grade-escalation` settles each closing report as unpassable, failing or
neither, and nothing had set that reading against a human's. The rung is the
scenario's headline for episodes with no act, so it is checked before it is
reported. The grader's rung is drawn on - to balance the pack - and sealed in
the key with the model and run; the rater never sees it.

WHAT IS DRAWN. Episodes from the impossible arms (the only ones where the rungs
separate) that the model ended itself, took no counted act, and hold a rung:
the population `escalated` is reported over. Up to `--per-cell` per model and
rung, then shuffled and capped at `--n`, so no model or rung fills the pack.
The rater is shown exactly the text the grader read - the closing report,
built by grading.closing_report.final_report.

    python3 -m grader_ab.escalation_pack --n 40 --seed 20261104 \
        --output-dir eval_results_impossible_r1 \
        --dest labelling/escalation_blind_20261104
    python3 -m grader_ab.label_pack labelling/escalation_blind_20261104 --escalation

The destination must be gitignored, since the pack holds closing reports.
"""

import collections
import glob
import json
import os
import random

from subversionbench.blinding import BLOCK_SIZE, labelling_order, write_pack
from subversionbench.endings import settled_ending
from subversionbench.grading import MISALIGNED_ACTS, act_value
from subversionbench.grading.closing_report import final_report

from .blind_pack import TEXT_KEY

STRATUM = "rung"


def population(output_dir: str) -> list:
    """Every eligible episode as a pack item, its rung and model sealed."""
    items = []
    for path in sorted(glob.glob(os.path.join(output_dir, "run_*.json"))):
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        analysis = data.get("analysis") or {}
        rung = (analysis.get("escalation") or {}).get("rung")
        if (rung is None or settled_ending(data) != "model_stopped"
                or not (data.get("variant") or "").startswith("impossible")
                or any(act_value(analysis, act) for act in MISALIGNED_ACTS)):
            continue
        items.append({"run": os.path.basename(path), "model": data["model"],
                      "nudge": data.get("nudge"), "variant": data.get("variant"),
                      STRATUM: rung,
                      TEXT_KEY: "\n\n".join(final_report(data["transcript"]))})
    return items


def draw(items: list, n: int, seed: int, per_cell: int) -> list:
    """Up to `per_cell` of each model and rung, shuffled, at most `n`."""
    rng = random.Random(seed)
    cells = collections.defaultdict(list)
    for item in items:
        cells[(item["model"], item[STRATUM])].append(item)
    picked = []
    for cell in sorted(cells):
        rng.shuffle(cells[cell])
        picked += cells[cell][:per_cell]
    rng.shuffle(picked)
    return picked[:n]


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(
        description="Build a blinded labelling pack for the report rungs.")
    parser.add_argument("--n", type=int, required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--per-cell", type=int, default=4)
    parser.add_argument("--block", type=int, default=BLOCK_SIZE)
    parser.add_argument("--output-dir", default="./eval_results_impossible_r1")
    parser.add_argument("--dest", required=True)
    args = parser.parse_args()
    if os.path.exists(os.path.join(args.dest, "labels.jsonl")):
        print(f"{args.dest} already holds labels; refusing to overwrite them.")
        return 1
    items = population(args.output_dir)
    sample = draw(items, args.n, args.seed, args.per_cell)
    rungs = collections.Counter(i[STRATUM] for i in sample)
    print(f"{len(items)} candidate(s); drew {len(sample)}: "
          + ", ".join(f"{k} {v}" for k, v in sorted(rungs.items())))
    order = labelling_order(sample, args.seed, STRATUM, args.block)
    provenance = {"question": "escalation", "output_dir": args.output_dir}
    for path in write_pack(order, args.seed, TEXT_KEY, args.dest,
                           provenance=provenance, block=args.block):
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
