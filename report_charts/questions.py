"""The research questions: one chart each, plus the overview that holds
them all on one axis.

The count is deliberately not written down here. It was "twelve" until a
thirteenth was added, and a number in a docstring is a fact with nothing
checking it - the module iterates whatever the report emits.
"""

from . import draw
from .captions import (_act_ordering_caption, _composite_caption,
                       _divergence_caption, _model_count_caption,
                       _rate_caption, _timing_caption)
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

    Draws NOTHING for a question EITHER narrowing collapsed - the arm exclusion
    or the awareness reading, both of which attach `collapsed_by_exclusion`.
    Those sections still hold a full set of per-model rows, every one of them
    "no data on one side", and a forest of thirty such lines under the
    question's own title reads as a measured null rather than as an absent
    comparison. The console says the same thing in words, and write_charts
    reports the omission.

    This said "the arm exclusion" while skipping for both, which is the same
    false specificity the overview row carried - see `_missing_label`. The skip
    was right; only the sentence describing it was narrow.

    ALSO DRAWS NOTHING for a question `out_of_scope_for_corpus` - a DIFFERENT
    field from `collapsed_by_exclusion`, and deliberately checked here rather
    than folded into it: this one skips the CHART only. The console still
    prints the section's real numbers, which on the goal-guarding corpus's
    sandbox and lure questions are not empty - see
    run_report._out_of_scope_for_this_corpus for why hiding the console text
    too would misreport a scope decision as an absence of data.
    """
    if section.get("collapsed_by_exclusion") or section.get(
            "out_of_scope_for_corpus"):
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
    # FIRST after the scope, because it says what the bars count. A reader who
    # takes "agentic misalignment" for one act reads every row wrong, and the
    # title cannot carry three act names without becoming unreadable.
    composite = _composite_caption(section)
    if composite:
        captions.append((composite, "#333333"))
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
            # Beneath the divergence warning and in the same colour:
            # both qualify the pooled estimate directly above them, and
            # a reader who takes either bar at face value needs both.
            (_timing_caption(section), "#b00020"),
            (_act_ordering_caption(section), "#555555"),
        ]
    captions.append((WILSON_NOTE, "#777777"))
    captions += _exclusion_captions(report)
    return draw._draw_forest(plt, rows,
                        _question_title(index, section)
                        + _exclusion_title_suffix(report),
                        captions, path, xlabel, legend=not paired)


def _missing_label(reason: str) -> str:
    """The row label for a question that has no effect to plot.

    THE SECTION'S OWN REASON, SHORTENED - not a reason of this layer's own.
    This read `collapsed_by_exclusion` as a boolean and printed
    "no comparator - the excluded arm was one side of this contrast", which
    names an arm exclusion. Two different narrowings attach that field, and
    under `--exclude-aware` NO arm is excluded: 8 of the 12 questions collapse
    because awareness is one side of them, so 8 rows gave the reader a cause
    that had not occurred.

    It also falsified the reason build_report gives for putting both narrowings
    on one field - that "the two consumers of it - the console banner and the
    chart layer's skip - already do the right thing with whatever reason is
    attached". The banner does; this did not, which is exactly the half of that
    claim nothing checked.

    THE HEADLINE, because the full reason is a sentence of 145 to 205
    characters and this is drawn at fontsize 7 beside a row. Both producers
    write it as `headline: detail` for that division to be available - the
    console prints the whole thing, and a reason with no colon is used whole
    rather than guessed at.
    """
    return reason.split(":", 1)[0].strip() or reason


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
        #
        # Same treatment for `out_of_scope_for_corpus` as for
        # `collapsed_by_exclusion` - both mean this chart has nothing to draw
        # for the question - even though the two are different facts about WHY
        # (see plot_question). The overview is a chart, not the console, so it
        # follows the chart-layer field the same way plot_question does.
        out_of_scope = (section.get("collapsed_by_exclusion")
                        or section.get("out_of_scope_for_corpus"))
        if out_of_scope:
            rows.append(Row(f"Q{i}. {short_label(section['id'])}",
                            None, None, None, "stratified",
                            missing=_missing_label(out_of_scope)))
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
        plt, rows, "All research questions: effect and 95% interval"
        + _exclusion_title_suffix(report),
        captions, path,
        "difference in rate, percentage points (exposed minus unexposed)",
        legend=True, bold_pooled=False)


# The three awareness-vs-misalignment readings that share one outcome: no
# flavour restriction, safety-flavoured, capability-flavoured. Order is the
# reading order a caption below explains - the top row's union, then its two
# non-overlapping halves - not question order, which is why this is a tuple
# of ids rather than a slice of `report["questions"]`.
_AWARENESS_KIND_IDS = (
    "awareness_vs_misalignment",
    "awareness_vs_misalignment_when_safety_aware",
    "awareness_vs_misalignment_when_capability_aware",
)
_AWARENESS_KIND_LABELS = {
    "awareness_vs_misalignment": "any flavour (question 5)",
    "awareness_vs_misalignment_when_safety_aware": "safety-flavoured",
    "awareness_vs_misalignment_when_capability_aware": "capability-flavoured",
}


def plot_awareness_kind_comparison(plt, report: dict, path: str) -> str:
    """
    The three awareness-vs-misalignment readings side by side.

    A FILTERED plot_overview, not a new chart type: the same
    stratified-else-crude pooled estimate per question, on the same Row and
    forest machinery, scoped to the three questions sharing this outcome so a
    reader can compare them without assembling three separately-numbered
    charts by hand. Question 5's row is not the sum of the other two -
    unspecified/ambiguous-flavoured episodes count toward it and toward
    neither flavour row - so the caption says so rather than let three rows
    read as one number split in half.

    Missing gracefully: a report built before the two flavour questions
    existed, or one where the flavour split collapsed for an exclusion
    reason, draws whichever rows it can with the reason in place of a bar -
    see plot_overview's own handling, mirrored here.
    """
    if not report.get("questions"):
        return None
    sections = {s["id"]: s for s in report["questions"]}
    rows = []
    flagged = False
    for qid in _AWARENESS_KIND_IDS:
        label = _AWARENESS_KIND_LABELS[qid]
        section = sections.get(qid)
        if section is None:
            rows.append(Row(label, None, None, None, "stratified",
                            missing="not in this report"))
            continue
        out_of_scope = (section.get("collapsed_by_exclusion")
                        or section.get("out_of_scope_for_corpus"))
        if out_of_scope:
            rows.append(Row(label, None, None, None, "stratified",
                            missing=_missing_label(out_of_scope)))
            continue
        mh = ((section.get("stratified") or {}).get("mantel_haenszel") or {})
        overall = section.get("overall") or {}
        diff = mh.get("risk_difference")
        ci = mh.get("risk_difference_ci95") or (None, None)
        kind = "stratified"
        if diff is None:
            diff, kind = overall.get("difference"), "crude"
            ci = overall.get("difference_ci95") or (None, None)
        if _divergence_caption(section):
            label += "  *"
            flagged = True
        if diff is None:
            rows.append(Row(label, None, None, None, kind,
                            missing="no estimate"))
            continue
        rows.append(Row(label, diff, ci[0], ci[1], kind,
                        marked=bool(mh.get("separated") if kind == "stratified"
                                    else overall.get("separated"))))
    if not any(r.diff is not None for r in rows):
        return None
    captions = [
        ("stratified (Mantel-Haenszel) estimate where a row has one, crude "
         "pooled where it does not - same convention as the overview chart",
         "#555555"),
        ("the top row is the union of the other two plus every "
         "unspecified/ambiguous-flavoured episode; the other two restrict to "
         "episodes whose flavour could be told and do not overlap each "
         "other - three separate contrasts, not one split in half",
         "#b00020"),
        ("* crude and stratified estimates diverge on this row - see its own "
         "chart" if flagged else "", "#b00020"),
        (WILSON_NOTE, "#777777"),
    ] + _exclusion_captions(report)
    return draw._draw_forest(
        plt, rows, "Misalignment rate by awareness flavour"
        + _exclusion_title_suffix(report),
        captions, path,
        "difference in misalignment rate, percentage points (aware minus "
        "not, within each flavour)",
        legend=True, bold_pooled=False)
