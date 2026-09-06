"""Multiplicity corrections over a family of p-values.
"""

from .constants import DEFAULT_ALPHA


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
