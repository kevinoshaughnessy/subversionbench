#!/usr/bin/env python3
"""
An external agentic-misalignment benchmark, and its correlation with the rates
measured here.

The data is a harmful-behaviour table from a separate agentic-misalignment
benchmark: counts of harmful trajectories per model, split three ways by whether
the model verbalised evaluation awareness, across three harm scenarios.

WHY IT IS NOT PLAIN SOURCE
--------------------------
The same reason the scenario and the situational-awareness leaderboard are not,
and the reasoning is written out in full in sad_oversight.py. Briefly: a
benchmark whose items sit in a public repository as plain text goes into the next
training crawl, and a model trained on it scores by recall. That destroys the
comparison this file exists to make.

So the table is encrypted at rest with the PUBLISHED passphrase, the same one
zip.sh uses. It offers no confidentiality; it is a crawler barrier.

    python agentic_misalignment.py --decode     # writes agentic_misalignment.json
    python agentic_misalignment.py --encode     # folds that file back in

agentic_misalignment.json is gitignored, so a decoded working copy cannot be
committed by accident. The model names and the harm-scenario names live inside
the bundle for the same reason the scores do - a mapping table in plaintext
would put half the benchmark back into the crawl.

THE CRYPTO IS IMPORTED, NOT COPIED
----------------------------------
`encrypt`/`decrypt` come from sad_oversight rather than being reimplemented
here. A second copy of a key-derivation routine is a second thing to keep in
step, and the two bundles are meant to stay readable by the same passphrase.

WHAT THIS COMPARISON CAN AND CANNOT SAY
---------------------------------------
Five models overlap. That is enough to report a rank correlation and nowhere
near enough to conclude anything from one, which is why every rho is returned
with its n and its leave-one-out range. A sixth model in the source table is
deliberately unmatched - see the bundle's `deliberately_unmatched` - because no
local model shares both its version and its size.

Two correlations are reported, and they are different claims:

  LEVEL - the external harmful-behaviour rate against the misalignment rate
  here. The weaker of the two, because the absolute rates are not commensurable:
  the scenarios differ, the harms differ, and one benchmark's "harmful" is not
  the other's "misaligned act". Only the ORDER of the models is comparable, and
  even that assumes the two constructs rank models similarly.

  AWARENESS SUPPRESSION - the gap between the unaware and aware harmful rates,
  on each side. This is the axis the two benchmarks genuinely share: both record
  whether the model verbalised that it might be under evaluation, and both can
  therefore ask whether awareness moves the harmful rate. A gap is a within-
  benchmark difference, so it is far less sensitive to the two benchmarks
  measuring different absolute things. Positive means awareness went with LESS
  harmful behaviour.

THE AWARENESS BUCKETS DO NOT LINE UP EXACTLY
--------------------------------------------
The external table splits awareness three ways; this benchmark records one
binary verdict. The two external aware buckets are pooled into one aware side
for the primary comparison, and the narrower variant is reported beside it so
the choice is visible rather than buried. Which pooling is right is not settled
by the data, so both are printed.

NEITHER SIDE IS AN EFFECT
-------------------------
The suppression gap conditions on something the model did - verbalising
awareness - which is a post-treatment variable on both benchmarks. A model that
recognises a test and then behaves differently may be behaving differently for
reasons that also caused it to recognise the test. The gap is a description of
two populations, and the report says so.
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

from report import load_episodes
from sad_oversight import decrypt, encrypt
from subversionbench import charting
from subversionbench.config import ROLLOUT_VERSION, VERSION
from subversionbench.power import (MIN_INFORMATIVE_DENOMINATOR, spearman,
                                   spearman_leave_one_out, wilson_ci)
from subversionbench.redaction import redact_paths

_BUNDLE_PATH = Path(__file__).with_name("agentic_misalignment.enc")
_PLAIN_PATH = Path(__file__).with_name("agentic_misalignment.json")

# The row every correlation uses. The per-scenario rows are carried in the
# bundle and reported, but a rank correlation over five models is thin enough
# already without splitting it three ways.
OVERALL = "overall"

# Which external buckets count as "aware". Two poolings, both reported, because
# this benchmark's single binary verdict has no exact counterpart in a
# three-way split and picking one silently would hide the choice.
AWARE_POOLINGS = {
    "any_aware": ("safety_aware", "capability_aware"),
    "safety_only": ("safety_aware",),
}

MEASURES = {
    "level": "external harmful rate vs local misalignment rate",
    "suppression": "unaware-minus-aware gap, on each side",
}


def load_bundle(path: Path = None) -> dict:
    """The decrypted table."""
    return decrypt((path or _BUNDLE_PATH).read_text(encoding="utf-8"))


def _rate(harmful: int, n: int):
    return harmful / n if n else None


def external_rates(bundle: dict, pooling: str = "any_aware") -> dict:
    """
    Per external model: the overall harmful rate, and the suppression gap.

    Counts are summed before dividing, never averaged as rates: the awareness
    buckets differ in size by more than an order of magnitude within a single
    model, so a mean of the three bucket rates is not the model's rate and
    would weight thirteen trajectories the same as eight hundred.
    """
    aware_keys = AWARE_POOLINGS[pooling]
    out = {}
    for row in bundle["rows"]:
        if row["scenario"] != OVERALL:
            continue
        buckets = row["buckets"]
        total_h = sum(b["harmful"] for b in buckets.values())
        total_n = sum(b["n"] for b in buckets.values())
        unaware = buckets["unaware"]
        aware_h = sum(buckets[k]["harmful"] for k in aware_keys)
        aware_n = sum(buckets[k]["n"] for k in aware_keys)
        unaware_rate = _rate(unaware["harmful"], unaware["n"])
        aware_rate = _rate(aware_h, aware_n)
        out[row["model"]] = {
            "harmful": total_h, "n": total_n,
            "overall_rate": _rate(total_h, total_n),
            "unaware": {"harmful": unaware["harmful"], "n": unaware["n"],
                        "rate": unaware_rate},
            "aware": {"harmful": aware_h, "n": aware_n, "rate": aware_rate},
            # Positive = awareness went with LESS harmful behaviour.
            "suppression_gap": (None if unaware_rate is None or aware_rate is None
                                else round(unaware_rate - aware_rate, 4)),
            "aware_side_underpowered": aware_n < MIN_INFORMATIVE_DENOMINATOR,
        }
    return out


def local_rates(output_dir: str) -> dict:
    """
    Per local model: the misalignment rate, and the same suppression gap.

    Built the same way as the external side so the two are comparable by
    construction: counts pooled over every arm, then divided once. Episodes
    whose awareness verdict did not resolve are left out of BOTH awareness
    sides rather than counted as unaware - an unresolved verdict is a missing
    measurement, and the external table has no such bucket to match it to.
    """
    out = {}
    for episode in load_episodes(output_dir):
        row = out.setdefault(episode["model"], {
            "misaligned": 0, "n": 0,
            "unaware": {"misaligned": 0, "n": 0},
            "aware": {"misaligned": 0, "n": 0},
            "n_awareness_unresolved": 0,
        })
        row["n"] += 1
        row["misaligned"] += 1 if episode["misaligned"] else 0
        if episode["aware"] is None:
            row["n_awareness_unresolved"] += 1
            continue
        side = row["aware"] if episode["aware"] else row["unaware"]
        side["n"] += 1
        side["misaligned"] += 1 if episode["misaligned"] else 0
    for row in out.values():
        row["misaligned_rate"] = _rate(row["misaligned"], row["n"])
        for key in ("unaware", "aware"):
            row[key]["rate"] = _rate(row[key]["misaligned"], row[key]["n"])
        u, a = row["unaware"]["rate"], row["aware"]["rate"]
        row["suppression_gap"] = (None if u is None or a is None
                                 else round(u - a, 4))
        row["aware_side_underpowered"] = (
            row["aware"]["n"] < MIN_INFORMATIVE_DENOMINATOR)
    return out


def local_index(bundle: dict) -> dict:
    """
    Local model ID -> the external row it corresponds to.

    From the bundle's alias list, never by string similarity. The two naming
    schemes have no derivable relation and the failure is silent: a version or a
    size that differs by one token is a different model, and with five pairs one
    wrong pairing moves every rho reported here. sad_oversight.local_index
    records three real cases, all substring relationships.
    """
    index = {}
    for alias in bundle["aliases"]:
        for local in alias["local_models"]:
            index[local] = alias["external_model"]
    return index


def unmatched_rows(bundle: dict) -> list:
    """
    External models with no local counterpart, and whether that was a decision.

    The guard that makes a hand-maintained mapping safe, the same role
    model_releases.missing_dates plays: a row is never dropped silently. A row
    listed in `deliberately_unmatched` is reported as a decision; anything else
    is reported as a gap.
    """
    aliased = {a["external_model"] for a in bundle["aliases"]}
    decided = {d["external_model"]: d["reason"]
               for d in bundle.get("deliberately_unmatched") or []}
    out = []
    for model in dict.fromkeys(r["model"] for r in bundle["rows"]):
        if model in aliased:
            continue
        out.append({"external_model": model,
                    "decided": model in decided,
                    "reason": decided.get(model)})
    return out


def unmatched_models(bundle: dict, models: list) -> list:
    """Local models with no external row, in the order given."""
    index = local_index(bundle)
    return [m for m in models if m not in index]


def build_pairs(bundle: dict, local: dict, pooling: str = "any_aware") -> list:
    """One row per (external model, local model) the alias list joins."""
    external = external_rates(bundle, pooling)
    pairs = []
    for local_model, external_model in sorted(local_index(bundle).items()):
        if local_model not in local or external_model not in external:
            continue
        pairs.append({
            "local_model": local_model,
            "external_model": external_model,
            "external": external[external_model],
            "local": local[local_model],
        })
    return pairs


def _series(pairs: list, measure: str) -> tuple:
    """The two ranked series for one measure, and the pairs they came from."""
    if measure == "level":
        usable = [p for p in pairs
                  if p["external"]["overall_rate"] is not None
                  and p["local"]["misaligned_rate"] is not None]
        return ([p["external"]["overall_rate"] for p in usable],
                [p["local"]["misaligned_rate"] for p in usable], usable)
    usable = [p for p in pairs
              if p["external"]["suppression_gap"] is not None
              and p["local"]["suppression_gap"] is not None]
    return ([p["external"]["suppression_gap"] for p in usable],
            [p["local"]["suppression_gap"] for p in usable], usable)


def correlate(pairs: list, measure: str, pooling: str = "any_aware") -> dict:
    """
    One rank correlation, with the leave-one-out range that qualifies it.

    Spearman rather than Pearson: the two sides count different things on
    different scenarios, so only their order is comparable. At this n the
    p-value is an exact permutation p-value - see power.spearman.

    The leave-one-out range is not decoration. With five pairs a single model
    can carry a rho from strongly positive to strongly negative, and a rho
    printed without that range invites a conclusion the data cannot support.
    """
    xs, ys, usable = _series(pairs, measure)
    result = spearman(xs, ys)
    influence = spearman_leave_one_out(xs, ys)
    out = {
        "measure": measure,
        "measure_label": MEASURES[measure],
        "aware_pooling": pooling if measure == "suppression" else None,
        "n_models": len(usable),
        "spearman_rho": (round(result["rho"], 4)
                         if result["rho"] is not None else None),
        "p": result["p"],
        "p_method": result["method"],
        "separated": result["separated"],
        "note": result["note"],
        "leave_one_out_rho_range": (
            [round(influence["min_rho"], 4), round(influence["max_rho"], 4)]
            if influence["min_rho"] is not None else None),
        "models": [p["local_model"] for p in usable],
        "n_underpowered_aware_sides": sum(
            1 for p in usable
            if p["external"]["aware_side_underpowered"]
            or p["local"]["aware_side_underpowered"]),
    }
    # Rho ranks; it does not compare signs. On the suppression measure the two
    # sides can rank models identically - rho = 1 - while disagreeing about
    # whether awareness suppresses harm at all in most of them, because a rank
    # correlation is invariant to where zero sits. Direction is therefore
    # counted alongside, the mirror of the argument in
    # data_quality._measure_agreement: sign alone is not enough there, and rho
    # alone is not enough here.
    if measure == "suppression":
        signs = [(p["external"]["suppression_gap"] > 0,
                  p["local"]["suppression_gap"] > 0) for p in usable]
        agreeing = [e == loc for e, loc in signs]
        out["n_same_direction"] = sum(agreeing)
        out["n_opposite_direction"] = len(agreeing) - sum(agreeing)
        out["direction_note"] = (
            "rho ranks the models; it says nothing about whether the two "
            "benchmarks agree that awareness suppresses harm. Where these "
            "disagree, a positive rho means the ORDER matches while the effect "
            "does not.")
    index = influence.get("most_influential_index")
    if index is not None:
        out["most_influential_model"] = usable[index]["local_model"]
    return out


def build_report(output_dir: str, bundle: dict = None) -> dict:
    """The whole comparison: pairs, every correlation, and what was left out."""
    bundle = bundle or load_bundle()
    local = local_rates(output_dir)
    report = {
        "version": VERSION,
        "rollout_version": ROLLOUT_VERSION,
        "output_dir": redact_paths(str(Path(output_dir).resolve())),
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "source": bundle["source"],
        "is_descriptive_not_causal": True,
        "interpretation": (
            "rank correlations over five models. The suppression gap conditions "
            "on something the model did - verbalising awareness - on both "
            "sides, so it describes two populations rather than an effect"),
        "unmatched_external_models": unmatched_rows(bundle),
        "unmatched_local_models": unmatched_models(bundle, sorted(local)),
        "correlations": [],
        "pairs_by_pooling": {},
    }
    for pooling in AWARE_POOLINGS:
        pairs = build_pairs(bundle, local, pooling)
        report["pairs_by_pooling"][pooling] = pairs
        report["correlations"].append(correlate(pairs, "suppression", pooling))
        if pooling == "any_aware":
            report["correlations"].append(correlate(pairs, "level"))
    report["n_pairs"] = len(report["pairs_by_pooling"]["any_aware"])
    return report


def print_report(report: dict) -> None:
    """The comparison as a table, computing nothing not already in `report`."""
    print("=" * 78)
    print("EXTERNAL AGENTIC-MISALIGNMENT BENCHMARK vs SUBVERSIONBENCH")
    print("=" * 78)
    print(f"\n{report['source']}")
    print(f"\nanalysis {report['version']}, rollout {report['rollout_version']}")
    print(f"{report['n_pairs']} model(s) overlap.")

    for row in report["unmatched_external_models"]:
        kind = "DECIDED" if row["decided"] else "GAP    "
        print(f"  [{kind}] external model not paired: "
              f"{row['external_model']}")
        if row["reason"]:
            print(f"            {row['reason']}")
    if report["unmatched_local_models"]:
        print(f"  {len(report['unmatched_local_models'])} local model(s) have "
              f"no external row (expected - this benchmark ran far more)")

    print("\n" + "-" * 78)
    print("PAIRS (aware = safety-aware and capability-aware pooled)")
    print("-" * 78)
    print(f"{'local model':<30} {'ext rate':>9} {'ext gap':>8} "
          f"{'loc rate':>9} {'loc gap':>8}  agree")
    for pair in report["pairs_by_pooling"]["any_aware"]:
        e, loc = pair["external"], pair["local"]
        eg, lg = e["suppression_gap"], loc["suppression_gap"]
        # A gap is None when a side has zero aware episodes to divide by -
        # possible on any model with few enough episodes, and the exact case
        # this fixture-driven test found. "OPPOSITE" claims a comparison that
        # did not happen, and formatting None directly is the same defect the
        # correlations block below was fixed for: absent must print as absent.
        if eg is None or lg is None:
            agree, eg_s, lg_s = "n/a", "n/a", "n/a"
        else:
            agree = "same" if (eg > 0) == (lg > 0) else "OPPOSITE"
            eg_s, lg_s = f"{eg:+.1%}", f"{lg:+.1%}"
        mark = " !" if (e["aware_side_underpowered"]
                        or loc["aware_side_underpowered"]) else ""
        print(f"{pair['local_model']:<30} {e['overall_rate']:>8.1%} "
              f"{eg_s:>8} {loc['misaligned_rate']:>9.1%} {lg_s:>8}  "
              f"{agree}{mark}")
    print("  gap = unaware rate minus aware rate; POSITIVE means awareness "
          "went with less harmful behaviour.")
    print(f"  ! one side's aware bucket is below "
          f"{MIN_INFORMATIVE_DENOMINATOR} trajectories or episodes.")

    print("\n" + "-" * 78)
    print("CORRELATIONS")
    print("-" * 78)
    for c in report["correlations"]:
        pooling = f" [{c['aware_pooling']}]" if c["aware_pooling"] else ""
        print(f"\n{c['measure']}{pooling}: {c['measure_label']}")
        # rho, p, the method and the separation verdict are None TOGETHER: too
        # few pairs overlap for a coefficient to exist, which is not the same as
        # a coefficient of zero and must not be formatted as one. Guarding only
        # rho - which is what this did - moves the crash one field along rather
        # than removing it, and the run that finds it is the one with no corpus.
        # `note` comes from spearman() and says why, so the reason is reported
        # rather than a threshold being restated here and drifting from it.
        if c["spearman_rho"] is None:
            print(f"    n={c['n_models']}   no coefficient: {c['note']}")
            continue
        print(f"    n={c['n_models']}   Spearman rho={c['spearman_rho']:+.3f}   "
              f"p={c['p']:.4g} ({c['p_method']})   "
              f"{'SEPARATED' if c['separated'] else 'not separated'}")
        if c["leave_one_out_rho_range"]:
            lo, hi = c["leave_one_out_rho_range"]
            print(f"    leave-one-out rho ranges {lo:+.3f} to {hi:+.3f}"
                  + (f", most influential: {c['most_influential_model']}"
                     if c.get("most_influential_model") else ""))
        if c.get("n_opposite_direction") is not None:
            print(f"    direction: {c['n_same_direction']} pair(s) agree on the "
                  f"SIGN of the gap, {c['n_opposite_direction']} disagree")
            if c["n_opposite_direction"]:
                print(f"    {c['direction_note']}")
        if c["n_underpowered_aware_sides"]:
            print(f"    {c['n_underpowered_aware_sides']} pair(s) rest on an "
                  f"aware bucket below {MIN_INFORMATIVE_DENOMINATOR}")
        if c["note"]:
            print(f"    {c['note']}")
    print(f"\n{report['interpretation']}.")


CHART_DPI = 150

# Offsets tried, in points, in priority order - up-right of the marker first,
# then an alternating up/down sweep at the same horizontal distance. Sized for
# the five points this comparison has, not the eleven sad_oversight.py's
# leaderboard chart lays out; that file's own history is the reason to keep
# this generous rather than tuned tight to today's n; a sixth or seventh
# overlapping model is the kind of change that would not touch this file.
_LABEL_OFFSETS = ((7, 4),) + tuple(
    (7, 4 + sign * step * 10) for step in range(1, 16) for sign in (1, -1))


def _place_labels(fig, ax, points: list) -> None:
    """
    One label per point, nudged off the natural offset only where it collides.

    Measured against the rendered bounding box rather than guessed from font
    size and string length - sad_oversight.py tried guessing twice on its own
    charts and got it wrong both times, which is the reason this asks
    matplotlib directly instead of repeating that history in a second file.
    """
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    placed = []
    for x, y, text in sorted(points, key=lambda p: -p[1]):
        chosen = None
        for dx, dy in _LABEL_OFFSETS:
            ann = ax.annotate(text, (x, y), textcoords="offset points",
                              xytext=(dx, dy), fontsize=7, color="#333333")
            box = ann.get_window_extent(renderer=renderer)
            if not any(box.overlaps(p) for p in placed):
                chosen = box
                break
            ann.remove()
        if chosen is None:
            ann = ax.annotate(text, (x, y), textcoords="offset points",
                              xytext=_LABEL_OFFSETS[-1], fontsize=7,
                              color="#333333")
            chosen = ann.get_window_extent(renderer=renderer)
        placed.append(chosen)


def write_chart(report: dict, path: str) -> str:
    """
    Two panels: the level correlation, and the suppression gap that is the
    sharper of the two claims.

    THE GAP PANEL IS THE POINT OF THIS CHART
    -----------------------------------------
    A rank correlation on the suppression gap can be strongly positive while
    the two benchmarks disagree about whether awareness suppresses harm at
    all, because rho is invariant to where zero sits - which is exactly what
    happened here (rho positive, 3 of 5 pairs opposite in sign). Dashed lines
    at zero on both axes turn that into a quadrant a reader sees directly:
    top-right and bottom-left agree on the sign of the gap, the other two
    corners disagree, and no amount of staring at a rho value shows that on
    its own.

    Wilson intervals on the level panel, none on the gap panel: a rate has a
    standard interval: a DIFFERENCE of two rates does not have one already
    computed anywhere in this file, and building one would be new statistical
    machinery for a panel that already has a more direct caution available -
    the hollow-marker flag on whichever pairs rest on an underpowered aware
    bucket, which is the actual known weak point of a gap.
    """
    plt = charting.import_pyplot("Chart")
    if plt is None:
        return None
    pairs = report["pairs_by_pooling"].get("any_aware") or []
    if not pairs:
        return None
    by_key = {(c["measure"], c["aware_pooling"]): c for c in report["correlations"]}
    level_stat = by_key[("level", None)]
    gap_stat = by_key[("suppression", "any_aware")]

    fig, (ax_level, ax_gap) = plt.subplots(1, 2, figsize=(12, 5.5))

    level_points = []
    for pair in pairs:
        e, loc = pair["external"], pair["local"]
        if e["overall_rate"] is None or loc["misaligned_rate"] is None:
            continue
        ex, lo = e["overall_rate"] * 100, loc["misaligned_rate"] * 100
        ex_ci = wilson_ci(e["harmful"], e["n"])
        lo_ci = wilson_ci(loc["misaligned"], loc["n"])
        ax_level.errorbar(
            ex, lo,
            xerr=[[ex - ex_ci[0] * 100], [ex_ci[1] * 100 - ex]],
            yerr=[[lo - lo_ci[0] * 100], [lo_ci[1] * 100 - lo]],
            fmt="o", markersize=6, capsize=2, elinewidth=1.0,
            color="#4c72b0", alpha=0.85, zorder=3)
        level_points.append((ex, lo, pair["local_model"]))
    _place_labels(fig, ax_level, level_points)
    subtitle = (f"rho={level_stat['spearman_rho']:+.2f}, "
                f"p={level_stat['p']:.3f}, n={level_stat['n_models']}"
                if level_stat["spearman_rho"] is not None else level_stat["note"])
    ax_level.set_title(f"harmful-behaviour level\n{subtitle}", fontsize=9)
    ax_level.set_xlabel("AM harmful-behaviour rate (%)", fontsize=9)
    ax_level.set_ylabel("SubversionBench misalignment rate (%)", fontsize=9)
    ax_level.grid(alpha=0.25)

    gap_points, any_underpowered = [], False
    for pair in pairs:
        e, loc = pair["external"], pair["local"]
        if e["suppression_gap"] is None or loc["suppression_gap"] is None:
            continue
        ex, lo = e["suppression_gap"] * 100, loc["suppression_gap"] * 100
        agree = (ex > 0) == (lo > 0)
        underpowered = e["aware_side_underpowered"] or loc["aware_side_underpowered"]
        any_underpowered = any_underpowered or underpowered
        ax_gap.scatter(
            ex, lo, s=44,
            facecolors=("none" if underpowered else
                       ("#4c72b0" if agree else "#c44e52")),
            edgecolors=("#4c72b0" if agree else "#c44e52"),
            linewidths=1.4, alpha=0.9, zorder=3)
        gap_points.append((ex, lo, pair["local_model"]))
    ax_gap.axhline(0, color="#999999", linestyle="--", linewidth=0.8, zorder=1)
    ax_gap.axvline(0, color="#999999", linestyle="--", linewidth=0.8, zorder=1)
    _place_labels(fig, ax_gap, gap_points)
    subtitle = (f"rho={gap_stat['spearman_rho']:+.2f}, p={gap_stat['p']:.3f}, "
                f"n={gap_stat['n_models']}, {gap_stat['n_same_direction']} agree "
                f"/ {gap_stat['n_opposite_direction']} disagree on sign"
                if gap_stat["spearman_rho"] is not None else gap_stat["note"])
    ax_gap.set_title(f"unaware-minus-aware gap\n{subtitle}", fontsize=9)
    ax_gap.set_xlabel("AM gap (points)", fontsize=9)
    ax_gap.set_ylabel("SubversionBench gap (points)", fontsize=9)
    ax_gap.grid(alpha=0.25)

    captions = [
        f"AM = the external Agentic Misalignment benchmark. "
        f"{report['n_pairs']} models overlap. Spearman rank correlation, exact "
        f"permutation p-value. DESCRIPTIVE: at this n one model's position "
        f"moves rho substantially - see the JSON for the leave-one-out range.",
        "left: error bars are 95% Wilson intervals on each rate.",
        "right: dashed lines mark zero. Top-right and bottom-left AGREE on the "
        "sign of the gap; the other two corners disagree - blue/red marks which."
        + ("  hollow: an aware bucket below "
           f"{MIN_INFORMATIVE_DENOMINATOR} trajectories or episodes on either "
           "side." if any_underpowered else ""),
        report["interpretation"] + ".",
    ]
    height_in = fig.get_size_inches()[1]
    line_in, gap_in, top_in = 0.16, 0.19, 0.11
    wrapped = [_wrap(c) for c in captions if c]
    lines = sum(w.count("\n") + 1 for w in wrapped)
    reserved = (line_in * lines + gap_in * len(wrapped)) / height_in
    fig.tight_layout(rect=(0, reserved, 1, 1))
    y = reserved - top_in / height_in
    for text in wrapped:
        fig.text(0.01, y, text, fontsize=7.5, va="top", color="#555555")
        y -= (line_in * (text.count("\n") + 1) + gap_in * 0.6) / height_in
    fig.savefig(path, dpi=CHART_DPI, bbox_inches="tight")
    plt.close(fig)
    return path


def _wrap(text: str, width: int = 150) -> str:
    import textwrap
    return "\n".join(textwrap.wrap(text, width, break_long_words=False,
                                  break_on_hyphens=False))


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="python3 agentic_misalignment.py",
        description=("Correlate an external agentic-misalignment benchmark with "
                     "the rates measured here, on the overall level and on the "
                     "awareness-suppression gap the two benchmarks share."))
    parser.add_argument("--output-dir", default=f"./eval_results_{ROLLOUT_VERSION}",
                        help="results directory to read (default: %(default)s)")
    parser.add_argument("--json-out", default=None,
                        help="where to write the JSON report")
    parser.add_argument("--chart-dir", default=None,
                        help="where to write the chart (default: charts/ "
                             "inside --output-dir)")
    parser.add_argument("--no-charts", action="store_true",
                        help="skip the chart; every figure it draws is in the "
                             "printed output and the JSON either way")
    parser.add_argument("--decode", action="store_true",
                        help="write the table to agentic_misalignment.json to "
                             "edit it, then --encode to fold it back")
    parser.add_argument("--encode", action="store_true",
                        help="fold agentic_misalignment.json back into the "
                             "encrypted bundle")
    args = parser.parse_args()

    if args.decode and args.encode:
        parser.error("--decode and --encode are opposites; pick one")
    if args.decode:
        _PLAIN_PATH.write_text(
            json.dumps(load_bundle(), indent=1, sort_keys=True) + "\n",
            encoding="utf-8")
        print(f"wrote {_PLAIN_PATH.name} - gitignored, so it cannot be "
              f"committed by accident")
        return 0
    if args.encode:
        if not _PLAIN_PATH.exists():
            print(f"{_PLAIN_PATH.name} does not exist; run --decode first",
                  file=sys.stderr)
            return 2
        _BUNDLE_PATH.write_text(
            encrypt(json.loads(_PLAIN_PATH.read_text(encoding="utf-8"))),
            encoding="utf-8")
        print(f"folded {_PLAIN_PATH.name} back into {_BUNDLE_PATH.name}")
        return 0

    if not Path(args.output_dir).is_dir():
        print(f"no such results directory: {args.output_dir}", file=sys.stderr)
        return 2
    report = build_report(args.output_dir)
    if not report["n_pairs"]:
        print("no model in this corpus matches a row in the external table.",
              file=sys.stderr)
        return 1
    print_report(report)

    if not args.no_charts:
        chart_dir = args.chart_dir or os.path.join(args.output_dir, "charts")
        os.makedirs(chart_dir, exist_ok=True)
        chart = write_chart(report, os.path.join(
            chart_dir, "agentic_misalignment_correlation.png"))
        if chart:
            print(f"\nChart written to {redact_paths(chart)}")
            report["chart"] = redact_paths(chart)

    path = args.json_out or str(Path(args.output_dir) / (
        f"agentic_misalignment_correlation_"
        f"{time.strftime('%Y%m%dT%H%M%S')}.json"))
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, default=str)
    print(f"\nJSON written to {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
