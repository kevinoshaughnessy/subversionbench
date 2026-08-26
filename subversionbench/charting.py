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
