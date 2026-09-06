"""Stratified comparison: holding a nuisance variable constant.
"""

import math

from .chi2 import chi2_sf
from .constants import DEFAULT_ALPHA, Z_95


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
