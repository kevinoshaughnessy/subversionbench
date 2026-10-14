"""Misaligned acts by how many turns after first verbalised awareness they
were taken: one chart for the corpus, and one per arm across models.

Its own module because it is the only chart drawn once per arm, so it writes
a variable number of files - see write_charts.
"""

import os

from .captions import _wrap
from .exclusion import _exclusion_captions, _exclusion_title_suffix
from .style import CHART_DPI, _COLOURS, _FIGURE_WIDTH, _TITLE_WRAP

_ACT_COLOURS = {"oversight": _COLOURS["crude"],
                "sandbox": _COLOURS["model"],
                "goalguard": _COLOURS["model_significant"]}


def _draw(plt, report: dict, counts: dict, title: str, path: str) -> str:
    fig, ax = plt.subplots(figsize=(_FIGURE_WIDTH, 5.2))
    gaps = sorted({gap for pairs in counts["by_act"].values()
                   for gap, _n in pairs})
    xs = list(range(gaps[0], gaps[-1] + 1))
    bottom = [0] * len(xs)
    for name, pairs in counts["by_act"].items():
        by_gap = dict(pairs)
        heights = [by_gap.get(x, 0) for x in xs]
        ax.bar(xs, heights, bottom=bottom, width=0.8, label=name,
               color=_ACT_COLOURS.get(name, _COLOURS["parallel"]))
        bottom = [b + h for b, h in zip(bottom, heights, strict=True)]
    ax.axvline(-0.5, color="#555555", linewidth=0.8, linestyle=":")
    ax.set_xlabel("act turn minus first-awareness turn")
    ax.set_ylabel("misaligned acts")
    ax.yaxis.get_major_locator().set_params(integer=True)
    ax.xaxis.get_major_locator().set_params(integer=True)
    ax.legend(fontsize=8, frameon=False, title="act", title_fontsize=8)
    ax.set_title(_wrap(title + _exclusion_title_suffix(report), _TITLE_WRAP),
                 fontsize=10, loc="left")
    captions = [
        f"{counts['n_placed']} acts placed. Not drawn: {counts['n_not_aware']} "
        f"taken in episodes with no verbalised awareness, "
        f"{counts['n_unlocatable']} that no command could be tied to.",
        "Awareness is the keyword measure, the only one with a position; it "
        "under-detects. 0 is the same turn; left of the dotted line, "
        "awareness came only after the act. One count per act, so an episode "
        "with two acts counts twice.",
    ] + [text for text, _colour in _exclusion_captions(report)]
    fig.text(0.01, 0.01, "\n".join(_wrap(c) for c in captions), fontsize=7,
             color="#555555", va="bottom")
    fig.subplots_adjust(bottom=0.27, top=0.88)
    fig.savefig(path, dpi=CHART_DPI, bbox_inches="tight")
    plt.close(fig)
    return path


def plot_act_awareness_gap(plt, report: dict, path: str):
    """The corpus chart at `path` and one per arm beside it, named
    `<stem>_<arm>.png`. Returns every path written, or None when no act could
    be placed; an arm with none is not drawn."""
    block = (report.get("characteristics") or {}).get("act_awareness_gap")
    if not block or not block["pooled"]["n_placed"]:
        return None
    written = [_draw(plt, report, block["pooled"],
                     "Misaligned acts by turns since first verbalised "
                     "awareness, all models and arms", path)]
    stem, ext = os.path.splitext(path)
    for arm in block["by_arm"]:
        if arm["n_placed"]:
            written.append(_draw(
                plt, report, arm,
                f"Misaligned acts by turns since first verbalised awareness, "
                f"all models, arm {arm['arm']}", f"{stem}_{arm['arm']}{ext}"))
    return written
