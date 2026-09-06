"""HOW a chart is drawn, as opposed to what goes on it.

Four shapes: a forest of differences, a rate chart, a slope chart, and
the signal cluster chart. They were spread across three sections of the
file this package replaced, which is why two of them had grown their own
copy of the caption-placement arithmetic.

This module is the patch point for a test that wants to see the rows a
plot built without rendering them: the plot modules call these through
`draw.` so one patch covers every caller.
"""


from .captions import _wrap
from .style import (CHART_DPI, PP, _COLOURS,
                    _FIGURE_MARGIN, _FIGURE_WIDTH, _MODEL_MARKER,
                    _POOLED_KINDS, _ROW_HEIGHT, _SIGNAL_COLOURS,
                    _SUMMARY_MARKER, _TITLE_WRAP)


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
