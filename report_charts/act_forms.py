"""Each counted act by the form it took, per model: one panel per act, the
forms stacked so the exploitative shape stays visible beside the rest (D7)."""

from .captions import _wrap
from .exclusion import _exclusion_captions, _exclusion_title_suffix
from .style import CHART_DPI, _COLOURS, _FIGURE_WIDTH, _TITLE_WRAP

_FORM_COLOURS = {"persisted": _COLOURS["model_significant"],
                 "undone_exploited": _COLOURS["crude"],
                 "undone": _COLOURS["parallel"],
                 "attempted": "#a0a0a0"}


def _took(block: dict, name: str) -> list:
    """(model, counts) for the models that took `name` in any form."""
    return [(r["model"], r["acts"][name]) for r in block["by_model"]
            if any(r["acts"].get(name, {}).get(f) for f in block["forms"])]


def plot_act_forms(plt, report: dict, path: str):
    """The chart at `path`, or None when no episode took a formed act."""
    block = (report.get("characteristics") or {}).get("act_forms")
    panels = [(name, _took(block, name)) for name in (block or {}).get(
        "pooled", {})] if block else []
    panels = [(name, rows) for name, rows in panels if rows]
    if not panels:
        return None
    heights = [max(1.6, 0.32 * len(rows) + 0.9) for _n, rows in panels]
    fig, axes = plt.subplots(len(panels), 1, squeeze=False,
                             figsize=(_FIGURE_WIDTH, sum(heights) + 1.6),
                             gridspec_kw={"height_ratios": heights})
    for ax, (name, rows) in zip(axes[:, 0], panels, strict=True):
        ys = list(range(len(rows)))
        left = [0] * len(rows)
        for form in block["forms"]:
            widths = [counts[form] for _m, counts in rows]
            ax.barh(ys, widths, left=left, height=0.7, label=form,
                    color=_FORM_COLOURS.get(form, _COLOURS["model"]))
            left = [a + b for a, b in zip(left, widths, strict=True)]
        ax.set_yticks(ys, [m for m, _c in rows], fontsize=7)
        ax.invert_yaxis()
        ax.xaxis.get_major_locator().set_params(integer=True)
        ax.set_xlim(0, max(left) * 1.04)
        pooled = block["pooled"][name]
        ax.set_title(f"{name}: of {pooled['n_observable']} episodes that "
                     f"could take it", fontsize=9, loc="left")
    axes[0, 0].legend(fontsize=7, frameon=False, ncol=len(block["forms"]),
                      loc="lower right", bbox_to_anchor=(1.0, 1.08))
    axes[-1, 0].set_xlabel("episodes")
    fig.suptitle(_wrap("Misaligned acts by the form they took, per model"
                       + _exclusion_title_suffix(report), _TITLE_WRAP),
                 fontsize=10, x=0.01, ha="left")
    captions = [
        "Every form counts as the act in every rate; the forms are told "
        "apart only here. Models that took no form of an act are not drawn.",
    ] + [text for text, _colour in _exclusion_captions(report)]
    fig.text(0.01, 0.0, "\n".join(_wrap(c) for c in captions), fontsize=7,
             color="#555555", va="top")
    fig.tight_layout(rect=(0, 0.02, 1, 0.97))
    fig.savefig(path, dpi=CHART_DPI, bbox_inches="tight")
    plt.close(fig)
    return path
