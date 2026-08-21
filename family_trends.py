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

TWO X AXES, TWO DIFFERENT QUESTIONS
-----------------------------------
Version POSITION spaces every release equally, which is the axis the trend tests
run on and the one the question is about. It also hides the calendar: four grok
releases over four months and four gemini releases over eight draw the same
shape on it. So each chart is drawn a second time against the release dates in
model_releases.py, with no connecting lines - a segment between two releases
would invite reading a slope off months in which nothing was measured. Each
family gets one straight dotted least-squares fit there instead, which says how
fast in time and carries no p-value: the test stays on version position, and
refitting on the calendar with an interval would be a second test of one
hypothesis on one dataset.

A release date cannot be derived from a model ID, so it has to be recorded, and
a model that has not been recorded is reported as an error and then dropped from
the release charts alone. Nothing else here depends on a date: every rate,
interval, trend and p-value is computed from version order.

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
from datetime import date, timedelta

from model_releases import release_date
from run_report import load_summaries
from subversionbench.config import ROLLOUT_VERSION, VERSION
from subversionbench.power import (MIN_INFORMATIVE_DENOMINATOR,
                                  benjamini_hochberg, cochran_armitage,
                                  compare_rates, holm_bonferroni, sign_test,
                                  step_directions, weighted_least_squares,
                                  wilson_ci)
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

    # `stamp` rather than `date`: this module now imports datetime.date for the
    # release-date charts, and a local of that name would shadow it here.
    stem_parts, version, stamp, tags, unparsed = [], [], None, [], []
    for token in tokens:
        # Dates BEFORE versions, because a stamp is a run of digits and the
        # version pattern matches it: without this, deepseek-v4-pro-0813 parsed
        # as version (4, 813) - sorting it after a hypothetical v4.99 - and
        # claude-haiku-4-5-20251001 as version (4, 5, 20251001).
        if _DATE_RE.match(token):
            stamp = token
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
                   version=tuple(version), date=stamp, tags=tuple(sorted(tags)),
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
        # What n counts, for the charts. Not always "episodes": the awareness
        # denominator is the episodes whose verdict RESOLVED, which is fewer.
        "denominator_label": "episodes",
        # Derived from the act keys by classify_misalignment, so a batch whose
        # grader or classifier calls failed still carries a sound figure.
        "llm_dependent": False,
    },
    "scheming": {
        "num": "n_scheming", "den": "n_runs",
        "label": "scheming rate (act plus concealment)",
        "denominator_label": "episodes",
        # Concealment comes from a sampled classifier, so this metric inherits
        # every classifier failure in the batch.
        "llm_dependent": True,
    },
    "aware": {
        "num": "n_aware", "den": "n_awareness_resolved",
        "label": "verbalised evaluation awareness rate",
        "denominator_label": "graded episodes",
        "llm_dependent": True,
    },
}


# Runs every metric in one invocation. Not a metric itself, so it never reaches
# METRICS - the loop in main expands it and each pass is an ordinary single-metric
# run, which is what keeps the two paths from drifting apart.
METRIC_ALL = "all"


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
        # `date` is the snapshot stamp parsed out of the ID and says nothing
        # about when the model shipped; `released` is the recorded release date
        # and is None for anything model_releases.py has not been told about.
        # Two different things, kept as two fields rather than merged.
        released = release_date(entry.raw)
        ordered.append({
            "model": entry.raw,
            "version": ".".join(str(p) for p in entry.version) or None,
            "date": entry.date,
            "released": released.isoformat() if released else None,
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
        # In the report rather than computed at draw time, so the dotted line on
        # the chart and the slope in the JSON cannot disagree - the same rule the
        # rest of this file follows, that a chart is a second reading of numbers
        # the report already holds rather than a place where new ones appear.
        "release_fit": release_fit(ordered),
    }


# The unit a slope is reported in. Points per DAY is always -0.00 or +0.00 at
# this precision, and points per YEAR extrapolates wildly past the data: grok's
# four releases span 134 days, and its fit reads +197.9 points/year - a rise no
# rate can make. A month is the largest unit no family in this corpus outruns, so
# the reported number stays inside the window it was fitted on.
_DAYS_PER_MONTH = 30.44


def release_fit(members: list) -> dict:
    """
    The straight line through a family's rates against their release dates.

    DESCRIPTIVE, and deliberately not a second trend test. The statistic in this
    file is Cochran-Armitage on version POSITION; refitting on the calendar and
    reporting a p-value would be a second test of one hypothesis on one dataset,
    and it would assume something the position test does not - that the rate
    moves by a constant amount per month.

    So this returns a slope and two endpoints and no inference. What it adds is
    the thing the position axis cannot show: how fast, in time.

    The endpoints are the family's OWN first and last release, never the full
    axis. Extending the line across months in which the family shipped nothing
    would draw a claim about models that do not exist.

    None where no line is defined - fewer than two dated members, or every
    member released on one day.
    """
    dated = [(m, _member_release_date(m)) for m in members
             if _member_release_date(m) and m.get("rate") is not None]
    if len(dated) < 2:
        return None
    first = min(when for _m, when in dated)
    xs = [(when - first).days for _m, when in dated]
    ys = [m["rate"] for m, _when in dated]
    fit = weighted_least_squares(xs, ys, [m.get("n") or 0 for m, _w in dated])
    if fit["slope"] is None:
        return {"n_points": fit["n_points"], "slope_per_month": None,
                "span_days": (max(when for _m, when in dated) - first).days,
                "note": fit["note"]}
    last_x = max(xs)
    return {
        "n_points": len(dated),
        "weighted_by": "episodes",
        "slope_per_month": fit["slope"] * _DAYS_PER_MONTH,
        # How much calendar the fit actually covers. A slope with no span is the
        # number that invites extrapolating it past the last release.
        "span_days": last_x,
        "from": {"released": first.isoformat(), "rate": fit["intercept"]},
        "to": {"released": (first + timedelta(days=last_x)).isoformat(),
               "rate": fit["intercept"] + fit["slope"] * last_x},
        # Two points determine a line exactly, so the fit repeats them and adds
        # nothing. Said here rather than left for the reader to notice, and the
        # chart repeats it.
        "note": ("two points: the line is exact and carries nothing the two "
                 "points do not" if len(dated) == 2 else None),
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
        # An ERROR rather than a note, because unlike everything else in this
        # block it is fixable in one edit and it silently shrinks a chart: an
        # undated model cannot be placed on a calendar axis, so it vanishes from
        # the release charts while still appearing in every table. Reported for
        # the whole corpus, with the plotted ones separated out, since a
        # singleton's missing date costs nothing - it is in no family and so on
        # no chart either way.
        "models_without_release_date": sorted(
            m for m in all_models if release_date(m) is None),
        "plotted_models_without_release_date": sorted(
            m for m in in_family if release_date(m) is None),
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
        "metric_denominator_label": METRICS[metric]["denominator_label"],
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

# Point labels on the combined chart sit BESIDE their marker, not above or
# below it, because the error bars own the vertical space at each x. Horizontal
# clearance, then one row of vertical separation per colliding family.
_LABEL_DX = 10
_LABEL_ROW = 11

# How close two families have to be, as a fraction of the axis height, before
# their labels are treated as colliding.
_LABEL_GAP = 0.06

# Wording used on every chart that draws an interval, so the reader is never
# left to guess what the whiskers are.
WILSON_NOTE = "error bars: 95% Wilson intervals"
WILSON_NOTE_WITH_BRACKETS = (
    "error bars and [brackets]: 95% Wilson intervals")
# The release charts draw no error bars, so the brackets are the only interval
# on them and the note has to say so alone.
WILSON_NOTE_BRACKETS_ONLY = "[brackets]: 95% Wilson intervals"

# Every chart that draws a fitted line says what the line is. Without this a
# dotted line through four points reads as a trend TEST, which it is not: the
# test in this file runs on version position, and this is a description of the
# same rates against the calendar.
FIT_NOTE = ("dotted: least-squares fit on release date, weighted by episodes "
            "(descriptive, no p-value)")

# Where the release-date axis starts. Fixed rather than taken from the earliest
# model, so that adding an older model does not silently rescale every chart in
# the corpus and change what a reader remembers the spacing to look like.
#
# It is a FLOOR, not a hard left edge: release_span extends it leftward if a
# model predates it, because a point drawn outside the axis is worse than an
# axis that begins earlier than asked for.
#
# Was 2025-07-01, which put four empty months at the left of every chart: the
# earliest model in a family in r9 is kimi-k2-thinking on 2025-11-06, and
# kimi-k2 and kimi-k2-0905 are older but sit in no family here. Moving the floor
# spends the width on the range that carries points. It is still a floor, so an
# older model collected later reclaims the space automatically.
RELEASE_AXIS_START = date(2025, 11, 1)

# Horizontal clearance and one row of vertical separation per colliding label,
# the same mechanism the combined version chart uses. Two labels collide when
# they are close on BOTH axes - a calendar axis puts three deepseek and gemini
# releases within days of each other, at rates far enough apart to need no
# stagger at all.
_DATE_LABEL_DX = 8
_DATE_LABEL_ROW = 11

# Labels sit just ABOVE their point rather than centred on it. Centred is what
# the combined version chart does, and it cannot work here: the newest model in
# a family often sits at 0.0%, where a centred label straddles the x axis and
# half of it prints over the spine.
_DATE_LABEL_DY = 5

# How high a point has to sit, as a fraction of the axis, before its label is
# written below it instead of above. A 100% rate is a real answer in this corpus,
# and a label above one prints over the title.
_DATE_LABEL_CEILING = 0.88

# How close two points have to be on the x axis, as a fraction of the plotted
# span, before their labels are treated as sharing a column. Also how close to
# the right edge a point has to be before its label is written leftward.
_DATE_LABEL_XGAP = 0.09

# Mean glyph advance as a fraction of the font size, used to estimate how wide a
# label is before anything is drawn. Generous on purpose: over-estimating costs a
# row of stagger that was not needed, under-estimating costs a collision.
_LABEL_CHAR_PT = 0.6

# Roughly how many points of the figure width the axes get, once the margins and
# (on the combined chart) the legend are taken out. Only ever used to convert a
# label's width into days, so an estimate is enough - and the figure widths it
# divides are fixed a few lines below in the plotting calls.
_PER_FAMILY_AXIS_PT = 540.0
_COMBINED_AXIS_PT = 500.0


def _point_label(member: dict, rate: float) -> str:
    """
    The rate and its interval, for the label above a point.

    The interval is written out beside the estimate rather than left to the
    error bar alone, because a whisker can be read off the axis only
    approximately and the numbers are what a reader copies into a write-up. A
    member with no interval - nothing collected - gets the rate alone rather
    than an empty pair of brackets.

    Percent signs are not repeated inside the brackets: the axis is already in
    percent and `86.6% [81.7, 90.3]` reads more cleanly than the alternative.
    """
    label = f"{rate:.1f}%"
    if member.get("ci95"):
        low, high = member["ci95"]
        label += f" [{low * 100:.1f}, {high * 100:.1f}]"
    return label


def _lower_error(member: dict) -> float:
    """Distance from the rate down to its Wilson lower bound, in points."""
    if not member.get("ci95"):
        return 0.0
    return max(0.0, (member["rate"] or 0) * 100 - member["ci95"][0] * 100)


def _upper_error(member: dict) -> float:
    """
    Distance from the rate up to its Wilson upper bound, in points.

    Asymmetric with the lower bound by construction: a Wilson interval around a
    rate near 0 or 100 is not centred on the estimate, which is the reason
    Wilson is used here rather than the normal approximation.
    """
    if not member.get("ci95"):
        return 0.0
    return max(0.0, member["ci95"][1] * 100 - (member["rate"] or 0) * 100)


def _label_layout(families: list, longest: int, top: float) -> dict:
    """
    Where each family's point label goes, as {(family, x): (dx, dy)} in points.

    WHY THIS IS A LAYOUT PASS AND NOT A PER-FAMILY CONSTANT
    -------------------------------------------------------
    Each family used to get a fixed corner, which cannot work: an offset chosen
    without looking at the other families pushes a label straight into one of
    them. grok's 4.3 sits at 0.0% and its fixed offset lifted the label 34
    points, landing it on kimi's marker at 13.3% - a collision created by the
    very mechanism meant to prevent one.

    So the labels at each x are laid out together. Families are sorted by rate
    and given a row each only where they are close enough to overlap, so a chart
    whose lines are well separated gets no stagger at all and stays readable.
    """
    layout = {}
    for x in range(longest):
        present = sorted(
            ((index, (family["members"][x]["rate"] or 0) * 100)
             for index, family in enumerate(families)
             if x < family["n_members"]),
            key=lambda pair: pair[1])
        row = 0
        for position, (index, rate) in enumerate(present):
            if position and rate - present[position - 1][1] < top * _LABEL_GAP:
                # Push the HIGHER of the two upward, away from the one below.
                row += 1
            else:
                row = 0
            # Lean left on the last column so a label cannot run off the axis.
            dx = -_LABEL_DX if x == longest - 1 else _LABEL_DX
            layout[(index, x)] = (dx, row * _LABEL_ROW)
    return layout

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
        # The denominator each point's rate and interval are computed on. A
        # width of interval means nothing without it, and it is not constant
        # across a family - gemini-3.5-flash carries 205 against its siblings'
        # 120, and grok-4.5 239 against 120.
        if member.get("n") is not None:
            label += f"\nn={member['n']}"
        labels.append(label)
    return labels


def _plot_family(plt, family: dict, metric_label: str, den_label: str,
                 path: str) -> str:
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
    lower = [_lower_error(m) for m in members]
    upper = [_upper_error(m) for m in members]

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
    for x, member, rate, up in zip(xs, members, rates, upper):
        ax.annotate(_point_label(member, rate),
                    (x, min(top * 0.97, rate + up)),
                    textcoords="offset points", xytext=(0, 7), ha="center",
                    fontsize=8)
    ax.set_xticks(xs)
    ax.set_xticklabels(_member_labels(family), fontsize=9)
    ax.set_xlim(-0.4, len(members) - 0.6)
    ax.set_ylim(0, top)
    ax.set_ylabel(f"{metric_label} (%)")
    ax.set_xlabel(f"version, oldest to newest    ({WILSON_NOTE_WITH_BRACKETS})")
    # Padded when the warning below is going to sit above the axes, or the two
    # print on top of each other.
    total = sum(m["n"] or 0 for m in members)
    ax.set_title(f"{family['family']} - {family['n_members']} versions, "
                 f"{total} {den_label}",
                 fontsize=11, pad=20 if family["ordering_ambiguous"] else 6)
    # NO VERDICT CAPTION.
    #
    # It used to sit under the axis, on the reasoning that a reader who never
    # opened the table might take a falling line for a monotone one. Two things
    # were wrong with that. The chart already shows the direction and, now that
    # the intervals are drawn, roughly how firm each step is - so the caption
    # restated what was in front of the reader. And its wording is directional:
    # "consistently RISING - the opposite of falling" reads as a disappointment,
    # which is right for misalignment and wrong for awareness, where a rise with
    # capability is the expected result rather than a failure to improve. A
    # caption that means different things by metric is worse than none.
    #
    # The verdict is unchanged in the console table and in the JSON, where it
    # sits beside the counts it is derived from.
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
    colours = _family_colours(plt, families)

    width = max(7, 2.0 * max(f["n_members"] for f in families))
    fig, ax = plt.subplots(figsize=(width, 5.2))
    longest = max(f["n_members"] for f in families)
    # Computed before anything is drawn, because the whiskers have to fit and
    # the label layout needs to know how tall a percentage point is.
    top = axis_top([(m["rate"] or 0) * 100 + _upper_error(m)
                    for f in families for m in f["members"]])
    layout = _label_layout(families, longest, top)

    for index, (family, colour) in enumerate(zip(families, colours)):
        members = family["members"]
        rates = [(m["rate"] or 0) * 100 for m in members]
        xs = list(range(len(rates)))
        # Dashed where the ordering is a judgement call, so the reader can see
        # which line would move under the other --version-style.
        style = "--" if family["ordering_ambiguous"] else "-"
        # Intervals at a lighter weight than the lines, so four families of them
        # read as uncertainty around the shapes rather than competing with them.
        ax.errorbar(xs, rates,
                    yerr=[[_lower_error(m) for m in members],
                          [_upper_error(m) for m in members]],
                    fmt=style, marker="o", linewidth=2, markersize=7,
                    color=colour,
                    label=f"{family['family']}  "
                          f"(n={sum(m['n'] or 0 for m in members)})",
                    ecolor=colour, elinewidth=1.1, capsize=3, alpha=0.9)
        for x, member, rate in zip(xs, members, rates):
            dx, dy = layout[(index, x)]
            ax.annotate(member["version"] or "?", (x, rate),
                        textcoords="offset points", xytext=(dx, dy),
                        ha="left" if dx > 0 else "right", va="center",
                        fontsize=7.5, color=colour,
                        # Four families cross each other, so a label with no
                        # backing has another family's line drawn through it.
                        bbox={"boxstyle": "round,pad=0.15", "fc": "white",
                              "ec": "none", "alpha": 0.72})

    ax.set_xticks(list(range(longest)))
    ax.set_xticklabels([f"v{i + 1}" for i in range(longest)])
    # ONE axis across every family, computed above from the tallest whisker
    # anywhere. Scaling each family separately here would defeat the chart: its
    # whole job is to put families on a common scale, and per-family axes are
    # what the per-family charts are for.
    ax.set_ylim(0, top)
    ax.set_xlabel("position in family, oldest to newest "
                  "(point labels give the version)")
    ax.set_ylabel(f"{report['metric_label']} (%)")
    total = sum(m["n"] or 0 for f in families for m in f["members"])
    ax.set_title(f"{report['metric_label']} by model family "
                 f"({report['n_families']} families, {total} "
                 f"{report['metric_denominator_label']})", fontsize=12)
    ax.grid(axis="y", alpha=0.3)
    ax.legend(title="family", fontsize=9, title_fontsize=9,
              loc="upper left", bbox_to_anchor=(1.01, 1.0))
    # Under the legend rather than under the axis, because that is where a
    # reader decoding the colours is already looking.
    ax.text(1.01, 0.0, WILSON_NOTE, transform=ax.transAxes,
            fontsize=8, va="bottom", color="#444444")
    if any(f["ordering_ambiguous"] for f in families):
        ax.text(0.0, -0.16, "dashed = version order depends on "
                            "--version-style",
                transform=ax.transAxes, fontsize=8, color="#b34700")
    fig.tight_layout()
    fig.savefig(path, dpi=CHART_DPI, bbox_inches="tight")
    plt.close(fig)
    return path


# ---------------------------------------------------------------------------
# Release-date charts
# ---------------------------------------------------------------------------
#
# The charts above put version POSITION on the x axis, which spaces every
# release equally. That is the right axis for the question they answer - does a
# rate fall as a family advances - but it hides something the answer depends on:
# four grok releases spanning four months and four gemini releases spanning
# eight draw the same shape on a positional axis.
#
# These charts put the calendar there instead, so the reader can see how much
# time each step actually had. They draw NO LINES. A line between two releases
# claims a path between them, and on a calendar axis that claim is stronger than
# the data supports - nothing was measured between two release dates, and the
# gaps are unequal, so a connecting segment invites reading a slope off empty
# space. Points and labels only.

def _member_release_date(member: dict):
    """
    The release date on a report member, as a date, or None when unrecorded.

    Parses back from the ISO string the report stores rather than calling
    release_date() again, so the charts plot exactly what the JSON says. A
    malformed stamp returns None instead of raising: a chart must never be the
    thing that stops the analysis.
    """
    stamp = member.get("released")
    if not stamp:
        return None
    try:
        return date.fromisoformat(stamp)
    except (TypeError, ValueError):
        return None


def release_span(report: dict):
    """
    The (start, end) the release charts share, or None if no date is known.

    ONE span across every chart in the run, computed from every plotted family
    rather than per chart. Per-family calendars would each be scaled to their own
    family's dates, and then the whole point - that grok's four releases are
    tighter together than gemini's four - would be scaled away.

    The end is the latest release plotted, with no padding: the axis stops where
    the newest model is, and labels near that edge are written leftward instead.
    """
    dates = [d for family in report["families"] for member in family["members"]
             if (d := _member_release_date(member))]
    if not dates:
        return None
    start = min(RELEASE_AXIS_START, min(dates))
    end = max(dates)
    # A corpus whose models all predate the floor would otherwise ask matplotlib
    # for a zero-width or inverted axis.
    return (start, end if end > start else start + timedelta(days=30))


def _label_extent(text: str, fontsize: float, axis_width_pt: float,
                  width_days: int) -> float:
    """
    How wide a label is, in days of the calendar axis.

    Estimated from the character count rather than measured, because the layout
    has to run before anything is drawn and a real measurement needs a renderer.
    An estimate is enough: the question is only whether two labels are far
    enough apart, and _LABEL_CHAR_PT is deliberately generous.
    """
    widest = max((len(line) for line in text.split("\n")), default=1)
    return width_days * (widest * fontsize * _LABEL_CHAR_PT) / max(
        1.0, axis_width_pt)


def _date_label_layout(points: list, span: tuple, top: float,
                       labels: dict = None, fontsize: float = 8.0,
                       axis_width_pt: float = 520.0) -> dict:
    """
    Where each point's label goes, as {key: (dx, dy, ha, va)} in points.

    Same reasoning as _label_layout, and a different geometry. There the x values
    are integer columns, so collisions can only happen within a column; here x is
    continuous, so two labels collide when they are close on BOTH axes.

    WHY THIS COMPARES BOXES AND NOT DISTANCES
    -----------------------------------------
    It first compared the distance between the two POINTS against a fixed gap,
    which misses two things and produced a collision on the gemini-flash chart
    that this replaces. A label is much wider than its point - `0.5% [0.1, 2.7]`
    covers about 70 points, some 75 days on a 14-month axis - and a label near
    the right edge is written LEFTWARD, so two labels 63 days apart can still
    overlap when the left one reaches right and the right one reaches left.

    So each label is given an estimated box in calendar days, on the side it is
    actually written, and two labels share a row only when their boxes miss each
    other or their rates are far enough apart to be on different lines anyway.

    Three edges to keep a label off: the right one, where it is written leftward;
    the top, where it is written below its point instead of above; and the x axis
    itself, which is why the base offset is upward rather than centred.
    """
    start, end = span
    width = max(1, (end - start).days)
    ygap = top * _LABEL_GAP
    # The offset that pushes a label clear of its own marker, in days.
    nudge = _label_extent("x", 1.0, axis_width_pt, width) * _DATE_LABEL_DX
    # A row has to clear the whole label, not one line of it. The per-family
    # chart writes two lines - the version and its interval - and a row height
    # fixed at one line stacked them ON each other, which is a collision
    # produced by the mechanism meant to prevent one.
    tallest = max((text.count("\n") + 1
                   for text in (labels or {}).values()), default=1)
    row_pt = _DATE_LABEL_ROW * tallest
    placed, layout = [], {}
    ordered = sorted(points, key=lambda p: ((p[1] - start).days, p[2]))
    for key, when, rate in ordered:
        x = (when - start).days
        # Lean left for anything near the right edge, where a label written
        # rightward would run past the end of the axis.
        leans_left = x > width * (1 - _DATE_LABEL_XGAP)
        text = (labels or {}).get(key, "xxxxxx")
        extent = _label_extent(text, fontsize, axis_width_pt, width)
        box = ((x - nudge - extent, x - nudge) if leans_left
               else (x + nudge, x + nudge + extent))
        row = 0
        while any(prow == row and box[0] < pbox[1] and pbox[0] < box[1]
                  and abs(rate - pr) < ygap for pbox, pr, prow in placed):
            row += 1
        placed.append((box, rate, row))
        # A rate at the ceiling - 100% is a real answer here, not an artefact -
        # has no room above it, and a label written upward from one lands on the
        # title. Written downward it lands on empty axis.
        offset = _DATE_LABEL_DY + row * row_pt
        hangs_below = rate > top * _DATE_LABEL_CEILING
        layout[key] = (-_DATE_LABEL_DX if leans_left else _DATE_LABEL_DX,
                       -offset if hangs_below else offset,
                       "right" if leans_left else "left",
                       "top" if hangs_below else "bottom")
    return layout


def _date_axis(plt, ax, span: tuple) -> None:
    """
    A calendar x axis over `span`, with ticks matplotlib chooses for the width.

    ConciseDateFormatter rather than a fixed month interval, because the span
    grows by months every time a model is collected and a hand-picked interval
    that reads well over one year crowds over three.
    """
    from matplotlib import dates as mdates
    locator = mdates.AutoDateLocator(minticks=4, maxticks=9)
    ax.xaxis.set_major_locator(locator)
    ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(locator))
    ax.set_xlim(*span)


def _slope_label(fit: dict) -> str:
    """
    The fitted slope for a legend entry, or nothing when there is no line.

    Empty rather than "n/a" for a family that could not be fitted: a legend is
    read at a glance, and the family's marker count in the same entry already
    says why - one dated release cannot have a slope.
    """
    if not fit or fit.get("slope_per_month") is None:
        return ""
    return f", {fit['slope_per_month'] * 100:+.1f} pts/month"


def _draw_release_fit(ax, fit: dict, colour) -> bool:
    """
    One family's fitted line, dotted, between its own first and last release.

    Dotted rather than solid, and drawn UNDER the markers, because it is a
    summary of the points and not a path between them: nothing was measured
    along it. Silently draws nothing when there is no line to draw - a family
    with one dated release, or several released on one day - since the caption
    and the JSON both already say why.
    """
    if not fit or fit.get("slope_per_month") is None:
        return False
    start = date.fromisoformat(fit["from"]["released"])
    end = date.fromisoformat(fit["to"]["released"])
    ax.plot([start, end],
            [fit["from"]["rate"] * 100, fit["to"]["rate"] * 100],
            linestyle=":", linewidth=1.8, color=colour, alpha=0.9, zorder=2)
    return True


def _release_point_name(member: dict) -> str:
    """
    What identifies one point on a calendar axis, in one line.

    The version alone is not enough and the model ID is too much. Two members of
    a family can share a version - deepseek-v4-pro and deepseek-v4-pro-0813 are
    both `4`, kimi-k2 and kimi-k2-thinking are both `2` - and a chart that labels
    both points `4` reads as a mistake even though the x positions differ. So the
    stamp and the tags come along, written the way the ID writes them.

    One line rather than the three _member_labels uses: those are tick labels
    with a column to themselves, these sit beside a point among other points.
    """
    name = member["version"] or "?"
    if member["date"]:
        name += f"-{member['date']}"
    if member["tags"]:
        name += f" ({','.join(member['tags'])})"
    return name


def _dated_members(family: dict) -> list:
    """The members of one family that can be placed on a calendar."""
    return [(m, _member_release_date(m)) for m in family["members"]
            if _member_release_date(m)]


def _plot_family_dates(plt, family: dict, metric_label: str, den_label: str,
                       colour, span: tuple, path: str):
    """
    One family against the calendar. Points and labels, no line.

    The interval is in the label's brackets rather than as a whisker, because a
    whisker is a line and this chart draws none; the per-family version chart is
    where the bars are. Returns None when nothing in the family has a recorded
    release date, so a caller writes no empty chart.
    """
    dated = _dated_members(family)
    if not dated:
        return None
    rates = [(m["rate"] or 0) * 100 for m, _ in dated]
    top = axis_top(rates)
    # The labels go to the layout, not just the points: these carry the interval
    # as well as the version, so they are several times wider than a marker and
    # the layout cannot tell whether two of them overlap without seeing them.
    labels = {index: f"{_release_point_name(m)}\n{_point_label(m, rate)}"
              for index, ((m, _when), rate) in enumerate(zip(dated, rates))}
    layout = _date_label_layout(
        [(index, when, rate)
         for index, ((_m, when), rate) in enumerate(zip(dated, rates))],
        span, top, labels, fontsize=8.0,
        axis_width_pt=_PER_FAMILY_AXIS_PT)

    fig, ax = plt.subplots(figsize=(9, 4.5))
    _draw_release_fit(ax, family.get("release_fit"), colour)
    # clip_on=False so the newest model, which sits exactly ON the right edge
    # by construction, draws as a whole marker rather than a half one.
    ax.scatter([when for _m, when in dated], rates, s=90, color=colour,
               zorder=3, edgecolors="white", linewidths=0.8, clip_on=False)
    for index, ((member, when), rate) in enumerate(zip(dated, rates)):
        dx, dy, ha, va = layout[index]
        ax.annotate(labels[index], (when, rate), textcoords="offset points",
                    xytext=(dx, dy), ha=ha, ma=ha, va=va, fontsize=8,
                    color="#333333",
                    # The fitted line crosses the middle of the panel, and
                    # without a backing it draws straight through whichever
                    # label sits there.
                    bbox={"boxstyle": "round,pad=0.15", "fc": "white",
                          "ec": "none", "alpha": 0.85})
    _date_axis(plt, ax, span)
    ax.set_ylim(0, top)
    ax.set_ylabel(f"{metric_label} (%)")
    ax.set_xlabel(f"release date    ({WILSON_NOTE_BRACKETS_ONLY})")
    total = sum(m["n"] or 0 for m, _ in dated)
    title = (f"{family['family']} by release date - {len(dated)} version(s), "
             f"{total} {den_label}")
    ax.set_title(title, fontsize=11)
    fit = family.get("release_fit")
    if fit and fit.get("slope_per_month") is not None:
        # The slope in words as well as in ink, because a dotted line's gradient
        # cannot be read off an axis and this is the number a write-up quotes.
        caption = (f"{FIT_NOTE}: {fit['slope_per_month'] * 100:+.1f} "
                   f"points/month over {fit['span_days']} days")
        # A second LINE rather than a longer one: bbox_inches="tight" grows the
        # canvas to fit whatever is widest, so appending the two-point note
        # inline stretched the figure to half again its width and squeezed the
        # axes into the left of it.
        if fit.get("note"):
            caption += f"\n{fit['note']}"
        # BELOW the axis, not above it. Above, this ran straight through the
        # title - it is a long line, and the title is centred in the same band.
        ax.text(0.0, -0.20, caption, transform=ax.transAxes, fontsize=8,
                color="#555555", va="top")
    # Said on the chart rather than only in the console, because a chart that
    # quietly holds three of a family's four versions misleads on its own.
    omitted = family["n_members"] - len(dated)
    if omitted:
        # Below the fit caption, which now occupies the first line under the
        # axis, so the two do not print on each other.
        ax.text(0.0, -0.27,
                f"! {omitted} version(s) omitted: no release date recorded in "
                f"model_releases.py",
                transform=ax.transAxes, fontsize=8, color="#b00020")
    ax.grid(axis="y", alpha=0.3)
    ax.grid(axis="x", alpha=0.15)
    fig.tight_layout()
    fig.savefig(path, dpi=CHART_DPI, bbox_inches="tight")
    plt.close(fig)
    return path


def _plot_all_family_dates(plt, report: dict, colours, span: tuple, path: str):
    """
    Every family on one calendar, coloured by family. Points and labels only.

    This is the chart the release dates were recorded for: it puts every model in
    the corpus on a single time axis, so a rate that looks like a family trend
    can be checked against the possibility that it is a date trend running
    through all of them at once.

    The only line is one dotted least-squares fit per family, drawn between that
    family's own first and last release. No connecting lines, for a second reason
    on top of the one above: the families interleave on a calendar in a way they
    cannot on a position axis, so five joined-up families would cross into an
    unreadable mesh, while five straight fits stay legible.
    """
    families = [f for f in report["families"] if _dated_members(f)]
    if not families:
        return None
    top = axis_top([(m["rate"] or 0) * 100
                    for f in families for m, _ in _dated_members(f)])
    points, labels = [], {}
    for index, family in enumerate(families):
        for position, (member, when) in enumerate(_dated_members(family)):
            key = (index, position)
            points.append((key, when, (member["rate"] or 0) * 100))
            labels[key] = _release_point_name(member)
    layout = _date_label_layout(points, span, top, labels, fontsize=7.5,
                                axis_width_pt=_COMBINED_AXIS_PT)

    fig, ax = plt.subplots(figsize=(11, 5.6))
    fitted = 0
    for index, (family, colour) in enumerate(zip(families, colours)):
        dated = _dated_members(family)
        fitted += _draw_release_fit(ax, family.get("release_fit"), colour)
        # Semi-transparent because two families can land on the same point and
        # a calendar axis gives no honest way to separate them: grok-4.6 and
        # deepseek-v4-pro-0813 shipped on the same day at 3.33% and 3.36%, and
        # an opaque marker would hide one entirely. Blended, the overlap is at
        # least visible, and both labels are drawn either way.
        ax.scatter([when for _m, when in dated],
                   [(m["rate"] or 0) * 100 for m, _ in dated],
                   s=90, color=colour, zorder=3, edgecolors="white",
                   linewidths=0.8, clip_on=False, alpha=0.85,
                   # The slope goes in the legend, not on the line: five
                   # gradients cannot be read off a shared axis, and a caption
                   # per line would land in the middle of the data.
                   label=f"{family['family']}  "
                         f"({len(dated)} of {family['n_members']} dated"
                         f"{_slope_label(family.get('release_fit'))})")
    for key, when, rate in points:
        dx, dy, ha, va = layout[key]
        colour = colours[key[0] % len(colours)]
        ax.annotate(labels[key], (when, rate),
                    textcoords="offset points", xytext=(dx, dy), ha=ha,
                    va=va, fontsize=7.5, color=colour,
                    # Families interleave on a calendar, so a label with no
                    # backing lands on another family's point - and now on
                    # another family's fitted line, which is why this is more
                    # opaque than the version chart's equivalent.
                    bbox={"boxstyle": "round,pad=0.15", "fc": "white",
                          "ec": "none", "alpha": 0.85})
    _date_axis(plt, ax, span)
    ax.set_ylim(0, top)
    ax.set_xlabel("release date (point labels give the version)")
    ax.set_ylabel(f"{report['metric_label']} (%)")
    total = sum(m["n"] or 0 for f in families for m, _ in _dated_members(f))
    plotted = sum(len(_dated_members(f)) for f in families)
    ax.set_title(f"{report['metric_label']} by release date "
                 f"({len(families)} families, {plotted} models, {total} "
                 f"{report['metric_denominator_label']})", fontsize=12)
    ax.grid(axis="y", alpha=0.3)
    ax.grid(axis="x", alpha=0.15)
    ax.legend(title="family", fontsize=9, title_fontsize=9,
              loc="upper left", bbox_to_anchor=(1.01, 1.0))
    if fitted:
        # Under the legend, where a reader decoding the lines is already looking,
        # and wrapped because the note is longer than the legend is wide.
        ax.text(1.01, 0.0, FIT_NOTE.replace(", weighted", ",\nweighted"),
                transform=ax.transAxes, fontsize=8, va="bottom",
                color="#444444")
    missing = report["data_quality"]["plotted_models_without_release_date"]
    if missing:
        ax.text(0.0, -0.16,
                f"! {len(missing)} model(s) omitted: no release date recorded "
                f"in model_releases.py",
                transform=ax.transAxes, fontsize=8, color="#b00020")
    fig.tight_layout()
    fig.savefig(path, dpi=CHART_DPI, bbox_inches="tight")
    plt.close(fig)
    return path


def _family_colours(plt, families: list):
    """
    One colour per family, by position in the family list.

    Shared by every chart that colours by family so a family keeps its colour
    across them. By position rather than hashed, because a hash reorders the
    whole palette whenever a family is added.
    """
    return plt.get_cmap(_PALETTE)([i % 10 for i in range(len(families))])


def write_charts(report: dict, chart_dir: str) -> list:
    """
    One chart per family plus one combined, against version order and again
    against release date. Returns the paths written.

    Empty when matplotlib is absent, which is not an error: the same numbers are
    in the table and the JSON.

    A missing release date is reported and then worked around: the release charts
    drop that model, every other chart is unaffected, and nothing here returns a
    failure. The report has already printed by the time this runs.
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
        written.append(_plot_family(plt, family, report["metric_label"],
                                    report["metric_denominator_label"], path))
    combined = _plot_all_families(
        plt, report, os.path.join(chart_dir, f"family_{metric}_all.png"))
    if combined:
        written.append(combined)

    span = release_span(report)
    if span is None:
        print("\n!! ERROR: no release date is recorded for any model in a "
              "family, so the release-date charts were skipped. Add them to "
              "RELEASE_DATES in model_releases.py. Every other chart, the "
              "table above and the JSON are unaffected.")
        return written
    # Colours are taken from the same list _plot_all_families enumerates, so a
    # family is the same colour on the combined version chart, the combined
    # release chart and its own release chart.
    drawn = [f for f in report["families"] if f["members"]]
    colours = _family_colours(plt, drawn)
    for family, colour in zip(drawn, colours):
        slug = family["family"].replace("/", "_")
        path = os.path.join(chart_dir, f"release_{metric}_{slug}.png")
        if _plot_family_dates(plt, family, report["metric_label"],
                              report["metric_denominator_label"], colour,
                              span, path):
            written.append(path)
    combined_dates = _plot_all_family_dates(
        plt, report, colours, span,
        os.path.join(chart_dir, f"release_{metric}_all.png"))
    if combined_dates:
        written.append(combined_dates)
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
    _print_release_fit(family.get("release_fit"))
    print(f"\n  => {family['verdict']}")


def _print_release_fit(fit: dict) -> None:
    """
    The slope the release charts draw as a dotted line.

    Printed so that the line on the chart is a second reading of a number in the
    report rather than the only place it exists. Labelled descriptive on every
    line it appears on: it has no p-value, and the trend test two lines above it
    does, so a reader skimming could easily take one for the other.
    """
    if not fit:
        return
    if fit.get("slope_per_month") is None:
        print(f"  release-date fit: none ({fit.get('note')})")
        return
    note = f"  - {fit['note']}" if fit.get("note") else ""
    print(f"  release-date fit (descriptive, no p-value): "
          f"{fit['slope_per_month'] * 100:+.1f} points/month across "
          f"{fit['span_days']} days and {fit['n_points']} "
          f"dated release(s){note}")


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
    _print_release_date_errors(dq)


def _print_release_date_errors(dq: dict) -> None:
    """
    Name every model with no recorded release date, loudly, and carry on.

    Louder than the warnings above it because it is the only line in the block
    that names a fix, and quieter than a failure because nothing above it
    depends on a release date: an undated model is missing from the release
    charts and present in every table, trend, interval and p-value. Stopping the
    analysis over a chart would be the wrong trade, so this returns nothing and
    changes no exit code.
    """
    missing = dq["models_without_release_date"]
    if not missing:
        return
    plotted = dq["plotted_models_without_release_date"]
    print(f"\n  !! ERROR: no release date recorded for {len(missing)} "
          f"model(s): {', '.join(missing)}")
    print(f"     Add them to RELEASE_DATES in model_releases.py. "
          f"{len(plotted)} of them sit in a family and are therefore MISSING "
          f"from the release-date charts;")
    print("     every figure above is unaffected, and so is every "
          "version-order chart.")


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
    parser.add_argument("--metric", default="misaligned",
                        choices=sorted(METRICS) + [METRIC_ALL],
                        help="which rate to trend, or 'all' for one report per "
                             "metric (default: %(default)s)")
    parser.add_argument("--version-style", default="decimal",
                        choices=VERSION_STYLES,
                        help="how to order a version: 'decimal' reads 4.20 as "
                             "4.2, so before 4.3 - which is what the vendors "
                             "mean; 'component' reads it as 4 major 20 minor, "
                             "so after 4.6, the way a package manager reads a "
                             "semantic version (default: %(default)s)")
    parser.add_argument("--json-out", default=None,
                        help="where to write the JSON report (default: "
                             "family_trends_<metric>_<timestamp>.json inside "
                             "--output-dir)")
    parser.add_argument("--chart-dir", default=None,
                        help="where to write the PNG charts (default: "
                             "charts/ inside --output-dir). One per family plus "
                             "one combined, against version order and again "
                             "against release date; needs the 'charts' extra")
    parser.add_argument("--no-charts", action="store_true",
                        help="skip the charts. Every figure they plot is in the "
                             "table and the JSON either way")
    args = parser.parse_args()

    if not os.path.isdir(args.output_dir):
        print(f"No such directory: {redact_paths(args.output_dir)}")
        return 1

    metrics = sorted(METRICS) if args.metric == METRIC_ALL else [args.metric]
    if args.json_out and len(metrics) > 1:
        parser.error("--json-out names one file, and --metric all writes one "
                     "report per metric. Drop --json-out to get "
                     "family_trends_<metric>_<timestamp>.json for each, or "
                     "name a single --metric.")

    # One stamp for the whole invocation rather than one per metric, so the
    # reports from a single run share a filename suffix and sort together
    # instead of being separated by however long the run took.
    stamp = time.strftime("%Y%m%dT%H%M%S")
    failed = 0
    for metric in metrics:
        if len(metrics) > 1:
            print(f"\n\n{'#' * 78}\n# metric: {metric}\n{'#' * 78}")
        failed += _report_one_metric(args, metric, stamp)
    return 1 if failed else 0


def _report_one_metric(args, metric: str, stamp: str) -> int:
    """
    One metric, end to end. Returns 0 on success and 1 on failure.

    Split out of main so `--metric all` runs the same path three times rather
    than a second implementation of it.
    """
    report = build_report(args.output_dir, metric, args.version_style)
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
        # The metric is in the name for the same reason it is in the chart
        # names: two metrics of one corpus are two different reports, and a
        # directory of timestamped files gives no way to tell which is which
        # without opening them.
        f"family_trends_{metric}_{stamp}.json")
    with open(out, "w") as f:
        json.dump(report, f, indent=2)
    print(f"\nJSON written to {redact_paths(out)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
