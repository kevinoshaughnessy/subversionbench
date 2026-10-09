"""
Where pyplot comes from, for everything in this repository that draws.

WHY THIS IS IN THE PACKAGE AND NOT BESIDE ONE OF THE CHART SCRIPTS
------------------------------------------------------------------
Three places draw: `trends/`, `report_charts.py` and `sad_oversight.py`. All
three had their own copy of this function, two of them character-for-character
identical and the third differing only in whether it said "Chart" or "Charts".
Three copies of the decision "what happens when the optional dependency is
missing" is three chances to answer it differently.

It cannot live in `trends/` - `report_charts.py` is imported by `report/`, and
`trends/` imports `report/`, so a chart script reaching into `trends` for this
would close a cycle. `subversionbench` is the one module all three already
depend on, so it is the only place that works.

WHY THE BACKEND IS FORCED BEFORE THE IMPORT
-------------------------------------------
The default backend on macOS is an interactive one that wants a window, so a
report run over ssh or from a batch script would either block or fail on a
display it cannot open. `matplotlib.use("Agg")` has to happen between importing
matplotlib and importing pyplot, which is why this is a function and not an
import line.

WHY A MISSING INSTALL IS NOT AN ERROR
-------------------------------------
Every figure any of these scripts plots is already in a printed table and in a
JSON file, so a chart is a second reading of the same numbers rather than a new
claim. Losing it costs presentation and no analysis. That is why matplotlib is
an extra rather than a dependency, and why this returns None with a hint instead
of raising.

Call it through the module - `charting.import_pyplot()`, never
`from .charting import import_pyplot` - so the suite has exactly one patch
point. See test_init.py, which enforces this.
"""

import contextlib


def import_pyplot(what: str = "Charts"):
    """
    pyplot with a headless backend, or None with the reason printed.

    `what` names the thing being skipped, because the scripts differ: two draw a
    set of charts and one draws a single chart, and "Charts skipped" is wrong for
    the third. It is the only thing that ever varied between the three copies.
    """
    try:
        import matplotlib
    except ImportError:
        print(f"\n{what} skipped: matplotlib is not installed. "
              "Install it with:\n    pip install 'subversionbench[charts]'")
        return None
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    return plt


# The caption block under a chart.
#
# Space is reserved for the captions FIRST, then they are laid into it from the
# top down. Writing them at a fixed y and then calling tight_layout with a
# reserved fraction leaves the axes floating well above the text, because the
# two numbers are computed independently and neither knows the other.
#
# MEASURED IN INCHES, NOT IN FIGURE FRACTION
# -------------------------------------------
# tight_layout's rect is a fraction of the whole figure, and a figure's height
# is not fixed - three stacked panels are 2.7x the height of the three-across
# layout this reservation was first tuned against. A caption written to occupy
# a FRACTION of the figure grows with it: the panels went from 5.4in tall to
# 14.5in and the same fraction opened a gap of dead space between the last
# x-axis label and the first line of text. A line of 7.5pt caption text is the
# same physical height regardless of how tall the figure around it is, so the
# reservation is sized in inches and only converted to a fraction at the end,
# against this figure's ACTUAL height.
_CAPTION_LINE_IN = 0.16
_CAPTION_GAP_IN = 0.19
_CAPTION_TOP_IN = 0.11
_CAPTION_POINTS = 7.5
_CAPTION_COLOUR = "#555555"


def caption_below(fig, captions, wrap) -> None:
    """
    Reserve room under the axes for `captions`, and write them there.

    THREE COPIES BEFORE THIS FUNCTION EXISTED, and this module's docstring
    above describes the same defect one layer down: the same three places that
    each had their own pyplot import each had their own copy of this
    arithmetic, five magic numbers included, and the comment explaining why it
    is measured in inches sat over only one of them. A figure whose captions
    are placed by a fourth copy of these numbers is a figure that will drift
    away from the others the first time one of them is tuned.

    `wrap` is the caller's own folding function: the wrap width and the
    hyphen rules differ by package and are not this function's business.
    Empty captions are dropped rather than reserved for - a blank line of
    reserved space is dead space no reader can see the purpose of.
    """
    height_in = fig.get_size_inches()[1]
    wrapped = [wrap(c) for c in captions if c]
    lines = sum(w.count("\n") + 1 for w in wrapped)
    reserved = ((_CAPTION_LINE_IN * lines + _CAPTION_GAP_IN * len(wrapped))
                / height_in)
    fig.tight_layout(rect=(0, reserved, 1, 1))
    y = reserved - _CAPTION_TOP_IN / height_in
    for text in wrapped:
        fig.text(0.01, y, text, fontsize=_CAPTION_POINTS, va="top",
                 color=_CAPTION_COLOUR)
        y -= (_CAPTION_LINE_IN * (text.count("\n") + 1)
              + _CAPTION_GAP_IN * 0.6) / height_in


# The prefix every corpus directory carries, stripped so that the chart
# directory is named for the rollout rather than for the naming convention.
_CORPUS_PREFIX = "eval_results_"


@contextlib.contextmanager
def scenario_marked(scenario):
    """Every figure saved inside this block names its scenario in its title.

    A chart read away from its directory said nothing about which scenario
    it came from, and the mainline and goal-guarding corpora draw charts of
    the same names with the same composite outcome. Marked at the one point
    every chart passes through - saving it - rather than at each of the
    dozen places a title is set, so a chart added later cannot be drawn
    without it.

    The mark leads the first axes title found, on a line of its own, so it
    takes the title's position whatever that chart aligns its title to.
    None marks nothing: a report with no rows has no scenario to name.

    ponytail: wraps Figure.savefig for the block's duration, so it is not
    safe to draw two corpora's charts concurrently in one process; the
    upgrade is passing the scenario to every draw function.
    """
    try:
        from matplotlib.figure import Figure
    except ImportError:
        # The charts extra is absent, so nothing will be drawn to mark -
        # import_pyplot says so to the caller inside the block.
        Figure = None
    if not scenario or Figure is None:
        yield
        return
    original = Figure.savefig
    # "Mainline and goal-guarding scenarios": a mark naming two is plural.
    mark = f"{scenario} scenario" + ("s" if " and " in scenario else "")

    def savefig(fig, *args, **kwargs):
        # A figure-wide title heads the chart, so it takes the mark ahead of
        # any panel's: replacing it lost a chart's whole title, and marking
        # the first panel instead put the scenario over one panel of two.
        suptitle = getattr(fig, "_suptitle", None)
        if suptitle is not None and suptitle.get_text():
            suptitle.set_text(f"{mark}\n{suptitle.get_text()}")
            return original(fig, *args, **kwargs)
        # The Text objects themselves rather than set_title, which would reset
        # each chart's own font size to the default. `_left_title` is private
        # but has been the left title's home for as long as `loc` has existed.
        for ax in fig.axes:
            for text in (getattr(ax, "_left_title", None), ax.title):
                if text is not None and text.get_text():
                    text.set_text(f"{mark}\n{text.get_text()}")
                    return original(fig, *args, **kwargs)
        fig.suptitle(mark, x=0.01, ha="left", fontsize=10)
        return original(fig, *args, **kwargs)

    Figure.savefig = savefig
    try:
        yield
    finally:
        Figure.savefig = original


def default_chart_dir(output_dir: str, suffix: str = "") -> str:
    """Where charts go when the caller did not say: charts/<rollout><suffix>.

    OUTSIDE THE CORPUS, and that is the point.
    ------------------------------------------
    Charts used to default to `charts/` inside the results directory they were
    drawn from, which put derived pictures inside the thing that holds the
    episodes. Two consequences, both real:

      - `zip.sh` archives every `eval_results_*` directory whole, so every
        published archive carried a set of PNGs regenerable from the JSON
        beside them, in an artefact whose whole purpose is the transcripts;
      - a reader comparing two rollouts had to open two directories that each
        called their charts the same thing, because the only thing telling
        `family_misaligned_all.png` of r9 from r10's was which corpus it sat
        in.

    One `charts/` beside the corpora, with a subdirectory per rollout, answers
    both: the archive holds only what cannot be regenerated, and every chart in
    the project is reachable from one place without being pooled into one
    namespace.

    BESIDE THE CORPUS RATHER THAN AT A FIXED ROOT. Derived from the output
    directory's own parent, so a corpus read from somewhere else - a scratch
    copy, a mounted archive - puts its charts beside itself instead of writing
    into the working tree of whoever happens to be running.

    `suffix` is for a report that holds different numbers under the same
    filenames, which is what the exclusion flags produce.
    """
    import os

    output_dir = str(output_dir).rstrip(os.sep)
    corpus = os.path.basename(os.path.abspath(output_dir))
    if corpus.startswith(_CORPUS_PREFIX):
        corpus = corpus[len(_CORPUS_PREFIX):]
    parent = os.path.dirname(os.path.abspath(output_dir))
    return os.path.join(parent, "charts", corpus + suffix)


def grader_chart_dir(chart_dir: str, grader: str) -> str:
    """One grader's charts: a subdirectory of `chart_dir` named for it.

    Every grader's charts share one set of filenames, so a directory per grader
    is what keeps charts/r10/gpt-6-sol/ from being overwritten by
    charts/r10/claude-opus-5/. A "/" in an OpenRouter ID becomes "_", the
    spelling the regrade files already use, rather than a nested directory.
    """
    import os

    return os.path.join(chart_dir, grader.replace("/", "_"))
