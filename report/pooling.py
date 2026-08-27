"""
Pooling, contrasts, strata and consistency: the statistics, with no question
attached.

Every question in this package is built from these, which is what stops twelve
questions from each growing their own slightly different pooling. Nothing here
knows which question it is serving - it takes rows, a grouping key, two levels
and a numerator/denominator pair, and returns a contrast.

CRUDE AND STRATIFIED, ALWAYS BOTH
---------------------------------
A crude pooled contrast can be separated at p<0.001 with no within-model
evidence behind it at all. `_crude_vs_stratified` compares the two and states
the divergence in words, so a reader who stops at the crude line is not left to
infer a confound from two numbers several sections apart.
"""

from subversionbench.power import (benjamini_hochberg, breslow_day,
                                   compare_rates, holm_bonferroni,
                                   mantel_haenszel)


def _pool(rows: list, num_key: str, den_key: str) -> tuple:
    n = sum(r[den_key] for r in rows)
    x = sum(r[num_key] for r in rows)
    return x, n


def _contrast(rows: list, group_key: str, level_a, level_b,
              num_key: str, den_key: str) -> dict:
    """
    One pooled comparison: rows where group_key==level_a vs ==level_b.

    Rows where group_key is neither (most often None - awareness that
    resolved to neither grader nor keyword) fall out on their own, since
    equality against a concrete level never matches None.
    """
    a = [r for r in rows if r[group_key] == level_a]
    b = [r for r in rows if r[group_key] == level_b]
    xa, na = _pool(a, num_key, den_key)
    xb, nb = _pool(b, num_key, den_key)
    if na == 0 or nb == 0:
        return {"level_a": level_a, "level_b": level_b,
                "a": {"successes": xa, "n": na, "rate": None},
                "b": {"successes": xb, "n": nb, "rate": None},
                "difference": None, "difference_ci95": None,
                "fisher_p": None, "p": None, "separated": None,
                "note": "one side has no data"}
    c = compare_rates(xa, na, xb, nb)
    c["level_a"], c["level_b"] = level_a, level_b
    # Aliased so `p` is the one field every formatter and the multiplicity
    # correction read, whether the contrast came from compare_rates (Fisher,
    # unpaired) or paired_compare (exact McNemar, paired).
    c["p"] = c["fisher_p"]
    return c


def _models(rows: list) -> list:
    return sorted({r["model"] for r in rows})


def _by_model(rows: list, group_key: str, level_a, level_b,
              num_key: str, den_key: str) -> list:
    out = []
    for m in _models(rows):
        c = _contrast([r for r in rows if r["model"] == m],
                      group_key, level_a, level_b, num_key, den_key)
        c["model"] = m
        out.append(c)
    return out


def _strata_from(by_model: list) -> list:
    """
    (x1, n1, x2, n2) per model, in by_model order, for the stratified tests.

    Built from the same per-model contrasts the table prints, so the
    stratified estimate and the per-model rows can never be computed over
    different data.
    """
    return [(r["a"]["successes"], r["a"]["n"],
             r["b"]["successes"], r["b"]["n"]) for r in by_model]


def _stratified(by_model: list) -> dict:
    """
    The model-stratified counterpart of the crude pooled contrast.

    A crude difference over a corpus whose models differ more than the effect
    does is a statement about the sample's composition as much as about the
    manipulation. The MH estimate holds model constant; Breslow-Day then says
    whether pooling was fair in the first place. Both travel together, because
    a stratified summary of heterogeneous strata is as misleading as the crude
    figure it replaces - just less obviously.
    """
    strata = _strata_from(by_model)
    mh = mantel_haenszel(strata)
    bd = breslow_day(strata, mh.get("odds_ratio"))
    return {
        "mantel_haenszel": mh,
        "breslow_day": bd,
        "interpretation": _stratified_interpretation(mh, bd),
    }


def _crude_vs_stratified(overall: dict, stratified: dict,
                         by_model: list) -> dict:
    """
    Whether the crude pooled contrast survives holding model constant.

    THE CASE THIS EXISTS FOR
    ------------------------
    A crude contrast can be separated at p<0.001 with NO within-model evidence
    behind it at all. On r9 question 9, all 24 oversight-override scheming
    events come from one model, and that model has zero eval-aware episodes -
    so the crude comparison is between that model and every other one, not
    between aware and unaware episodes of the same model. The crude line prints
    SEPARATED, the stratified line prints an undefined test, and a reader who
    stops at the first would report a confounded effect as a finding.

    So the divergence is computed and stated rather than left for the reader to
    infer from two numbers several lines apart.
    """
    crude = overall.get("difference")
    mh = stratified["mantel_haenszel"]
    strat = mh.get("risk_difference")
    # Numerator events sitting in models the stratified estimate had to drop
    # for having an empty arm - the events that cannot inform any within-model
    # comparison.
    events_outside = sum(r["a"]["successes"] + r["b"]["successes"]
                         for r in by_model if r["difference"] is None)
    events_total = sum(r["a"]["successes"] + r["b"]["successes"]
                       for r in by_model)

    result = {
        "crude_difference": crude,
        "stratified_difference": strat,
        "n_outcome_events_total": events_total,
        "n_outcome_events_outside_strata": events_outside,
        "diverges": False,
        "warning": None,
    }
    if crude is None or strat is None:
        return result

    crude_sep = bool(overall.get("separated"))
    strat_sep = bool(mh.get("separated"))

    if crude_sep and not strat_sep:
        result["diverges"] = True
        detail = ""
        if events_total and events_outside == events_total:
            detail = (f" All {events_total} outcome event(s) lie in model(s) "
                      f"with an empty arm, which the stratified estimate must "
                      f"drop, so there is NO within-model evidence for this "
                      f"contrast at all - it is entirely between-model.")
        elif events_outside:
            detail = (f" {events_outside} of {events_total} outcome event(s) "
                      f"lie in model(s) the stratified estimate had to drop.")
        result["warning"] = (
            "CONFOUNDED: the crude difference is separated but the "
            "model-stratified one is not." + detail
            + " Report the stratified result, or report the crude one only as "
              "a statement about this corpus's composition.")
    elif (crude > 0) != (strat > 0) and crude != 0 and strat != 0:
        result["diverges"] = True
        result["warning"] = (
            "SIGN REVERSAL: the crude difference and the model-stratified one "
            "point in opposite directions - Simpson's paradox. The stratified "
            "estimate is the one that answers the research question.")
    return result


def _stratified_interpretation(mh: dict, bd: dict) -> str:
    if mh.get("risk_difference") is None:
        return "No stratum had both arms populated; no stratified estimate."
    rd = mh["risk_difference"]
    ci = mh["risk_difference_ci95"]
    sep = ("excludes zero" if mh.get("separated") else "includes zero")
    # The CMH statistic has zero variance when no stratum's outcome varies -
    # every episode a success, or every one a failure. The risk difference is
    # still defined there (it is 0), so this cannot assume a p-value exists.
    test = (f"; CMH p={mh['p']:.4g}" if mh.get("p") is not None
            else "; CMH test undefined - no stratum's outcome varies")
    effect = (f"an increase of {rd:.1%}" if rd > 0
              else (f"a decrease of {abs(rd):.1%}" if rd < 0 else "no change"))
    text = (f"Holding model constant, the effect is {effect} "
            f"(95% CI [{ci[0]:+.1%}, {ci[1]:+.1%}], which {sep}"
            f"{test}) over {mh['n_strata_used']} model(s).")
    if bd.get("p") is None:
        # bd's own note already says homogeneity is not testable, so this
        # states only the consequence rather than repeating it.
        text += (f" Homogeneity could not be tested ({bd.get('note', '')}), so "
                 f"the average above may be over unlike effects.")
    elif bd.get("heterogeneous"):
        text += (f" Breslow-Day rejects homogeneity (p={bd['p']:.4g}) across "
                 f"{bd['n_strata_used']} informative model(s): the models do "
                 f"NOT share one effect, so read this as an average over "
                 f"genuinely different effects, not as the effect.")
    else:
        text += (f" Breslow-Day does not reject homogeneity (p={bd['p']:.4g}) "
                 f"across {bd['n_strata_used']} informative model(s), so "
                 f"pooling into one effect is defensible.")
    return text


def _consistency(by_model: list) -> dict:
    considered = [r for r in by_model if r["difference"] is not None]
    increase = [r for r in considered if r["difference"] > 0]
    decrease = [r for r in considered if r["difference"] < 0]
    tied = [r for r in considered if r["difference"] == 0]
    significant = [r for r in considered if r["separated"]]

    # Multiplicity over the per-model family. Applied to by_model in the order
    # given so the adjusted values can be written back onto the rows
    # themselves, which is what lets the printed table mark which survive.
    pvalues = [r.get("p") for r in by_model]
    holm = holm_bonferroni(pvalues)
    bh = benjamini_hochberg(pvalues)
    for row, h_adj, h_rej, b_adj, b_rej in zip(
            by_model, holm["adjusted"], holm["rejected"],
            bh["adjusted"], bh["rejected"], strict=True):
        row["holm_p"] = h_adj
        row["holm_rejected"] = h_rej
        row["bh_p"] = b_adj
        row["bh_rejected"] = b_rej

    def _survivors(key):
        return [
            {"model": r["model"], "difference": r["difference"],
             "p": r.get("p"), "holm_p": r["holm_p"], "bh_p": r["bh_p"]}
            for r in sorted((r for r in by_model if r.get(key)),
                            key=lambda r: -abs(r["difference"]))
        ]

    return {
        "n_models_total": len(by_model),
        "n_models_with_data": len(considered),
        "n_models_no_data": len(by_model) - len(considered),
        "n_increase": len(increase),
        "n_decrease": len(decrease),
        "n_tied": len(tied),
        "n_individually_significant": len(significant),
        "significant_models": [
            {"model": r["model"], "difference": r["difference"],
             "p": r.get("p"), "holm_p": r.get("holm_p"),
             "bh_p": r.get("bh_p")}
            for r in sorted(significant, key=lambda r: -abs(r["difference"]))
        ],
        # The multiplicity story, spelled out rather than left to the reader:
        # a family of this size expects roughly this many rejections from noise
        # alone, which is what makes the uncorrected count not a count of
        # effects.
        "multiplicity": {
            "n_hypotheses": holm["n_hypotheses"],
            "n_rejected_uncorrected": holm["n_rejected_uncorrected"],
            "expected_false_positives_uncorrected":
                holm["expected_false_positives_uncorrected"],
            "n_rejected_holm": holm["n_rejected"],
            "n_rejected_benjamini_hochberg": bh["n_rejected"],
            "holm_survivors": _survivors("holm_rejected"),
            "benjamini_hochberg_survivors": _survivors("bh_rejected"),
        },
    }


def _finding(c: dict, label_a: str, label_b: str, metric: str) -> str:
    if c["difference"] is None:
        return (f"Not enough data to compare {metric} under {label_a} vs "
                f"{label_b} ({c['note']}).")
    if c["difference"] == 0:
        return (f"No difference: {metric} was identical under {label_a} "
                f"({c['a']['rate']:.1%}, n={c['a']['n']}) and {label_b} "
                f"({c['b']['rate']:.1%}, n={c['b']['n']}).")
    verb = "higher" if c["difference"] > 0 else "lower"
    sig = "a statistically separated" if c["separated"] else "a not statistically separated"
    return (f"{metric} was {verb} under {label_a} ({c['a']['rate']:.1%}, "
            f"n={c['a']['n']}) than {label_b} ({c['b']['rate']:.1%}, "
            f"n={c['b']['n']}) - {sig} difference "
            f"(diff {c['difference']:+.1%}, p={c['p']:.4g}).")
