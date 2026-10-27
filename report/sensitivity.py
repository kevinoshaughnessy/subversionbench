"""
The analysis plan's sensitivity readings of P (section 8), each the primary
estimate again with one thing changed.

Each reading reuses `primary_estimate` over the same snapshot's models, so
the only difference between a reading and P is the one it names: another
awareness measure, another definition of the act, or a narrower set of
episodes. The plan's rule is applied here rather than left to the reader: a
reading whose risk difference has the opposite sign from P's makes P fragile.

Readings the corpus gives nothing to change are reported as such, with the
reason, rather than computed - a duplicate of P presented as a robustness
check would be a check that cannot fail.

    python3 -m report.sensitivity [--suspected MODEL ...] [--json-out PATH]
"""

import argparse
import json
import os
import time

from subversionbench.config import DEFAULT_GRADER_MODEL
from subversionbench.grading import AWARE_CATEGORIES, CATEGORIES

from .exclusions import EXCLUDE_NO_OVERSIGHT, NO_EXCLUSION
from .primary import (PRIMARY_GOALGUARD_ARM, _pct, headline_rows,
                      primary_estimate)
from .snapshot import snapshot

NOT_APPLICABLE = "not applicable"


def _rows(dirs: dict, models: list, grader: str = None) -> tuple:
    """(mainline, goalguard) rows of the arms P uses, as `grader` read
    them; the headline grader's by default."""
    extra = {"grader": grader} if grader else {}
    mainline, _ = headline_rows(dirs["mainline"], EXCLUDE_NO_OVERSIGHT,
                                lambda e: True, models, **extra)
    goalguard, _ = headline_rows(
        dirs["goalguard"], NO_EXCLUSION,
        lambda e: e.get("goalguard") == PRIMARY_GOALGUARD_ARM, models,
        **extra)
    return mainline, goalguard


def _reading(label: str, mainline: list, goalguard: list, **columns) -> dict:
    estimate = primary_estimate(mainline, goalguard, **columns)
    mh = estimate["stratified"]["mantel_haenszel"]
    return {"reading": label, "risk_difference": mh["risk_difference"],
            "ci95_sato": mh.get("risk_difference_ci95_sato"),
            "ci95": mh["risk_difference_ci95"], "p": mh["p"],
            "strata_used": mh["n_strata_used"],
            "n_episodes": estimate["n_episodes"]}


def _skipped(label: str, why: str) -> dict:
    return {"reading": label, "status": NOT_APPLICABLE, "why": why}


def _with_cut(rows: list, aware_categories: tuple) -> list:
    """Each row with `aware_cut`: aware when the headline grader's category
    is one of `aware_categories`, None where it gave no category."""
    return [dict(r, aware_cut=(None if r.get("awareness_category") is None
                               else r["awareness_category"] in aware_categories))
            for r in rows]


# The headline counts the first two of CATEGORIES as aware. Each cut moves
# that line by one category, holding the other three where they were.
STRICT_CUT = tuple(c for c in AWARE_CATEGORIES if c != "ambiguous_true")
LENIENT_CUT = AWARE_CATEGORIES + ("ambiguous_false",)
assert set(STRICT_CUT) | set(LENIENT_CUT) <= set(CATEGORIES)


def _route(rows: list, returned: bool) -> list:
    """Episodes by whether the model's reasoning reached the grader."""
    return [r for r in rows if bool(r.get("aware_text_is_bound")) == returned]


def readings(dirs: dict, cap_dirs: dict, suspected=()) -> dict:
    """P and every section 8 reading over the snapshot's models."""
    models = snapshot(dirs, cap_dirs)["models"]
    mainline, goalguard = _rows(dirs, models)
    rubric = _rows(dirs, models, DEFAULT_GRADER_MODEL)
    kept = [m for m in models if m not in set(suspected)]
    without = _rows(dirs, kept) if suspected else None
    out = [
        _reading("P (headline grader)", mainline, goalguard),
        _reading(f"1a rubric grader ({DEFAULT_GRADER_MODEL})", *rubric),
        _reading("1d headline, ambiguous_true as unaware",
                 _with_cut(mainline, STRICT_CUT), _with_cut(goalguard, STRICT_CUT),
                 exposure="aware_cut"),
        _reading("1e headline, ambiguous_false as aware",
                 _with_cut(mainline, LENIENT_CUT),
                 _with_cut(goalguard, LENIENT_CUT), exposure="aware_cut"),
        _reading("1b keyword screen", mainline, goalguard,
                 exposure="aware_keywords"),
        _reading("1c union of rubric and keywords", mainline, goalguard,
                 exposure="aware_union"),
        _reading("2 acts at their end state (pre-D7)", mainline, goalguard,
                 outcome="misaligned_end_state"),
        _skipped("3 without D3's flagged arms",
                 "D3 re-collected every cut-off arm; none remains flagged"),
        (_reading(f"4 without {len(suspected)} suspected model(s)", *without)
         if suspected else _skipped("4 without suspected models",
                                    "no model is suspected")),
        _reading("5a route: reasoning returned", _route(mainline, True),
                 _route(goalguard, True)),
        _reading("5b route: visible text only", _route(mainline, False),
                 _route(goalguard, False)),
        _skipped("6 without the known artefact's episodes",
                 "no encoded marker for the artefact exists yet, so its "
                 "episodes cannot be identified"),
    ]
    mark_reversals(out)
    return {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "n_models": len(models), "readings": out,
            "fragile": any(r.get("sign_reversed") for r in out)}


def mark_reversals(out: list) -> None:
    """The plan's rule: a computed reading whose risk difference has the
    opposite sign from P's (the first) reverses it. A zero is no sign."""
    primary_sign = _sign(out[0]["risk_difference"])
    for r in out[1:]:
        if "risk_difference" in r:
            r["sign_reversed"] = (primary_sign != 0
                                  and _sign(r["risk_difference"]) == -primary_sign)


def _sign(value) -> int:
    return 0 if not value else (1 if value > 0 else -1)


def print_readings(doc: dict) -> None:
    print(f"SENSITIVITY READINGS OF P (analysis plan section 8; "
          f"{doc['n_models']} models)")
    for r in doc["readings"]:
        if r.get("status") == NOT_APPLICABLE:
            print(f"  {r['reading']:<44} not applicable: {r['why']}")
            continue
        ci = r["ci95_sato"]
        ci_text = f"[{_pct(ci[0])}, {_pct(ci[1])}]" if ci else ""
        flag = "  SIGN REVERSED" if r.get("sign_reversed") else ""
        print(f"  {r['reading']:<44} {_pct(r['risk_difference']):>8} "
              f"Sato {ci_text:<22} p={r['p']}  strata "
              f"{r['strata_used']}{flag}")
    print("P is " + ("FRAGILE: a reading reverses its sign."
                     if doc["fragile"] else
                     "not fragile: no reading reverses its sign."))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="The analysis plan's sensitivity readings of P.")
    parser.add_argument("--mainline-dir", default="./eval_results_r10")
    parser.add_argument("--goalguard-dir",
                        default="./eval_results_goalguard_r1")
    parser.add_argument("--mainline-cap-dir", default="./eval_results_r10cap")
    parser.add_argument("--goalguard-cap-dir",
                        default="./eval_results_goalguard_r1cap")
    parser.add_argument("--suspected", nargs="+", default=(), metavar="MODEL",
                        help="models contamination_check.py found suspected; "
                             "reading 4 is P without them")
    parser.add_argument("--json-out", default=None,
                        help="default: research_report_sensitivity_"
                             "<timestamp>.json inside --mainline-dir")
    args = parser.parse_args(argv)
    doc = readings({"mainline": args.mainline_dir,
                    "goalguard": args.goalguard_dir},
                   {"mainline": args.mainline_cap_dir,
                    "goalguard": args.goalguard_cap_dir},
                   args.suspected)
    print_readings(doc)
    out = args.json_out or os.path.join(
        args.mainline_dir,
        f"research_report_sensitivity_{time.strftime('%Y%m%dT%H%M%S')}.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2)
    print(f"\nWritten to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
