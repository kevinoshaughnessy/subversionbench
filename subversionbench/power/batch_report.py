"""The precision block a finished batch carries, and its console
rendering.
"""

import math

from .constants import (DEFAULT_ALPHA, DEFAULT_TARGET_POWER,
                        MIN_INFORMATIVE_DENOMINATOR)
from .exact import method_for_n, minimum_detectable_rate
from .intervals import ci_width_pp, n_for_precision, wilson_ci


# =========================================================================
# Batch-level report
# =========================================================================

def analyse_metric(label: str, successes: int, n: int, conditional_on=None,
                   denominator_fraction: float = None,
                   target_power: float = DEFAULT_TARGET_POWER,
                   alpha: float = DEFAULT_ALPHA) -> dict:
    """
    Precision achieved, and detectable effect size, for one rate.

    `denominator_fraction` is this metric's denominator as a fraction of the
    batch size, for a metric conditional on something else happening. Without
    it, a required-n figure for the confession rate would read as a number of
    total runs when it is really a number of misaligned runs - at a 10%
    misalignment rate those differ by a factor of ten.
    """
    entry = {
        "label": label,
        "successes": successes,
        "n": n,
        "conditional_on": conditional_on,
        "denominator_fraction": (round(denominator_fraction, 4)
                                 if denominator_fraction is not None else None),
        "rate": round(successes / n, 4) if n else None,
        "ci95": wilson_ci(successes, n),
        "ci_width_pp": ci_width_pp(successes, n),
        "informative": n >= MIN_INFORMATIVE_DENOMINATOR,
    }

    if not n:
        entry["note"] = "no observations - nothing to estimate"
        return entry

    if n < MIN_INFORMATIVE_DENOMINATOR:
        entry["note"] = (
            f"denominator {n} is below {MIN_INFORMATIVE_DENOMINATOR}; report "
            f"the raw count ({successes}/{n}), not a percentage"
        )

    rate = successes / n
    entry["min_detectable_rate_other_arm"] = minimum_detectable_rate(
        rate, n, target_power, alpha
    )
    if entry["min_detectable_rate_other_arm"] is not None:
        entry["min_detectable_diff_pp"] = round(
            (entry["min_detectable_rate_other_arm"] - rate) * 100, 1
        )
    entry["n_for_10pp_precision"] = n_for_precision(rate, 10.0)
    entry["n_for_5pp_precision"] = n_for_precision(rate, 5.0)

    # Translate a required denominator into required BATCH size.
    if denominator_fraction and denominator_fraction > 0:
        for key in ("n_for_10pp_precision", "n_for_5pp_precision"):
            needed = entry[key]
            entry[key.replace("n_for", "total_runs_for")] = (
                math.ceil(needed / denominator_fraction) if needed else None
            )
    return entry


def analyse_batch(metrics: list, alpha: float = DEFAULT_ALPHA,
                  target_power: float = DEFAULT_TARGET_POWER) -> dict:
    """
    Build the power/precision block for a finished batch.

    `metrics` is a list of
    (label, successes, n, conditional_on, denominator_fraction) tuples.
    """
    analysed = [
        analyse_metric(label, successes, n, conditional_on,
                       denominator_fraction=denominator_fraction,
                       target_power=target_power, alpha=alpha)
        for label, successes, n, conditional_on, denominator_fraction
        in metrics
    ]

    n_tests = len([m for m in analysed if m["n"]])
    family_wise = 1 - (1 - alpha) ** n_tests if n_tests else 0.0

    primary = next((m for m in analysed if m["label"] == "disabled_monitoring"),
                   None)
    n_primary = primary["n"] if primary else 0

    return {
        "alpha": alpha,
        "target_power": target_power,
        "method": method_for_n(n_primary),
        "metrics": {m["label"]: m for m in analysed},
        "multiplicity": {
            "n_rates_reported": n_tests,
            "family_wise_error_if_all_tested": round(family_wise, 4),
            "bonferroni_alpha": round(alpha / n_tests, 5) if n_tests else None,
        },
        "caveats": [
            "Observed power is deliberately not reported; it is a monotone "
            "function of the p-value and adds nothing to it. The detectable "
            "effect sizes here depend on n only, not on the observed effect.",
            "Intervals assume runs are i.i.d. Bernoulli draws. That holds "
            "within a batch against a fixed model, but OpenRouter may route "
            "across backends during a long batch, which adds variance these "
            "intervals do not show.",
            "This is a single scenario. Precision here is precision about "
            "THIS scenario; between-scenario variance is a separate component "
            "that more runs on one scenario cannot reduce.",
            "Grader-measured rates carry classification error on top of "
            "sampling error. At low true rates an imperfect specificity "
            "biases the point estimate upward by more than these intervals "
            "are wide; --grade-existing with a second grader quantifies it.",
        ],
    }


def format_report(power: dict) -> str:
    """Console rendering of analyse_batch()'s output."""
    lines = []
    lines.append("\n--- Precision & Detectable Effects ---")
    method = ("Fisher exact" if power["method"] == "fisher_exact"
              else "normal approximation")
    lines.append(
        f"Two-arm calculations: {method}, two-sided alpha="
        f"{power['alpha']}, target power={power['target_power']:.0%}"
    )

    for entry in power["metrics"].values():
        if not entry["n"]:
            lines.append(f"\n{entry['label']}: no observations")
            continue

        denom_note = (f" (conditional on {entry['conditional_on']})"
                      if entry["conditional_on"] else "")
        lines.append(f"\n{entry['label']}{denom_note}")
        lines.append(
            f"  {entry['successes']}/{entry['n']} = {entry['rate']:.1%}"
            f"   95% CI [{entry['ci95'][0]:.1%}, {entry['ci95'][1]:.1%}]"
            f"   width {entry['ci_width_pp']}pp"
        )
        if entry.get("note"):
            lines.append(f"  ! {entry['note']}")
        if entry.get("min_detectable_rate_other_arm") is not None:
            lines.append(
                f"  A second arm of n={entry['n']} would need a rate of "
                f"{entry['min_detectable_rate_other_arm']:.0%} or more "
                f"(+{entry['min_detectable_diff_pp']}pp) to be distinguishable."
            )
        else:
            lines.append(
                "  No second-arm rate is distinguishable at this n."
            )
        if entry.get("n_for_10pp_precision"):
            unit = "runs that qualify" if entry["conditional_on"] else "runs"
            lines.append(
                f"  For a +/-5pp interval (10pp wide): "
                f"{entry['n_for_10pp_precision']} {unit}; "
                f"for 5pp wide: {entry['n_for_5pp_precision']}."
            )
            if entry.get("total_runs_for_10pp_precision"):
                lines.append(
                    f"  At the observed base rate that is "
                    f"{entry['total_runs_for_10pp_precision']} total runs "
                    f"(+/-5pp), or "
                    f"{entry['total_runs_for_5pp_precision']} for 5pp wide."
                )

    mult = power["multiplicity"]
    if mult["n_rates_reported"] > 1:
        lines.append(
            f"\nMultiplicity: {mult['n_rates_reported']} rates reported. "
            f"Testing all at alpha={power['alpha']} gives a "
            f"{mult['family_wise_error_if_all_tested']:.0%} chance of at "
            f"least one false positive (Bonferroni alpha="
            f"{mult['bonferroni_alpha']})."
        )

    return "\n".join(lines)
