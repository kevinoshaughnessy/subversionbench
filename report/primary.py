"""
The analysis plan's primary estimate, P, and its secondary family, read from
the two corpora together (analysis plan sections 2 to 5).

P is ONE Mantel-Haenszel risk difference in the counted act between aware and
unaware episodes. Its strata are model x arm cells (D5), each inside one
scenario: the mainline's arms with oversight present, the no-oversight arm
excluded as the plan's primary reading, and the goal-guarding replacement arms
(D6). What it pools is the within-stratum difference, never a rate, so the
crude contrast is given for each scenario and not across the two (section 3).

The exposure is the headline reading alone (section 4). An episode it has not
read is missing, not unaware: it leaves the denominator and is counted here.

The secondary family is read off the reports the questions already build, each
on the reading it belongs to, and corrected together with Benjamini-Hochberg.
Nothing here recomputes a question, so the two documents cannot disagree.

`python3 -m report.primary`. Reads run files only; calls nothing.
"""

import argparse
import json
import os
import time

from subversionbench.config import HEADLINE_AWARENESS_GRADER
from subversionbench.power import benjamini_hochberg

from .exclusions import (EXCLUDE_NO_OVERSIGHT, NO_AWARENESS_EXCLUSION,
                         NO_EXCLUSION)
from .loading import arm_key
from .pooling import BY_CELL, _by_cell, _contrast, _stratified
from .run_report import _narrowed_corpus, build_report
from .snapshot import snapshot

PRIMARY_GOALGUARD_ARM = "replacement"

# Which corpus and arm exclusion each reading is.
READINGS = {"mainline": ("mainline", EXCLUDE_NO_OVERSIGHT),
            "mainline_all_arms": ("mainline", NO_EXCLUSION),
            "goalguard": ("goalguard", NO_EXCLUSION)}

# The secondary family of section 2: (label, reading, question id, part).
# `part` names the block holding the estimate when it is not the question's
# own - the deferred control D6 attaches beside the replacement answer. The
# goal-guarding corpus's question 5 is question 17 on the same episodes
# (motive_split answers both in the replacement arms), so it is tested once.
SECONDARY_FAMILY = (
    ("Q5 awareness vs counted act, mainline", "mainline",
     "awareness_vs_misalignment", None),
    ("Q6 awareness vs monitor disabled", "mainline",
     "awareness_vs_monitoring_disabled", None),
    ("Q7 awareness vs sandbox escape", "mainline",
     "awareness_vs_sandbox_escape", None),
    ("Q15 awareness vs quality check modified", "mainline",
     "awareness_vs_quality_check_modified", None),
    ("Q16 awareness vs oversight tampered", "mainline",
     "awareness_vs_oversight_tampered", None),
    ("Q17 awareness vs goal-guarding, replacement arms", "goalguard",
     "awareness_vs_goal_guarding", None),
    ("Q17 deferred arms, the control", "goalguard",
     "awareness_vs_goal_guarding", "deferred_control"),
    ("Q2 oversight vs awareness", "mainline_all_arms",
     "oversight_vs_awareness", None),
    ("Q4 nudge vs awareness", "mainline_all_arms", "nudge_vs_awareness", None),
    ("Q14 replacement vs deferred, goal-guarding act", "goalguard",
     "goalguard_vs_act", None),
)


def headline_rows(output_dir: str, exclusion: str, keep,
                  only_models=None) -> tuple:
    """`output_dir`'s episodes on `exclusion`, kept by `keep`, as
    (the ones the headline grader read, how many it has not)."""
    _, episodes, _, _, _, pending, _, _ = _narrowed_corpus(
        output_dir, exclusion, NO_AWARENESS_EXCLUSION,
        HEADLINE_AWARENESS_GRADER, only_models=only_models)
    kept = [e for e in episodes if keep(e)]
    read = [e for e in kept if e["aware_source"] == "grader"]
    return read, len(kept) - len(read) + sum(1 for e in pending if keep(e))


def primary_estimate(mainline: list, goalguard: list) -> dict:
    """P over both scenarios' strata, with each scenario's crude contrast."""
    if {arm_key(r) for r in mainline} & {arm_key(r) for r in goalguard}:
        raise ValueError("a stratum holds episodes of both scenarios")
    strata = _by_cell(mainline + goalguard, "aware", True, False,
                      "misaligned", "one", arm_key)
    return {
        "stratified": _stratified(strata, BY_CELL),
        "crude_by_scenario": {
            name: _contrast(rows, "aware", True, False, "misaligned", "one")
            for name, rows in (("mainline", mainline),
                               ("goalguard", goalguard))},
        "n_episodes": {"mainline": len(mainline),
                       "goalguard": len(goalguard)},
        "n_models": len({r["model"] for r in mainline + goalguard}),
    }


def secondary_family(reports: dict) -> list:
    """Each test of the family, its stratified estimate as its question
    reports it, and its Benjamini-Hochberg adjusted p over the family."""
    tests = []
    for label, reading, qid, part in SECONDARY_FAMILY:
        section = next(q for q in reports[reading]["questions"]
                       if q["id"] == qid)
        mh = (section[part] if part else section)["stratified"][
            "mantel_haenszel"]
        tests.append({"test": label, "reading": reading, "question": qid,
                      "risk_difference": mh["risk_difference"],
                      "ci95": mh["risk_difference_ci95"], "p": mh["p"]})
    bh = benjamini_hochberg([t["p"] for t in tests])
    for t, adj, rej in zip(tests, bh["adjusted"], bh["rejected"],
                           strict=True):
        t["p_bh"], t["rejected_bh"] = adj, rej
    return tests


def build_primary(mainline_dir: str, goalguard_dir: str,
                  mainline_cap_dir: str, goalguard_cap_dir: str) -> dict:
    """P and its family over the snapshot's models only (D2): every reading
    below is narrowed to the same models, so P and the family describe one
    corpus."""
    dirs = {"mainline": mainline_dir, "goalguard": goalguard_dir}
    snap = snapshot(dirs, {"mainline": mainline_cap_dir,
                           "goalguard": goalguard_cap_dir})
    models = snap["models"]
    mainline, mainline_missing = headline_rows(
        mainline_dir, EXCLUDE_NO_OVERSIGHT, lambda e: True, models)
    goalguard, goalguard_missing = headline_rows(
        goalguard_dir, NO_EXCLUSION,
        lambda e: e.get("goalguard") == PRIMARY_GOALGUARD_ARM, models)
    reports = {name: build_report(dirs[corpus], exclusion,
                                  grader=HEADLINE_AWARENESS_GRADER,
                                  only_models=models)
               for name, (corpus, exclusion) in READINGS.items()}
    return {
        "grader": HEADLINE_AWARENESS_GRADER,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "snapshot": snap,
        "primary": dict(primary_estimate(mainline, goalguard),
                        n_missing_headline_reading={
                            "mainline": mainline_missing,
                            "goalguard": goalguard_missing}),
        "secondary": secondary_family(reports),
    }


def _pct(v) -> str:
    return "n/a" if v is None else f"{100 * v:+.2f}%"


def _ci(ci) -> str:
    return "" if not ci else f"[{_pct(ci[0])}, {_pct(ci[1])}]"


def print_primary(doc: dict) -> None:
    p = doc["primary"]
    mh, bd = (p["stratified"][k] for k in ("mantel_haenszel", "breslow_day"))
    print(f"PRIMARY P (exposure: {doc['grader']}; strata: model x arm cell; "
          f"{p['n_models']} models; episodes {p['n_episodes']}; missing "
          f"headline reading {p['n_missing_headline_reading']})")
    print(f"  MH risk difference {_pct(mh['risk_difference'])} "
          f"{_ci(mh['risk_difference_ci95'])}  OR {mh['odds_ratio']} "
          f"{mh['odds_ratio_ci95']}  p={mh['p']}  strata used "
          f"{mh['n_strata_used']}/{mh['n_strata_given']}")
    print(f"  Breslow-Day: {bd}")
    for name, c in p["crude_by_scenario"].items():
        print(f"  crude, {name}: aware {c['a']['successes']}/{c['a']['n']} "
              f"vs unaware {c['b']['successes']}/{c['b']['n']}  "
              f"difference {_pct(c['difference'])} "
              f"{_ci(c['difference_ci95'])}  p={c['p']}")
    _print_snapshot(doc["snapshot"])
    print("\nSECONDARY FAMILY (stratified, Benjamini-Hochberg over the family)")
    for t in doc["secondary"]:
        print(f"  {t['test']:<50} {_pct(t['risk_difference']):>8} "
              f"{_ci(t['ci95']):<22} p={t['p']}  p_bh={t['p_bh']}")


def _print_snapshot(snap: dict) -> None:
    print(f"\nSNAPSHOT (D2): {len(snap['models'])} complete models; "
          f"{len(snap['excluded'])} kept out")
    for model, why in snap["excluded"].items():
        print(f"  out: {model} - {'; '.join(why)}")
    gaps = snap["capability_gaps"]
    print(f"  capability verdict still owed (kept in, section 7): {len(gaps)} "
          f"models")
    for model, acts in gaps.items():
        print(f"    {model}: {', '.join(acts)}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="The analysis plan's primary estimate P over both "
                    "scenarios, and its secondary family.")
    parser.add_argument("--mainline-dir", default="./eval_results_r10")
    parser.add_argument("--goalguard-dir",
                        default="./eval_results_goalguard_r1")
    parser.add_argument("--mainline-cap-dir", default="./eval_results_r10cap")
    parser.add_argument("--goalguard-cap-dir",
                        default="./eval_results_goalguard_r1cap")
    parser.add_argument("--json-out", default=None,
                        help="default: research_report_primary_<timestamp>"
                             ".json inside --mainline-dir")
    args = parser.parse_args(argv)
    doc = build_primary(args.mainline_dir, args.goalguard_dir,
                        args.mainline_cap_dir, args.goalguard_cap_dir)
    print_primary(doc)
    out = args.json_out or os.path.join(
        args.mainline_dir,
        f"research_report_primary_{time.strftime('%Y%m%dT%H%M%S')}.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2)
    print(f"\nWritten to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
