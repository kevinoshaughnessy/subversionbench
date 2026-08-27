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
from functools import lru_cache, cache

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


# =========================================================================
# Paired comparison
# =========================================================================
#
# WHY THE UNPAIRED TESTS ABOVE ARE THE WRONG ONES HERE
# ----------------------------------------------------
# Every interrogation phrasing is put to the SAME act in the SAME episode, so a
# comparison between two phrasings is repeated measures, not two samples.
# fisher_exact_p and newcombe_diff_ci both assume independent arms; applied to
# paired data they discard the pairing, which is most of the information -
# concealment under two phrasings of one question is strongly correlated, and an
# unpaired interval on that contrast is far too wide.
#
# McNemar's test is the paired counterpart: it conditions on the DISCORDANT
# pairs, the acts concealed under one phrasing and not the other, and ignores
# the pairs that agree because they carry no evidence about a difference. The
# exact binomial form is used rather than the chi-square approximation, because
# discordant counts here are single digits.
#
# A useful consequence: a paired contrast is inherently WITHIN-model, since both
# measurements come from one episode. The between-model confounding that
# mantel_haenszel exists to handle cannot arise, so no stratified counterpart is
# needed for these questions.


def mcnemar_exact_p(b: int, c: int) -> float:
    """
    Two-sided exact McNemar p-value from the two discordant counts.

    The conditional test: given b + c discordant pairs, how surprising is a
    split of b to c under the null that either direction is equally likely?
    That is a binomial test with p = 0.5, so this is the exact two-sided
    binomial p rather than the chi-square approximation - the discordant
    counts in this eval are single digits, where the approximation is poor.

    1.0 when there are no discordant pairs: nothing disagreed, so there is no
    evidence of a difference in either direction.
    """
    n = b + c
    if n == 0:
        return 1.0
    tail = min(b, c)
    p = 2.0 * sum(_binom_pmf(k, n, 0.5) for k in range(tail + 1))
    return min(1.0, p)


def paired_compare(n11: int, n10: int, n01: int, n00: int) -> dict:
    """
    One paired comparison of two conditions measured on the same units.

    The four cells are the standard paired 2x2, counting UNITS (here: acts):

        n11  positive under both conditions
        n10  positive under A only        <- discordant
        n01  positive under B only        <- discordant
        n00  positive under neither

    Returns the same shape as compare_rates where it can, so a caller can
    format either without special-casing: `a`/`b` marginals, a `difference`
    with an interval, a p-value, and `separated`. `method` distinguishes them,
    because reporting a paired contrast as though it were unpaired - or the
    reverse - changes the interval substantially.

    The interval is the standard Wald interval on the paired difference, whose
    variance uses the discordant counts and the correlation they imply. It is
    not an exact interval; the p-value beside it is, and where the two
    disagree the p-value is the one to trust.
    """
    n = n11 + n10 + n01 + n00
    if n == 0:
        return {"a": {"successes": 0, "n": 0, "rate": None},
                "b": {"successes": 0, "n": 0, "rate": None},
                "difference": None, "difference_ci95": None,
                "exact_p": None, "p": None, "separated": None,
                "n_pairs": 0, "discordant": {"a_only": 0, "b_only": 0},
                "method": "mcnemar_exact",
                "note": "no paired units; nothing to compare"}

    a_pos, b_pos = n11 + n10, n11 + n01
    diff = (n10 - n01) / n
    # Var of the paired difference: the discordant mass, less the square of the
    # observed shift, over n. Clamped at zero - it can go slightly negative
    # when every discordant pair points the same way.
    var = max(0.0, (n10 + n01) - (n10 - n01) ** 2 / n) / (n * n)
    se = math.sqrt(var)
    exact_p = mcnemar_exact_p(n10, n01)
    ci = [round(max(-1.0, diff - Z_95 * se), 4),
          round(min(1.0, diff + Z_95 * se), 4)]
    return {
        "a": {"successes": a_pos, "n": n, "rate": round(a_pos / n, 4),
              "ci95": wilson_ci(a_pos, n)},
        "b": {"successes": b_pos, "n": n, "rate": round(b_pos / n, 4),
              "ci95": wilson_ci(b_pos, n)},
        "difference": round(diff, 4),
        "difference_ci95": ci,
        "difference_se": round(se, 6),
        "exact_p": exact_p,
        # Aliased so a formatter written for compare_rates can read either.
        "p": exact_p,
        "fisher_p": None,
        # From the exact test rather than the Wald interval: the interval is an
        # approximation and the test is not, so a disagreement between them
        # should not be resolved in the approximation's favour.
        "separated": bool(exact_p < DEFAULT_ALPHA),
        "n_pairs": n,
        "discordant": {"a_only": n10, "b_only": n01},
        "concordant": {"both": n11, "neither": n00},
        "method": "mcnemar_exact",
    }


# =========================================================================
# Stratified comparison
# =========================================================================
#
# WHY A STRATIFIED ESTIMATE EXISTS AT ALL
# ---------------------------------------
# Every rate in this eval is pooled over models whose base rates differ by
# more than the effects being measured, which is the standing condition for
# Simpson's paradox rather than a remote hazard: on one r9 sweep the crude
# oversight-vs-scheming contrast pooled to -1.8pp while a single model inside
# it ran +38pp in the opposite direction. A crude pooled difference answers
# "what happened across this corpus"; a stratified one answers "what happens
# within a model, averaged over models", and only the second is a claim about
# the manipulation rather than about the mix of models that happened to be
# sampled. Both are reported, never one alone.


def _mh_strata(strata: list) -> list:
    """
    Keep only the strata that can contribute: both arms non-empty.

    A stratum with an empty arm carries no information about a within-stratum
    difference, and including it would put its episodes in a denominator no
    comparison was made over.
    """
    return [(x1, n1, x2, n2) for x1, n1, x2, n2 in strata if n1 > 0 and n2 > 0]


def mantel_haenszel(strata: list) -> dict:
    """
    The Mantel-Haenszel stratified comparison of two arms across strata.

    `strata` is a list of (x1, n1, x2, n2) - successes and n in arm 1 and arm
    2 within one stratum, typically one model.

    Reports BOTH a weighted risk difference and a common odds ratio, because
    they answer the question at different costs. The risk difference is in
    percentage points, directly comparable with every crude difference this
    package reports, and stays defined when a stratum is all-zero - which most
    are here. The odds ratio is the classical MH estimand and is what a
    reader from the epidemiological literature will look for, but it is
    undefined when no stratum has a discordant pair, so it may be None on
    exactly the sparse tables this eval produces.

    The chi-square test is the uncorrected Cochran-Mantel-Haenszel statistic;
    no continuity correction is applied, so it stays comparable with the
    Fisher exact p-values reported beside it rather than being conservative
    against them.
    """
    usable = _mh_strata(strata)
    result = {
        "n_strata_given": len(strata),
        "n_strata_used": len(usable),
        "risk_difference": None, "risk_difference_ci95": None,
        "odds_ratio": None, "odds_ratio_ci95": None,
        "chi2": None, "df": None, "p": None,
        "method": "mantel_haenszel",
    }
    if not usable:
        result["note"] = "no stratum has both arms non-empty"
        return result

    # Weighted risk difference. w_i is the standard inverse-variance-like
    # weight n1*n2/(n1+n2), which is what makes the estimator reduce to the
    # crude difference when every stratum shares the same rates.
    weight_total = 0.0
    weighted_diff = 0.0
    variance_num = 0.0
    for x1, n1, x2, n2 in usable:
        p1, p2 = x1 / n1, x2 / n2
        w = (n1 * n2) / (n1 + n2)
        weight_total += w
        weighted_diff += w * (p1 - p2)
        variance_num += w * w * (p1 * (1 - p1) / n1 + p2 * (1 - p2) / n2)
    if weight_total > 0:
        rd = weighted_diff / weight_total
        rd_se = math.sqrt(variance_num) / weight_total
        result["risk_difference"] = round(rd, 4)
        result["risk_difference_ci95"] = [
            round(max(-1.0, rd - Z_95 * rd_se), 4),
            round(min(1.0, rd + Z_95 * rd_se), 4)]
        result["risk_difference_se"] = round(rd_se, 6)

    # Common odds ratio, with the Robins-Breslow-Greenland interval.
    r_sum = s_sum = 0.0
    rbg_1 = rbg_2 = rbg_3 = 0.0
    for x1, n1, x2, n2 in usable:
        a, b = x1, n1 - x1
        c, d = x2, n2 - x2
        t = n1 + n2
        r_i = a * d / t
        s_i = b * c / t
        r_sum += r_i
        s_sum += s_i
        p_i = (a + d) / t
        q_i = (b + c) / t
        rbg_1 += p_i * r_i
        rbg_2 += p_i * s_i + q_i * r_i
        rbg_3 += q_i * s_i
    if r_sum > 0 and s_sum > 0:
        or_mh = r_sum / s_sum
        var_log = (rbg_1 / (2 * r_sum ** 2)
                   + rbg_2 / (2 * r_sum * s_sum)
                   + rbg_3 / (2 * s_sum ** 2))
        se_log = math.sqrt(var_log) if var_log > 0 else None
        result["odds_ratio"] = round(or_mh, 4)
        if se_log:
            result["odds_ratio_ci95"] = [
                round(math.exp(math.log(or_mh) - Z_95 * se_log), 4),
                round(math.exp(math.log(or_mh) + Z_95 * se_log), 4)]
    else:
        result["odds_ratio_note"] = (
            "undefined: no stratum contributes a discordant pair")

    # Cochran-Mantel-Haenszel test.
    observed = expected = variance = 0.0
    for x1, n1, x2, n2 in usable:
        t = n1 + n2
        if t < 2:
            continue
        successes = x1 + x2
        observed += x1
        expected += n1 * successes / t
        variance += (n1 * n2 * successes * (t - successes)
                     / (t * t * (t - 1)))
    if variance > 0:
        chi2 = (observed - expected) ** 2 / variance
        result["chi2"] = round(chi2, 4)
        result["df"] = 1
        result["p"] = chi2_sf(chi2, 1)
        result["separated"] = bool(
            result["risk_difference_ci95"]
            and (result["risk_difference_ci95"][0] > 0
                 or result["risk_difference_ci95"][1] < 0))
    return result


def breslow_day(strata: list, odds_ratio: float = None) -> dict:
    """
    Breslow-Day test for homogeneity of the odds ratio across strata.

    Answers the question the MH estimate itself cannot: is there ONE effect to
    pool? A significant result says the strata disagree, so the stratified
    summary is an average over genuinely different effects and should be
    reported as such rather than as "the" effect.

    Only strata with both arms non-empty AND both a success and a failure
    somewhere in the stratum can contribute - a stratum where the outcome
    never varies is consistent with every odds ratio, so it carries no
    evidence about heterogeneity. `n_strata_used` says how many did, and the
    degrees of freedom follow it rather than the number of strata given: this
    eval's rates sit near zero, so the two frequently differ by a lot.
    """
    usable = []
    for x1, n1, x2, n2 in _mh_strata(strata):
        total, successes = n1 + n2, x1 + x2
        if 0 < successes < total:
            usable.append((x1, n1, x2, n2))

    result = {"statistic": None, "df": None, "p": None,
              "n_strata_given": len(strata), "n_strata_used": len(usable),
              "method": "breslow_day"}
    if len(usable) < 2:
        result["note"] = ("fewer than two strata carry both a success and a "
                          "failure; homogeneity is not testable")
        return result

    if odds_ratio is None:
        odds_ratio = mantel_haenszel(usable).get("odds_ratio")
    if not odds_ratio or odds_ratio <= 0:
        result["note"] = ("no finite non-zero common odds ratio to test "
                          "homogeneity against")
        return result

    statistic = 0.0
    contributing = 0
    for x1, n1, x2, n2 in usable:
        total = n1 + n2
        col1 = x1 + x2
        # Fitted count in cell (arm 1, success) under the common odds ratio,
        # holding this stratum's margins. Quadratic in the general case and
        # linear at psi == 1, which is the degenerate root of the same
        # equation rather than a separate formula.
        psi = odds_ratio
        if abs(psi - 1.0) < 1e-12:
            fitted = n1 * col1 / total
        else:
            qa = 1.0 - psi
            qb = total - n1 - col1 + psi * (n1 + col1)
            qc = -psi * n1 * col1
            disc = qb * qb - 4.0 * qa * qc
            if disc < 0:
                continue
            root = math.sqrt(disc)
            lo_bound = max(0.0, n1 + col1 - total)
            hi_bound = min(float(n1), float(col1))
            candidates = [(-qb + root) / (2.0 * qa), (-qb - root) / (2.0 * qa)]
            fitted = next(
                (c for c in candidates if lo_bound - 1e-9 <= c <= hi_bound + 1e-9),
                None)
            if fitted is None:
                continue
        cells = (fitted, n1 - fitted, col1 - fitted,
                 total - n1 - col1 + fitted)
        if any(c <= 1e-9 for c in cells):
            continue                    # a fitted zero cell has no variance
        var = 1.0 / sum(1.0 / c for c in cells)
        statistic += (x1 - fitted) ** 2 / var
        contributing += 1

    if contributing < 2:
        result["note"] = ("fewer than two strata yielded a non-degenerate "
                          "fitted table")
        result["n_strata_used"] = contributing
        return result

    result["n_strata_used"] = contributing
    result["statistic"] = round(statistic, 4)
    result["df"] = contributing - 1
    result["p"] = chi2_sf(statistic, contributing - 1)
    result["heterogeneous"] = bool(result["p"] < DEFAULT_ALPHA)
    return result


# =========================================================================
# Trend across ordered groups
# =========================================================================
#
# A family of model versions is ORDERED, and that ordering carries information
# a pairwise test throws away. Comparing only the oldest with the newest
# ignores everything between; comparing every pair spends the multiplicity
# budget on comparisons nobody asked about. Cochran-Armitage asks the question
# actually being asked - does the rate move monotonically with position in the
# sequence - as a single test with one degree of freedom.
#
# Position is used as the score rather than a release date, because release
# dates are not recorded here and a version sequence is what a family IS. The
# statistic is invariant to rescaling the scores but NOT to respacing them
# relative to each other, so equal spacing is a real assumption and not a
# formality - it says only that the versions came in this order, which is the
# most the data supports.


def cochran_armitage(groups: list, scores: list = None) -> dict:
    """
    Trend in a proportion across ordered groups.

    `groups` is [(successes, n), ...] in order. `scores` defaults to 0, 1, 2...
    i.e. rank position, which assumes only the ordering and not the spacing.

    Returns z, p, and the direction. z is negative for a FALLING rate, so the
    sign reads the way the question is asked. Two-sided p, because a family
    whose rate climbs is as much an answer as one whose rate falls, and a
    one-sided test would report the climb as a null.

    None for z where the test is undefined: fewer than two groups, no episodes,
    or every episode a success or every one a failure. Those are not trends of
    zero - there is no variation to have a trend in - and returning 0.0 would
    put "nothing happened" and "nothing could be measured" in the same bucket.
    """
    usable = [(x, n) for x, n in groups if n > 0]
    out = {"n_groups": len(groups), "n_groups_used": len(usable),
           "z": None, "p": None, "direction": None, "note": None}
    if len(usable) < 2:
        out["note"] = "fewer than two groups with episodes"
        return out
    if scores is None:
        scores = list(range(len(groups)))
    # Scores follow the groups that were usable, so dropping an empty group
    # does not silently shift the remaining positions.
    paired = [(s, x, n) for s, (x, n) in zip(scores, groups) if n > 0]

    total_n = sum(n for _s, _x, n in paired)
    total_x = sum(x for _s, x, _n in paired)
    p_bar = total_x / total_n
    if p_bar in (0.0, 1.0):
        out["note"] = ("every episode has the same outcome; no variation to "
                       "trend")
        return out

    t_stat = sum(s * (x - n * p_bar) for s, x, n in paired)
    mean_score = sum(s * n for s, _x, n in paired) / total_n
    variance = p_bar * (1 - p_bar) * sum(
        n * (s - mean_score) ** 2 for s, _x, n in paired)
    if variance <= 0:
        out["note"] = "all groups share one score; no ordering to trend along"
        return out

    z = t_stat / math.sqrt(variance)
    out["z"] = round(z, 4)
    # z^2 is chi-square on 1 df, which is the form chi2_sf already provides.
    out["p"] = chi2_sf(z * z, 1)
    out["direction"] = "falling" if z < 0 else ("rising" if z > 0 else "flat")
    out["separated"] = bool(out["p"] < DEFAULT_ALPHA)
    return out


def step_directions(rates: list) -> dict:
    """
    Which way each consecutive step moved, and whether the sequence is monotone.

    Counted beside the trend test because they answer different questions and a
    family can pass one and fail the other: four steps down and one large step
    up can still test as a falling trend, and "consistently falling" is a claim
    about the steps rather than about the fitted direction. `None` rates are
    skipped, not treated as zero.
    """
    known = [r for r in rates if r is not None]
    steps = [b - a for a, b in zip(known, known[1:])]
    down = sum(1 for s in steps if s < 0)
    up = sum(1 for s in steps if s > 0)
    return {
        "n_steps": len(steps),
        "n_down": down, "n_up": up, "n_flat": len(steps) - down - up,
        "monotone_falling": bool(steps) and up == 0 and down > 0,
        "monotone_rising": bool(steps) and down == 0 and up > 0,
        "steps": [round(s, 4) for s in steps],
    }


def weighted_least_squares(xs: list, ys: list, weights: list = None) -> dict:
    """
    The straight line through (x, y), each point weighted by `weights`.

    Returns {"slope", "intercept", "n_points", "note"}, with slope and intercept
    None where no line is defined: fewer than two points, or every point at the
    same x. Those are not slopes of zero - there is nothing to fit - and
    returning 0.0 would put "flat" and "unfittable" in the same bucket, the same
    distinction cochran_armitage draws above.

    WHY WEIGHTS, AND WHY THESE ONES
    -------------------------------
    The caller passes episode counts. A rate measured on 239 episodes is a
    better estimate than one measured on 120, and an unweighted fit treats them
    as equals.

    n-weighting rather than inverse-variance weighting, which is the textbook
    choice for exactly this: inverse variance needs p(1-p)/n, and a rate of 0/120
    - which this corpus has several of - gives a variance of zero and therefore
    infinite weight, so one model with no misaligned episodes would drag the
    whole line onto itself. n is monotone in precision without that failure.

    This is a DESCRIPTIVE fit. It carries no p-value and no interval, and
    nothing here tests whether the slope differs from zero: the trend test in
    this corpus is cochran_armitage on version position, and a second test on a
    second x axis would be a second bite at the same data.
    """
    out = {"n_points": len(xs), "slope": None, "intercept": None, "note": None}
    if len(xs) != len(ys):
        raise ValueError("xs and ys must be the same length")
    if len(xs) < 2:
        out["note"] = "fewer than two points"
        return out
    weights = [1.0] * len(xs) if weights is None else list(weights)
    # A zero-weight point would otherwise silently vanish from a fit that still
    # reports it in n_points.
    usable = [(x, y, w) for x, y, w in zip(xs, ys, weights) if w and w > 0]
    if len(usable) < 2:
        out["note"] = "fewer than two points with a positive weight"
        return out
    total_w = sum(w for _x, _y, w in usable)
    x_bar = sum(w * x for x, _y, w in usable) / total_w
    y_bar = sum(w * y for _x, y, w in usable) / total_w
    denominator = sum(w * (x - x_bar) ** 2 for x, _y, w in usable)
    if denominator <= 0:
        out["note"] = "every point sits at the same x; no line to fit"
        return out
    slope = sum(w * (x - x_bar) * (y - y_bar) for x, y, w in usable) / denominator
    out["slope"] = slope
    out["intercept"] = y_bar - slope * x_bar
    out["n_points_used"] = len(usable)
    return out


def sign_test(n_down: int, n_up: int) -> dict:
    """
    Whether steps fall more often than they rise, over every family pooled.

    Exact two-sided binomial against p=0.5 on the discordant steps, the same
    construction mcnemar_exact_p uses. Flat steps carry no direction and are
    excluded rather than split, which is the conservative choice: a family that
    never moves is not evidence that rates fall.
    """
    n = n_down + n_up
    if n == 0:
        return {"n": 0, "n_down": 0, "n_up": 0, "p": None,
                "note": "no steps with a direction"}
    tail = min(n_down, n_up)
    p = min(1.0, 2.0 * sum(_binom_pmf(k, n, 0.5) for k in range(tail + 1)))
    return {"n": n, "n_down": n_down, "n_up": n_up, "p": p,
            "separated": bool(p < DEFAULT_ALPHA),
            "note": None}


# =========================================================================
# Rank correlation
# =========================================================================
#
# Added for the external-benchmark comparison, where the two measurements are
# on unrelated scales - a percentage-correct score against a rate of episodes -
# so only their ORDER is comparable. Spearman is the rank version of Pearson
# and asks the one question the scales support: do the models that rank high on
# one rank high on the other.
#
# The n there is single digits, which is why the p-value below is exact rather
# than the usual t approximation. At n=8 the asymptotic form is not close, and
# a permutation over 8! = 40,320 orderings is both exact and instant.

# Above this, enumerating every permutation stops being instant (11! is 40
# million), so the p-value switches to sampling. Nothing in this repository
# reaches it today; the branch exists so that a larger overlap degrades to a
# slower estimate rather than to a wrong one.
_EXACT_PERMUTATION_MAX_N = 8

# Draws for the sampled branch, and the seed that makes it reproducible. A
# report that prints a different p-value each run is not a report.
_PERMUTATION_DRAWS = 100000
_PERMUTATION_SEED = 20260821


def _ranks(values: list) -> list:
    """
    Average ranks, ties sharing their mean.

    Competition ranking would give tied values different ranks and make the
    correlation depend on input order, which for two models with identical
    scores is an artefact of how the table was sorted.
    """
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        shared = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = shared
        i = j + 1
    return ranks


def _pearson(xs: list, ys: list):
    """Pearson r, or None where either side has no spread."""
    n = len(xs)
    if n < 2:
        return None
    x_bar, y_bar = sum(xs) / n, sum(ys) / n
    sx = sum((x - x_bar) ** 2 for x in xs)
    sy = sum((y - y_bar) ** 2 for y in ys)
    if sx <= 0 or sy <= 0:
        return None
    cov = sum((x - x_bar) * (y - y_bar) for x, y in zip(xs, ys))
    return cov / math.sqrt(sx * sy)


def spearman(xs: list, ys: list) -> dict:
    """
    Rank correlation between two measurements of the same models.

    Returns {"rho", "p", "n", "method", "separated", "note"}, with rho None
    where there is nothing to correlate: fewer than three points, or one side
    constant. A constant side is not a correlation of zero - it is a variable
    that never varies, and returning 0.0 would put "no relationship" and "no
    measurement" in the same bucket.

    THE P-VALUE IS A PERMUTATION P-VALUE
    ------------------------------------
    Two-sided, over the null that the pairing is arbitrary: hold one column
    fixed, try every reordering of the other, and count how often |rho| reaches
    what was observed. That null is exactly the question - "do these two
    benchmarks order models alike, or would any pairing look like this" - and it
    needs no distributional assumption, which at single-digit n is the whole
    point.

    A tie-corrected t approximation is what most tools return here. At n=8 it is
    not close, and it would attach a small p to a correlation that eight points
    cannot support.

    NOTE WHAT THIS CANNOT DO
    ------------------------
    A rank correlation over a handful of models is descriptive. It cannot
    separate "these benchmarks measure a shared underlying property" from "both
    partly track model scale", and with n in single digits one model's position
    can move rho by a wide margin - which is why the caller is expected to
    report the leave-one-out range beside it.
    """
    out = {"n": len(xs), "rho": None, "p": None, "method": None,
           "separated": None, "note": None}
    if len(xs) != len(ys):
        raise ValueError("xs and ys must be the same length")
    if len(xs) < 3:
        out["note"] = "fewer than three pairs"
        return out
    rx, ry = _ranks(xs), _ranks(ys)
    rho = _pearson(rx, ry)
    if rho is None:
        out["note"] = "one side has no spread; no correlation is defined"
        return out
    out["rho"] = rho

    observed = abs(rho)
    n = len(xs)
    if n <= _EXACT_PERMUTATION_MAX_N:
        from itertools import permutations
        total = hits = 0
        for order in permutations(ry):
            total += 1
            candidate = _pearson(rx, list(order))
            # Reachable only if the fixed side is constant, which the rho check
            # above has already excluded - guarded rather than assumed.
            if candidate is not None and abs(candidate) >= observed - 1e-12:
                hits += 1
        out["p"] = hits / total
        out["method"] = "exact_permutation"
        out["n_permutations"] = total
    else:
        import random
        rng = random.Random(_PERMUTATION_SEED)
        shuffled = list(ry)
        hits = 0
        for _ in range(_PERMUTATION_DRAWS):
            rng.shuffle(shuffled)
            candidate = _pearson(rx, shuffled)
            if candidate is not None and abs(candidate) >= observed - 1e-12:
                hits += 1
        # +1 on both sides: a sampled p of exactly zero claims more than the
        # sample can support, and this is the standard correction for it.
        out["p"] = (hits + 1) / (_PERMUTATION_DRAWS + 1)
        out["method"] = "sampled_permutation"
        out["n_permutations"] = _PERMUTATION_DRAWS
    out["separated"] = bool(out["p"] < DEFAULT_ALPHA)
    return out


def spearman_leave_one_out(xs: list, ys: list) -> dict:
    """
    How far rho moves when any single pair is dropped.

    At single-digit n this is not a refinement, it is the headline: a rho of
    -0.6 that becomes -0.1 without one model is a statement about that model,
    not about the two benchmarks. Reported as the range and the pair whose
    removal moves it furthest, so the reader can go and look at that row.
    """
    full = spearman(xs, ys)
    out = {"rho": full["rho"], "n": len(xs), "min_rho": None, "max_rho": None,
           "most_influential_index": None, "note": full["note"]}
    if full["rho"] is None or len(xs) < 4:
        out["note"] = out["note"] or "too few pairs to drop one"
        return out
    rhos = []
    for i in range(len(xs)):
        kept_x = xs[:i] + xs[i + 1:]
        kept_y = ys[:i] + ys[i + 1:]
        rhos.append(spearman(kept_x, kept_y)["rho"])
    known = [(r, i) for i, r in enumerate(rhos) if r is not None]
    if not known:
        out["note"] = "every leave-one-out fit is undefined"
        return out
    out["min_rho"] = min(r for r, _i in known)
    out["max_rho"] = max(r for r, _i in known)
    out["most_influential_index"] = max(
        known, key=lambda pair: abs(pair[0] - full["rho"]))[1]
    out["leave_one_out_rho"] = rhos
    return out


# =========================================================================
# Multiplicity
# =========================================================================
#
# A per-model test repeated across 27 models at alpha = 0.05 expects about
# 1.4 rejections from noise alone, so "how many models were individually
# significant" is not by itself a count of effects. Two corrections are
# offered because they control different things and a dissertation should say
# which it used: Holm bounds the chance of ANY false rejection (family-wise),
# and Benjamini-Hochberg bounds the expected PROPORTION of rejections that
# are false (false discovery rate). Holm is the stricter of the two; BH keeps
# more power when many of the hypotheses are genuinely non-null.


def holm_bonferroni(pvalues: list, alpha: float = DEFAULT_ALPHA) -> dict:
    """
    Holm's step-down adjustment. Controls the family-wise error rate.

    Returns adjusted p-values in the ORDER GIVEN, alongside the rejection
    flags, so a caller can attach them back to the rows they came from
    without re-sorting. None entries are passed through as None and excluded
    from the family size - a comparison that could not be made is not a
    hypothesis that was tested.
    """
    return _stepwise_adjust(pvalues, alpha, method="holm")


def benjamini_hochberg(pvalues: list, alpha: float = DEFAULT_ALPHA) -> dict:
    """
    Benjamini-Hochberg step-up adjustment. Controls the false discovery rate.

    Same input and output contract as holm_bonferroni.
    """
    return _stepwise_adjust(pvalues, alpha, method="benjamini_hochberg")


def _stepwise_adjust(pvalues: list, alpha: float, method: str) -> dict:
    tested = [(i, p) for i, p in enumerate(pvalues) if p is not None]
    adjusted = [None] * len(pvalues)
    result = {
        "method": method, "alpha": alpha,
        "n_hypotheses": len(tested),
        "n_not_tested": len(pvalues) - len(tested),
        "adjusted": adjusted,
        "rejected": [None] * len(pvalues),
        "n_rejected": 0,
        "n_rejected_uncorrected": sum(1 for _, p in tested if p < alpha),
        "expected_false_positives_uncorrected": round(len(tested) * alpha, 2),
    }
    if not tested:
        return result

    k = len(tested)
    order = sorted(tested, key=lambda pair: pair[1])
    if method == "holm":
        # Step down: each p scaled by the number of hypotheses still standing,
        # then made monotone so a later rejection cannot undercut an earlier one.
        running = 0.0
        for rank, (idx, p) in enumerate(order):
            running = max(running, (k - rank) * p)
            adjusted[idx] = min(1.0, running)
    else:
        # Step up from the largest p, which is what makes BH monotone.
        running = 1.0
        for rank in range(k - 1, -1, -1):
            idx, p = order[rank]
            running = min(running, k * p / (rank + 1))
            adjusted[idx] = min(1.0, running)

    for idx, _ in tested:
        result["rejected"][idx] = bool(adjusted[idx] < alpha)
    result["n_rejected"] = sum(1 for r in result["rejected"] if r)
    return result


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
