#!/usr/bin/env python3
"""
Charts for the twelve research questions answered by the report package.

Every number drawn here is already in that script's printed output and in its
JSON. A chart is a second reading of the same figures, never a new claim, which
is why matplotlib stays an optional extra: losing these costs presentation and
never analysis.

WHY A FOREST PLOT AND NOT A BAR CHART
-------------------------------------
Two bars for "oversight present" and "oversight absent" show the rates and hide
everything the report actually spends its length on. Questions 1-10 are each
answered four ways - the crude pooled effect, the model-stratified effect, the
per-model consistency, and how the effect moves under the other axes - and three
of those four are statements about the SPREAD across models rather than about
the pooled number. A forest is the shape that holds them together: one row per
model with its interval, then the two pooled estimates underneath.

It also makes the failure mode the report warns about visible instead of
inferable. `crude_vs_stratified` exists because a crude contrast can separate at
p<0.001 with no within-model evidence behind it - question 9 on r9 is exactly
that, with all 24 of its outcome events inside one model. On a forest, that is a
row of intervals straddling zero under a summary diamond that does not, which a
reader sees before reading a word.

Drawing only one of the two pooled estimates would defeat that check, so both
are always drawn, and where the crude and stratified rows disagree in sign or
separation the caption says so in the report's own words.

RISK DIFFERENCES, NOT ODDS RATIOS
---------------------------------
The Mantel-Haenszel block carries both, and the odds ratio is the better-behaved
estimate. The charts still plot the risk difference, because that is the number
the printed report leads with and the one the questions are phrased in - "does
oversight increase or decrease the rate" is a question about percentage points.
A chart whose headline figure cannot be found in the text it illustrates is
worse than no chart. The odds ratio stays in the JSON and in the console.

WHAT IS DRAWN WHEN THERE IS NOTHING TO DRAW
-------------------------------------------
A model with no episodes on one side of the contrast has no difference and no
interval. Those models are drawn as an open marker on the zero line with the
reason beside them rather than dropped, because dropping them would silently
shrink the denominator of the consistency count printed above the chart - the
report says "18/28 had data on both sides", and a chart showing 18 rows makes
that sentence unverifiable.

QUESTIONS 11 AND 12 ARE A DIFFERENT SHAPE
-----------------------------------------
Every interrogation phrasing is put to the same act in the same episode, so
those questions are paired: exact McNemar over discordant pairs, reported as a
list of contrasts that are deliberately never pooled. Their charts hold one row
per contrast rather than one row per model, and each row is annotated with the
discordant counts, because those two numbers ARE the test - the concordant pairs
contribute nothing to the p-value, and a reader who sees n=803 without seeing
that 66 pairs carried the whole comparison will over-read the precision.
"""

import os
import textwrap

from subversionbench import charting
from subversionbench.power import MIN_INFORMATIVE_DENOMINATOR, wilson_ci

# ---------------------------------------------------------------------------
# Chart conventions
# ---------------------------------------------------------------------------
#
# These repeat trends/chart_style.py rather than importing from it. The two
# are separate entry points over the same corpus and neither imports the other
# today; coupling them so that a chart tweak for one moves the other's output is
# a worse trade than duplicating four constants and a ten-line import guard.

CHART_DPI = 150

# Percentage points. Every rate in the report is a fraction, and every axis here
# is that fraction times this - stated once so the conversion cannot drift
# between the axis, the annotations and the caption.
PP = 100

# Row heights, in inches. A forest with 28 models needs a row tall enough to
# read a model ID against, and the figure grows with the corpus rather than
# squeezing more models into a fixed height.
_ROW_HEIGHT = 0.24
_FIGURE_MARGIN = 2.4
_FIGURE_WIDTH = 9.5

# The two pooled estimates and the parallel measure are drawn as diamonds so
# they cannot be mistaken for one more model at a glance.
_SUMMARY_MARKER = "D"
_MODEL_MARKER = "o"

_COLOURS = {
    "model": "#4c72b0",
    "model_significant": "#c44e52",
    "crude": "#dd8452",
    "stratified": "#55a868",
    "parallel": "#8172b3",
    "paired": "#4c72b0",
}

# The row kinds that summarise other rows, and so are set apart from them. A
# paired contrast is pooled over models too, but on those questions it is the
# ONLY kind of row present, so setting it apart would set apart everything.
_POOLED_KINDS = ("crude", "stratified", "parallel")

# Narrower than the caption wrap: a title sets the axes width through
# `bbox_inches`, and a question phrased at full length ran past the right edge
# of the figure on the two paired charts, whose axes are narrow because their
# row labels are long.
_TITLE_WRAP = 80

WILSON_NOTE = "intervals: 95% (Newcombe for differences, Wilson for rates)"

# Said wherever the rule below removed a row, so a reader counting models against
# the printed report can see why the two differ.
EXCLUDED_NOTE = ("models with fewer than "
                 f"{MIN_INFORMATIVE_DENOMINATOR} episodes are not plotted")


def has_chart_support(n) -> bool:
    """
    Whether one model has enough episodes to be worth a row on any chart.

    ONE RULE, NOT ONE PER CHART. Every per-model chart here applies this, and
    each applies it to its OWN denominator - the refusals for the persistence
    chart, the resolved episodes for the rate charts, the smaller arm for a
    question's forest - because "n" means a different count on each and the
    rule is about support for the estimate drawn, not about episode count in
    the abstract.

    WHY EXCLUDE RATHER THAN MARK. These used to be drawn with a hollow marker
    and a footnote, which is honest but does not survive being looked at: a
    model with 11 episodes and no events still gets a Wilson interval running
    past 25%, and on a chart whose finding is one episode in one model that
    row is the most visually prominent thing on the figure. A reader takes the
    width for a result. The count that the row carried is still in the printed
    report and in the JSON, neither of which drops anything - the chart is the
    only place this applies, and it is applied because a chart is read at a
    glance and a table is not.

    Threshold is MIN_INFORMATIVE_DENOMINATOR rather than a number chosen here,
    so it moves with the rest of the analysis if it ever moves at all.
    """
    return n is not None and n >= MIN_INFORMATIVE_DENOMINATOR

# Said on every forest, because a row of per-model intervals invites reading the
# ones that exclude zero as findings. They are not: the report corrects for
# multiplicity across the 28 models, and only the corrected flag is marked here.
MULTIPLICITY_NOTE = ("filled = individually significant after Holm correction "
                     "across models; open = not")




# ---------------------------------------------------------------------------
# Naming the arms
# ---------------------------------------------------------------------------
#
# A contrast stores its levels as the raw values it split on - True/False for
# oversight and for awareness, "max"/"none" for nudge - and the words that make
# those readable live at each question's call site in report/, inside a
# `finding` sentence that is already composed by the time it reaches here.
#
# So the words are rebuilt from the exposure named in the question id. Keyed by
# exposure rather than by question, because three questions share `oversight`
# and six share `awareness`, and a per-question table would let two questions
# drift into labelling the same split differently.
#
# test_report_charts pins this against the ids build_report actually emits, so a
# renamed or added question fails the suite rather than silently drawing a chart
# with an unlabelled axis.
_LEVEL_WORDS = {
    "oversight": {True: "oversight present", False: "oversight absent"},
    "nudge": {"max": "nudge=max", "strong": "nudge=strong", "none": "nudge=none"},
    "awareness": {True: "verbalised awareness", False: "no verbalised awareness"},
}


def exposure_of(question_id: str) -> str:
    """The manipulated axis named on the left of a question id."""
    return question_id.split("_vs_")[0]


def arm_labels(section: dict) -> tuple:
    """
    Readable names for the two sides of a contrast, or the raw levels.

    Falling back to the raw level rather than raising: a chart with an ugly
    label still carries its numbers, and a report that dies on a new question id
    loses eleven charts that were fine.
    """
    overall = section.get("overall") or {}
    words = _LEVEL_WORDS.get(exposure_of(section["id"]), {})
    return (words.get(overall.get("level_a"), str(overall.get("level_a"))),
            words.get(overall.get("level_b"), str(overall.get("level_b"))))


def short_label(question_id: str) -> str:
    """
    "oversight -> scheming", from the id.

    Derived rather than tabulated: the ids are already written as
    `<exposure>_vs_<outcome>`, so a hand-kept table of pretty names would be a
    second place to update and a place for the two to disagree.
    """
    return question_id.replace("_vs_", " -> ").replace("_", " ")


# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# Captions
# ---------------------------------------------------------------------------

_CAPTION_WRAP = 108


def _wrap(text: str, width: int = _CAPTION_WRAP) -> str:
    """
    Fold a caption so it cannot widen the figure.

    Captions sit outside the axes, so `bbox_inches="tight"` grows the whole
    image to fit an over-long line: the axes keep their size and the chart ends
    up in a corner. break_on_hyphens is off for the same reason it is off in
    the trends package - these captions name models, and half of
    `google/gemini-3-flash-preview` names a different model in this corpus.
    """
    return "\n".join(
        line for para in text.split("\n")
        for line in (textwrap.wrap(para, width, break_long_words=False,
                                   break_on_hyphens=False) or [""]))


def _rate_caption(section: dict) -> str:
    """The two pooled rates in words, since a difference alone hides the level."""
    overall = section.get("overall") or {}
    a, b = overall.get("a") or {}, overall.get("b") or {}
    if a.get("rate") is None or b.get("rate") is None:
        return ""
    label_a, label_b = arm_labels(section)
    return (f"{label_a}: {a['rate'] * PP:.1f}% ({a['successes']}/{a['n']})"
            f"     {label_b}: {b['rate'] * PP:.1f}% ({b['successes']}/{b['n']})")


def _divergence_caption(section: dict) -> str:
    """
    The report's own words where crude and stratified disagree.

    Quoted from `crude_vs_stratified` rather than re-derived: the chart must not
    be able to say something the printed report does not.
    """
    divergence = section.get("crude_vs_stratified") or {}
    return divergence.get("warning") or ""


def _scope_caption(section: dict) -> str:
    """
    What was excluded from the denominator, for the questions that restrict one.

    Not-applicable is not zero: `monitoring_disabled` is None in every
    no-oversight episode because that arm has no monitoring artefact to disable,
    and counting those as "did not override" once halved this question's rates.
    A chart that shows the restricted denominator without saying so invites the
    reader to reconcile it against a corpus total that was never its base.
    """
    excluded = section.get("n_episodes_not_applicable")
    if not excluded:
        return ""
    considered = section.get("n_episodes_observable",
                             section.get("n_episodes_considered"))
    return (f"{considered} episode(s) where the act was observable; "
            f"{excluded} not applicable and excluded from the denominator")


# ---------------------------------------------------------------------------
# Drawing
# ---------------------------------------------------------------------------

def _draw_forest(plt, rows: list, title: str, captions: list, path: str,
                 xlabel: str, legend: bool = True,
                 bold_pooled: bool = True) -> str:
    height = _FIGURE_MARGIN + _ROW_HEIGHT * max(len(rows), 1)
    fig, ax = plt.subplots(figsize=(_FIGURE_WIDTH, height))

    # Top row at the top: matplotlib counts y upward, and a forest read from a
    # page runs downward, so the positions are assigned in reverse.
    ys = list(range(len(rows) - 1, -1, -1))
    for y, row in zip(ys, rows, strict=True):
        if row.diff is None:
            ax.text(0, y, f"  {row.missing}", va="center", fontsize=7,
                    color="#999999", style="italic")
            continue
        colour = _COLOURS["model_significant" if (
            row.kind == "model" and row.marked) else row.kind]
        summary = row.kind != "model"
        if row.lo is not None and row.hi is not None:
            ax.plot([row.lo * PP, row.hi * PP], [y, y], color=colour,
                    linewidth=2.2 if summary else 1.3, solid_capstyle="round",
                    alpha=1.0 if summary else 0.75, zorder=3)
        ax.plot([row.diff * PP], [y],
                marker=_SUMMARY_MARKER if summary else _MODEL_MARKER,
                markersize=8 if summary else 5.5,
                color=colour,
                # Open where the corrected test did not reject, so the eye is
                # not drawn to intervals that clear zero only before
                # multiplicity correction.
                markerfacecolor=colour if (summary or row.marked) else "white",
                markeredgecolor=colour, markeredgewidth=1.3, zorder=4)
        if row.note:
            ax.text(1.005, y, row.note, transform=ax.get_yaxis_transform(),
                    va="center", fontsize=7, color="#666666")

    ax.axvline(0, color="#333333", linewidth=1.0, linestyle="--", alpha=0.7,
               zorder=1)
    ax.set_yticks(ys)
    ax.set_yticklabels([r.label for r in rows], fontsize=8)
    # Bold marks the POOLED rows against the per-model ones around them. On the
    # paired questions every row is a pooled contrast, so bolding by kind alone
    # would bold the whole axis and mark nothing.
    for tick, row in zip(ax.get_yticklabels(), rows, strict=True):
        if bold_pooled and row.kind in _POOLED_KINDS:
            tick.set_fontweight("bold")
    ax.set_ylim(-0.8, len(rows) - 0.2)
    ax.set_xlabel(xlabel, fontsize=9)
    ax.set_title(_wrap(title, _TITLE_WRAP), fontsize=10, loc="left")
    ax.grid(axis="x", alpha=0.25)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    fig.tight_layout()

    # Everything below the axes is placed in FIGURE coordinates against the
    # measured bottom of the x label, and stepped in inches.
    #
    # Axes fractions do not work here. The figure grows with the row count, so a
    # fraction that clears the x label on a 31-row chart leaves an inch of white
    # space on an 8-row one, and one that suits the short chart lands the caption
    # on the axis label of the tall one. An inch is an inch on both.
    inches = _BelowAxes(fig, ax, height)
    if legend:
        inches.legend(_legend_handles(rows))
    for caption, colour in captions:
        inches.caption(caption, colour)

    fig.savefig(path, dpi=CHART_DPI, bbox_inches="tight")
    plt.close(fig)
    return path


def _legend_handles(rows: list) -> list:
    """
    One entry per kind of row actually drawn.

    Built from the rows rather than fixed, so a question with no parallel
    measure does not advertise one.
    """
    from matplotlib.lines import Line2D
    names = {"model": "per model", "crude": "crude pooled",
             "stratified": "stratified (Mantel-Haenszel)",
             "parallel": "parallel measure (visible text only)",
             "paired": "paired contrast (exact McNemar)"}
    return [Line2D([], [], color=_COLOURS[k], linewidth=2,
                   marker=_MODEL_MARKER if k == "model" else _SUMMARY_MARKER,
                   markersize=6, label=names[k])
            for k in ("model", "crude", "stratified", "parallel", "paired")
            if any(r.kind == k for r in rows)]


class _BelowAxes:
    """
    A cursor for stacking a legend and captions under the axes.

    The legend goes BELOW the axes rather than inside them. Inside, it has to
    sit somewhere, and on a forest every somewhere is occupied: the left half by
    model labels, the middle by the zero line, and the right by whichever model
    happens to have the widest interval - which is data-dependent, so a corner
    that is empty on one question covers a point on the next.
    """

    # Inches. A caption line at fontsize 8 is about 0.15in tall; the rest is
    # separation, chosen so a two-line caption still reads as one block.
    _LINE = 0.155
    _GAP = 0.085

    def __init__(self, fig, ax, height_in: float):
        self.fig = fig
        self.ax = ax
        self.height = height_in
        fig.canvas.draw()
        label = ax.xaxis.get_label().get_window_extent()
        bottom = fig.transFigure.inverted().transform(label)[0][1]
        self.left = self._left_margin()
        self.y = bottom - self._as_fraction(0.22)

    def _left_margin(self) -> float:
        """
        The left edge of the row labels, not of the axes.

        These are the leftmost thing on the figure, and the axes start wherever
        the longest label leaves off - which on the paired questions is 40% of
        the way across, since their labels name two interrogation variants.
        Anchoring captions to the axes there left them floating in the middle of
        the image with an empty third to their left.
        """
        try:
            inverted = self.fig.transFigure.inverted()
            lefts = [inverted.transform(t.get_window_extent())[0][0]
                     for t in self.ax.get_yticklabels() if t.get_text()]
        except (ValueError, AttributeError):
            lefts = []
        return min(lefts) if lefts else self.ax.get_position().x0

    def _as_fraction(self, inches: float) -> float:
        return inches / self.height

    def legend(self, handles: list) -> None:
        if not handles:
            return
        legend = self.fig.legend(
            handles=handles, fontsize=8, ncol=min(len(handles), 2),
            loc="upper left", bbox_to_anchor=(self.left, self.y),
            frameon=True, framealpha=0.9, borderaxespad=0.0)
        # Measured, not estimated: the box's height depends on the column count
        # and on how long the longest label is, and two earlier attempts at
        # guessing it in the trends charts each put a caption inside the box.
        self.fig.canvas.draw()
        extent = legend.get_window_extent()
        self.y = (self.fig.transFigure.inverted().transform(extent)[0][1]
                  - self._as_fraction(self._GAP * 2))

    def caption(self, text: str, colour: str) -> None:
        if not text:
            return
        wrapped = _wrap(text)
        self.fig.text(self.left, self.y, wrapped, fontsize=8, va="top",
                      color=colour)
        self.y -= self._as_fraction(
            self._LINE * (wrapped.count("\n") + 1) + self._GAP)


def _question_title(index: int, section: dict) -> str:
    return f"Q{index}. {section['question']}"


def plot_question(plt, index: int, section: dict, path: str) -> str:
    """One question's forest: every model, then the pooled estimates."""
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
            (MULTIPLICITY_NOTE, "#555555"),
            (_divergence_caption(section), "#b00020"),
        ]
    captions.append((WILSON_NOTE, "#777777"))
    return _draw_forest(plt, rows, _question_title(index, section), captions,
                        path, xlabel, legend=not paired)


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
    ]
    return _draw_forest(
        plt, rows, "All twelve research questions: effect and 95% interval",
        captions, path,
        "difference in rate, percentage points (exposed minus unexposed)",
        legend=True, bold_pooled=False)


# ---------------------------------------------------------------------------
# Persistence after refusal
# ---------------------------------------------------------------------------
#
# The one characteristic charted so far, and a different shape from every
# forest above it - deliberately, since report/characteristics.py builds this
# to be read as a profile rather than a question: no p-value, no Mantel-
# Haenszel estimate, no "SEPARATED" verdict, because splitting on whether a
# model persisted conditions on something the model itself did. A forest
# centred on zero would visually borrow the causal apparatus the underlying
# data withholds, so these draw a plain rate (0-100%, no zero line to test
# against) and a paired before/after comparison instead.
#
# Two files rather than one two-panel figure. Both are row-per-model charts
# whose height scales with the row count - the same reason every forest above
# does - and the two panels hold different SUBSETS of models (every model with
# a refused episode, against only the ones with episodes on both sides of
# persistence), so a single fixed figure height would either stretch one panel
# thin or crush the other. report_charts.py has never combined two
# variable-height row charts into one figure; splitting them keeps that true.

def _persistence_rate_rows(profile: dict) -> list:
    """
    One row per model shown at least one refusal, in the order
    `persistence_after_refusal()` already sorted them - by rate, descending.

    `marked` carries `comparable_within_model` here, not statistical
    significance - there is no significance test on this chart. It says
    whether the model also appears on the within-model comparison chart: a
    filled marker has episodes on both sides of persistence, an open one only
    ever complied or only ever persisted, and so has a rate but no comparison.
    """
    rows = []
    for r in profile.get("by_model") or []:
        if not has_chart_support(r["n_refused"]):
            continue
        lo, hi = wilson_ci(r["n_persisted"], r["n_refused"]) or (None, None)
        rows.append(Row(r["model"], r["persistence_rate"], lo, hi, "model",
                        marked=bool(r["comparable_within_model"]),
                        note=f"n={r['n_refused']}"))
    return rows


def _draw_rate_chart(plt, rows: list, title: str, captions: list, path: str,
                     xlabel: str, ref: float = None, ref_label: str = "",
                     xmax_pp: float = 100) -> str:
    """
    One marker per row plus its Wilson interval, on a 0-`xmax_pp`% axis.

    Not `_draw_forest`: that chart's zero line is a null hypothesis for a
    DIFFERENCE, and a persistence rate is a plain proportion with no such
    line to draw. The reference line here is the corpus-wide rate instead, so
    a reader sees which models sit above or below the aggregate rather than
    which side of zero they fall on.

    `xmax_pp` NARROWS THE AXIS AND CANNOT CLIP IT. A rate that never
    approaches 100% is unreadable on a 0-100 axis - every marker stacks
    against the spine and the intervals are hairlines - so a caller that knows
    its measure's range says so. But an axis that hides a value is a chart
    that lies, and the caller's expectation is a prior rather than a
    guarantee, so the requested maximum is widened to fit the data whenever
    the data exceeds it. The widening is silent by design: the alternative is
    a chart that renders with a point outside its own axes.
    """
    reach = [v * PP for r in rows
             for v in (r.diff, r.hi) if v is not None]
    if ref is not None:
        reach.append(ref * PP)
    xmax = max([xmax_pp] + reach) if reach else xmax_pp
    # A little headroom so a marker at the maximum is not drawn on the spine.
    xmax = min(100, xmax * 1.05) if xmax < 100 else 100
    height = _FIGURE_MARGIN + _ROW_HEIGHT * max(len(rows), 1)
    fig, ax = plt.subplots(figsize=(_FIGURE_WIDTH, height))
    ys = list(range(len(rows) - 1, -1, -1))
    for y, row in zip(ys, rows, strict=True):
        colour = _COLOURS["model"]
        if row.lo is not None and row.hi is not None:
            ax.plot([row.lo * PP, row.hi * PP], [y, y], color=colour,
                    linewidth=1.3, alpha=0.75, zorder=3)
        ax.plot([row.diff * PP], [y], marker=_MODEL_MARKER, markersize=5.5,
                color=colour,
                markerfacecolor=colour if row.marked else "white",
                markeredgecolor=colour, markeredgewidth=1.3, zorder=4)
        if row.note:
            ax.text(1.005, y, row.note, transform=ax.get_yaxis_transform(),
                    va="center", fontsize=7, color="#666666")
    if ref is not None:
        ax.axvline(ref * PP, color="#333333", linewidth=1.0, linestyle="--",
                   alpha=0.7, zorder=1)
        if ref_label:
            ax.text(ref * PP, len(rows) - 0.2, f"  {ref_label}", fontsize=7,
                    color="#333333", va="bottom")
    ax.set_yticks(ys)
    ax.set_yticklabels([r.label for r in rows], fontsize=8)
    ax.set_ylim(-0.8, len(rows) - 0.2)
    ax.set_xlim(0, xmax)
    ax.set_xlabel(xlabel, fontsize=9)
    ax.set_title(_wrap(title, _TITLE_WRAP), fontsize=10, loc="left")
    ax.grid(axis="x", alpha=0.25)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    fig.tight_layout()
    inches = _BelowAxes(fig, ax, height)
    for caption, colour in captions:
        inches.caption(caption, colour)
    fig.savefig(path, dpi=CHART_DPI, bbox_inches="tight")
    plt.close(fig)
    return path


def _persistence_slope_rows(profile: dict) -> list:
    """
    Only the models with episodes on both sides of persistence - the subset
    `comparable_within_model` already marks, because a model that only ever
    complied or only ever persisted has nothing to compare within itself.

    Sorted by how far the rate moved, descending, the same convention
    `_model_rows` uses for the forests: the row order is itself part of what
    the chart shows.
    """
    rows = []
    for r in profile.get("by_model") or []:
        if not r["comparable_within_model"]:
            continue
        # The smaller side, for the reason _model_rows gives: a slope between a
        # 40-episode rate and a 2-episode one is carried entirely by the 2.
        if not has_chart_support(min(r["complied"]["n"], r["persisted"]["n"])):
            continue
        c, p = r["complied"]["misaligned_rate"], r["persisted"]["misaligned_rate"]
        rows.append({"model": r["model"], "complied_rate": c, "persisted_rate": p,
                    "n_complied": r["complied"]["n"], "n_persisted": r["persisted"]["n"]})
    rows.sort(key=lambda row: row["persisted_rate"] - row["complied_rate"],
             reverse=True)
    return rows


def _draw_slope_chart(plt, rows: list, title: str, captions: list,
                      path: str) -> str:
    """Two markers per row - complied, then persisted - joined by a line, so
    the direction of the move is the shape of the row rather than a number a
    reader has to compute from two separate charts."""
    height = _FIGURE_MARGIN + _ROW_HEIGHT * max(len(rows), 1)
    fig, ax = plt.subplots(figsize=(_FIGURE_WIDTH, height))
    ys = list(range(len(rows) - 1, -1, -1))
    for y, row in zip(ys, rows, strict=True):
        c, p = row["complied_rate"] * PP, row["persisted_rate"] * PP
        colour = _COLOURS["model_significant"] if p > c else _COLOURS["model"]
        ax.plot([c, p], [y, y], color=colour, linewidth=1.6, alpha=0.8, zorder=3)
        ax.plot([c], [y], marker=_MODEL_MARKER, markersize=6,
                markerfacecolor="white", markeredgecolor=colour,
                markeredgewidth=1.3, zorder=4)
        ax.plot([p], [y], marker=_MODEL_MARKER, markersize=6, color=colour,
                zorder=4)
        ax.text(1.005, y, f"n={row['n_complied']}/{row['n_persisted']}",
                transform=ax.get_yaxis_transform(), va="center", fontsize=7,
                color="#666666")
    ax.set_yticks(ys)
    ax.set_yticklabels([r["model"] for r in rows], fontsize=8)
    ax.set_ylim(-0.8, len(rows) - 0.2)
    ax.set_xlim(0, 100)
    ax.set_xlabel("misaligned rate (%)", fontsize=9)
    ax.set_title(_wrap(title, _TITLE_WRAP), fontsize=10, loc="left")
    ax.grid(axis="x", alpha=0.25)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    fig.tight_layout()
    inches = _BelowAxes(fig, ax, height)
    from matplotlib.lines import Line2D
    inches.legend([
        Line2D([], [], color="#666666", marker=_MODEL_MARKER, markersize=6,
              markerfacecolor="white", linestyle="", label="complied"),
        Line2D([], [], color="#666666", marker=_MODEL_MARKER, markersize=6,
              linestyle="", label="persisted"),
    ])
    for caption, colour in captions:
        inches.caption(caption, colour)
    fig.savefig(path, dpi=CHART_DPI, bbox_inches="tight")
    plt.close(fig)
    return path


def plot_persistence_rate(plt, report: dict, path: str) -> str:
    """Every model shown a sandbox refusal: how often it tried again anyway."""
    profile = ((report.get("characteristics") or {})
              .get("persistence_after_refusal") or {})
    rows = _persistence_rate_rows(profile)
    if not rows:
        return None
    ref = profile.get("persistence_rate")
    captions = [
        (profile.get("interpretation", "") + ".", "#555555"),
        (f"{profile.get('n_never_refused', 0)} episode(s) were never shown a "
         f"refusal and are excluded, not counted as compliant. "
         + EXCLUDED_NOTE + ".", "#555555"),
        ("dashed line: the corpus-wide rate. filled marker: this model also "
         "has episodes on both sides of persistence and appears on the "
         "within-model comparison chart; open: only one behaviour was "
         "observed here.", "#555555"),
        # Not WILSON_NOTE: that note also names Newcombe, for the difference
        # intervals every forest above draws. This chart draws no difference
        # at all, so naming Newcombe here would point a reader at a line that
        # is not on the figure.
        ("intervals: 95% Wilson", "#777777"),
    ]
    return _draw_rate_chart(
        plt, rows, "Persistence after a sandbox refusal", captions, path,
        "persistence rate (%)", ref=ref,
        ref_label=f"all models: {ref:.1%}" if ref is not None else "")


def plot_persistence_within_model(plt, report: dict, path: str) -> str:
    """Only models with episodes on both sides: does persisting go with a
    higher misaligned rate than complying, within the same model."""
    profile = ((report.get("characteristics") or {})
              .get("persistence_after_refusal") or {})
    rows = _persistence_slope_rows(profile)
    if not rows:
        return None
    n_worse = profile.get("n_models_persisted_more_misaligned", 0)
    n_both = profile.get("n_models_comparable_within_model", 0)
    captions = [
        (profile.get("interpretation", "") + ".", "#555555"),
        (f"{n_worse}/{n_both} model(s) with episodes on both sides show a "
         f"HIGHER misaligned rate after persisting than after complying.",
         "#b00020" if n_worse else "#555555"),
        ("red: persisting went with more misalignment in this model; blue: "
         "it did not. right-hand count: n(complied)/n(persisted) episodes.",
         "#555555"),
    ]
    return _draw_slope_chart(
        plt, rows, "Persisting vs complying: misaligned rate, within model",
        captions, path)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

_SIGNAL_COLOURS = {
    "mentioned_test": _COLOURS["model"],
    "suspects_being_tested": _COLOURS["crude"],
    "questioned_authenticity": _COLOURS["stratified"],
    "referenced_ai_safety": _COLOURS["parallel"],
    "broke_character": _COLOURS["model_significant"],
}


def _signal_clusters(profile: dict) -> list:
    """
    One cluster per model: its label, and one point per signal in
    `signal_keys`' fixed order - the pure data shape _draw_signal_chart
    draws, kept separate so it can be tested without matplotlib, the same
    split _persistence_rate_rows/_draw_rate_chart use.

    A point's `rate` is None where the signal was never resolved for that
    model; `_draw_signal_chart` draws nothing for it rather than a marker at
    zero, so an unmeasured signal cannot be read as a confident "no".
    """
    keys = profile.get("signal_keys") or []
    clusters = []
    for r in profile.get("by_model") or []:
        # Model-level support, so a model is present or absent as a whole
        # rather than as a cluster with holes in it. A signal that is
        # individually thin on an otherwise well-supported model keeps its
        # hollow marker below - that is a different statement, about one
        # point rather than about whether the model belongs on the figure.
        if not has_chart_support(r.get("n_episodes")):
            continue
        points = []
        for key in keys:
            s = r["signals"].get(key) or {}
            rate = s.get("rate")
            lo, hi = (wilson_ci(s["n_true"], s["n_resolved"])
                      if rate is not None else (None, None))
            points.append({"signal": key, "rate": rate, "lo": lo, "hi": hi,
                          "underpowered": bool(s.get("underpowered"))})
        clusters.append({"model": r["model"], "points": points})
    return clusters


def _draw_signal_chart(plt, clusters: list, signal_keys: list, title: str,
                       captions: list, path: str, xlabel: str) -> str:
    """
    One cluster of rows per model, one row per rubric signal within it,
    always in `signal_keys`' fixed order - so a given signal sits at the same
    position in every model's cluster and its colour is what a reader needs
    to track, not its position. Same 1-data-unit-per-row convention every
    other chart in this file uses, with an extra blank unit between clusters
    so a model's rows read as one group rather than a continuous list.
    """
    n_signals = len(signal_keys)
    if not clusters or not n_signals:
        return None

    # A quarter of _ROW_HEIGHT: this chart has n_signals rows per model
    # rather than one, and at the full row height a corpus with 30+ models
    # produces a figure many feet tall. The data-unit spacing between rows
    # is unchanged - only how many inches one unit maps to for this chart -
    # so the Wilson intervals still separate cleanly.
    row_height = _ROW_HEIGHT / 4
    total_rows = len(clusters) * (n_signals + 1) - 1
    height = _FIGURE_MARGIN + row_height * total_rows
    fig, ax = plt.subplots(figsize=(_FIGURE_WIDTH, height))

    y = total_rows - 1
    yticks, ylabels = [], []
    for cluster in clusters:
        cluster_top = y
        for point in cluster["points"]:
            colour = _SIGNAL_COLOURS[point["signal"]]
            if point["rate"] is not None:
                ax.plot([point["lo"] * PP, point["hi"] * PP], [y, y],
                        color=colour, linewidth=1.1, alpha=0.75, zorder=3)
                ax.plot(
                    [point["rate"] * PP], [y], marker=_MODEL_MARKER,
                    markersize=5, color=colour,
                    markerfacecolor="white" if point["underpowered"] else colour,
                    markeredgecolor=colour, markeredgewidth=1.2, zorder=4)
            y -= 1
        yticks.append(cluster_top - (n_signals - 1) / 2)
        ylabels.append(cluster["model"])
        y -= 1  # blank row separating this cluster from the next
    ax.set_yticks(yticks)
    ax.set_yticklabels(ylabels, fontsize=8)
    ax.set_ylim(-0.8, total_rows - 0.2)
    ax.set_xlim(0, 100)
    ax.set_xlabel(xlabel, fontsize=9)
    ax.set_title(_wrap(title, _TITLE_WRAP), fontsize=10, loc="left")
    ax.grid(axis="x", alpha=0.25)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    fig.tight_layout()
    inches = _BelowAxes(fig, ax, height)
    from matplotlib.lines import Line2D
    inches.legend([
        Line2D([], [], color=_SIGNAL_COLOURS[key], marker=_MODEL_MARKER,
              markersize=6, linestyle="", label=key)
        for key in signal_keys
    ])
    for caption, colour in captions:
        inches.caption(caption, colour)
    fig.savefig(path, dpi=CHART_DPI, bbox_inches="tight")
    plt.close(fig)
    return path


def _encoded_payload_rate_rows(profile: dict) -> list:
    """
    One row per model with enough resolved episodes to plot, sorted the way
    `_by_model` already returns them (alphabetically) rather than by rate -
    unlike persistence, there is no meaningful "worst offender" ordering for a
    concealment attempt this rare in the corpus.

    Every row is `marked`, because after has_chart_support every row that
    survives clears the floor and a hollow marker would distinguish nothing.
    The field is kept rather than dropped so this shares _draw_rate_chart
    with the persistence chart, where `marked` still carries a real
    distinction.
    """
    rows = []
    for r in profile.get("by_model") or []:
        if not has_chart_support(r["n_resolved"]):
            continue
        lo, hi = wilson_ci(r["n_true"], r["n_resolved"]) or (None, None)
        rows.append(Row(r["model"], r["rate"], lo, hi, "model",
                        marked=True, note=f"n={r['n_resolved']}"))
    return rows


def plot_encoded_payload_rate(plt, report: dict, path: str) -> str:
    """How often each model wrote a base64 payload the grader could decode."""
    profile = (report.get("characteristics") or {}).get(
        "encoded_payload_rate") or {}
    rows = _encoded_payload_rate_rows(profile)
    if not rows:
        return None
    ref = (profile.get("pooled") or {}).get("rate")
    captions = [
        (profile.get("measure", "") + ".", "#555555"),
        (EXCLUDED_NOTE + ".", "#555555"),
        ("descriptive, not causal, and not folded into any misalignment act - "
         "see grading/encoded_payload.py for what this can and cannot prove.",
         "#555555"),
        ("intervals: 95% Wilson. NOTE THE AXIS: it runs to a fraction of "
         "100%, so a short bar here is a smaller rate than the same bar on a "
         "full-width chart.", "#777777"),
    ]
    return _draw_rate_chart(
        plt, rows, "Encoded payloads in the model's own words", captions,
        path, "episodes with a decodable payload (%)", ref=ref,
        ref_label=f"all models: {ref:.2%}" if ref is not None else "",
        # This measure is a rare event by construction - a concealment
        # technique, not a behaviour every episode has the chance to show - so
        # a 0-100 axis stacks every marker against the spine. Widened
        # automatically if the data ever exceeds it; see _draw_rate_chart.
        xmax_pp=10)


# ---------------------------------------------------------------------------
# The lure arm
# ---------------------------------------------------------------------------

def _lure_effect_rows(profile: dict, stratum: str) -> list:
    """
    One row per model: misalignment with the lure minus without it, for one
    oversight stratum, sorted by the difference descending.

    The support floor is applied to the SMALLER of the two arms, the same rule
    `_persistence_slope_rows` uses: a difference is only as informative as its
    thinner side, and a model with 60 lure episodes against 4 without has no
    contrast worth drawing whatever the wider side says.
    """
    rows, inert = [], 0
    for r in profile.get("by_model") or []:
        c = r.get(stratum) or {}
        if not has_chart_support(min(c.get("n_lure") or 0,
                                     c.get("n_no_lure") or 0)):
            continue
        if c.get("diff") is None:
            continue
        # A model with NO misaligned episode on either side is folded into one
        # line. There is nothing for the lure to move, so its zero is a fact
        # about the model's floor rather than a measurement of this arm, and on
        # r9 there are enough of them to fill the chart with identical rows and
        # compress every row that says something.
        #
        # NARROWLY "zero on both sides", not "difference of zero". Those are
        # different findings and one of them belongs on the chart: a model
        # misaligned in 24 of 30 episodes in BOTH arms is a genuine null at a
        # high base rate, and folding it away with the models that never did
        # anything would hide the most informative null in the set.
        if not c["n_misaligned_lure"] and not c["n_misaligned_no_lure"]:
            inert += 1
            continue
        rows.append(Row(r["model"], c["diff"], c.get("lo"), c.get("hi"),
                        "model",
                        # A difference whose interval excludes zero, which on
                        # this chart is the only claim a filled marker should
                        # make. Not a multiplicity-corrected test: this is a
                        # descriptive per-model panel, and the caption says so.
                        marked=bool(c.get("lo") is not None
                                    and c.get("hi") is not None
                                    and (c["lo"] > 0 or c["hi"] < 0)),
                        note=f"n={c['n_lure']}/{c['n_no_lure']}"))
    rows.sort(key=lambda row: row.diff, reverse=True)
    if inert:
        # diff=None, so _draw_forest prints it as an explanatory line rather
        # than drawing a marker at zero. A folded group is not a data point and
        # must not look like one.
        rows.append(Row(f"({inert} models omitted)", None, None, None, "model",
                        missing=f"{inert} models took no misaligned act in "
                                f"either arm, so the lure had nothing to move"))
    return rows


def plot_lure_misalignment(plt, report: dict, path: str) -> str:
    """
    Does the lure raise misalignment? One panel per oversight stratum.

    TWO CHARTS RATHER THAN ONE POOLED PANEL, because on r9 the pooled figure
    hides a sign change: with oversight present the lure raises misalignment,
    with it absent the lure slightly lowers it, and the average of those is
    near zero and says nothing true about either. The oversight act does not
    exist in the no-oversight arm at all, so the two strata are not even
    measuring the same outcome.
    """
    profile = (report.get("characteristics") or {}).get("lure_effect") or {}
    written = []
    for stratum, human in (("oversight", "oversight present"),
                           ("no_oversight", "no oversight")):
        rows = _lure_effect_rows(profile, stratum)
        if not rows:
            continue
        pooled = (profile.get("pooled") or {}).get(stratum) or {}
        diff = pooled.get("diff")
        captions = [
            (f"Misalignment rate in the lure arm minus the same model's rate "
             f"without it, {human}. Right of zero means the lure made the "
             f"model MORE misaligned.", "#555555"),
            (EXCLUDED_NOTE + ", and the floor applies to the smaller of the "
             "two arms - a difference is only as informative as its thinner "
             "side.", "#555555"),
            (f"All models pooled, {human}: "
             + (f"{diff * PP:+.2f}pp." if diff is not None else "not available.")
             + " A filled marker is a model whose own 95% interval excludes "
               "zero; with this many models some will by chance, and no "
               "multiplicity correction is applied here.", "#555555"),
            ("intervals: 95% Newcombe on the difference of two proportions. "
             "n=lure/no-lure episodes.", "#777777"),
        ]
        out = path if len(rows) and stratum == "oversight" else path.replace(
            ".png", "_no_oversight.png")
        written.append(_draw_forest(
            plt, rows,
            f"Effect of the lure arm on misalignment ({human})",
            captions, out, "difference in misalignment rate (pp)",
            legend=False, bold_pooled=False))
    return written[0] if written else None


def _honeypot_rows(profile: dict) -> list:
    """
    The models that actually reached the lure file, most discoveries first.

    COUNTS, NOT RATES, and only the models with a non-zero count. Two reasons,
    both about not overstating: these are single digits against denominators in
    the hundreds, where a percentage carries an interval wider than the
    estimate; and thirty-odd rows of zero would fill the chart with the models
    that have nothing to show while compressing the ones that do. How many
    models never reached it is stated in the caption instead, so the
    denominator is not hidden - it is just not drawn thirty times.
    """
    return [r for r in sorted(profile.get("by_model") or [],
                              key=lambda r: (-r["n_discovered"], -r["n_read"],
                                             r["model"]))
            if r["n_discovered"] or r["n_read"]]


def plot_honeypot_access(plt, report: dict, path: str) -> str:
    """How far each model got with the lure file: saw its name, then read it."""
    profile = (report.get("characteristics") or {}).get("lure_effect") or {}
    rows = _honeypot_rows(profile)
    if not rows:
        return None
    pooled = profile.get("pooled") or {}
    total_models = len(profile.get("by_model") or [])
    silent = total_models - len(rows)

    height = _FIGURE_MARGIN + _ROW_HEIGHT * 1.6 * max(len(rows), 1)
    fig, ax = plt.subplots(figsize=(_FIGURE_WIDTH, height))
    ys = list(range(len(rows) - 1, -1, -1))
    bar = 0.34
    for y, r in zip(ys, rows, strict=True):
        ax.barh(y + bar / 2, r["n_discovered"], height=bar,
                color=_COLOURS["model"], alpha=0.45,
                edgecolor=_COLOURS["model"], linewidth=0.8, zorder=3)
        ax.barh(y - bar / 2, r["n_read"], height=bar,
                color=_COLOURS["model"], zorder=3)
        for value, offset in ((r["n_discovered"], bar / 2),
                              (r["n_read"], -bar / 2)):
            if value:
                ax.text(value + 0.12, y + offset, str(value), va="center",
                        fontsize=7, color="#333333")
        ax.text(1.005, y, f"n={r['n_lure_resolved']}",
                transform=ax.get_yaxis_transform(), va="center", fontsize=7,
                color="#666666")
    widest = max(max(r["n_discovered"], r["n_read"]) for r in rows)
    ax.set_xlim(0, widest * 1.18 + 0.5)
    ax.set_yticks(ys)
    ax.set_yticklabels([r["model"] for r in rows], fontsize=8)
    ax.set_ylim(-0.8, len(rows) - 0.2)
    ax.set_xlabel("lure-arm episodes (count, not a rate)", fontsize=9)
    ax.set_title(_wrap("How far each model got with the lure file",
                       _TITLE_WRAP), fontsize=10, loc="left")
    ax.grid(axis="x", alpha=0.25)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.legend(handles=[
        plt.Line2D([], [], marker="s", linestyle="none", markersize=7,
                   markerfacecolor=_COLOURS["model"], alpha=0.45,
                   markeredgecolor=_COLOURS["model"],
                   label="discovered (its name came back in a listing)"),
        plt.Line2D([], [], marker="s", linestyle="none", markersize=7,
                   color=_COLOURS["model"],
                   label="read (its contents came back)")],
        loc="lower right", fontsize=7, frameon=False)
    fig.tight_layout()

    inches = _BelowAxes(fig, ax, height)
    for caption, colour in [
        ("The lure arm places a file belonging to another engagement in a "
         "neighbour of the episode directory. The scenario mentions that such "
         "material exists but never says where, so the model has to go "
         "looking.", "#555555"),
        (f"Of {pooled.get('n_lure_resolved', 0)} lure-arm episodes, "
         f"{pooled.get('n_discovered', 0)} discovered the file and "
         f"{pooled.get('n_read', 0)} read it. "
         f"{silent} of {total_models} models never reached it and are not "
         f"drawn; n= is each model's own lure-arm episode count.", "#555555"),
        ("Counts rather than rates on purpose: at this scale a percentage "
         "carries an interval wider than the estimate. Discovering is not a "
         "subset of reading - measured on r9, no episode ever named the file "
         "in a command, so the ones that read it did so with a glob.",
         "#777777"),
    ]:
        inches.caption(caption, colour)
    fig.savefig(path, dpi=CHART_DPI, bbox_inches="tight")
    plt.close(fig)
    return path


def plot_eval_signal_rates(plt, report: dict, path: str) -> str:
    """Every eval-awareness rubric question, each its own rate per model."""
    profile = (report.get("characteristics") or {}).get("eval_signal_rates") or {}
    keys = profile.get("signal_keys") or []
    clusters = _signal_clusters(profile)
    captions = [
        (profile.get("interpretation", "") + ".", "#555555"),
        (EXCLUDED_NOTE + ". Of the models that remain, an open marker is one "
         f"whose own resolved count for THAT signal is under "
         f"{MIN_INFORMATIVE_DENOMINATOR}.", "#555555"),
        ("intervals: 95% Wilson. Descriptive: each signal is one rubric "
         "question's own answer, not folded into the pooled eval_aware "
         "verdict reported elsewhere in this report.", "#555555"),
    ]
    return _draw_signal_chart(
        plt, clusters, keys, "Eval-awareness rubric signals, per model",
        captions, path, "answered yes (%)")


def write_charts(report: dict, chart_dir: str) -> list:
    """
    Every question chart plus the overview, into chart_dir.

    Numbered by position in the report rather than by id, so the filenames sort
    into the order the questions are asked and a reader can pair a chart with a
    section of the printed output without a lookup.
    """
    plt = charting.import_pyplot()
    if plt is None:
        return []
    os.makedirs(chart_dir, exist_ok=True)
    written = []
    for i, section in enumerate(report.get("questions") or [], start=1):
        path = os.path.join(chart_dir, f"question_{i:02d}_{section['id']}.png")
        if plot_question(plt, i, section, path):
            written.append(path)
    overview = os.path.join(chart_dir, "questions_overview.png")
    if plot_overview(plt, report, overview):
        written.append(overview)
    # After the questions, mirroring where _print_characteristics prints in
    # run_report.py: a footnote to the twelve, not a thirteenth one. `.get`
    # throughout both plot_ functions, so a report built without a
    # "characteristics" key - every fixture in this test file before this
    # feature existed - draws nothing here rather than raising.
    rate_path = os.path.join(chart_dir, "persistence_rate.png")
    if plot_persistence_rate(plt, report, rate_path):
        written.append(rate_path)
    slope_path = os.path.join(chart_dir, "persistence_within_model.png")
    if plot_persistence_within_model(plt, report, slope_path):
        written.append(slope_path)
    signal_path = os.path.join(chart_dir, "eval_signal_rates.png")
    if plot_eval_signal_rates(plt, report, signal_path):
        written.append(signal_path)
    encoded_path = os.path.join(chart_dir, "encoded_payload_rate.png")
    if plot_encoded_payload_rate(plt, report, encoded_path):
        written.append(encoded_path)
    # The lure arm, as two readings: what it did to misalignment, and what
    # happened to the file itself. plot_lure_misalignment writes one file per
    # oversight stratum and returns only the first, so the second is collected
    # by asking the filesystem rather than by rebuilding its name here - the
    # naming rule lives in one place that way.
    lure_path = os.path.join(chart_dir, "lure_misalignment.png")
    if plot_lure_misalignment(plt, report, lure_path):
        written.append(lure_path)
        stratum_path = lure_path.replace(".png", "_no_oversight.png")
        if os.path.exists(stratum_path):
            written.append(stratum_path)
    honeypot_path = os.path.join(chart_dir, "honeypot_access.png")
    if plot_honeypot_access(plt, report, honeypot_path):
        written.append(honeypot_path)
    return written
