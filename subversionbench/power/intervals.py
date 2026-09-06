"""Interval estimation: what one rate, or a difference of two, is
known to within.
"""

import math

from .constants import Z_95
from .exact import fisher_exact_p


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


def newcombe_diff_ci(x1: int, n1: int, x2: int, n2: int, z: float = Z_95):
    """
    95% CI for the difference between two proportions (p1 - p2), as
    [lower, upper] on the -1..1 scale. None if either n is 0.

    WHY A DIFFERENCE INTERVAL AND NOT TWO MARGINAL ONES
    ---------------------------------------------------
    Comparing two models by checking whether their confidence intervals
    overlap is the standard mistake, and it errs in the direction that matters
    here: non-overlap does imply a significant difference, but overlap does NOT
    imply the absence of one. Two intervals can overlap substantially while the
    difference is comfortably significant, so eyeballing a results table
    systematically under-reports real differences. The interval on the
    difference is the quantity a comparison claim actually rests on.

    Newcombe's hybrid score method (his method 10), which composes the two
    Wilson intervals rather than assuming normality of the difference. Chosen
    for the same reason Wilson is used for the marginals: rates here sit at the
    boundary - a model that concealed 0 of 87 acts - and the Wald interval on a
    difference involving a zero rate is both too narrow and capable of
    straying outside [-1, 1].
    """
    if n1 == 0 or n2 == 0:
        return None
    p1, p2 = x1 / n1, x2 / n2
    l1, u1 = wilson_ci(x1, n1, z)
    l2, u2 = wilson_ci(x2, n2, z)
    lower = (p1 - p2) - math.sqrt((p1 - l1) ** 2 + (u2 - p2) ** 2)
    upper = (p1 - p2) + math.sqrt((u1 - p1) ** 2 + (p2 - l2) ** 2)
    return [round(max(-1.0, lower), 4), round(min(1.0, upper), 4)]


def compare_rates(x1: int, n1: int, x2: int, n2: int) -> dict:
    """
    One comparison of two rates: both marginals, the difference with its own
    interval, and an exact p-value.

    `separated` is the honest headline. It is taken from the difference
    interval excluding zero, not from whether the marginal intervals overlap,
    because those two disagree in exactly the cases a reader is most likely to
    get wrong.
    """
    if not n1 or not n2:
        return {"a": {"successes": x1, "n": n1},
                "b": {"successes": x2, "n": n2},
                "difference": None, "difference_ci95": None,
                "fisher_p": None, "separated": None,
                "note": "one arm is empty; nothing to compare"}

    diff_ci = newcombe_diff_ci(x1, n1, x2, n2)
    p = fisher_exact_p(x1, n1, x2, n2)
    marginal_a, marginal_b = wilson_ci(x1, n1), wilson_ci(x2, n2)
    return {
        "a": {"successes": x1, "n": n1, "rate": round(x1 / n1, 4),
              "ci95": marginal_a},
        "b": {"successes": x2, "n": n2, "rate": round(x2 / n2, 4),
              "ci95": marginal_b},
        "difference": round(x1 / n1 - x2 / n2, 4),
        "difference_ci95": diff_ci,
        "fisher_p": p,
        "separated": bool(diff_ci[0] > 0 or diff_ci[1] < 0),
        # Recorded because the two criteria disagree, and when they do it is
        # nearly always overlap-but-separated: the case where reading the
        # marginals would have missed a real difference.
        "marginals_overlap": not (marginal_a[0] > marginal_b[1]
                                  or marginal_b[0] > marginal_a[1]),
    }


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
