"""Paired comparison: the same episodes measured twice.
"""

import math

from .constants import DEFAULT_ALPHA, Z_95
from .exact import _binom_pmf
from .intervals import wilson_ci


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
