"""Exact two-arm machinery: Fisher's test, and the power and
detectable-effect calculations built on enumerating it.
"""

import math
from functools import lru_cache, cache

from .constants import (DEFAULT_ALPHA, DEFAULT_TARGET_POWER,
                        EXACT_MAX_N, Z_95)


# =========================================================================
# Exact two-arm machinery
# =========================================================================

@cache
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
