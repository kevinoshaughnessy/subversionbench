"""
Rate against version POSITION - the axis the trend tests actually run on.

Every release is spaced equally here, which is what the question is about: does
the rate fall as the family advances. The cost is that the calendar is hidden -
four releases over four months and four over eight draw the same shape - and
that is what date_charts.py exists to show instead.
"""

from .captions import _exposure_note, _exposure_range_note, _member_labels
from .chart_geometry import (_label_layout, _lower_error, _point_label,
                             _upper_error, axis_top)
from .chart_style import (CHART_DPI, WILSON_NOTE, WILSON_NOTE_WITH_BRACKETS,
                          _family_colours)
from .metrics import AWARENESS_METRICS


def _plot_family(plt, family: dict, metric_label: str, den_label: str,
                 path: str, metric: str = None) -> str:
    """
    One family: the rate against version order, with its Wilson intervals.

    The interval is drawn rather than left to the table because the whole
    question is whether a sequence of rates is falling, and four points with
    overlapping intervals is a different answer from four without. A chart of
    bare point estimates would make every family look decisive.
    """
    members = family["members"]
    xs = list(range(len(members)))
    rates = [(m["rate"] or 0) * 100 for m in members]
    lower = [_lower_error(m) for m in members]
    upper = [_upper_error(m) for m in members]

    fig, ax = plt.subplots(figsize=(max(6, 1.9 * len(members)), 4.5))
    ax.errorbar(xs, rates, yerr=[lower, upper], marker="o", capsize=4,
                linewidth=2, markersize=7, color="#1f77b4",
                ecolor="#8c9fb5", elinewidth=1.4)
    # Scaled to this family's own whiskers, so three steps of a few points each
    # fill the panel instead of hugging the floor of a 0-100 axis. See axis_top
    # for what that costs.
    top = axis_top([rate + up
                    for rate, up in zip(rates, upper, strict=True)])
    # Above the upper WHISKER rather than above the point, or the label sits on
    # the error-bar cap and both become hard to read.
    for x, member, rate, up in zip(xs, members, rates, upper,
                                   strict=True):
        ax.annotate(_point_label(member, rate),
                    (x, min(top * 0.97, rate + up)),
                    textcoords="offset points", xytext=(0, 7), ha="center",
                    fontsize=8)
    ax.set_xticks(xs)
    ax.set_xticklabels(_member_labels(family), fontsize=9)
    ax.set_xlim(-0.4, len(members) - 0.6)
    ax.set_ylim(0, top)
    ax.set_ylabel(f"{metric_label} (%)")
    ax.set_xlabel(f"version, oldest to newest    ({WILSON_NOTE_WITH_BRACKETS})")
    # Padded when the warning below is going to sit above the axes, or the two
    # print on top of each other.
    total = sum(m["n"] or 0 for m in members)
    ax.set_title(f"{family['family']} - {family['n_members']} versions, "
                 f"{total} {den_label}",
                 fontsize=11, pad=20 if family["ordering_ambiguous"] else 6)
    # NO VERDICT CAPTION.
    #
    # It used to sit under the axis, on the reasoning that a reader who never
    # opened the table might take a falling line for a monotone one. Two things
    # were wrong with that. The chart already shows the direction and, now that
    # the intervals are drawn, roughly how firm each step is - so the caption
    # restated what was in front of the reader. And its wording is directional:
    # "consistently RISING - the opposite of falling" reads as a disappointment,
    # which is right for misalignment and wrong for awareness, where a rise with
    # capability is the expected result rather than a failure to improve. A
    # caption that means different things by metric is worse than none.
    #
    # The verdict is unchanged in the console table and in the JSON, where it
    # sits beside the counts it is derived from.
    if family["ordering_ambiguous"]:
        ax.text(0.5, 1.012,
                f"version order depends on --version-style "
                f"{family['version_style']}",
                transform=ax.transAxes, ha="center", fontsize=8, color="#b34700")
    # Which instrument each point was measured with. Only on the awareness
    # metrics: a misalignment rate comes off the act keys and does not move with
    # what the route returned.
    if metric in AWARENESS_METRICS:
        note = _exposure_note(family["members"], metric)
        if note:
            ax.text(0.0, -0.22, note, transform=ax.transAxes, fontsize=8,
                    va="top", color="#555555")
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=CHART_DPI, bbox_inches="tight")
    plt.close(fig)
    return path


def _plot_all_families(plt, report: dict, path: str) -> str:
    """
    Every family on one axis, one line each.

    The x axis is POSITION in the family, not the version number: families run
    on their own numbering - k2.5 against 3.7-flash against v4 - so there is no
    shared version axis to put them on. Position is what they do share, and it
    is the axis the question is actually about, which is whether a rate falls as
    a family advances rather than at which version number it does so.

    Intervals are left off here. Four families of overlapping error bars is
    unreadable, and the per-family charts carry them; this one is for comparing
    SHAPES.
    """
    families = [f for f in report["families"] if f["members"]]
    if not families:
        return None
    colours = _family_colours(plt, families)

    width = max(7, 2.0 * max(f["n_members"] for f in families))
    fig, ax = plt.subplots(figsize=(width, 5.2))
    longest = max(f["n_members"] for f in families)
    # Computed before anything is drawn, because the whiskers have to fit and
    # the label layout needs to know how tall a percentage point is.
    top = axis_top([(m["rate"] or 0) * 100 + _upper_error(m)
                    for f in families for m in f["members"]])
    layout = _label_layout(families, longest, top)

    for index, (family, colour) in enumerate(zip(families, colours,
                                                 strict=True)):
        members = family["members"]
        rates = [(m["rate"] or 0) * 100 for m in members]
        xs = list(range(len(rates)))
        # Dashed where the ordering is a judgement call, so the reader can see
        # which line would move under the other --version-style.
        style = "--" if family["ordering_ambiguous"] else "-"
        # Intervals at a lighter weight than the lines, so four families of them
        # read as uncertainty around the shapes rather than competing with them.
        ax.errorbar(xs, rates,
                    yerr=[[_lower_error(m) for m in members],
                          [_upper_error(m) for m in members]],
                    fmt=style, marker="o", linewidth=2, markersize=7,
                    color=colour,
                    label=f"{family['family']}  "
                          f"(n={sum(m['n'] or 0 for m in members)})",
                    ecolor=colour, elinewidth=1.1, capsize=3, alpha=0.9)
        for x, member, rate in zip(xs, members, rates, strict=True):
            dx, dy = layout[(index, x)]
            ax.annotate(member["version"] or "?", (x, rate),
                        textcoords="offset points", xytext=(dx, dy),
                        ha="left" if dx > 0 else "right", va="center",
                        fontsize=7.5, color=colour,
                        # Four families cross each other, so a label with no
                        # backing has another family's line drawn through it.
                        bbox={"boxstyle": "round,pad=0.15", "fc": "white",
                              "ec": "none", "alpha": 0.72})

    ax.set_xticks(list(range(longest)))
    ax.set_xticklabels([f"v{i + 1}" for i in range(longest)])
    # ONE axis across every family, computed above from the tallest whisker
    # anywhere. Scaling each family separately here would defeat the chart: its
    # whole job is to put families on a common scale, and per-family axes are
    # what the per-family charts are for.
    ax.set_ylim(0, top)
    ax.set_xlabel("position in family, oldest to newest "
                  "(point labels give the version)")
    ax.set_ylabel(f"{report['metric_label']} (%)")
    total = sum(m["n"] or 0 for f in families for m in f["members"])
    ax.set_title(f"{report['metric_label']} by model family "
                 f"({report['n_families']} families, {total} "
                 f"{report['metric_denominator_label']})", fontsize=12)
    ax.grid(axis="y", alpha=0.3)
    ax.legend(title="family", fontsize=9, title_fontsize=9,
              loc="upper left", bbox_to_anchor=(1.01, 1.0))
    # Under the legend rather than under the axis, because that is where a
    # reader decoding the colours is already looking.
    ax.text(1.01, 0.0, WILSON_NOTE, transform=ax.transAxes,
            fontsize=8, va="bottom", color="#444444")
    below_all = -0.16
    if report["metric"] in AWARENESS_METRICS:
        note = _exposure_range_note(families, report["metric"])
        if note:
            ax.text(0.0, below_all, note, transform=ax.transAxes, fontsize=8,
                    va="top", color="#555555")
            below_all -= 0.06 * note.count("\n") + 0.06
    if any(f["ordering_ambiguous"] for f in families):
        ax.text(0.0, below_all, "dashed = version order depends on "
                                "--version-style",
                transform=ax.transAxes, fontsize=8, va="top", color="#b34700")
    fig.tight_layout()
    fig.savefig(path, dpi=CHART_DPI, bbox_inches="tight")
    plt.close(fig)
    return path
