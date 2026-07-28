"""
Statistical precision and power analysis for SubversionBench.

Answers, for a batch that has just finished: how precisely did it measure
each rate, and what size of difference could a comparison against another
batch actually have detected?

WHAT THIS DELIBERATELY DOES NOT REPORT
--------------------------------------
"Observed power" - power recomputed from the effect size the batch happened
to produce - is not reported, because it is a known fallacy: it is a
monotone function of the p-value and so adds no information beyond it, and
a non-significant result always yields low observed power, which then gets
misread as "the test was underpowered" rather than "the effect was small".

Everything here is a function of n and of pre-chosen reference effect sizes
only, never of the observed effect:

  - achieved precision:  the width of the interval this n produced
  - minimum detectable rate:  given this n and an observed rate as the
    BASELINE, how far a second arm would have to sit before an effect that
    size would be caught at `target_power` - a statement about the design,
    useful for sizing the next batch
  - required n:  how many runs a target precision would have taken

Rates in this eval sit near zero, so the two-arm calculations use Fisher's
exact test (enumerated over every possible pair of outcomes) rather than a
normal approximation, which is anticonservative in that regime. Above
EXACT_MAX_N the enumeration gets too expensive and a normal approximation
is used instead, flagged as such in the output.
"""

import math
from functools import lru_cache

Z_95 = 1.96
DEFAULT_ALPHA = 0.05
DEFAULT_TARGET_POWER = 0.80

# Above this per-arm n, the exact enumeration is O(n^3) and too slow to run
# by default, so two_arm_power() falls back to a normal approximation.
EXACT_MAX_N = 250

# Denominator below which a rate should be read as a raw count instead. A
# conditional metric like the confession rate has the misaligned-episode
# count as its denominator, not n, so a 100-run batch with a 10%
# misalignment rate reports it over 10 runs - an interval ~50 points wide.
MIN_INFORMATIVE_DENOMINATOR = 20


# =========================================================================
# Interval estimation
# =========================================================================

def wilson_ci(successes: int, n: int, z: float = Z_95):
    """95% Wilson score confidence interval for a binomial proportion, as
    [lower, upper]. Preferred over the naive normal-approximation (Wald)
    interval here because rates in this eval are often at or near 0% -
    Wald degenerates to a zero-width [0, 0] in that case, understating
    the real uncertainty from a small sample; Wilson stays well-behaved
    at the boundaries. Returns None if n is 0 (nothing to estimate)."""
    if n == 0:
        return None
    p_hat = successes / n
    denom = 1 + z * z / n
    center = (p_hat + z * z / (2 * n)) / denom
    half_width = (
        z * math.sqrt((p_hat * (1 - p_hat) / n) + (z * z / (4 * n * n)))
    ) / denom
    lower = max(0.0, center - half_width)
    upper = min(1.0, center + half_width)
    return [round(lower, 4), round(upper, 4)]


def ci_width_pp(successes: int, n: int) -> float:
    """Width of the Wilson interval in percentage points."""
    ci = wilson_ci(successes, n)
    if ci is None:
        return None
    return round((ci[1] - ci[0]) * 100, 1)


def n_for_precision(p: float, target_width_pp: float, cap: int = 100000):
    """
    Smallest n whose Wilson interval around rate `p` is no wider than
    `target_width_pp` percentage points. None if `cap` is reached.
    """
    target = target_width_pp / 100
    n = 5
    while n <= cap:
        ci = wilson_ci(round(p * n), n)
        if ci and (ci[1] - ci[0]) <= target:
            return n
        n = n + 1 if n < 50 else int(n * 1.1) + 1
    return None


# =========================================================================
# Exact two-arm machinery
# =========================================================================

@lru_cache(maxsize=None)
def _logfact(n: int) -> float:
    return math.lgamma(n + 1)


def _logchoose(n: int, k: int) -> float:
    if k < 0 or k > n:
        return -math.inf
    return _logfact(n) - _logfact(k) - _logfact(n - k)


def _binom_pmf(k: int, n: int, p: float) -> float:
    if p <= 0:
        return 1.0 if k == 0 else 0.0
    if p >= 1:
        return 1.0 if k == n else 0.0
    return math.exp(_logchoose(n, k) + k * math.log(p)
                    + (n - k) * math.log1p(-p))


def fisher_exact_p(x1: int, n1: int, x2: int, n2: int) -> float:
    """Two-sided Fisher exact p: total probability of every table no more
    likely than the observed one, under the same margins."""
    total, successes = n1 + n2, x1 + x2
    if total == 0:
        return 1.0
    denom = _logchoose(total, successes)

    def log_p(a):
        return _logchoose(n1, a) + _logchoose(n2, successes - a) - denom

    observed = log_p(x1)
    lo = max(0, successes - n2)
    hi = min(n1, successes)
    return min(1.0, sum(
        math.exp(v) for v in (log_p(a) for a in range(lo, hi + 1))
        if v <= observed + 1e-9
    ))


@lru_cache(maxsize=8)
def _rejection_grid(n: int, alpha: float) -> tuple:
    """
    For equal arms of size n, which (x1, x2) outcomes Fisher's test rejects.

    Built once per n and cached: the decision depends only on the counts, so
    every subsequent power evaluation at this n is a weighted sum over this
    grid rather than another O(n^3) sweep of exact tests.
    """
    return tuple(
        tuple(fisher_exact_p(x1, n, x2, n) <= alpha for x2 in range(n + 1))
        for x1 in range(n + 1)
    )


def _normal_approx_power(p1: float, p2: float, n: int,
                         alpha: float = DEFAULT_ALPHA) -> float:
    """Two-proportion power via normal approximation (large-n fallback)."""
    p_bar = (p1 + p2) / 2
    se_null = math.sqrt(2 * p_bar * (1 - p_bar) / n)
    se_alt = math.sqrt((p1 * (1 - p1) + p2 * (1 - p2)) / n)
    if se_alt == 0:
        return 1.0 if p1 != p2 else alpha
    # z for a two-sided test at `alpha`; 1.96 at the 0.05 default.
    z_alpha = Z_95 if abs(alpha - 0.05) < 1e-9 else _z_for_alpha(alpha)
    shift = (abs(p2 - p1) - z_alpha * se_null) / se_alt
    return _std_normal_cdf(shift)


def _std_normal_cdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def _z_for_alpha(alpha: float) -> float:
    """Two-sided critical value, found by bisection (no scipy dependency)."""
    lo, hi = 0.0, 10.0
    for _ in range(200):
        mid = (lo + hi) / 2
        if 2 * (1 - _std_normal_cdf(mid)) > alpha:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def two_arm_power(p1: float, p2: float, n: int,
                  alpha: float = DEFAULT_ALPHA) -> float:
    """
    Probability that two arms of n runs each, with true rates p1 and p2,
    produce a significant difference. Exact for n <= EXACT_MAX_N.
    """
    if n <= 0:
        return 0.0
    if n > EXACT_MAX_N:
        return _normal_approx_power(p1, p2, n, alpha)

    grid = _rejection_grid(n, alpha)
    w1 = [_binom_pmf(k, n, p1) for k in range(n + 1)]
    w2 = [_binom_pmf(k, n, p2) for k in range(n + 1)]

    power = 0.0
    for x1, a in enumerate(w1):
        if a < 1e-12:
            continue
        row = grid[x1]
        power += a * sum(b for x2, b in enumerate(w2) if b >= 1e-12 and row[x2])
    return power


def minimum_detectable_rate(baseline: float, n: int,
                            target_power: float = DEFAULT_TARGET_POWER,
                            alpha: float = DEFAULT_ALPHA, step: float = 0.01):
    """
    How high a second arm's rate would have to be, against this `baseline`
    and this per-arm `n`, before the difference would be caught with
    `target_power`. None if even a rate of 1.0 wouldn't be.

    A property of the design, not of the observed effect - see the module
    docstring on why observed power is not reported.
    """
    if n <= 0:
        return None
    candidate = baseline
    while candidate < 1.0:
        candidate = min(1.0, candidate + step)
        if two_arm_power(baseline, candidate, n, alpha) >= target_power:
            return round(candidate, 4)
    return None


def method_for_n(n: int) -> str:
    return "fisher_exact" if n <= EXACT_MAX_N else "normal_approximation"


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
    lines.append(f"\n--- Precision & Detectable Effects ---")
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
                f"  No second-arm rate is distinguishable at this n."
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
