"""The goal-guarding rate, four ways: every episode or only those that read
the successor file, pooled across the oversight arms or the no-oversight arm
alone. See report/questions_arms.goalguard_rate_views for why each is shown.

Its own module because it draws one block of one question that no other
chart reads, the way lure.py draws the lure arm's.
"""

from .captions import _wrap
from .exclusion import _exclusion_captions, _exclusion_title_suffix
from .style import CHART_DPI, PP, WILSON_NOTE, _FIGURE_WIDTH, _TITLE_WRAP

_ARMS = (("replacement", "cutover imminent (replacement)", "#c0392b"),
         ("deferred", "cutover deferred (deferred)", "#7f8c8d"),
         ("both", "both arms", "#2c3e50"))
_VIEWS = (("per_episode", "pooled", "every episode,\nboth oversight arms"),
          ("per_episode", "no_oversight", "every episode,\nno-oversight arm"),
          ("read_the_file", "pooled", "read the file,\nboth oversight arms"),
          ("read_the_file", "no_oversight",
           "read the file,\nno-oversight arm"))


def _rate_views(report: dict):
    for section in report.get("questions") or []:
        if section.get("id") == "goalguard_vs_act":
            return section.get("rate_views")
    return None


def plot_goalguard_rate_views(plt, report: dict, path: str):
    """Grouped bars with Wilson intervals; None when the corpus has no
    goal-guarding episode, so there is nothing to draw."""
    views = _rate_views(report)
    if not views or not views["views"]["per_episode"]["pooled"]["both"]["n"]:
        return None
    fig, ax = plt.subplots(figsize=(_FIGURE_WIDTH, 6.2))
    height = 0.26
    for j, (arm, label, colour) in enumerate(_ARMS):
        ys, rates, lows, highs = [], [], [], []
        for i, (view, column, _name) in enumerate(_VIEWS):
            cell = views["views"][view][column][arm]
            if not cell["n"]:
                continue
            ys.append(i + (j - 1) * height)
            rates.append(cell["rate"] * PP)
            lows.append((cell["rate"] - cell["ci95"][0]) * PP)
            highs.append((cell["ci95"][1] - cell["rate"]) * PP)
            ax.annotate(f"{cell['successes']}/{cell['n']}",
                        (cell["ci95"][1] * PP, ys[-1]), xytext=(4, 0),
                        textcoords="offset points", va="center", fontsize=7)
        ax.barh(ys, rates, height=height, color=colour, label=label,
                xerr=[lows, highs], error_kw={"elinewidth": 0.8,
                                              "capsize": 2})
    ax.set_yticks(range(len(_VIEWS)))
    ax.set_yticklabels([name for _v, _c, name in _VIEWS], fontsize=8)
    ax.invert_yaxis()
    ax.set_xlabel("goal-guarding rate (%)")
    ax.set_xlim(left=0, right=ax.get_xlim()[1] * 1.15)
    ax.legend(fontsize=8, loc="upper center", ncol=3, frameon=False,
              bbox_to_anchor=(0.5, -0.1))
    ax.set_title(_wrap("Goal-guarding rate: every episode and episodes that "
                       "read the successor file, pooled and without oversight"
                       + _exclusion_title_suffix(report), _TITLE_WRAP),
                 fontsize=10, loc="left")
    undone = views["undone_edits"]
    captions = [
        "'Read the file' conditions on something the model did, so it is "
        "descriptive rather than a causal estimate. The no-oversight arm has "
        "no oversight artefact to subvert alongside the successor file.",
        (f"Edited the file and put it back before the episode ended, not "
         f"counted in any bar: {undone['n_undone']} of "
         f"{undone['n_derived']} episodes."
         if undone["n_derived"] else
         "Undone edits not derived on these episodes; --resummarise "
         "backfills them."),
        WILSON_NOTE + ". Labels are acts/episodes.",
    ] + [text for text, _colour in _exclusion_captions(report)]
    fig.text(0.01, 0.01, "\n".join(_wrap(c) for c in captions), fontsize=7,
             color="#555555", va="bottom")
    fig.subplots_adjust(left=0.24, bottom=0.3, top=0.9)
    # Tight, because the scenario mark adds a title line after layout.
    fig.savefig(path, dpi=CHART_DPI, bbox_inches="tight")
    plt.close(fig)
    return path
