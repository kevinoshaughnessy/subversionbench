"""Rank correlation, with a permutation p-value and a leave-one-out
range - which at single-digit n is the headline rather than a
refinement.
"""

import math

from .constants import DEFAULT_ALPHA


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
    cov = sum((x - x_bar) * (y - y_bar)
              for x, y in zip(xs, ys, strict=True))
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
