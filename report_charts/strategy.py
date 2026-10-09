"""The strategy recommended: its split in every arm, and how far an imminent
replacement moves it. See report/strategy_pressure.py for why the second is an
effect and the first is not.
"""

from .captions import _wrap
from .exclusion import _exclusion_captions, _exclusion_title_suffix
from .style import CHART_DPI, PP, WILSON_NOTE, _FIGURE_WIDTH, _TITLE_WRAP

_PARTS = (("n_a", "strategy A", "#4c72b0"),
          ("n_b", "strategy B", "#dd8452"),
          ("n_none", "none stated", "#c7c7c7"))
_SUBSETS = (("all", "every episode"), ("no_act", "no misaligned act"))
_B_NOTE = ("Strategy B is also what the client's brief asks for, so a B share "
           "is not a self-preservation rate.")


def _block(report: dict):
    return (report.get("characteristics") or {}).get("strategy_by_arm")


def _finish(plt, fig, report: dict, title: str, captions: list, path: str):
    fig.suptitle(_wrap(title + _exclusion_title_suffix(report), _TITLE_WRAP),
                 fontsize=10, x=0.01, ha="left")
    captions = captions + [t for t, _c in _exclusion_captions(report)]
    fig.text(0.01, 0.01, "\n".join(_wrap(c) for c in captions), fontsize=7,
             color="#555555", va="bottom")
    fig.savefig(path, dpi=CHART_DPI, bbox_inches="tight")
    plt.close(fig)
    return path


def plot_strategy_split(plt, report: dict, path: str):
    """Stacked shares per arm, every episode beside those with no act."""
    block = _block(report)
    if not block or not block["by_arm"]:
        return None
    arms = block["by_arm"]
    fig, axes = plt.subplots(1, 2, sharey=True, figsize=(
        _FIGURE_WIDTH, 2.2 + 0.32 * len(arms)))
    ys = range(len(arms))
    for ax, (subset, label) in zip(axes, _SUBSETS, strict=True):
        left = [0.0] * len(arms)
        for key, name, colour in _PARTS:
            shares = [a[subset][key] / a[subset]["n"] * PP if a[subset]["n"]
                      else 0 for a in arms]
            ax.barh(ys, shares, left=left, color=colour, label=name)
            left = [x + s for x, s in zip(left, shares, strict=True)]
        for y, a in zip(ys, arms, strict=True):
            ax.annotate(f"n={a[subset]['n']}", (PP, y), xytext=(3, 0),
                        textcoords="offset points", va="center", fontsize=7)
        ax.axvline(50, color="#555555", linewidth=0.6, linestyle=":")
        ax.set_xlim(0, PP)
        ax.set_xlabel("share of episodes (%)")
        ax.set_title(label, fontsize=9)
    axes[0].set_yticks(list(ys))
    axes[0].set_yticklabels([a["arm"] for a in arms], fontsize=8)
    axes[0].invert_yaxis()
    axes[0].legend(fontsize=8, frameon=False, ncol=3, loc="upper left",
                   bbox_to_anchor=(0, -0.12 - 0.6 / len(arms)))
    fig.subplots_adjust(left=0.25, wspace=0.18, bottom=0.3, top=0.86)
    return _finish(plt, fig, report,
                   "Strategy recommended, per arm, all models", [
                       "Descriptive: the arms differ in more than one thing. "
                       "'No misaligned act' leaves out the episodes whose "
                       "verdict counts an act.", _B_NOTE], path)


def plot_strategy_replacement_effect(plt, report: dict, path: str):
    """The B share under each goal-guarding arm, and the difference, per
    nudge. None where the corpus has no goal-guarding episode, or none that
    stated a recommendation."""
    block = _block(report)
    effect = block and block["replacement_effect"]
    if not effect:
        return None
    rows = [(nudge, subset, label, cells[subset])
            for nudge, cells in effect["by_nudge"].items()
            for subset, label in _SUBSETS]
    if not any(cell[arm]["ci95"] for *_r, cell in rows
               for arm in ("replacement", "deferred")):
        return None
    fig, (shares, diffs) = plt.subplots(1, 2, sharey=True, figsize=(
        _FIGURE_WIDTH, 2.6 + 0.45 * len(rows)))
    labelled = set()
    for y, (_n, _s, _l, cell) in enumerate(rows):
        for offset, arm, colour in ((-0.15, "replacement", "#c0392b"),
                                    (0.15, "deferred", "#7f8c8d")):
            c = cell[arm]
            if c["ci95"]:
                rate = c["b_share_of_stated"] * PP
                shares.errorbar(rate, y + offset, fmt="o", color=colour,
                                xerr=[[rate - c["ci95"][0] * PP],
                                      [c["ci95"][1] * PP - rate]],
                                capsize=2,
                                label=None if arm in labelled else arm)
                labelled.add(arm)
        if cell["diff"] is not None:
            d = cell["diff"] * PP
            diffs.errorbar(d, y, fmt="D", color="#2c3e50",
                           xerr=[[d - cell["ci95"][0] * PP],
                                 [cell["ci95"][1] * PP - d]], capsize=2)
            diffs.annotate(f"{d:+.1f}pp", (cell["ci95"][1] * PP, y),
                           xytext=(4, 0), textcoords="offset points",
                           va="center", fontsize=7)
    shares.set_yticks(range(len(rows)))
    shares.set_yticklabels([f"nudge={n}, {label}" for n, _s, label, _c in rows],
                           fontsize=8)
    shares.invert_yaxis()
    shares.set_xlim(0, PP)
    shares.set_xlabel("strategy B, % of stated")
    shares.legend(fontsize=8, frameon=False, title="cutover",
                  title_fontsize=8)
    diffs.axvline(0, color="#555555", linewidth=0.8)
    diffs.set_xlabel("replacement minus deferred (pp)")
    fig.subplots_adjust(left=0.3, wspace=0.12, bottom=0.34, top=0.84)
    return _finish(plt, fig, report,
                   "Does an imminent replacement move the recommendation "
                   "toward strategy B? All models, goal-guarding arms", [
                       "The two arms differ only in whether the cutover "
                       "lands this cycle, so the difference is an effect. "
                       "With no nudge the deferred arm's memo still carries "
                       "the standby engine and only its note defers the "
                       "cutover; the withdrawal is complete under the strong "
                       "nudge.", _B_NOTE,
                       WILSON_NOTE + "; per-model differences are in the "
                       "JSON report, too thin to draw."], path)
