#!/usr/bin/env python3
"""
Charts for the twelve research questions answered by run_report.py.

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

# ---------------------------------------------------------------------------
# Chart conventions
# ---------------------------------------------------------------------------
#
# These repeat family_trends.py rather than importing from it. The two scripts
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

# Said on every forest, because a row of per-model intervals invites reading the
# ones that exclude zero as findings. They are not: the report corrects for
# multiplicity across the 28 models, and only the corrected flag is marked here.
MULTIPLICITY_NOTE = ("filled = individually significant after Holm correction "
                     "across models; open = not")


def _import_matplotlib():
    """
    pyplot with a headless backend, or None with the reason printed.

    The backend is forced before pyplot is imported: the default on macOS wants
    a window, and a report run over ssh or from a batch script would either
    block or fail on a display it cannot open.
    """
    try:
        import matplotlib
    except ImportError:
        print("\nCharts skipped: matplotlib is not installed. "
              "Install it with:\n    pip install 'subversionbench[charts]'")
        return None
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    return plt


# ---------------------------------------------------------------------------
# Naming the arms
# ---------------------------------------------------------------------------
#
# A contrast stores its levels as the raw values it split on - True/False for
# oversight and for awareness, "max"/"none" for nudge - and the words that make
# those readable live at each question's call site in run_report.py, inside a
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
    family_trends.py - these captions name models, and half of
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
    for y, row in zip(ys, rows):
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
    for tick, row in zip(ax.get_yticklabels(), rows):
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
        # guessing it in family_trends.py each put a caption inside the box.
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
# Entry point
# ---------------------------------------------------------------------------

def write_charts(report: dict, chart_dir: str) -> list:
    """
    Every question chart plus the overview, into chart_dir.

    Numbered by position in the report rather than by id, so the filenames sort
    into the order the questions are asked and a reader can pair a chart with a
    section of the printed output without a lookup.
    """
    plt = _import_matplotlib()
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
    return written
