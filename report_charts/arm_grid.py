"""Every model in every arm on one grid, a cell per (model, arm) holding k of
n: any single-arm comparison is a column, and an arm-specific effect is a
cell that stands out from its row. Counts for the reason report/single_arm.py
gives. Its own module because it is the one chart here not about a named arm.
"""

from .captions import _wrap
from .exclusion import _exclusion_captions, _exclusion_title_suffix
from .single_arm import _EMPTY, COUNT_NOTE, MEASURE_WORDS
from .style import CHART_DPI, _TITLE_WRAP

_CMAPS = {"aware": "Blues", "misaligned": "Reds"}


def _plot_grid(plt, report: dict, measure: str, path: str):
    grid = (report.get("single_arm") or {}).get("grid")
    if not grid or not grid["arms"] or not grid["by_model"]:
        return None
    arms, rows = grid["arms"], grid["by_model"]
    fig, ax = plt.subplots(figsize=(2.6 + 0.62 * len(arms),
                                    1.9 + 0.2 * len(rows)))
    cmap = plt.get_cmap(_CMAPS[measure])
    for y, row in enumerate(rows):
        for x, arm in enumerate(arms):
            cell = row["cells"][arm][measure]
            share = cell["k"] / cell["n"] if cell["n"] else None
            ax.add_patch(plt.Rectangle(
                (x - 0.5, y - 0.5), 1, 1, linewidth=0.4, edgecolor="white",
                facecolor=(_EMPTY if share is None else "white" if not share
                           else cmap(0.15 + 0.75 * share))))
            if cell["n"]:
                ax.text(x, y, f"{cell['k']}/{cell['n']}", ha="center",
                        va="center", fontsize=5,
                        color="white" if share > 0.55 else "#222222")
    ax.set_xlim(-0.5, len(arms) - 0.5)
    ax.set_ylim(len(rows) - 0.5, -0.5)
    ax.set_xticks(range(len(arms)), arms, rotation=60, ha="right", fontsize=6)
    ax.set_yticks(range(len(rows)), [r["model"] for r in rows], fontsize=6)
    ax.tick_params(length=0)
    for side in ax.spines.values():
        side.set_visible(False)
    ax.set_title(_wrap(f"{MEASURE_WORDS[measure].capitalize()}, every model "
                       f"in every arm" + _exclusion_title_suffix(report),
                       _TITLE_WRAP), fontsize=10, loc="left")
    captions = [
        "Arms spelt as the run files' suffixes spell them: nudge first, then "
        "goal-guarding, nooversight and lure where they apply. White: none "
        "of n. Grey: no episode of that model in that arm could be read.",
        COUNT_NOTE,
    ] + [text for text, _colour in _exclusion_captions(report)]
    fig.text(0.01, 0.0, "\n".join(_wrap(c) for c in captions), fontsize=7,
             color="#555555", va="top")
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(path, dpi=CHART_DPI, bbox_inches="tight")
    plt.close(fig)
    return path


def plot_arm_grid_awareness(plt, report: dict, path: str):
    return _plot_grid(plt, report, "aware", path)


def plot_arm_grid_act(plt, report: dict, path: str):
    return _plot_grid(plt, report, "misaligned", path)
