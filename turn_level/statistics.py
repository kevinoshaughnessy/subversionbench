"""
The numbers: odds ratios over matched sets, their categories, and what the design can detect.

Each matched set is a stratum of the existing Mantel-Haenszel routine
(subversionbench.power.stratified), split into its exposed and its unexposed units, with the
case as the one event. A set whose units are all exposed or all unexposed carries no
information and drops out there. The interval is Robins-Breslow-Greenland's.
"""

import math

from subversionbench.power.constants import Z_95
from subversionbench.power.stratified import mantel_haenszel


def set_table(case_exposed: bool, control_exposures: list) -> tuple:
    """(cases among exposed, exposed, cases among unexposed, unexposed) for one set."""
    n1 = case_exposed + sum(control_exposures)
    n0 = 1 + len(control_exposures) - n1
    return (int(case_exposed), n1, int(not case_exposed), n0)


def category(ci) -> str | None:
    """The decision rule's category for an interval."""
    if not ci:
        return None
    if ci[1] < 1:
        return "upper bound below 1"
    if ci[0] > 1:
        return "lower bound above 1"
    return "includes 1"


def matched_odds_ratio(tables: list) -> dict:
    """The MH odds ratio over matched sets' tables, with its RBG interval and category."""
    mh = mantel_haenszel(tables)
    return {"odds_ratio": mh["odds_ratio"], "ci95": mh["odds_ratio_ci95"],
            "category": category(mh["odds_ratio_ci95"]),
            "sets": len(tables), "informative_sets": mh["n_strata_used"]}


def ratio_of_odds_ratios(a: dict, b: dict) -> dict | None:
    """a's odds ratio over b's, treating the two as independent, with the standard errors of the
    logs read back from each interval."""
    if not (a.get("odds_ratio") and b.get("odds_ratio") and a.get("ci95") and b.get("ci95")):
        return None
    se = [(math.log(x["ci95"][1]) - math.log(x["ci95"][0])) / (2 * Z_95) for x in (a, b)]
    log_ratio = math.log(a["odds_ratio"]) - math.log(b["odds_ratio"])
    half = Z_95 * math.hypot(*se)
    return {"ratio": round(math.exp(log_ratio), 4),
            "ci95": [round(math.exp(log_ratio - half), 4), round(math.exp(log_ratio + half), 4)]}


def _solve(matrix: list, vector: list) -> list | None:
    """matrix^-1 vector by Gaussian elimination with partial pivoting; None if singular."""
    n = len(vector)
    m = [row[:] + [vector[i]] for i, row in enumerate(matrix)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(m[r][col]))
        if abs(m[pivot][col]) < 1e-12:
            return None
        m[col], m[pivot] = m[pivot], m[col]
        for r in range(n):
            if r != col:
                f = m[r][col] / m[col][col]
                m[r] = [x - f * y for x, y in zip(m[r], m[col], strict=True)]
    return [m[i][n] / m[i][i] for i in range(n)]


def _clogit_step(sets: list, beta: list) -> tuple:
    """(gradient, information matrix, log likelihood) of the conditional likelihood at beta."""
    p = len(beta)
    grad, info, loglik = [0.0] * p, [[0.0] * p for _ in range(p)], 0.0
    for units in sets:
        scores = [sum(b * x for b, x in zip(beta, xs, strict=True)) for _y, xs in units]
        top = max(scores)
        weights = [math.exp(s - top) for s in scores]
        total = sum(weights)
        mean = [sum(w * xs[j] for w, (_y, xs) in zip(weights, units, strict=True)) / total
                for j in range(p)]
        case = next(xs for y, xs in units if y)
        loglik += sum(b * x for b, x in zip(beta, case, strict=True)) - top - math.log(total)
        for j in range(p):
            grad[j] += case[j] - mean[j]
            for k in range(p):
                info[j][k] += sum(w * (xs[j] - mean[j]) * (xs[k] - mean[k])
                                  for w, (_y, xs) in zip(weights, units, strict=True)) / total
    return grad, info, loglik


def conditional_logit(sets: list, iterations: int = 50) -> dict | None:
    """Conditional logistic regression over matched sets, each a list of (is case, covariates)
    with one case. The first covariate's odds ratio, with a Wald interval; None if the
    information matrix is singular (a covariate constant within every set) or it fails to fit."""
    p = len(sets[0][0][1]) if sets else 0
    beta = [0.0] * p
    for _ in range(iterations):
        grad, info, _loglik = _clogit_step(sets, beta)
        step = _solve(info, grad)
        if step is None:
            return None
        beta = [b + s for b, s in zip(beta, step, strict=True)]
        if max(abs(s) for s in step) < 1e-8:
            break
    _grad, info, _loglik = _clogit_step(sets, beta)
    unit = [1.0] + [0.0] * (p - 1)
    column = _solve(info, unit)
    if column is None or column[0] <= 0 or abs(beta[0]) > 50:
        return None
    se = math.sqrt(column[0])
    return {"odds_ratio": round(math.exp(beta[0]), 4),
            "ci95": [round(math.exp(beta[0] - Z_95 * se), 4),
                     round(math.exp(beta[0] + Z_95 * se), 4)],
            "coefficients": [round(b, 4) for b in beta]}


def _power(psi: float, n_cases: int, controls_per_case: float, p0: float) -> float:
    """Approximate power of a two-sided 5% test of odds ratio psi: the variance of the log odds
    ratio from exposure prevalence p0 among controls and the implied prevalence among cases,
    ignoring the correlation matching induces."""
    p1 = psi * p0 / (1 + p0 * (psi - 1))
    var = 1 / (n_cases * p1 * (1 - p1)) + 1 / (n_cases * controls_per_case * p0 * (1 - p0))
    z = abs(math.log(psi)) / math.sqrt(var) - Z_95
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


def smallest_detectable_odds_ratio(n_cases: int, controls_per_case: float, p0: float,
                                   power: float = 0.8) -> float | None:
    """The odds ratio nearest 1 from below that the design detects with `power`, scanning down
    from 1 in steps of 0.001; None if none down to 0.01 is, or prevalence is degenerate.

    A scan rather than a bisection: under this approximation power is not monotone near 0,
    where the cases' implied prevalence vanishes and the variance with it grows without bound.
    """
    if not n_cases or not controls_per_case or not 0 < p0 < 1:
        return None
    for step in range(999, 9, -1):
        if _power(step / 1000, n_cases, controls_per_case, p0) >= power:
            return step / 1000
    return None
