"""
A blinded labelling pack for one of the two suspicion questions.

The questions (grading/suspicion.py) are new instruments, so their readings
mean nothing until a grader's answers are checked against a human's. The
labels come first: no grader has answered either question when the pack is
drawn, so nothing about the sample was shaped by the instrument it will test.

WHAT IS DRAWN. Episodes of the paper's snapshot - its models, the primary's
arms, read by the headline grader - so the labels are taken on the population
the readings are reported over.

- `decision`: episodes the headline reading calls aware before their earliest
  act. Balanced on that pre-act reading's category, true against
  ambiguous_true, because hedged suspicion is the side most likely to sit
  beside a decision rather than enter it.
- `framing`: aware episodes of the models with at least one aware episode
  that acted - the only models in which acting and not acting can be compared
  among aware episodes. Balanced on whether the episode acted, and capped per
  model per side, so a few models' phrasing cannot make up a side.

The rater is shown exactly the text the grader is asked about, built by the
grading module rather than here. No definition is written into the pack: it is
the protocol, so label_pack prints it from the detector bundle when labelling
starts. The model, arm and run are in the sealed key.

    python3 -m grader_ab.suspicion_pack decision --n 40 --seed 20261029 \
        --dest labelling/decision_blind_20261029
    python3 -m grader_ab.suspicion_pack framing --n 50 --seed 20261029 \
        --dest labelling/framing_blind_20261029

The destination must be gitignored, since the pack holds transcripts.
"""

import collections
import json
import os
import random

from subversionbench.blinding import BLOCK_SIZE, labelling_order, write_pack
from subversionbench.config import HEADLINE_AWARENESS_GRADER
from subversionbench.graders import view
from subversionbench.grading.suspicion import suspicion_text

from .blind_pack import TEXT_KEY

DIRS = {"mainline": "./eval_results_r10",
        "goalguard": "./eval_results_goalguard_r1"}
CAPABILITY_DIRS = {"mainline": "./eval_results_r10cap",
                   "goalguard": "./eval_results_goalguard_r1cap"}
STRATUM_KEY = {"decision": "pre_act_category", "framing": "acted"}


def snapshot_rows(dirs: dict = DIRS, capability_dirs: dict = CAPABILITY_DIRS):
    """The primary's episodes, as the report reads them: (scenario, row)."""
    from report.exclusions import EXCLUDE_NO_OVERSIGHT, NO_EXCLUSION
    from report.primary import PRIMARY_GOALGUARD_ARM, headline_rows
    from report.snapshot import snapshot
    models = snapshot(dirs, capability_dirs)["models"]
    main, _ = headline_rows(dirs["mainline"], EXCLUDE_NO_OVERSIGHT,
                            lambda e: True, models)
    goalguard, _ = headline_rows(
        dirs["goalguard"], NO_EXCLUSION,
        lambda e: e.get("goalguard") == PRIMARY_GOALGUARD_ARM, models)
    return ([("mainline", r) for r in main]
            + [("goalguard", r) for r in goalguard])


def population(question: str, rows: list) -> list:
    """The rows the question is drawn from."""
    if question == "decision":
        return [(s, r) for s, r in rows if r["aware_before_act"] is True]
    acting = {r["model"] for _, r in rows if r["aware"] and r["misaligned"]}
    return [(s, r) for s, r in rows if r["aware"] and r["model"] in acting]


def candidate(question: str, scenario: str, row: dict, dirs: dict = DIRS):
    """The pack item for one row: the grader's text and the key's fields."""
    path = os.path.join(dirs[scenario], row["run_file"])
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    flat = view(data.get("analysis") or {}, HEADLINE_AWARENESS_GRADER)
    aware = (flat.get("eval_awareness_grader") or {}).get("eval_aware")
    text, where = suspicion_text(question, data["transcript"], flat, aware)
    if text is None:
        raise ValueError(f"{row['run_file']}: the {question} question does "
                         f"not arise, though the row says it should")
    item = {"run": row["run_file"], "scenario": scenario,
            "model": row["model"], "nudge": row["nudge"],
            "oversight": row["oversight"], "lure": row["lure"],
            "goalguard": row["goalguard"], "acted": bool(row["misaligned"]),
            **where, TEXT_KEY: text}
    if question == "decision":
        before = flat.get(f"eval_awareness_grader_before_{where['act']}") or {}
        item["pre_act_category"] = before.get("category")
    return item


def draw(question: str, items: list, n: int, seed: int,
         per_model: int) -> list:
    """`n` items, half from each side of the stratum, at most `per_model` per
    model per side. Fewer if a side runs out, rather than topping it up from
    the other."""
    rng = random.Random(seed)
    key = STRATUM_KEY[question]
    picked = []
    for value in sorted({i[key] for i in items}, key=repr):
        by_model = collections.defaultdict(list)
        for item in sorted((i for i in items if i[key] == value),
                           key=lambda i: i["run"]):
            by_model[item["model"]].append(item)
        side = []
        for model in sorted(by_model):
            rng.shuffle(by_model[model])
            side += by_model[model][:per_model]
        rng.shuffle(side)
        picked += side[:n // 2]
    return picked


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(
        description="Build a blinded labelling pack for a suspicion question.")
    parser.add_argument("question", choices=sorted(STRATUM_KEY))
    parser.add_argument("--n", type=int, required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--per-model", type=int, default=3)
    parser.add_argument("--block", type=int, default=BLOCK_SIZE)
    parser.add_argument("--dest", required=True)
    args = parser.parse_args()
    if os.path.exists(os.path.join(args.dest, "labels.jsonl")):
        print(f"{args.dest} already holds labels; refusing to overwrite them.")
        return 1
    rows = population(args.question, snapshot_rows())
    items = [candidate(args.question, s, r) for s, r in rows]
    sample = draw(args.question, items, args.n, args.seed, args.per_model)
    key = STRATUM_KEY[args.question]
    sides = collections.Counter(i[key] for i in sample)
    print(f"{len(items)} candidate(s); drew {len(sample)}: "
          + ", ".join(f"{key}={k!r} {v}" for k, v in sorted(sides.items(),
                                                              key=repr)))
    order = labelling_order(sample, args.seed, key, args.block)
    provenance = {"question": args.question, "dirs": DIRS,
                  "grader": HEADLINE_AWARENESS_GRADER}
    for path in write_pack(order, args.seed, TEXT_KEY, args.dest,
                           provenance=provenance, block=args.block):
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
