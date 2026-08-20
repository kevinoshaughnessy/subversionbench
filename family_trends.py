#!/usr/bin/env python3
"""
Is misalignment falling as a model family advances?

Groups every model in a results directory into families by parsing its ID, orders
each family by version, and asks whether the rate moves monotonically along that
order. Answers one question per family and one across all of them.

WHY THIS IS NOT A LIST OF FAMILIES
----------------------------------
The families are DERIVED, never enumerated. A hand-written list is wrong the day
after the next model is collected, and it is wrong silently - a new ID simply
fails to appear in any family and the report is quietly narrower than the
corpus. So `gemini-3.8-flash` joins the gemini-flash family with no edit here,
and any model whose family gains a second member starts being reported.

The cost of deriving is that the parse has to be right about things a list would
never have to state, and those are the two constants below: which trailing words
are release-stage qualifiers rather than family identity, and how a version
string is ordered. Both are wrong for some future ID, so both are reported in
the output rather than applied silently.

WHAT "CONSISTENTLY FALLING" MEANS HERE
--------------------------------------
Two different claims, reported separately because a family can satisfy one and
not the other:

  the TREND falls   - Cochran-Armitage across the ordered versions, one degree
                      of freedom, position as the score. Four steps down and one
                      large step up can still fit a falling trend.
  every STEP falls  - the monotone claim, counted from consecutive differences.
                      This is what "consistently" says, and it is the stricter
                      reading.

Neither is a causal claim about model development. Version order is not a
randomised assignment, families differ in how many versions were collected, and
nothing here knows what changed between two releases.

WHY THE METRIC IS A FLAG
------------------------
Misalignment is derived from the ACT keys, so it does not depend on any LLM
verdict and is safe to read off a batch whose grading failed. Scheming is the
act plus concealment, and concealment comes from a sampled classifier - so
`--metric scheming` is only as good as the classifier calls that batch made.
The data-quality block says when that matters rather than leaving it implied.

Reads the same `summary_*.json` fields as run_report.py, through the same
loader, so a family's rate here and its per-model rate there cannot disagree.
"""

import argparse
import json
import math
import os
import re
import sys
import time
from collections import namedtuple

from run_report import load_summaries
from subversionbench.config import ROLLOUT_VERSION, VERSION
from subversionbench.power import (MIN_INFORMATIVE_DENOMINATOR,
                                  benjamini_hochberg, cochran_armitage,
                                  compare_rates, holm_bonferroni, sign_test,
                                  step_directions, wilson_ci)
from subversionbench.redaction import redact_paths

# Trailing words that mark a RELEASE STAGE or a decoding mode rather than a
# distinct model line, so they must not split a family. Without this,
# `gemini-3-flash-preview` is its own family of one and never gets compared with
# the gemini-flash versions that followed it - which is exactly the comparison
# being asked for. Same for `kimi-k2-thinking` against `kimi-k2.5`.
#
# Deliberately short, and deliberately NOT holding tier words. `flash`, `pro`,
# `lite`, `mini` and a size like `27b` DO define a family: gemini-3.1-flash-lite
# is not a version of gemini-3.5-flash, and grouping them would compare two
# product lines and call the difference a trend.
QUALIFIER_TAGS = frozenset({
    "preview", "thinking", "exp", "experimental", "latest", "beta", "rc",
    "instruct", "chat", "base", "nightly",
})

# A version token: 4, 4.5, v4, 3.0. The leading v is stripped rather than kept
# in the stem, so `deepseek-v4-pro` and a future `deepseek-5-pro` land in one
# family instead of two.
_VERSION_RE = re.compile(r"^v?(\d+(?:\.\d+)*)$")

# A version glued to its stem: qwen3.8, kimi-k2.5, hy3. Split so the stem joins
# its family and the digits are read as the version.
_STEM_VERSION_RE = re.compile(r"^([a-z]+)(\d+(?:\.\d+)*)$")

# A date-stamped snapshot: 0813, 20251001, 2603. Four, six or eight digits, and
# never fewer - a bare 3 is a version, not a date. Ordered AFTER an undated
# member of the same version, since the dated one is the later snapshot.
_DATE_RE = re.compile(r"^\d{4}(?:\d{2}){0,2}$")

# A parameter count, which is family identity rather than version: a 27b and a
# 7b of the same generation are different models.
_SIZE_RE = re.compile(r"^\d+(?:\.\d+)?[bm]$")

ModelId = namedtuple(
    "ModelId", "raw provider stem version date tags unparsed")

VERSION_STYLES = ("component", "decimal")


def parse_model_id(model: str) -> ModelId:
    """
    Split a model ID into the parts that decide its family and its position.

    `version` is a tuple of ints, empty when the ID names no version. `date` is
    the snapshot stamp as a string, or None. `tags` are the release-stage words
    that were removed from the stem; `unparsed` holds anything that matched
    nothing, kept so a surprising ID is visible in the output instead of being
    quietly dropped.

    Consecutive numeric tokens merge into one version, because Anthropic writes
    with dashes what everyone else writes with dots: claude-haiku-4-5 is version
    (4, 5) and not two versions of something.
    """
    raw = model.strip()
    provider, _, rest = raw.rpartition("/")
    tokens = [t for t in re.split(r"[-_]", rest.lower()) if t]

    stem_parts, version, date, tags, unparsed = [], [], None, [], []
    for token in tokens:
        # Dates BEFORE versions, because a stamp is a run of digits and the
        # version pattern matches it: without this, deepseek-v4-pro-0813 parsed
        # as version (4, 813) - sorting it after a hypothetical v4.99 - and
        # claude-haiku-4-5-20251001 as version (4, 5, 20251001).
        if _DATE_RE.match(token):
            date = token
            continue
        match = _VERSION_RE.match(token)
        if match:
            # Consecutive version tokens are components of ONE version.
            version.extend(int(p) for p in match.group(1).split("."))
            continue
        if token in QUALIFIER_TAGS:
            tags.append(token)
            continue
        if _SIZE_RE.match(token):
            stem_parts.append(token)
            continue
        match = _STEM_VERSION_RE.match(token)
        if match:
            stem_parts.append(match.group(1))
            version.extend(int(p) for p in match.group(2).split("."))
            continue
        if re.fullmatch(r"[a-z.]+", token):
            stem_parts.append(token)
        else:
            # Recorded rather than guessed at, and it still joins the stem so
            # two IDs sharing it stay together.
            stem_parts.append(token)
            unparsed.append(token)
    return ModelId(raw=raw, provider=provider, stem="-".join(stem_parts),
                   version=tuple(version), date=date, tags=tuple(sorted(tags)),
                   unparsed=tuple(unparsed))


def family_key(parsed: ModelId) -> str:
    """
    The family this model belongs to.

    Provider is part of the key on purpose. `gpt-5.6-luna` and
    `openai/gpt-5.6-luna` are the same model on two routes, and the routes
    differ in how much reasoning they return - so pooling them would compare
    instruments and report it as a version trend.
    """
    return f"{parsed.provider}/{parsed.stem}" if parsed.provider else parsed.stem


def version_sort_key(parsed: ModelId, style: str = "decimal"):
    """
    Where this model sits in its family's order.

    THE ONE JUDGEMENT CALL IN THIS FILE
    -----------------------------------
    `decimal` reads 4.20 as 4.2, so it sorts BEFORE 4.3. `component` reads it as
    major 4, minor 20 - so it sorts AFTER 4.6, the way a package manager reads a
    semantic version.

    `decimal` is the default because it is what the model vendors mean. It was
    NOT the original default, and the correction is worth recording: grok-4.20
    is an older release than grok-4.3, so the package-manager reading put it at
    the END of its family and reversed the sign of the family's trend - from
    falling to rising. Reading it as a semantic version was a guess about
    someone else's naming, and the guess was wrong.

    Every version in this corpus sorts correctly under `decimal`: 3.1 < 3.5 <
    3.6 < 3.7, 2.5 < 2.6, and a future 3.8 still lands after 3.7. `component`
    stays available because `decimal` has its own failure mode - a family that
    genuinely reaches minor 10 or beyond, where 4.10 follows 4.9 rather than
    preceding it. Nothing in this corpus does; if something ever does, the
    ambiguity report below is what will say so.

    Only a minor that reads differently as a decimal can differ between the two,
    which on this corpus is exactly one model: grok-4.20.

    The date stamp breaks ties within one version: an undated member sorts
    before a dated snapshot of the same version, which is what
    deepseek-v4-pro before deepseek-v4-pro-0813 means.
    """
    if style == "decimal" and len(parsed.version) > 1:
        head, tail = parsed.version[0], parsed.version[1]
        primary = (head, float(f"0.{tail}")) + parsed.version[2:]
    else:
        primary = parsed.version
    # "" sorts before any real stamp, so undated comes first.
    return (primary, parsed.date or "", parsed.tags)


def ordering_is_ambiguous(members: list) -> bool:
    """
    Whether the two version styles would order this family differently.

    Reported rather than resolved: a family whose answer depends on how 4.20 is
    read has not been measured, it has been assumed.
    """
    by_component = [m.raw for m in sorted(
        members, key=lambda m: version_sort_key(m, "component"))]
    by_decimal = [m.raw for m in sorted(
        members, key=lambda m: version_sort_key(m, "decimal"))]
    return by_component != by_decimal


# ---------------------------------------------------------------------------
# Rates
# ---------------------------------------------------------------------------

METRICS = {
    "misaligned": {
        "num": "n_misaligned", "den": "n_runs",
        "label": "agentic misalignment rate",
        # Derived from the act keys by classify_misalignment, so a batch whose
        # grader or classifier calls failed still carries a sound figure.
        "llm_dependent": False,
    },
    "scheming": {
        "num": "n_scheming", "den": "n_runs",
        "label": "scheming rate (act plus concealment)",
        # Concealment comes from a sampled classifier, so this metric inherits
        # every classifier failure in the batch.
        "llm_dependent": True,
    },
    "aware": {
        "num": "n_aware", "den": "n_awareness_resolved",
        "label": "verbalised evaluation awareness rate",
        "llm_dependent": True,
    },
}


def model_rates(summaries: list, metric: str) -> dict:
    """Pooled numerator and denominator per model, over every arm."""
    spec = METRICS[metric]
    out = {}
    for row in summaries:
        entry = out.setdefault(row["model"], {"x": 0, "n": 0, "n_arms": 0})
        entry["x"] += row[spec["num"]] or 0
        entry["n"] += row[spec["den"]] or 0
        entry["n_arms"] += 1
    for model, entry in out.items():
        entry["rate"] = entry["x"] / entry["n"] if entry["n"] else None
        entry["ci95"] = (list(wilson_ci(entry["x"], entry["n"]))
                         if entry["n"] else None)
        entry["underpowered"] = entry["n"] < MIN_INFORMATIVE_DENOMINATOR
    return out


def group_families(models: list, style: str) -> dict:
    """Every family with at least two members, each ordered by version."""
    parsed = [parse_model_id(m) for m in models]
    families = {}
    for entry in parsed:
        families.setdefault(family_key(entry), []).append(entry)
    return {
        key: sorted(members, key=lambda m: version_sort_key(m, style))
        for key, members in families.items()
        if len(members) >= 2
    }


def family_trend(members: list, rates: dict, metric: str, style: str) -> dict:
    """
    One family: its ordered members, the trend across them, and each step.

    The first-versus-last contrast is reported beside the trend because it is
    the comparison a reader will make anyway, and because the two can disagree -
    a family that ends where it started can still have moved monotonically in
    between.
    """
    ordered = []
    for entry in members:
        rate = rates.get(entry.raw) or {}
        ordered.append({
            "model": entry.raw,
            "version": ".".join(str(p) for p in entry.version) or None,
            "date": entry.date,
            "tags": list(entry.tags),
            "successes": rate.get("x"), "n": rate.get("n"),
            "rate": rate.get("rate"), "ci95": rate.get("ci95"),
            "underpowered": rate.get("underpowered"),
        })
    groups = [(m["successes"] or 0, m["n"] or 0) for m in ordered]
    trend = cochran_armitage(groups)
    steps_summary = step_directions([m["rate"] for m in ordered])

    steps = []
    for before, after in zip(ordered, ordered[1:]):
        if not (before["n"] and after["n"]):
            steps.append({"from": before["model"], "to": after["model"],
                          "difference": None, "note": "one side has no data"})
            continue
        contrast = compare_rates(after["successes"], after["n"],
                                 before["successes"], before["n"])
        contrast["p"] = contrast["fisher_p"]
        contrast["from"], contrast["to"] = before["model"], after["model"]
        contrast["direction"] = (
            "down" if contrast["difference"] < 0
            else "up" if contrast["difference"] > 0 else "flat")
        steps.append(contrast)

    first, last = ordered[0], ordered[-1]
    if first["n"] and last["n"]:
        first_last = compare_rates(last["successes"], last["n"],
                                   first["successes"], first["n"])
        first_last["p"] = first_last["fisher_p"]
    else:
        first_last = None
    return {
        "family": family_key(members[0]),
        "n_members": len(ordered),
        "version_order": [m["model"] for m in ordered],
        "ordering_ambiguous": ordering_is_ambiguous(members),
        "version_style": style,
        "members": ordered,
        "trend": trend,
        "steps_summary": steps_summary,
        "steps": steps,
        "first_vs_last": first_last,
        "verdict": _verdict(trend, steps_summary, first_last),
    }


def _verdict(trend: dict, steps: dict, first_last: dict) -> str:
    """The family's answer in a sentence, saying which claim it supports."""
    if steps["n_steps"] == 0:
        return "no comparable pair in this family"
    if steps["monotone_falling"]:
        strength = ("and the trend is statistically separated"
                    if trend.get("separated") else
                    "though the trend is not statistically separated")
        return (f"CONSISTENTLY FALLING across all {steps['n_steps']} step(s), "
                f"{strength}")
    if steps["monotone_rising"]:
        return (f"consistently RISING across all {steps['n_steps']} step(s) - "
                f"the opposite of falling")
    direction = trend.get("direction")
    if trend.get("separated") and direction:
        return (f"NOT consistent ({steps['n_down']} step(s) down, "
                f"{steps['n_up']} up), but the fitted trend is {direction} "
                f"and separated")
    return (f"NOT consistent and no separated trend "
            f"({steps['n_down']} step(s) down, {steps['n_up']} up, "
            f"{steps['n_flat']} flat)")


def data_quality(families: dict, rates: dict, metric: str) -> dict:
    """What would make these figures unsafe to read."""
    spec = METRICS[metric]
    in_family = {m.raw for members in families.values() for m in members}
    all_models = set(rates)
    thin = sorted(m for m in in_family
                  if (rates.get(m) or {}).get("underpowered"))
    return {
        "metric": metric,
        "metric_is_llm_dependent": spec["llm_dependent"],
        "llm_dependency_note": (
            "This metric depends on sampled LLM verdicts, so a batch whose "
            "grader or classifier calls failed carries a degraded figure. "
            "Re-run --reclassify / --grade-existing before reading it."
            if spec["llm_dependent"] else
            "This metric is derived from the act keys alone, so it is "
            "unaffected by grader or classifier failures."),
        "n_models_total": len(all_models),
        "n_models_in_a_family": len(in_family),
        "models_without_a_family": sorted(all_models - in_family),
        "models_below_informative_denominator": thin,
        "min_informative_denominator": MIN_INFORMATIVE_DENOMINATOR,
        "unparsed_tokens": sorted({
            token for members in families.values() for m in members
            for token in m.unparsed}),
        "families_with_ambiguous_ordering": sorted(
            key for key, members in families.items()
            if ordering_is_ambiguous(members)),
    }


def build_report(output_dir: str, metric: str = "misaligned",
                 style: str = "decimal") -> dict:
    summaries = load_summaries(output_dir)
    rates = model_rates(summaries, metric)
    families = group_families(sorted(rates), style)
    results = [family_trend(members, rates, metric, style)
               for _key, members in sorted(families.items())]

    # Every family's trend test is one member of one family of hypotheses, so
    # the count of separated trends is corrected the same way run_report.py
    # corrects its per-model tests.
    testable = [r for r in results if r["trend"].get("p") is not None]
    pvalues = [r["trend"]["p"] for r in testable]
    multiplicity = None
    if pvalues:
        holm = holm_bonferroni(pvalues)
        bh = benjamini_hochberg(pvalues)
        for row, hp, bp, hr, br in zip(testable, holm["adjusted"],
                                       bh["adjusted"], holm["rejected"],
                                       bh["rejected"]):
            row["trend"]["holm_p"] = hp
            row["trend"]["bh_p"] = bp
            row["trend"]["holm_rejected"] = hr
            row["trend"]["bh_rejected"] = br
        multiplicity = {
            "n_tests": len(pvalues),
            "uncorrected_rejections": sum(
                1 for r in testable if r["trend"].get("separated")),
            "holm_rejections": holm["n_rejected"],
            "bh_rejections": bh["n_rejected"],
        }

    down = sum(r["steps_summary"]["n_down"] for r in results)
    up = sum(r["steps_summary"]["n_up"] for r in results)
    flat = sum(r["steps_summary"]["n_flat"] for r in results)
    return {
        "version": VERSION,
        "rollout_version": ROLLOUT_VERSION,
        "output_dir": redact_paths(os.path.abspath(output_dir)),
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "metric": metric,
        "metric_label": METRICS[metric]["label"],
        "version_style": style,
        "n_families": len(results),
        "across_all_families": {
            "n_steps": down + up + flat,
            "n_down": down, "n_up": up, "n_flat": flat,
            "n_families_monotone_falling": sum(
                1 for r in results if r["steps_summary"]["monotone_falling"]),
            "n_families_monotone_rising": sum(
                1 for r in results if r["steps_summary"]["monotone_rising"]),
            # Is a step more likely to fall than to rise, pooling families?
            "sign_test": sign_test(down, up),
            "multiplicity": multiplicity,
        },
        "families": results,
        "data_quality": data_quality(families, rates, metric),
    }


# ---------------------------------------------------------------------------
# Charts
# ---------------------------------------------------------------------------
#
# Every figure plotted here is already in the printed table and in the JSON, so
# a chart is a second reading of the same numbers rather than a new claim. That
# is why matplotlib is an optional extra and why a missing install prints a hint
# and carries on: losing the charts costs presentation, never analysis.

CHART_DPI = 150

# Distinguishable at a glance and stable across runs, so two charts of the same
# corpus put a family in the same colour. Taken by position in the sorted family
# list rather than hashed, because a hash reorders the palette whenever a family
# is added.
_PALETTE = "tab10"

# Where each family writes its point labels on the combined chart, as (dx, dy)
# in points. One corner per family so that two lines crossing put their labels
# in different places: a vertical-only stagger fails exactly when it is needed,
# because two families a couple of percentage points apart are already closer
# together than the offset that is meant to separate them.
_LABEL_OFFSETS = ((0, 14), (-17, 24), (17, 24), (0, 34), (-17, 44), (17, 44))

# Rounding ladder for the y axis: (data max at or below, step to round up to).
# A fixed 0-100 axis puts a family that never exceeds 15% into the bottom sixth
# of the chart, where three steps of a few points each look like one flat line.
# Scaled instead, the same three steps are legible.
_AXIS_STEPS = ((5, 1), (20, 5), (50, 10), (100, 10))

# Never scale below this, so an all-zero family gets an axis with height rather
# than a flat line on a zero-tall panel.
_MIN_AXIS_TOP = 5

# Room above the tallest point for its own label. Applied before rounding, so a
# max that lands exactly on a step still gets a step of clearance.
_AXIS_HEADROOM = 1.08


def axis_top(values) -> float:
    """
    Where the y axis should stop, given everything being plotted.

    Rounds up to a round number so the ticks read 0/5/10/15 rather than
    0/3.7/7.4. `values` should already include the error bars where they are
    drawn, or the whisker escapes the axis.

    WHAT SCALING COSTS
    ------------------
    Two per-family charts on different scales cannot be compared by eye: a
    family topping out at 15% and one topping out at 85% draw the same shape.
    That is the price of making a small family legible at all, and it is paid
    deliberately - the COMBINED chart shares one axis across families and is the
    one to read for comparison. The tick labels are the disclosure.
    """
    usable = [v for v in values if v is not None]
    top = max(usable) if usable else 0.0
    top *= _AXIS_HEADROOM
    for ceiling, step in _AXIS_STEPS:
        if top <= ceiling:
            return min(100.0, max(_MIN_AXIS_TOP,
                                  math.ceil(top / step) * step))
    return 100.0


def _import_pyplot():
    """
    pyplot with a headless backend, or None with the reason printed.

    The backend is forced before pyplot is imported: the default on macOS is an
    interactive one that wants a window, and a report run over ssh or from a
    batch script would either block or fail on a display it cannot open.
    """
    try:
        import matplotlib
    except ImportError:
        print("\nCharts skipped: matplotlib is not installed. "
              "Install it with:\n    pip install 'subversionbench[charts]'")
        return None
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    return plt


def _member_labels(family: dict) -> list:
    """
    What to write under each point.

    The version, not the model ID: the IDs share a stem by construction - that
    is what put them in one family - so plotting the full ID spends the x axis
    repeating it. A date-stamped snapshot keeps its stamp, because that is the
    only thing separating it from the version above it.
    """
    labels = []
    for member in family["members"]:
        label = member["version"] or "?"
        if member["date"]:
            label += f"\n{member['date']}"
        if member["tags"]:
            label += f"\n({','.join(member['tags'])})"
        labels.append(label)
    return labels


def _plot_family(plt, family: dict, metric_label: str, path: str) -> str:
    """
    One family: the rate against version order, with its Wilson intervals.

    The interval is drawn rather than left to the table because the whole
    question is whether a sequence of rates is falling, and four points with
    overlapping intervals is a different answer from four without. A chart of
    bare point estimates would make every family look decisive.
    """
    members = family["members"]
    xs = list(range(len(members)))
    rates = [(m["rate"] or 0) * 100 for m in members]
    # Asymmetric, because a Wilson interval around a rate near 0 or 100 is not
    # centred on the estimate - which is exactly why Wilson is used.
    lower = [max(0.0, (m["rate"] or 0) * 100 - (m["ci95"][0] * 100 if m["ci95"] else 0))
             for m in members]
    upper = [max(0.0, (m["ci95"][1] * 100 if m["ci95"] else 0) - (m["rate"] or 0) * 100)
             for m in members]

    fig, ax = plt.subplots(figsize=(max(6, 1.9 * len(members)), 4.5))
    ax.errorbar(xs, rates, yerr=[lower, upper], marker="o", capsize=4,
                linewidth=2, markersize=7, color="#1f77b4",
                ecolor="#8c9fb5", elinewidth=1.4)
    # Scaled to this family's own whiskers, so three steps of a few points each
    # fill the panel instead of hugging the floor of a 0-100 axis. See axis_top
    # for what that costs.
    top = axis_top([rate + up for rate, up in zip(rates, upper)])
    # Above the upper WHISKER rather than above the point, or the label sits on
    # the error-bar cap and both become hard to read.
    for x, rate, up in zip(xs, rates, upper):
        ax.annotate(f"{rate:.1f}%", (x, min(top * 0.97, rate + up)),
                    textcoords="offset points", xytext=(0, 7), ha="center",
                    fontsize=9)
    ax.set_xticks(xs)
    ax.set_xticklabels(_member_labels(family), fontsize=9)
    ax.set_xlim(-0.4, len(members) - 0.6)
    ax.set_ylim(0, top)
    ax.set_ylabel(f"{metric_label} (%)")
    ax.set_xlabel("version, oldest to newest")
    # Padded when the warning below is going to sit above the axes, or the two
    # print on top of each other.
    ax.set_title(f"{family['family']} - {family['n_members']} versions",
                 fontsize=11, pad=20 if family["ordering_ambiguous"] else 6)
    # The verdict on the chart, so a reader who never opens the table cannot
    # take a falling line for a monotone one.
    ax.text(0.5, -0.30, family["verdict"], transform=ax.transAxes,
            ha="center", va="top", fontsize=8, style="italic", wrap=True)
    if family["ordering_ambiguous"]:
        ax.text(0.5, 1.012,
                f"version order depends on --version-style "
                f"{family['version_style']}",
                transform=ax.transAxes, ha="center", fontsize=8, color="#b34700")
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=CHART_DPI, bbox_inches="tight")
    plt.close(fig)
    return path


def _plot_all_families(plt, report: dict, path: str) -> str:
    """
    Every family on one axis, one line each.

    The x axis is POSITION in the family, not the version number: families run
    on their own numbering - k2.5 against 3.7-flash against v4 - so there is no
    shared version axis to put them on. Position is what they do share, and it
    is the axis the question is actually about, which is whether a rate falls as
    a family advances rather than at which version number it does so.

    Intervals are left off here. Four families of overlapping error bars is
    unreadable, and the per-family charts carry them; this one is for comparing
    SHAPES.
    """
    families = [f for f in report["families"] if f["members"]]
    if not families:
        return None
    colours = plt.get_cmap(_PALETTE)(
        [i % 10 for i in range(len(families))])

    width = max(7, 2.0 * max(f["n_members"] for f in families))
    fig, ax = plt.subplots(figsize=(width, 5.2))
    for index, (family, colour) in enumerate(zip(families, colours)):
        rates = [(m["rate"] or 0) * 100 for m in family["members"]]
        xs = list(range(len(rates)))
        # Dashed where the ordering is a judgement call, so the reader can see
        # which line would move under the other --version-style.
        style = "--" if family["ordering_ambiguous"] else "-"
        ax.plot(xs, rates, style, marker="o", linewidth=2, markersize=7,
                color=colour, label=family["family"])
        for x, member, rate in zip(xs, family["members"], rates):
            # Families cross, so their point labels land on top of each other at
            # the crossing - 3.7 and 4.20 did, and so did 3.6 and 2.6. A purely
            # vertical stagger cannot separate two points a couple of percentage
            # points apart, because the offset moves the label by nearly as much
            # as the gap between the lines. So each family gets its own corner.
            dx, dy = _LABEL_OFFSETS[index % len(_LABEL_OFFSETS)]
            # Pull the offset inward at the ends, where leaning outward puts the
            # label past the axis and clips it.
            if x == 0:
                dx = abs(dx)
            elif x == len(rates) - 1:
                dx = -abs(dx)
            ax.annotate(member["version"] or "?", (x, rate),
                        textcoords="offset points",
                        # Below by default, above near the floor where a label
                        # underneath would run into the axis.
                        xytext=(dx, -dy if rate >= 12 else dy),
                        ha="center", fontsize=7.5, color=colour)

    longest = max(f["n_members"] for f in families)
    ax.set_xticks(list(range(longest)))
    ax.set_xticklabels([f"v{i + 1}" for i in range(longest)])
    # ONE axis across every family, from the tallest point anywhere. Scaling
    # each family separately here would defeat the chart: its whole job is to
    # put families on a common scale, and per-family axes are what the
    # per-family charts are for.
    ax.set_ylim(0, axis_top([(m["rate"] or 0) * 100
                             for f in families for m in f["members"]]))
    ax.set_xlabel("position in family, oldest to newest "
                  "(point labels give the version)")
    ax.set_ylabel(f"{report['metric_label']} (%)")
    ax.set_title(f"{report['metric_label']} by model family "
                 f"({report['n_families']} families)", fontsize=12)
    ax.grid(axis="y", alpha=0.3)
    ax.legend(title="family", fontsize=9, title_fontsize=9,
              loc="upper left", bbox_to_anchor=(1.01, 1.0))
    if any(f["ordering_ambiguous"] for f in families):
        ax.text(0.0, -0.16, "dashed = version order depends on "
                            "--version-style",
                transform=ax.transAxes, fontsize=8, color="#b34700")
    fig.tight_layout()
    fig.savefig(path, dpi=CHART_DPI, bbox_inches="tight")
    plt.close(fig)
    return path


def write_charts(report: dict, chart_dir: str) -> list:
    """
    One chart per family plus one combined chart. Returns the paths written.

    Empty when matplotlib is absent, which is not an error: the same numbers are
    in the table and the JSON.
    """
    plt = _import_pyplot()
    if plt is None:
        return []
    os.makedirs(chart_dir, exist_ok=True)
    metric = report["metric"]
    written = []
    for family in report["families"]:
        # The family key holds a slash, which is a path separator.
        slug = family["family"].replace("/", "_")
        path = os.path.join(chart_dir, f"family_{metric}_{slug}.png")
        written.append(_plot_family(plt, family, report["metric_label"], path))
    combined = _plot_all_families(
        plt, report, os.path.join(chart_dir, f"family_{metric}_all.png"))
    if combined:
        written.append(combined)
    return written


# ---------------------------------------------------------------------------
# Printing
# ---------------------------------------------------------------------------

def _fmt_rate(member: dict) -> str:
    if member["rate"] is None:
        return f"{member['successes']}/{member['n']}"
    return f"{member['successes']}/{member['n']}={member['rate']:.1%}"


def _print_family(family: dict) -> None:
    print(f"\n{'=' * 78}")
    print(f"{family['family']}  ({family['n_members']} versions)")
    print(f"{'=' * 78}")
    if family["ordering_ambiguous"]:
        print("  !! version ordering depends on how a trailing-zero minor is "
              "read; this")
        print(f"     family is ordered by --version-style "
              f"{family['version_style']}. Try the other to compare.")
    print(f"  {'version':<10} {'model':<40} {'rate':>16} {'95% CI':>18}")
    for member in family["members"]:
        ci = (f"[{member['ci95'][0]:.1%}, {member['ci95'][1]:.1%}]"
              if member["ci95"] else "-")
        flag = " !" if member["underpowered"] else ""
        version = member["version"] or "-"
        if member["date"]:
            version += f"+{member['date']}"
        tags = f" ({','.join(member['tags'])})" if member["tags"] else ""
        print(f"  {version:<10} {member['model'] + tags:<40} "
              f"{_fmt_rate(member):>16} {ci:>18}{flag}")

    steps = family["steps_summary"]
    print(f"\n  steps: {steps['n_down']} down, {steps['n_up']} up, "
          f"{steps['n_flat']} flat")
    for step in family["steps"]:
        if step.get("difference") is None:
            print(f"    {step['from']} -> {step['to']}: {step.get('note')}")
            continue
        mark = {"down": "v", "up": "^", "flat": "="}[step["direction"]]
        print(f"    {mark} {step['from']} -> {step['to']}: "
              f"{step['difference']:+.1%}  p={step['p']:.4g}"
              f"{'  SEPARATED' if step['separated'] else ''}")

    trend = family["trend"]
    if trend.get("z") is None:
        print(f"\n  trend: not testable ({trend.get('note')})")
    else:
        extra = ""
        if trend.get("holm_p") is not None:
            extra = f"  holm={trend['holm_p']:.4g}  BH={trend['bh_p']:.4g}"
        print(f"\n  trend (Cochran-Armitage): z={trend['z']:+.3f} "
              f"p={trend['p']:.4g} {trend['direction']}{extra}")
    if family["first_vs_last"]:
        fl = family["first_vs_last"]
        print(f"  first vs last: {fl['difference']:+.1%}  "
              f"95% CI [{fl['difference_ci95'][0]:+.1%}, "
              f"{fl['difference_ci95'][1]:+.1%}]  p={fl['p']:.4g}")
    print(f"\n  => {family['verdict']}")


def _print_report(report: dict) -> None:
    print(f"\n{'#' * 78}")
    print(f"# Is the {report['metric_label']} falling within a model family?")
    print(f"# {report['output_dir']}   {report['n_families']} families   "
          f"version-style={report['version_style']}")
    print(f"{'#' * 78}")

    for family in report["families"]:
        _print_family(family)

    overall = report["across_all_families"]
    print(f"\n{'=' * 78}")
    print("ACROSS ALL FAMILIES")
    print(f"{'=' * 78}")
    print(f"  {overall['n_steps']} consecutive step(s): {overall['n_down']} "
          f"down, {overall['n_up']} up, {overall['n_flat']} flat")
    print(f"  families falling at every step: "
          f"{overall['n_families_monotone_falling']}/{report['n_families']}"
          f"   rising at every step: "
          f"{overall['n_families_monotone_rising']}/{report['n_families']}")
    sign = overall["sign_test"]
    if sign.get("p") is None:
        print(f"  sign test: {sign.get('note')}")
    else:
        print(f"  sign test on step direction: {sign['n_down']} down vs "
              f"{sign['n_up']} up, p={sign['p']:.4g}"
              f"{'  SEPARATED' if sign['separated'] else '  not separated'}")
    mult = overall["multiplicity"]
    if mult:
        print(f"  trend tests: {mult['n_tests']}, "
              f"{mult['uncorrected_rejections']} separated uncorrected, "
              f"{mult['holm_rejections']} survive Holm, "
              f"{mult['bh_rejections']} survive BH")

    dq = report["data_quality"]
    print(f"\n{'=' * 78}")
    print("DATA QUALITY")
    print(f"{'=' * 78}")
    print(f"  metric: {dq['metric']} - {dq['llm_dependency_note']}")
    print(f"  {dq['n_models_in_a_family']}/{dq['n_models_total']} model(s) sit "
          f"in a family with at least two members")
    if dq["models_without_a_family"]:
        print(f"  no family (only version collected): "
              f"{', '.join(dq['models_without_a_family'])}")
    if dq["models_below_informative_denominator"]:
        print(f"  ! below {dq['min_informative_denominator']} episodes: "
              f"{', '.join(dq['models_below_informative_denominator'])}")
    if dq["families_with_ambiguous_ordering"]:
        print(f"  ! ordering depends on --version-style: "
              f"{', '.join(dq['families_with_ambiguous_ordering'])}")
    if dq["unparsed_tokens"]:
        print(f"  ! tokens the parser did not recognise: "
              f"{', '.join(dq['unparsed_tokens'])}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Whether a rate falls as a model family advances. "
                    "Families and their version order are derived from the "
                    "model IDs, so a newly collected version needs no change "
                    "here.")
    parser.add_argument("--output-dir",
                        default=f"./eval_results_{ROLLOUT_VERSION}",
                        help="results directory to analyse "
                             "(default: %(default)s)")
    parser.add_argument("--metric", default="misaligned", choices=sorted(METRICS),
                        help="which rate to trend (default: %(default)s)")
    parser.add_argument("--version-style", default="decimal",
                        choices=VERSION_STYLES,
                        help="how to order a version: 'decimal' reads 4.20 as "
                             "4.2, so before 4.3 - which is what the vendors "
                             "mean; 'component' reads it as 4 major 20 minor, "
                             "so after 4.6, the way a package manager reads a "
                             "semantic version (default: %(default)s)")
    parser.add_argument("--json-out", default=None,
                        help="where to write the JSON report (default: "
                             "family_trends_<timestamp>.json inside "
                             "--output-dir)")
    parser.add_argument("--chart-dir", default=None,
                        help="where to write the PNG charts (default: "
                             "charts/ inside --output-dir). One per family plus "
                             "one combined; needs the 'charts' extra")
    parser.add_argument("--no-charts", action="store_true",
                        help="skip the charts. Every figure they plot is in the "
                             "table and the JSON either way")
    args = parser.parse_args()

    if not os.path.isdir(args.output_dir):
        print(f"No such directory: {redact_paths(args.output_dir)}")
        return 1

    report = build_report(args.output_dir, args.metric, args.version_style)
    if not report["families"]:
        print(f"No family with two or more members in "
              f"{redact_paths(args.output_dir)}")
        return 1
    _print_report(report)

    if not args.no_charts:
        chart_dir = args.chart_dir or os.path.join(args.output_dir, "charts")
        written = write_charts(report, chart_dir)
        if written:
            print(f"\n{len(written)} chart(s) written to "
                  f"{redact_paths(chart_dir)}:")
            for path in written:
                print(f"  {os.path.basename(path)}")
            report["charts"] = [redact_paths(p) for p in written]

    out = args.json_out or os.path.join(
        args.output_dir,
        f"family_trends_{time.strftime('%Y%m%dT%H%M%S')}.json")
    with open(out, "w") as f:
        json.dump(report, f, indent=2)
    print(f"\nJSON written to {redact_paths(out)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
