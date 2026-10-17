"""Each counted act by its purpose, per model: one panel per act, each purpose
split into the episodes that took this act alone and those that took the
other act too (D7). Beside act_forms.png, which draws the same acts by form.

Purpose is per act, so an episode that took both acts is drawn once in each
panel, and the caption says the panels are not to be added.
"""

from .captions import _wrap
from .exclusion import _exclusion_captions, _exclusion_title_suffix
from .style import CHART_DPI, _COLOURS, _FIGURE_WIDTH, _TITLE_WRAP

UNLABELLED = "unlabelled"
_PURPOSE_COLOURS = {"evade": _COLOURS["model_significant"],
                    "protect_goals": _COLOURS["model"],
                    "test": _COLOURS["stratified"],
                    "mistake": _COLOURS["parallel"],
                    "unclear": "#a0a0a0",
                    UNLABELLED: "#dddddd"}
_WITH_OTHER_ALPHA = 0.45


def _segments(acts: dict, name: str, purposes: list) -> list:
    """(purpose, alone, with the other act) for one model's act."""
    counts = acts.get(name) or {}
    cells = counts.get("by_purpose") or {}
    out = []
    for p in purposes:
        if p == UNLABELLED:
            out.append((p, counts["by_source"][UNLABELLED], 0))
            continue
        cell = cells.get(p) or {"act": 0, "hand": 0, "with_other_act": 0}
        total = cell["act"] + cell["hand"]
        out.append((p, total - cell["with_other_act"], cell["with_other_act"]))
    return out


def _draw_panel(ax, block: dict, name: str, purposes: list) -> None:
    rows = [(r["model"], r["acts"]) for r in block["by_model"]
            if name in r["acts"]]
    ys = list(range(len(rows)))
    left = [0] * len(rows)
    by_row = [_segments(acts, name, purposes) for _m, acts in rows]
    for i, p in enumerate(purposes):
        segs = [row[i] for row in by_row]
        colour = _PURPOSE_COLOURS.get(p, _COLOURS["model"])
        for part, alpha, suffix in ((1, 1.0, ""),
                                    (2, _WITH_OTHER_ALPHA, ", with the other act")):
            widths = [s[part] for s in segs]
            ax.barh(ys, widths, left=left, height=0.7, color=colour,
                    alpha=alpha, label=p + suffix if any(widths) else None)
            left = [a + b for a, b in zip(left, widths, strict=True)]
    ax.set_yticks(ys, [m for m, _a in rows], fontsize=7)
    ax.invert_yaxis()
    ax.xaxis.get_major_locator().set_params(integer=True)
    ax.set_xlim(0, max(left) * 1.04)
    pooled = block["pooled"][name]
    src = pooled["by_source"]
    ax.set_title(f"{name}: {pooled['n_acts']} acts - {src['act']} settled by "
                 f"the act, {src['hand']} hand-labelled, {src['unlabelled']} "
                 f"unlabelled", fontsize=9, loc="left")
    ax.legend(fontsize=7, frameon=False, loc="lower right")


def _order_caption(block: dict) -> list:
    out = []
    for name, pooled in block["pooled"].items():
        both = pooled["with_other_act"]
        if both["n"]:
            out.append(f"{name}: {both['n']} of its acts came in an episode "
                       f"that took the other act too; the other act came "
                       f"first in {both['other_first']}, and both were made "
                       f"in one command in {both['same_command']}. The order "
                       f"is descriptive, not evidence of purpose.")
    return out


def plot_act_purposes(plt, report: dict, path: str):
    """The chart at `path`, or None when no episode took a formed act."""
    block = (report.get("characteristics") or {}).get("act_purposes")
    names = list((block or {}).get("pooled") or {})
    if not names:
        return None
    present = {p for n in names for p in block["pooled"][n]["by_purpose"]}
    if any(block["pooled"][n]["by_source"][UNLABELLED] for n in names):
        present.add(UNLABELLED)
    purposes = ([p for p in _PURPOSE_COLOURS if p in present]
                + sorted(present - set(_PURPOSE_COLOURS)))
    sizes = [sum(1 for r in block["by_model"] if n in r["acts"])
             for n in names]
    heights = [max(1.6, 0.32 * k + 0.9) for k in sizes]
    fig, axes = plt.subplots(len(names), 1, squeeze=False,
                             figsize=(_FIGURE_WIDTH, sum(heights) + 1.8),
                             gridspec_kw={"height_ratios": heights})
    for ax, name in zip(axes[:, 0], names, strict=True):
        _draw_panel(ax, block, name, purposes)
    axes[-1, 0].set_xlabel("acts")
    fig.suptitle(_wrap("Misaligned acts by their purpose, per model"
                       + _exclusion_title_suffix(report), _TITLE_WRAP),
                 fontsize=10, x=0.01, ha="left")
    captions = [
        "Purpose is read off the act wherever the act settles it, else from "
        "a blind hand label; it never changes a count. Paler segments are "
        "acts in episodes that took the other act as well: such an episode "
        "is drawn in both panels, so the panels must not be added.",
    ] + _order_caption(block) + [
        text for text, _colour in _exclusion_captions(report)]
    fig.text(0.01, 0.0, "\n".join(_wrap(c) for c in captions), fontsize=7,
             color="#555555", va="top")
    fig.tight_layout(rect=(0, 0.02, 1, 0.97))
    fig.savefig(path, dpi=CHART_DPI, bbox_inches="tight")
    plt.close(fig)
    return path
