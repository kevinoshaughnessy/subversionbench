"""
The overall rate drawn three ways: ranked with its interval, ranked with
each act's share of it, and as a model-by-act grid.

The family trend charts for the overall rate are not here: trends.charts
draws them from the same document, since it is shaped like any metric's.
"""

import os

from subversionbench import charting

from .chart_style import CHART_DPI

_ACT_COLOURS = {"oversight": "#2c7fb8", "sandbox": "#f39c12",
                "goalguard": "#c0392b"}
_EFFECTIVE_NOTE = ("error bars: approximate 95% Wilson intervals on effective "
                   "counts (Kish), since the rate is a mean of three rates")


def _ranked(report: dict) -> list:
    """(model, entry) by overall rate, highest at the top of the chart."""
    return sorted(report["overall_by_model"].items(),
                  key=lambda kv: (kv[1]["rate"], kv[0]))


def _act_labels(report: dict) -> dict:
    from report.pooling import _ACT_LABELS
    return {name: _ACT_LABELS[name] for name in report["act_sources"]}


def _caption(fig, report: dict, *lines: str) -> None:
    excluded = len(report["excluded_models"])
    arms = report["matched_arms"]
    text = list(lines) + [
        f"Each act from its own scenario's corpus, over the episodes where it "
        f"was possible; nudge {'/'.join(arms['nudges'])}, lure off. "
        f"{excluded} model(s) without all three acts are not shown."]
    fig.text(0.01, 0.01, "\n".join(text), fontsize=7, color="#555555",
             va="bottom")


def _margins(fig, height: float) -> None:
    """Fixed margins in inches, so a corpus with more models grows the plot
    rather than the white space around it."""
    fig.subplots_adjust(left=0.3, top=1 - 0.75 / height,
                        bottom=1.0 / height)


def _plot_ranked(plt, report: dict, path: str) -> str:
    rows = _ranked(report)
    fig, ax = plt.subplots(figsize=(9.5, 1.6 + 0.28 * len(rows)))
    ys = range(len(rows))
    rates = [e["rate"] * 100 for _m, e in rows]
    lows = [(e["rate"] - e["ci95"][0]) * 100 for _m, e in rows]
    highs = [(e["ci95"][1] - e["rate"]) * 100 for _m, e in rows]
    ax.barh(ys, rates, color="#2c3e50", xerr=[lows, highs],
            error_kw={"elinewidth": 0.8, "capsize": 2})
    ax.set_yticks(list(ys))
    ax.set_yticklabels([m for m, _e in rows], fontsize=8)
    ax.set_xlabel("overall misalignment rate (%)", fontsize=9)
    ax.set_xlim(left=0)
    ax.grid(axis="x", alpha=0.2)
    ax.set_title(f"Overall misalignment rate by model ({len(rows)} models)",
                 fontsize=11)
    _caption(fig, report, f"Overall = {report['metric_definition']}.",
             _EFFECTIVE_NOTE + ".")
    _margins(fig, 1.6 + 0.28 * len(rows))
    fig.savefig(path, dpi=CHART_DPI, bbox_inches="tight")
    plt.close(fig)
    return path


def _plot_ranked_by_act(plt, report: dict, path: str) -> str:
    rows = _ranked(report)
    labels = _act_labels(report)
    fig, ax = plt.subplots(figsize=(9.5, 1.6 + 0.28 * len(rows)))
    ys = list(range(len(rows)))
    left = [0.0] * len(rows)
    k = len(labels)
    for name, label in labels.items():
        widths = [report["acts_by_model"][m][name]["rate"] / k * 100
                  for m, _e in rows]
        ax.barh(ys, widths, left=left, color=_ACT_COLOURS.get(name),
                label=f"{label} rate / {k}")
        left = [a + b for a, b in zip(left, widths, strict=True)]
    ax.set_yticks(ys)
    ax.set_yticklabels([m for m, _e in rows], fontsize=8)
    ax.set_xlabel("overall misalignment rate (%)", fontsize=9)
    ax.set_xlim(left=0)
    ax.grid(axis="x", alpha=0.2)
    ax.legend(fontsize=8, loc="lower right")
    ax.set_title("Overall misalignment rate by model, split by act",
                 fontsize=11)
    _caption(fig, report, f"Each segment is one act's rate divided by {k}, "
             "so the segments sum to the overall rate.")
    _margins(fig, 1.6 + 0.28 * len(rows))
    fig.savefig(path, dpi=CHART_DPI, bbox_inches="tight")
    plt.close(fig)
    return path


def _plot_grid(plt, report: dict, path: str) -> str:
    rows = list(reversed(_ranked(report)))
    labels = _act_labels(report)
    columns = list(labels) + ["overall"]
    values = [[report["acts_by_model"][m][c]["rate"] if c != "overall"
               else e["rate"] for c in columns] for m, e in rows]
    fig, ax = plt.subplots(figsize=(9.5, 1.8 + 0.3 * len(rows)))
    image = ax.imshow([[v * 100 for v in row] for row in values],
                      cmap="Reds", aspect="auto", vmin=0)
    for i, (model, entry) in enumerate(rows):
        for j, column in enumerate(columns):
            if column == "overall":
                text = f"{entry['rate']:.1%}"
            else:
                cell = report["acts_by_model"][model][column]
                text = f"{cell['rate']:.1%}  {cell['successes']}/{cell['n']}"
            dark = values[i][j] > 0.6 * max(max(r) for r in values)
            ax.text(j, i, text, ha="center", va="center", fontsize=7,
                    color="white" if dark else "black")
    ax.set_xticks(range(len(columns)))
    ax.set_xticklabels([labels.get(c, c) for c in columns], fontsize=8)
    ax.xaxis.tick_top()
    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels([m for m, _e in rows], fontsize=8)
    fig.colorbar(image, ax=ax, fraction=0.03, pad=0.02).set_label(
        "rate (%)", fontsize=8)
    ax.set_title("Each act's rate and the overall rate, by model",
                 fontsize=11, pad=24)
    _caption(fig, report, "Cells give rate and acts/episodes; the overall "
             "column is the equal-weight mean of the three.")
    fig.subplots_adjust(left=0.3, top=1 - 1.1 / (1.8 + 0.3 * len(rows)),
                        bottom=0.9 / (1.8 + 0.3 * len(rows)))
    fig.savefig(path, dpi=CHART_DPI, bbox_inches="tight")
    plt.close(fig)
    return path


OVERALL_CHARTS = (("overall_ranked.png", _plot_ranked),
                  ("overall_ranked_by_act.png", _plot_ranked_by_act),
                  ("overall_acts_grid.png", _plot_grid))


def write_overall_charts(report: dict, chart_dir: str) -> list:
    """The three overall charts, each naming the scenarios it draws on; empty
    without matplotlib or without a model to draw."""
    plt = charting.import_pyplot()
    if plt is None or not report["overall_by_model"]:
        return []
    os.makedirs(chart_dir, exist_ok=True)
    with charting.scenario_marked(report.get("scenario")):
        return [plot(plt, report, os.path.join(chart_dir, name))
                for name, plot in OVERALL_CHARTS]
