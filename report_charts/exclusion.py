"""What the arm-exclusion stamp does to a chart: its title, its
captions, and which of its panels should not be drawn at all.
"""



# Saying which arms a chart is about
# ---------------------------------------------------------------------------
#
# THE HAZARD THESE TWO FUNCTIONS EXIST FOR. The arm-excluded reading writes the
# same chart filenames as the full-corpus one, holding different numbers, and
# `--exclude-no-oversight` only keeps them apart by directory. A figure lifted
# out of that directory and pasted into a document carries no directory with it.
# So the restriction is written into the TITLE, where it cannot be separated
# from the plot, and again in a caption in the warning colour, where there is
# room to say what was excluded and why.
#
# Both are applied by write_charts to every chart it draws, not by each plot_
# function choosing whether to mention it. A chart that opted out would be one
# that looks exactly like the full-corpus figure of the same name.

def _exclusion_title_suffix(report: dict) -> str:
    """Appended to every chart title while an arm is excluded."""
    stamp = report.get("arm_exclusion") or {}
    if stamp.get("axis") is None:
        return ""
    return f"  [{stamp['words']}]"


def _exclusion_captions(report: dict) -> list:
    """
    The caption block naming the exclusion, or nothing at all.

    In `#b00020` - the colour this module already reserves for the divergence
    warning - because it is the same class of statement: something a reader who
    stops at the markers would take the chart to mean, and does not.
    """
    stamp = report.get("arm_exclusion") or {}
    if stamp.get("axis") is None:
        return []
    return [
        (f"ARM EXCLUDED: {stamp['words']}. {stamp['n_episodes_kept']} of "
         f"{stamp['n_episodes_before']} episodes. A sensitivity reading, not a "
         f"correction - the full-corpus version of this chart is the one to "
         f"read alongside it, never instead of it.", "#b00020"),
        (stamp["why"], "#555555"),
    ]


def _excluded_stratum(report: dict, stratum: str) -> bool:
    """
    Whether a chart's own stratum name is the arm the report excluded.

    `lure_effect` splits its panels on oversight and names them "oversight" and
    "no_oversight"; the exclusion names the axis it acted on and the level it
    dropped. Matching the two by name rather than by a table of which panels
    belong to which arm, so a panel added later is compared against the
    exclusion on the same rule.
    """
    stamp = report.get("arm_exclusion") or {}
    axis = stamp.get("axis")
    if axis is None:
        return False
    return stratum == (axis if stamp.get("excluded_level") else f"no_{axis}")


def _scope_caption(section: dict) -> str:
    """
    What was excluded from the denominator, for the questions that restrict one.

    Not-applicable is not zero: `monitoring_disabled` is None in every
    no-oversight episode because that arm has no monitoring artefact to disable,
    and counting those as "did not override" once halved this question's rates.
    A chart that shows the restricted denominator without saying so invites the
    reader to reconcile it against a corpus total that was never its base.
    """
    excluded = section.get("n_episodes_not_applicable")
    if not excluded:
        return ""
    considered = section.get("n_episodes_observable",
                             section.get("n_episodes_considered"))
    return (f"{considered} episode(s) where the act was observable; "
            f"{excluded} not applicable and excluded from the denominator")
