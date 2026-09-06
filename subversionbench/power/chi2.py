"""The chi-square upper tail, by series and continued fraction.

Its own module because it is a distribution tail rather than a
comparison: two different tests here reach for it and neither owns it.
"""

import math


# =========================================================================
# Chi-square tail
# =========================================================================
#
# Needed by the stratified tests below, and implemented here because this
# package depends on `anthropic` alone - there is no scipy to import. Both
# branches are the standard Numerical Recipes pair for the regularised
# incomplete gamma function, which the chi-square survival function is a
# reparameterisation of.

_GAMMA_ITER_MAX = 300
_GAMMA_EPS = 3e-14
_GAMMA_TINY = 1e-300


def _gamma_p_series(a: float, x: float) -> float:
    """Regularised lower incomplete gamma P(a, x), by series. For x < a + 1."""
    term = total = 1.0 / a
    for i in range(1, _GAMMA_ITER_MAX):
        term *= x / (a + i)
        total += term
        if abs(term) < abs(total) * _GAMMA_EPS:
            break
    return total * math.exp(-x + a * math.log(x) - math.lgamma(a))


def _gamma_q_continued_fraction(a: float, x: float) -> float:
    """Regularised upper incomplete gamma Q(a, x), by the modified Lentz
    continued fraction. For x >= a + 1, where the series above converges
    slowly."""
    b = x + 1.0 - a
    c = 1.0 / _GAMMA_TINY
    d = 1.0 / b
    h = d
    for i in range(1, _GAMMA_ITER_MAX):
        an = -i * (i - a)
        b += 2.0
        d = an * d + b
        if abs(d) < _GAMMA_TINY:
            d = _GAMMA_TINY
        c = b + an / c
        if abs(c) < _GAMMA_TINY:
            c = _GAMMA_TINY
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < _GAMMA_EPS:
            break
    return h * math.exp(-x + a * math.log(x) - math.lgamma(a))


def chi2_sf(statistic: float, df: int) -> float:
    """
    Upper tail of the chi-square distribution: P(X >= statistic) with df
    degrees of freedom. 1.0 for a non-positive statistic or df <= 0, so a
    degenerate test reports "no evidence" rather than raising.
    """
    if df <= 0 or statistic <= 0:
        return 1.0
    a, x = df / 2.0, statistic / 2.0
    if x < a + 1.0:
        return max(0.0, min(1.0, 1.0 - _gamma_p_series(a, x)))
    return max(0.0, min(1.0, _gamma_q_continued_fraction(a, x)))
