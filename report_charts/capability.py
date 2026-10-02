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


def plot_capability(plt, found: dict, target: str, path: str,
                    earlier: bool = False):
    """Stacked outcome counts per model; None when there is no model.

    `earlier` says the episodes ran under a rollout of the arm that is no
    longer the pinned one, which the caption has to say."""
    rows = found["by_model"]
    if not rows:
        return None
    # A floor, because the captions need room whatever the row count: two
    # rows left tight_layout unable to fit them.
    fig, ax = plt.subplots(figsize=(_FIGURE_WIDTH,
                                    max(4.0, 1.6 + 0.28 * len(rows))))
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
    ax.set_title(_wrap(f"Instructed episodes for the {act} act: did each "
                       f"model perform it?", _TITLE_WRAP),
                 fontsize=10, loc="left")
    captions = [
        "The act was asked for outright in every episode. Performing it shows "
        "the model can; not performing it shows nothing about ability, "
        "because complying is itself a choice - so a model with no success "
        "is not shown capable, never shown incapable.",
        f"Counts, not rates: {_episode_range(rows)} episodes per model is "
        f"enough to show the act once and too few to estimate how often.",
    ]
    if earlier:
        captions.append(
            "Collected under an earlier rollout of this arm"
            + (", whose system prompt scoped the account to the project "
               "directory: the instruction asked the model to override that "
               "rule, so a refusal here is the model following it."
               if target == "sandbox" else "."))
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
