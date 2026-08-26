"""
The one entry point into the chart layer.

`write_charts` is what the CLI calls, and the only function here, because
choosing which charts a run writes and what they are named is a separate
decision from how any one of them is drawn. It is also the only place that has
to cope with matplotlib being absent and with a model whose release date was
never recorded: both are worked around and neither is an error.
"""

import os

from .chart_geometry import release_span
from subversionbench import charting

from .chart_style import _family_colours
from .date_charts import _plot_all_family_dates, _plot_family_dates
from .version_charts import _plot_all_families, _plot_family


def write_charts(report: dict, chart_dir: str) -> list:
    """
    One chart per family plus one combined, against version order and again
    against release date. Returns the paths written.

    Empty when matplotlib is absent, which is not an error: the same numbers are
    in the table and the JSON.

    A missing release date is reported and then worked around: the release charts
    drop that model, every other chart is unaffected, and nothing here returns a
    failure. The report has already printed by the time this runs.
    """
    plt = charting.import_pyplot()
    if plt is None:
        return []
    os.makedirs(chart_dir, exist_ok=True)
    metric = report["metric"]
    written = []
    for family in report["families"]:
        # The family key holds a slash, which is a path separator.
        slug = family["family"].replace("/", "_")
        path = os.path.join(chart_dir, f"family_{metric}_{slug}.png")
        written.append(_plot_family(plt, family, report["metric_label"],
                                    report["metric_denominator_label"], path,
                                    metric))
    combined = _plot_all_families(
        plt, report, os.path.join(chart_dir, f"family_{metric}_all.png"))
    if combined:
        written.append(combined)

    span = release_span(report)
    if span is None:
        print("\n!! ERROR: no release date is recorded for any model in a "
              "family, so the release-date charts were skipped. Add them to "
              "RELEASE_DATES in model_releases.py. Every other chart, the "
              "table above and the JSON are unaffected.")
        return written
    # Colours are taken from the same list _plot_all_families enumerates, so a
    # family is the same colour on the combined version chart, the combined
    # release chart and its own release chart.
    drawn = [f for f in report["families"] if f["members"]]
    colours = _family_colours(plt, drawn)
    for family, colour in zip(drawn, colours):
        slug = family["family"].replace("/", "_")
        path = os.path.join(chart_dir, f"release_{metric}_{slug}.png")
        if _plot_family_dates(plt, family, report["metric_label"],
                              report["metric_denominator_label"], colour,
                              span, path, metric):
            written.append(path)
    combined_dates = _plot_all_family_dates(
        plt, report, colours, span,
        os.path.join(chart_dir, f"release_{metric}_all.png"))
    if combined_dates:
        written.append(combined_dates)
    return written
