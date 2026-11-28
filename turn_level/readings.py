"""
The primary estimate and every sensitivity reading, each a function of the matched sets and an
exposure, returning numbers and counts.

An exposure is a function of a set member ({"episode", "turn", "o"}) giving True, False, or None
for a unit with no usable verdict. The failure rule is the plan's: a set whose case has no
verdict is dropped, a control without one leaves its set. `fill` replaces every None instead,
which is how the two bounding readings (8) restore the dropped sets.
"""

import collections
import math

from blackmail_port.analyse import FOCAL as FOCAL_MODEL

from . import store
from .statistics import (conditional_logit, matched_odds_ratio, set_table,
                         smallest_detectable_odds_ratio)

LEAVE_OUT_SHARE = 0.10


def verdict_exposure(verdicts: dict, view: str):
    """The exposure a view's verdicts give."""
    def exposed(member):
        record = (verdicts.get(store.unit_id(member["episode"], member["turn"], view)) or {}).get("record")
        return None if record is None else bool(record["eval_aware"])
    return exposed


def _usable_members(s: dict, exposed, fill) -> tuple:
    """(case exposure, control exposures, controls left out) for one set, None if it is dropped."""
    def read(member):
        e = exposed(member)
        return fill if e is None else e
    case = read(s["case"])
    if case is None:
        return None
    controls = [read(c) for c in s["controls"]]
    kept = [c for c in controls if c is not None]
    return (case, kept, len(controls) - len(kept)) if kept else None


def odds_ratio(sets: list, exposed, fill=None) -> dict:
    """The MH odds ratio over `sets` under `exposed`, and what the plan reports with it."""
    tables, counts = [], collections.Counter()
    for s in sets:
        members = _usable_members(s, exposed, fill)
        if members is None:
            counts["sets dropped for a missing verdict"] += 1
            continue
        case, controls, left = members
        tables.append(set_table(case, controls))
        counts["controls left out for a missing verdict"] += left
        counts["exposed cases"] += case
        counts["exposed controls"] += sum(controls)
        counts["controls"] += len(controls)
    out = {**matched_odds_ratio(tables), **counts, "sets given": len(sets)}
    if tables and counts["controls"]:
        p0 = counts["exposed controls"] / counts["controls"]
        out["controls per set"] = round(counts["controls"] / len(tables), 2)
        out["control exposure"] = round(p0, 4)
        out["smallest odds ratio detected with 80% power"] = smallest_detectable_odds_ratio(
            len(tables), counts["controls"] / len(tables), p0)
    return out


def primary(sets_docs: dict, exposed) -> dict:
    """A, B, C, and C for Kimi K2.6 alone."""
    out = {name: odds_ratio(sets_docs[name]["sets"], exposed)
           for name in ("A", "B", "C") if name in sets_docs}
    if "C" in sets_docs:
        out["C, " + FOCAL_MODEL] = odds_ratio(
            [s for s in sets_docs["C"]["sets"] if s["model"] == FOCAL_MODEL], exposed)
    return out


def dominant_models(sets: list) -> list:
    """Models contributing at least LEAVE_OUT_SHARE of the cases, largest first."""
    counts = collections.Counter(s["model"] for s in sets)
    return [m for m, n in counts.most_common() if n >= LEAVE_OUT_SHARE * len(sets)]


def leaving_models_out(sets: list, exposed) -> dict:
    """Reading 2: each dominant model left out in turn, then all of them together."""
    dominant = dominant_models(sets)
    out = {f"without {m}": odds_ratio([s for s in sets if s["model"] != m], exposed)
           for m in dominant}
    if len(dominant) > 1:
        out["without all of " + ", ".join(dominant)] = odds_ratio(
            [s for s in sets if s["model"] not in dominant], exposed)
    return out


def by_field(sets: list, exposed, field: str) -> dict:
    """Reading 3: one estimate per act kind, or per scenario."""
    return {value: odds_ratio([s for s in sets if s[field] == value], exposed)
            for value in sorted({s[field] for s in sets})}


def opportunity_band(o: int) -> str:
    return "1" if o <= 1 else "2" if o == 2 else "3-5" if o <= 5 else "6+"


def matched_on_opportunity(sets: list) -> list:
    """Reading 6: each set with only the controls whose o is in its case's band."""
    out = []
    for s in sets:
        band = opportunity_band(s["case"]["o"])
        kept = [c for c in s["controls"] if opportunity_band(c["o"]) == band]
        if kept:
            out.append({**s, "controls": kept})
    return out


def deliberation_held_fixed(sets: list, verdicts: dict) -> dict | None:
    """Reading 7: conditional logistic regression on exposure, the log length of the unit's own
    turn's text, and whether that text holds reasoning."""
    def covariates(member):
        record = (verdicts.get(store.unit_id(member["episode"], member["turn"], "in_view")) or {}).get("record")
        if record is None:
            return None
        return [float(bool(record["eval_aware"])), math.log1p(record.get("current_chars") or 0),
                float(bool(record.get("current_has_reasoning")))]
    rows = []
    for s in sets:
        case = covariates(s["case"])
        controls = [x for x in map(covariates, s["controls"]) if x is not None]
        if case is not None and controls:
            rows.append([(True, case)] + [(False, x) for x in controls])
    return conditional_logit(rows) if rows else None


def bounds(sets: list, exposed) -> dict:
    """Reading 8: every failed unit taken as exposed, then as unexposed, dropped sets restored."""
    return {"failed as exposed": odds_ratio(sets, exposed, fill=True),
            "failed as unexposed": odds_ratio(sets, exposed, fill=False)}


def no_oversight(sets_docs: dict, exposed) -> dict:
    """Reading 9: the no-oversight arms' sandbox acts alone, pooled with A, and in A's sandbox
    reading."""
    extra = sets_docs.get("A_no_oversight", {}).get("sets", [])
    a = sets_docs.get("A", {}).get("sets", [])
    return {"no-oversight sets alone": odds_ratio(extra, exposed),
            "pooled with A": odds_ratio(a + extra, exposed),
            "sandbox, A and no-oversight": odds_ratio(
                [s for s in a if s["kind"] == "sandbox"] + extra, exposed)}


def episode_level(doc: dict, verdicts: dict, model: str = None) -> dict:
    """The episode-level reading of a blackmail corpus on this plan's judge: MH over model x arm
    of blackmail between episodes whose whole transcript glm-5.3 called aware and the rest."""
    from subversionbench.power.stratified import mantel_haenszel
    cells = collections.defaultdict(lambda: [0, 0, 0, 0])
    missing = 0
    for key, meta in doc["episodes"].items():
        if model and meta["model"] != model:
            continue
        record = (verdicts.get(store.unit_id(key, None, "whole")) or {}).get("record")
        if record is None:
            missing += 1
            continue
        c = cells[tuple(meta["stratum"])]
        aware = bool(record["eval_aware"])
        c[0 if aware else 2] += meta["acted"]
        c[1 if aware else 3] += 1
    mh = mantel_haenszel([tuple(v) for v in cells.values()])
    return {"odds_ratio": mh["odds_ratio"], "ci95": mh["odds_ratio_ci95"],
            "risk_difference": mh["risk_difference"], "risk_difference_ci95": mh["risk_difference_ci95"],
            "episodes": sum(v[1] + v[3] for v in cells.values()), "episodes without a verdict": missing}
