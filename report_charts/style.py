"""The conventions every chart here follows: sizes, colours, markers,
and the notes that must appear beside a figure for it to be readable.
"""

from subversionbench.power import MIN_INFORMATIVE_DENOMINATOR


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


# The five rubric signals, coloured from the table above rather than given
# their own palette: a signal and a pooled estimate never appear on one
# chart, so reusing the hues costs nothing and keeps one table to change.
_SIGNAL_COLOURS = {
    "mentioned_test": _COLOURS["model"],
    "suspects_being_tested": _COLOURS["crude"],
    "questioned_authenticity": _COLOURS["stratified"],
    "referenced_ai_safety": _COLOURS["parallel"],
    "broke_character": _COLOURS["model_significant"],
}
