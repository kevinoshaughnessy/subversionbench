"""
The same rates against the release CALENDAR.

The version charts put position on the x axis, which spaces every release
equally. That is the right axis for the question they answer - does a rate fall
as a family advances - but it hides something the answer depends on: four grok
releases spanning four months and four gemini releases spanning eight draw the
same shape on a positional axis.

These charts put the calendar there instead, so the reader can see how much time
each step actually had. They draw NO LINES. A line between two releases claims a
path between them, and on a calendar axis that claim is stronger than the data
supports - nothing was measured between two release dates, and the gaps are
unequal, so a connecting segment invites reading a slope off empty space. Points
and labels only, plus one straight least-squares fit that carries no p-value.
"""

from datetime import date

from .captions import (_exposure_note, _exposure_range_note,
                       _release_point_name, _slope_label)
from .chart_geometry import (_COMBINED_AXIS_PT, _PER_FAMILY_AXIS_PT,
                             _date_label_layout, _point_label, axis_top)
from .chart_style import (CHART_DPI, FIT_NOTE, WILSON_NOTE_BRACKETS_ONLY)
from .metrics import AWARENESS_METRICS
from .report import _member_release_date


def _date_axis(plt, ax, span: tuple) -> None:
    """
    A calendar x axis over `span`, with ticks matplotlib chooses for the width.

    ConciseDateFormatter rather than a fixed month interval, because the span
    grows by months every time a model is collected and a hand-picked interval
    that reads well over one year crowds over three.
    """
    from matplotlib import dates as mdates
    locator = mdates.AutoDateLocator(minticks=4, maxticks=9)
    ax.xaxis.set_major_locator(locator)
    ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(locator))
    ax.set_xlim(*span)


def _draw_release_fit(ax, fit: dict, colour) -> bool:
    """
    One family's fitted line, dotted, between its own first and last release.

    Dotted rather than solid, and drawn UNDER the markers, because it is a
    summary of the points and not a path between them: nothing was measured
    along it. Silently draws nothing when there is no line to draw - a family
    with one dated release, or several released on one day - since the caption
    and the JSON both already say why.
    """
    if not fit or fit.get("slope_per_month") is None:
        return False
    start = date.fromisoformat(fit["from"]["released"])
    end = date.fromisoformat(fit["to"]["released"])
    ax.plot([start, end],
            [fit["from"]["rate"] * 100, fit["to"]["rate"] * 100],
            linestyle=":", linewidth=1.8, color=colour, alpha=0.9, zorder=2)
    return True


def _dated_members(family: dict) -> list:
    """The members of one family that can be placed on a calendar."""
    return [(m, _member_release_date(m)) for m in family["members"]
            if _member_release_date(m)]


def _plot_family_dates(plt, family: dict, metric_label: str, den_label: str,
                       colour, span: tuple, path: str, metric: str = None):
    """
    One family against the calendar. Points and labels, no line.

    The interval is in the label's brackets rather than as a whisker, because a
    whisker is a line and this chart draws none; the per-family version chart is
    where the bars are. Returns None when nothing in the family has a recorded
    release date, so a caller writes no empty chart.
    """
    dated = _dated_members(family)
    if not dated:
        return None
    rates = [(m["rate"] or 0) * 100 for m, _ in dated]
    top = axis_top(rates)
    # The labels go to the layout, not just the points: these carry the interval
    # as well as the version, so they are several times wider than a marker and
    # the layout cannot tell whether two of them overlap without seeing them.
    labels = {index: f"{_release_point_name(m)}\n{_point_label(m, rate)}"
              for index, ((m, _when), rate) in enumerate(zip(dated, rates))}
    layout = _date_label_layout(
        [(index, when, rate)
         for index, ((_m, when), rate) in enumerate(zip(dated, rates))],
        span, top, labels, fontsize=8.0,
        axis_width_pt=_PER_FAMILY_AXIS_PT)

    fig, ax = plt.subplots(figsize=(9, 4.5))
    _draw_release_fit(ax, family.get("release_fit"), colour)
    # clip_on=False so the newest model, which sits exactly ON the right edge
    # by construction, draws as a whole marker rather than a half one.
    # zorder above the labels. The label layout avoids label-on-label
    # collisions but knows nothing about markers, so a translucent backing box
    # was free to sit on another point: gemini's 3.7 label washed out its 3.6
    # marker. Drawing markers last means the worst case is text partly under a
    # point, which a reader can see, rather than a point that is not there.
    ax.scatter([when for _m, when in dated], rates, s=90, color=colour,
               zorder=6, edgecolors="white", linewidths=0.8, clip_on=False)
    for index, ((_member, when), rate) in enumerate(zip(dated, rates)):
        dx, dy, ha, va = layout[index]
        ax.annotate(labels[index], (when, rate), textcoords="offset points",
                    xytext=(dx, dy), ha=ha, ma=ha, va=va, fontsize=8,
                    color="#333333",
                    # The fitted line crosses the middle of the panel, and
                    # without a backing it draws straight through whichever
                    # label sits there.
                    bbox={"boxstyle": "round,pad=0.15", "fc": "white",
                          "ec": "none", "alpha": 0.85})
    _date_axis(plt, ax, span)
    ax.set_ylim(0, top)
    ax.set_ylabel(f"{metric_label} (%)")
    ax.set_xlabel(f"release date    ({WILSON_NOTE_BRACKETS_ONLY})")
    total = sum(m["n"] or 0 for m, _ in dated)
    title = (f"{family['family']} by release date - {len(dated)} version(s), "
             f"{total} {den_label}")
    ax.set_title(title, fontsize=11)
    fit = family.get("release_fit")
    if fit and fit.get("slope_per_month") is not None:
        # The slope in words as well as in ink, because a dotted line's gradient
        # cannot be read off an axis and this is the number a write-up quotes.
        caption = (f"{FIT_NOTE}: {fit['slope_per_month'] * 100:+.1f} "
                   f"points/month over {fit['span_days']} days")
        # A second LINE rather than a longer one: bbox_inches="tight" grows the
        # canvas to fit whatever is widest, so appending the two-point note
        # inline stretched the figure to half again its width and squeezed the
        # axes into the left of it.
        if fit.get("note"):
            caption += f"\n{fit['note']}"
        # BELOW the axis, not above it. Above, this ran straight through the
        # title - it is a long line, and the title is centred in the same band.
        ax.text(0.0, -0.20, caption, transform=ax.transAxes, fontsize=8,
                color="#555555", va="top")
    # Said on the chart rather than only in the console, because a chart that
    # quietly holds three of a family's four versions misleads on its own.
    below_release = -0.27
    if metric in AWARENESS_METRICS:
        note = _exposure_note([m for m, _ in dated], metric)
        if note:
            ax.text(0.0, below_release, note, transform=ax.transAxes,
                    fontsize=8, va="top", color="#555555")
            below_release -= 0.07 * (note.count("\n") + 1)
    omitted = family["n_members"] - len(dated)
    if omitted:
        # Below the fit caption, which now occupies the first line under the
        # axis, so the two do not print on each other.
        ax.text(0.0, below_release,
                f"! {omitted} version(s) omitted: no release date recorded in "
                f"model_releases.py",
                transform=ax.transAxes, fontsize=8, va="top", color="#b00020")
    ax.grid(axis="y", alpha=0.3)
    ax.grid(axis="x", alpha=0.15)
    fig.tight_layout()
    fig.savefig(path, dpi=CHART_DPI, bbox_inches="tight")
    plt.close(fig)
    return path


def _plot_all_family_dates(plt, report: dict, colours, span: tuple, path: str):
    """
    Every family on one calendar, coloured by family. Points and labels only.

    This is the chart the release dates were recorded for: it puts every model in
    the corpus on a single time axis, so a rate that looks like a family trend
    can be checked against the possibility that it is a date trend running
    through all of them at once.

    The only line is one dotted least-squares fit per family, drawn between that
    family's own first and last release. No connecting lines, for a second reason
    on top of the one above: the families interleave on a calendar in a way they
    cannot on a position axis, so five joined-up families would cross into an
    unreadable mesh, while five straight fits stay legible.
    """
    families = [f for f in report["families"] if _dated_members(f)]
    if not families:
        return None
    top = axis_top([(m["rate"] or 0) * 100
                    for f in families for m, _ in _dated_members(f)])
    points, labels = [], {}
    for index, family in enumerate(families):
        for position, (member, when) in enumerate(_dated_members(family)):
            key = (index, position)
            points.append((key, when, (member["rate"] or 0) * 100))
            labels[key] = _release_point_name(member)
    layout = _date_label_layout(points, span, top, labels, fontsize=7.5,
                                axis_width_pt=_COMBINED_AXIS_PT)

    fig, ax = plt.subplots(figsize=(11, 5.6))
    fitted = 0
    for family, colour in zip(families, colours):
        dated = _dated_members(family)
        fitted += _draw_release_fit(ax, family.get("release_fit"), colour)
        # Semi-transparent because two families can land on the same point and
        # a calendar axis gives no honest way to separate them: grok-4.6 and
        # deepseek-v4-pro-0813 shipped on the same day at 3.33% and 3.36%, and
        # an opaque marker would hide one entirely. Blended, the overlap is at
        # least visible, and both labels are drawn either way.
        ax.scatter([when for _m, when in dated],
                   [(m["rate"] or 0) * 100 for m, _ in dated],
                   s=90, color=colour, zorder=6, edgecolors="white",
                   linewidths=0.8, clip_on=False, alpha=0.85,
                   # The slope goes in the legend, not on the line: five
                   # gradients cannot be read off a shared axis, and a caption
                   # per line would land in the middle of the data.
                   label=f"{family['family']}  "
                         f"({len(dated)} of {family['n_members']} dated"
                         f"{_slope_label(family.get('release_fit'))})")
    for key, when, rate in points:
        dx, dy, ha, va = layout[key]
        colour = colours[key[0] % len(colours)]
        ax.annotate(labels[key], (when, rate),
                    textcoords="offset points", xytext=(dx, dy), ha=ha,
                    va=va, fontsize=7.5, color=colour,
                    # Families interleave on a calendar, so a label with no
                    # backing lands on another family's point - and now on
                    # another family's fitted line, which is why this is more
                    # opaque than the version chart's equivalent.
                    bbox={"boxstyle": "round,pad=0.15", "fc": "white",
                          "ec": "none", "alpha": 0.85})
    _date_axis(plt, ax, span)
    ax.set_ylim(0, top)
    ax.set_xlabel("release date (point labels give the version)")
    ax.set_ylabel(f"{report['metric_label']} (%)")
    total = sum(m["n"] or 0 for f in families for m, _ in _dated_members(f))
    plotted = sum(len(_dated_members(f)) for f in families)
    ax.set_title(f"{report['metric_label']} by release date "
                 f"({len(families)} families, {plotted} models, {total} "
                 f"{report['metric_denominator_label']})", fontsize=12)
    ax.grid(axis="y", alpha=0.3)
    ax.grid(axis="x", alpha=0.15)
    # BELOW the axes rather than beside them. A legend to the right takes its
    # width out of the plotting area, and on a calendar axis that width is
    # months: the same figure gives the data about a quarter more room with the
    # legend underneath. Two columns unless there are few enough families to sit
    # on one row, so the block stays wide and short rather than tall.
    ncol = 1 if len(families) <= 2 else 2 if len(families) <= 6 else 3
    # Far enough below the axes to clear the x-axis LABEL, not just the ticks.
    # At -0.16 the legend's top border cut through it once the notes below grew
    # tall enough for tight_layout to redistribute the figure.
    legend_y = -0.24
    legend = ax.legend(title="family", fontsize=9, title_fontsize=9, ncol=ncol,
                       loc="upper center", bbox_to_anchor=(0.5, legend_y),
                       frameon=True, borderaxespad=0.0)
    # MEASURE the legend rather than estimating its height. Two successive
    # guesses were wrong here - a fraction of a row, then a row height that did
    # not match this font - and each landed a caption inside the legend box.
    # Laying out first and asking matplotlib where the legend actually ended is
    # exact, and stays exact when the family count or font changes.
    fig.tight_layout()
    fig.canvas.draw()
    below = (legend.get_window_extent()
             .transformed(ax.transAxes.inverted()).y0 - 0.03)
    if fitted:
        ax.text(0.5, below, FIT_NOTE, transform=ax.transAxes, fontsize=8,
                ha="center", va="top", color="#444444")
        below -= 0.055
    if report["metric"] in AWARENESS_METRICS:
        note = _exposure_range_note(families, report["metric"])
        if note:
            ax.text(0.5, below, note, transform=ax.transAxes, fontsize=8,
                    ha="center", va="top", color="#555555")
            # The note names the zero-exposure models on a second line, so the
            # next caption has to clear both.
            below -= 0.055 * note.count("\n") + 0.055
    missing = report["data_quality"]["plotted_models_without_release_date"]
    if missing:
        ax.text(0.5, below,
                f"! {len(missing)} model(s) omitted: no release date recorded "
                f"in model_releases.py",
                transform=ax.transAxes, fontsize=8, ha="center", va="top",
                color="#b00020")
    # No second tight_layout: the notes were placed against the measured legend,
    # and re-running it would move the legend out from under them. bbox_inches
    # crops to include everything drawn.
    fig.savefig(path, dpi=CHART_DPI, bbox_inches="tight")
    plt.close(fig)
    return path
