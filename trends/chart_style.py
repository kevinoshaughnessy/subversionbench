"""
Where matplotlib comes from, and what every chart looks like.

Every figure plotted in this package is already in the printed table and in the
JSON, so a chart is a second reading of the same numbers rather than a new
claim. That is why matplotlib is an optional extra and why a missing install
prints a hint and carries on: losing the charts costs presentation, never
analysis. `_import_pyplot` is the one place that decision is taken.

The rest is the shared vocabulary - resolution, family colours, and the standing
notes that say what a whisker or a dotted line is. It lives here rather than in
either plotting module because a family must keep its colour across all four
charts, and a note must read the same on every one of them.
"""


CHART_DPI = 150

# Distinguishable at a glance and stable across runs, so two charts of the same
# corpus put a family in the same colour. Taken by position in the sorted family
# list rather than hashed, because a hash reorders the palette whenever a family
# is added.
_PALETTE = "tab10"


# Wording used on every chart that draws an interval, so the reader is never
# left to guess what the whiskers are.
WILSON_NOTE = "error bars: 95% Wilson intervals"
WILSON_NOTE_WITH_BRACKETS = (
    "error bars and [brackets]: 95% Wilson intervals")
# The release charts draw no error bars, so the brackets are the only interval
# on them and the note has to say so alone.
WILSON_NOTE_BRACKETS_ONLY = "[brackets]: 95% Wilson intervals"

# Every chart that draws a fitted line says what the line is. Without this a
# dotted line through four points reads as a trend TEST, which it is not: the
# test in this file runs on version position, and this is a description of the
# same rates against the calendar.
FIT_NOTE = ("dotted: least-squares fit on release date, weighted by episodes "
            "(descriptive, no p-value)")


def _import_pyplot():
    """
    pyplot with a headless backend, or None with the reason printed.

    The backend is forced before pyplot is imported: the default on macOS is an
    interactive one that wants a window, and a report run over ssh or from a
    batch script would either block or fail on a display it cannot open.
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


# Each lab's own brand colour, for the families that have one. Keyed by
# family_key(), so it survives a rename only if the family key itself does -
# see the same caveat on QUALIFIER_TAGS. A family with no entry here falls
# back to the shared palette rather than failing, since this corpus adds
# families (meta, openai, z-ai, ...) this table was never asked to cover.
_BRAND_COLOURS = {
    "moonshotai/kimi-k": "#007CFF",
    "google/gemini-flash": "#34A853",
    "x-ai/grok": "#000000",
    "qwen/qwen-flash": "#615CED",
    "deepseek/deepseek-flash": "#81858C",
    "deepseek/deepseek-pro": "#22C55E",
}


def _family_colours(plt, families: list):
    """
    One colour per family: its brand colour where one is on file, else the
    shared palette by position among the remaining families.

    Shared by every chart that colours by family so a family keeps its colour
    across them. The unbranded fallback is by position rather than hashed,
    because a hash reorders the whole palette whenever a family is added - and
    it is position AMONG THE UNBRANDED ones specifically, so adding a new
    branded family never reshuffles an unbranded one's colour either.
    """
    cmap = plt.get_cmap(_PALETTE)
    colours = []
    next_fallback = 0
    for family in families:
        brand = _BRAND_COLOURS.get(family["family"])
        if brand is not None:
            colours.append(brand)
        else:
            colours.append(cmap(next_fallback % 10))
            next_fallback += 1
    return colours
