"""The twelve research questions: one chart each, plus the overview
that holds all twelve on one axis.
"""

from . import draw
from .captions import (_divergence_caption, _model_count_caption,
                       _rate_caption)
from .exclusion import (_exclusion_captions, _exclusion_title_suffix,
                        _scope_caption)
from .labels import arm_labels, short_label
from .rows import Row, _model_rows, _paired_rows, _pooled_rows
from .style import MULTIPLICITY_NOTE, WILSON_NOTE


def _question_title(index: int, section: dict) -> str:
    return f"Q{index}. {section['question']}"


def plot_question(plt, index: int, section: dict, path: str,
                  report: dict) -> str:
    """
    One question's forest: every model, then the pooled estimates.

    `report` is required rather than defaulted, for the reason
    _exclusion_captions gives: a parameter a caller may omit is a chart that can
    silently be drawn without the words saying which arms it covers.

    Draws NOTHING for a question the arm exclusion collapsed. Those sections
    still hold a full set of per-model rows, every one of them "no data on one
    side", and a forest of thirty such lines under the question's own title
    reads as a measured null rather than as an absent comparison. The console
    says the same thing in words, and write_charts reports the omission.
    """
    if section.get("collapsed_by_exclusion"):
        return None
    paired = "contrasts" in section
    rows = (_paired_rows(section) if paired
            else _model_rows(section.get("by_model") or [])
            + _pooled_rows(section))
    if not rows:
        return None
    label_a, label_b = arm_labels(section)
    xlabel = (f"difference in rate, percentage points "
              f"({label_a} minus {label_b})" if not paired else
              "difference in concealment rate, percentage points "
              "(variant A minus variant B)")
    captions = [(_scope_caption(section), "#555555")]
    if paired:
        captions += [
            (section.get("not_pooled_because", ""), "#555555"),
            ("paired: exact McNemar over discordant pairs, not Fisher over "
             "independent arms - the concordant pairs carry no weight in the "
             "test", "#555555"),
        ]
    else:
        captions += [
            (_rate_caption(section), "#333333"),
            # Directly under the rates, because both describe the base of the
            # figure: what the pooled rates are over, and how many models that
            # is. Reading them apart is what invites the stratified row's
            # stratum count to be taken for the corpus total.
            (_model_count_caption(section), "#333333"),
            (MULTIPLICITY_NOTE, "#555555"),
            (_divergence_caption(section), "#b00020"),
        ]
    captions.append((WILSON_NOTE, "#777777"))
    captions += _exclusion_captions(report)
    return draw._draw_forest(plt, rows,
                        _question_title(index, section)
                        + _exclusion_title_suffix(report),
                        captions, path, xlabel, legend=not paired)


def plot_overview(plt, report: dict, path: str) -> str:
    """
    Every question on one axis.

    The stratified estimate where a question has one, because that is the figure
    the report treats as the defensible one, and the crude estimate is already
    on each question's own chart beside it. The two paired questions contribute
    their contrasts individually: they are explicitly never pooled, so a single
    row for either would be a number this benchmark does not compute.
    """
    rows = []
    flagged = False
    for i, section in enumerate(report.get("questions") or [], start=1):
        if "contrasts" in section:
            for row in _paired_rows(section):
                row.label = f"Q{i}. {row.label}"
                row.note = ""
                rows.append(row)
            continue
        # KEPT AS A ROW, not dropped. This chart's whole claim is that it holds
        # all twelve questions, and the caption below counts them; a version
        # silently showing nine would make a reader believe the three were never
        # asked rather than that the exclusion took their comparator away.
        if section.get("collapsed_by_exclusion"):
            rows.append(Row(f"Q{i}. {short_label(section['id'])}",
                            None, None, None, "stratified",
                            missing="no comparator - the excluded arm was one "
                                    "side of this contrast"))
            continue
        mh = ((section.get("stratified") or {}).get("mantel_haenszel") or {})
        overall = section.get("overall") or {}
        diff = mh.get("risk_difference")
        ci = mh.get("risk_difference_ci95") or (None, None)
        kind = "stratified"
        if diff is None:
            # No stratified estimate - every stratum uninformative - so the
            # crude one stands in, coloured as itself so the substitution is
            # visible rather than silently mixed in with the others.
            diff, kind = overall.get("difference"), "crude"
            ci = overall.get("difference_ci95") or (None, None)
        label = f"Q{i}. {short_label(section['id'])}"
        # Flagged so a reader cannot take a row off this chart without learning
        # that the question's own two estimates disagree. The row still shows
        # the stratified figure, which is the one to report; the marker says
        # there is a reason that choice matters here.
        if _divergence_caption(section):
            label += "  *"
            flagged = True
        if diff is None:
            rows.append(Row(label, None, None, None, kind,
                            missing="no estimate"))
            continue
        rows.append(Row(label, diff, ci[0], ci[1], kind,
                        marked=bool(mh.get("separated")
                                    if kind == "stratified"
                                    else overall.get("separated"))))
    if not rows:
        return None
    captions = [
        ("stratified (Mantel-Haenszel) estimate where a question has one, "
         "crude pooled where it does not; the two paired questions contribute "
         "their contrasts individually because they are never pooled",
         "#555555"),
        ("* crude and stratified estimates diverge on this question - see its "
         "own chart" if flagged else "", "#b00020"),
        ("each row is a different outcome on a different denominator: read the "
         "direction and interval, not the ranking", "#b00020"),
        (WILSON_NOTE, "#777777"),
    ] + _exclusion_captions(report)
    return draw._draw_forest(
        plt, rows, "All twelve research questions: effect and 95% interval"
        + _exclusion_title_suffix(report),
        captions, path,
        "difference in rate, percentage points (exposed minus unexposed)",
        legend=True, bold_pooled=False)
