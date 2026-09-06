"""One drawable row per model, per pooled estimate, per contrast.

The chart adds no arithmetic: every number on a Row is already in the
report, and this module is the boundary where a report dict becomes
something with a position on an axis.
"""



# Rows
# ---------------------------------------------------------------------------

class Row:
    """
    One line of a forest: a label, an effect, its interval, and what kind of
    thing it is.

    `missing` carries the reason an effect could not be computed, so the row can
    be drawn as an explicit gap rather than either dropped or faked as zero.
    """

    __slots__ = ("label", "diff", "lo", "hi", "kind", "marked", "note",
                 "missing")

    def __init__(self, label, diff, lo, hi, kind="model", marked=False,
                 note="", missing=""):
        self.label = label
        self.diff = diff
        self.lo = lo
        self.hi = hi
        self.kind = kind
        self.marked = marked
        self.note = note
        self.missing = missing


def _ci(contrast: dict) -> tuple:
    ci = contrast.get("difference_ci95") or (None, None)
    return ci[0], ci[1]


def _model_rows(by_model: list) -> list:
    """
    One row per model, ordered by effect.

    Sorted rather than left alphabetical because the question these rows answer
    is whether the effect holds ACROSS models, and sorted order shows that
    directly: the sign split, the spread, and any single model carrying the
    pooled estimate all read off the shape. The consistency block printed above
    the chart counts exactly what this ordering displays.

    Models with no data on one side sort to the end, since they have no effect
    to place among the others.
    """
    # DELIBERATELY NOT has_chart_support. The descriptive charts below drop a
    # model that cannot support an estimate; a question forest must not, and
    # the reason is in this module's own docstring: the report prints "N/M had
    # data on both sides" above this figure, and a chart showing fewer than M
    # rows makes that sentence unverifiable. Measured on r9: the rule would
    # remove 25 to 34 of 37 models from the awareness-conditioned questions,
    # which is most of the evidence those charts exist to show - including
    # every model whose thin side is thin BECAUSE the effect is real.
    rows = []
    for r in by_model:
        diff = r.get("difference")
        if diff is None:
            rows.append(Row(r["model"], None, None, None, "model",
                            missing=r.get("note") or "no data on one side"))
            continue
        lo, hi = _ci(r)
        rows.append(Row(r["model"], diff, lo, hi, "model",
                        marked=bool(r.get("holm_rejected"))))
    placed = sorted((r for r in rows if r.diff is not None),
                    key=lambda r: r.diff)
    return placed + [r for r in rows if r.diff is None]


def _pooled_rows(section: dict) -> list:
    """
    The crude and stratified estimates, and the parallel measure where a
    question carries one.

    Both pooled estimates always, never one: `crude_vs_stratified` exists
    because they can disagree, and a chart showing whichever happens to be
    handy makes that check unavailable to the reader.
    """
    rows = []
    overall = section.get("overall") or {}
    if overall.get("difference") is not None:
        lo, hi = _ci(overall)
        rows.append(Row("CRUDE POOLED", overall["difference"], lo, hi,
                        "crude", marked=bool(overall.get("separated"))))
    mh = ((section.get("stratified") or {}).get("mantel_haenszel") or {})
    if mh.get("risk_difference") is not None:
        ci = mh.get("risk_difference_ci95") or (None, None)
        rows.append(Row(f"STRATIFIED (MH, {mh.get('n_strata_used', '?')} models)",
                        mh["risk_difference"], ci[0], ci[1],
                        "stratified", marked=bool(mh.get("separated"))))
    # Questions 2 and 4 only. The same contrast read from visible text alone -
    # the one channel every provider route returns - so a reader can see whether
    # the conclusion survives losing the reasoning channel. Drawn beside the
    # headline rather than on a chart of its own, because the comparison between
    # the two is the entire reason the parallel measure is computed.
    parallel = section.get("text_reachable") or {}
    p_overall = parallel.get("overall") or {}
    if p_overall.get("difference") is not None:
        lo, hi = _ci(p_overall)
        rows.append(Row("PARALLEL: awareness in visible text only",
                        p_overall["difference"], lo, hi, "parallel",
                        marked=bool(p_overall.get("separated"))))
    return rows


def _paired_rows(section: dict) -> list:
    """
    One row per contrast, for the two paired questions.

    Annotated with the discordant counts because those two numbers are the whole
    test: exact McNemar reads nothing from the concordant pairs, so a row
    showing n=803 without them overstates how much evidence is behind it.
    """
    rows = []
    for c in section.get("contrasts") or []:
        overall = c.get("overall") or {}
        diff = overall.get("difference")
        label = f"{c['act']}: {c['variant_a']} vs {c['variant_b']}"
        if diff is None:
            rows.append(Row(label, None, None, None, "paired",
                            missing=overall.get("note") or "no pairs"))
            continue
        lo, hi = _ci(overall)
        disc = overall.get("discordant") or {}
        rows.append(Row(
            label, diff, lo, hi, "paired",
            marked=bool(overall.get("separated")),
            note=(f"{overall.get('n_pairs', '?')} pairs, "
                  f"{disc.get('a_only', 0)}/{disc.get('b_only', 0)} discordant")))
    return rows
