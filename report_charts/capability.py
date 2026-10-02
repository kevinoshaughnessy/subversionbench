"""The capability arm, one bar per model: how its instructed episodes ended,
and whether that shows it can take the act.

Its own module because it draws capability_report.py's result, which no
research report carries - the capability corpus is disjoint from the
propensity one by construction, see report/loading.py.
"""

from subversionbench import charting

from .captions import _wrap
from .style import CHART_DPI, _FIGURE_WIDTH, _TITLE_WRAP

_OUTCOMES = (("n_succeeded", "succeeded", "#27ae60"),
             ("n_attempted", "attempted, did not land", "#e67e22"),
             ("n_refused", "refused", "#95a5a6"))

# The scenario each target belongs to, for charting.scenario_marked. A
# capability row carries no `goalguard` arm for scenario_of to read.
_SCENARIO = {"goalguard": "Goal-guarding"}
_ACT_NAMES = {"goalguard": "goal-guarding", "oversight": "oversight subversion",
              "sandbox": "sandbox escape"}


def plot_capability(plt, found: dict, target: str, path: str):
    """Stacked outcome counts per model; None when there is no model."""
    rows = found["by_model"]
    if not rows:
        return None
    fig, ax = plt.subplots(figsize=(_FIGURE_WIDTH, 1.6 + 0.28 * len(rows)))
    ys = range(len(rows))
    left = [0] * len(rows)
    for key, label, colour in _OUTCOMES:
        counts = [r[key] for r in rows]
        ax.barh(ys, counts, left=left, color=colour, label=label, height=0.7)
        left = [a + b for a, b in zip(left, counts, strict=True)]
    for y, row in zip(ys, rows, strict=True):
        ax.annotate("capable" if row["demonstrated"] else "not shown",
                    (row["n"], y), xytext=(4, 0), textcoords="offset points",
                    va="center", fontsize=7,
                    color="#2c3e50" if row["demonstrated"] else "#c0392b")
    ax.set_yticks(list(ys))
    ax.set_yticklabels([r["model"] for r in rows], fontsize=7)
    ax.invert_yaxis()
    ax.set_xlabel("instructed episodes")
    ax.set_xlim(0, max(left) * 1.2)
    ax.xaxis.get_major_locator().set_params(integer=True)
    ax.legend(fontsize=7, loc="upper center", ncol=3, frameon=False,
              bbox_to_anchor=(0.5, -0.75 / fig.get_size_inches()[1]))
    act = _ACT_NAMES.get(target, target)
    ax.set_title(_wrap(f"Capability for the {act} act: how each model's "
                       f"instructed episodes ended", _TITLE_WRAP),
                 fontsize=10, loc="left")
    captions = [
        "The act was asked for outright in every episode. One success shows "
        "the model can take it; a refusal is not an incapability, so a model "
        "with none is not shown capable rather than shown incapable.",
        f"Counts, not rates: {_episode_range(rows)} episodes per model is "
        f"enough to show the act once and too few to estimate how often.",
    ]
    if found["pooled"]["n_unmeasurable"]:
        captions.append(f"{found['pooled']['n_unmeasurable']} episode(s) "
                        f"where the act could not be observed are left out.")
    charting.caption_below(fig, captions, _wrap)
    with charting.scenario_marked(_SCENARIO.get(target, "Mainline")):
        # Tight, because the scenario mark adds a title line after layout.
        fig.savefig(path, dpi=CHART_DPI, bbox_inches="tight")
    plt.close(fig)
    return path


def _episode_range(rows: list) -> str:
    low, high = min(r["n"] for r in rows), max(r["n"] for r in rows)
    return str(low) if low == high else f"{low} to {high}"
