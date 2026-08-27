"""
The report: families, trends, fits and the data-quality block.

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

This module is the whole of the analysis. `build_report` returns the document
the console printer, the charts and the JSON all read, and none of them computes
a figure of its own - so a rate on a chart and the same rate in the table cannot
disagree. It imports no drawing code and does not need matplotlib.
"""

import os
import time
from datetime import date, timedelta

from model_releases import release_date
from report import awareness_arm_rows, load_episodes, load_summaries
from subversionbench.config import ROLLOUT_VERSION, VERSION
from subversionbench.power import (MIN_INFORMATIVE_DENOMINATOR,
                                   benjamini_hochberg, cochran_armitage,
                                   compare_rates, holm_bonferroni, sign_test,
                                   step_directions, weighted_least_squares)
from subversionbench.redaction import redact_paths

from .metrics import METRICS, model_exposure, model_rates
from .model_ids import (family_key, ordering_is_ambiguous, parse_model_id,
                        version_sort_key)


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


def family_trend(members: list, rates: dict, metric: str, style: str,
                 exposure: dict = None) -> dict:
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
            # The instrument this point was measured with, carried on the member
            # so the chart and the JSON cannot disagree about it.
            "reasoning_exposure": (exposure or {}).get(entry.raw),
        })
    groups = [(m["successes"] or 0, m["n"] or 0) for m in ordered]
    trend = cochran_armitage(groups)
    steps_summary = step_directions([m["rate"] for m in ordered])

    steps = []
    for before, after in zip(ordered, ordered[1:], strict=False):
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
    # The exposure figures come from the summaries either way, because they
    # describe the model rather than the metric - a text_reachable chart still
    # has to say which instrument each point was measured with.
    exposure = model_exposure(summaries)
    rows = (awareness_arm_rows(load_episodes(output_dir))
            if METRICS[metric].get("from_episodes") else summaries)
    if METRICS[metric].get("oversight_only"):
        rows = [r for r in rows if r["oversight"]]
    rates = model_rates(rows, metric)
    families = group_families(sorted(rates), style)
    results = [family_trend(members, rates, metric, style, exposure)
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
                                       bh["rejected"], strict=True):
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
