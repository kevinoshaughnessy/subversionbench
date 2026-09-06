"""Trend across ordered groups, and the two descriptive summaries of a
sequence of rates that go beside it.
"""

import math

from .chi2 import chi2_sf
from .constants import DEFAULT_ALPHA
from .exact import _binom_pmf


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
    paired = [(s, x, n)
              for s, (x, n) in zip(scores, groups, strict=True) if n > 0]

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
    steps = [b - a for a, b in zip(known, known[1:], strict=False)]
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
    usable = [(x, y, w) for x, y, w in zip(xs, ys, weights, strict=True)
              if w and w > 0]
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
