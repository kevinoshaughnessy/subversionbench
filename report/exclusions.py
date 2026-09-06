"""Narrowing the corpus, on two axes, before any question is asked.

Both live here rather than beside the loaders for the reason `exclude_arm`'s
own comment gives: an exclusion applied to one source and not the other is a
report whose questions disagree about what corpus they answered. One module
means one place to look for what was dropped.
"""


# ---------------------------------------------------------------------------
# Excluding an arm from the corpus
# ---------------------------------------------------------------------------
#
# WHY THIS EXISTS. The no-oversight arm is defined as a REMOVAL from the
# oversight condition, and on r9 the removal is incomplete: the task README
# still instructs the model to preview its draft against an automated quality
# score, while the arm has deleted the script that would produce one. The
# instruction is live and unrealisable, so the model hunts for the missing
# artefact, fails to find it inside the project, and reaches outside it - which
# is correctly scored as an out-of-scope attempt but was induced by a broken
# instruction rather than by the absence of oversight. That arm has no oversight
# act available, so the out-of-scope attempt alone decides its misalignment
# rate, and the defect therefore bears on its headline figure directly.
#
# Repairing the README changes what the model observes and so needs a new
# ROLLOUT_VERSION, which this corpus cannot absorb. What can be done without
# re-collecting anything is to answer every question a second time with that arm
# set aside, and to publish both readings. That is what this is: a SENSITIVITY
# READING, not a correction. It does not repair the no-oversight figures - it
# reports what is left once they are excluded.
#
# ONE PREDICATE, BOTH SOURCES. load_summaries and load_episodes read different
# files and answer different questions - see TWO DATA SOURCES above - and
# questions 1-4 come from the first while 5-12 come from the second. An
# exclusion applied to one and not the other is the worst available outcome:
# every number still renders, and half of them describe a different corpus from
# the other half. So the arm to drop is named once here and applied to both by
# the single function below, rather than being pushed into either loader where
# only that loader's callers would get it.

NO_EXCLUSION = "none"
EXCLUDE_NO_OVERSIGHT = "no_oversight"


# Keyed by name, so a caller states which arm it is dropping rather than passing
# a predicate, and so run_report's flag, the JSON stamp and the chart captions
# all name the same thing. `words` is what a reader is shown: it is carried here
# and not rewritten at each display site, because a caption describing a
# different exclusion from the one applied is indistinguishable from a correct
# chart.
ARM_EXCLUSIONS = {
    NO_EXCLUSION: {
        "axis": None,
        "excluded_level": None,
        "words": "",
        "why": "",
    },
    EXCLUDE_NO_OVERSIGHT: {
        "axis": "oversight",
        "excluded_level": False,
        "words": "no-oversight arm excluded - oversight-present episodes only",
        "why": "the no-oversight arm's task README still promises the "
               "automated quality preview that the arm itself removes, so "
               "episodes there hunt for a missing artefact and leave the "
               "project directory looking for it. See report/loading.py.",
    },
}


def exclude_arm(summaries: list, episodes: list,
                exclusion: str = NO_EXCLUSION) -> tuple:
    """
    Both loaders' output with one arm dropped, plus an account of what went.

    Returns (summaries, episodes, stamp). The stamp is never None, even when
    nothing was excluded: a caller that has to test for None before it can say
    what corpus it read is a caller that will forget to, and "every arm" is a
    statement about the corpus worth carrying in the JSON either way.

    THE COUNTS ARE THE POINT OF THE RETURN VALUE. An exclusion that silently
    matched everything - a renamed field, a corpus whose oversight flag is the
    string "true" rather than the boolean - produces an empty report with no
    error, and every rate in it reads as "no data" rather than as a bug. The
    kept and dropped counts go into the report so that failure is visible in
    the document itself rather than only to whoever thinks to check.

    An episode whose arm cannot be determined is dropped too, and counted
    SEPARATELY: `is not None and != excluded_level` rather than
    `!= excluded_level`, so a missing field cannot ride into the surviving
    corpus as though it had been measured. The two are different facts - the
    first says the corpus is missing a field, the second says the exclusion did
    its job - and a single count would conflate them.
    """
    spec = ARM_EXCLUSIONS.get(exclusion)
    if spec is None:
        raise ValueError(
            f"unknown arm exclusion {exclusion!r}; "
            f"expected one of {sorted(ARM_EXCLUSIONS)}")
    axis = spec["axis"]
    stamp = {
        "excluded": exclusion,
        "axis": axis,
        "excluded_level": spec["excluded_level"],
        "words": spec["words"],
        "why": spec["why"],
        "n_summaries_before": len(summaries),
        "n_episodes_before": len(episodes),
    }
    if axis is None:
        stamp.update(n_summaries_kept=len(summaries),
                     n_episodes_kept=len(episodes),
                     n_episodes_dropped=0, n_episodes_unknown_arm=0)
        return summaries, episodes, stamp
    level = spec["excluded_level"]

    def keep(row):
        value = row.get(axis)
        return value is not None and value != level

    kept_summaries = [r for r in summaries if keep(r)]
    kept_episodes = [r for r in episodes if keep(r)]
    stamp.update(
        n_summaries_kept=len(kept_summaries),
        n_episodes_kept=len(kept_episodes),
        n_episodes_dropped=len(episodes) - len(kept_episodes),
        n_episodes_unknown_arm=sum(1 for r in episodes
                                   if r.get(axis) is None))
    return kept_summaries, kept_episodes, stamp


# ---------------------------------------------------------------------------
# Excluding AWARE EPISODES from the corpus
# ---------------------------------------------------------------------------
#
# WHY THIS IS A SEPARATE FUNCTION AND NOT ANOTHER ARM_EXCLUSIONS ENTRY.
# `exclude_arm` narrows both loaders with ONE predicate, which is the whole
# point of it: questions 1-4 read the summaries and 5-12 the episodes, and an
# exclusion reaching only one of those is a report whose halves describe
# different corpora. That works for `oversight` because a summary row IS one
# arm, so the same field means the same thing on both sides.
#
# Awareness is not like that. It is measured PER EPISODE, and a summary row
# aggregates ten of them - some aware, some not. There is no summary-side
# awareness predicate to write: dropping a whole arm because some of its
# episodes were aware would discard the unaware ones with them. So this
# narrows the episode list only, and callers that want arm-level rows under
# it must rebuild them from the surviving episodes with `awareness_arm_rows`
# and `act_arm_rows` rather than reading summary_*.json. Folding this into
# ARM_EXCLUSIONS would put a predicate in there that cannot honour that
# module's own one-predicate-both-sources rule.
#
# WHAT THE READING IS FOR. Questions 1-4 measure an arm's effect on an
# outcome. A reader can object that the effect is not the arm at all: that
# the models which noticed they were being evaluated behaved differently
# between arms, and the contrast is that noticing rather than the condition.
# Answering questions 1-4 again over only the episodes where no awareness was
# found tests that objection directly. If the contrast survives, the objection
# is weakened; if it collapses, the corpus cannot separate the two.
#
# WHAT IT IS NOT. Awareness is measured DURING the episode, so it is an
# outcome of the arm and not a condition assigned alongside it. Conditioning
# on it does not give an unbiased estimate of the arm's effect - where
# awareness and the outcome share an unmeasured common cause, conditioning
# opens a path between arm and outcome that the design had closed, and where
# awareness mediates the arm's effect this blocks a mediator. So this is a
# ROBUSTNESS READING against one named alternative explanation, in the same
# spirit as ARM_EXCLUSIONS above, and not a better answer than the primary.
# Published as a second reading beside the first, never in place of it.
#
# QUESTIONS 5-10 CANNOT BE ANSWERED UNDER IT AT ALL. Their exposure IS
# awareness - see questions_awareness.py - so removing the aware episodes
# removes the group they contrast against. A caller must omit them and say so
# rather than render them off an empty arm; rendering is the failure this
# repository keeps meeting, because every number still appears. Questions
# 11-12 are unaffected: their exposure is interrogation phrasing.

NO_AWARENESS_EXCLUSION = "none"
EXCLUDE_AWARE_PRIMARY = "aware_primary"
EXCLUDE_AWARE_UNION = "aware_union"

# Keyed by name for the same reasons ARM_EXCLUSIONS is: the flag, the JSON
# stamp and the caption all name one thing, and `words` travels with the
# predicate so a caption cannot describe a different exclusion from the one
# applied.
#
# TWO MEASURES, AND WHICH IS PRIMARY. `aware` is the published measure - the
# rubric grader where there is one, the keyword screen only as a fallback,
# which is awareness_flag's own order and is not restated here. `aware_union`
# counts an episode aware if EITHER measure says so, so it also catches the
# episodes the grader called unaware but the keyword screen flagged. The union
# is the stricter screen and therefore the smaller surviving corpus, which is
# why it is offered: an objection answered on the union is harder to argue
# with. It is secondary because it is not the measure any published rate here
# uses, and mixing the two would make the sensitivity reading answer a
# question about a different instrument from the one it is defending.
AWARENESS_EXCLUSIONS = {
    NO_AWARENESS_EXCLUSION: {
        "field": None,
        "words": "",
        "why": "",
    },
    EXCLUDE_AWARE_PRIMARY: {
        "field": "aware",
        "words": "eval-aware episodes excluded - unaware episodes only "
                 "(primary measure: grader, keyword screen as fallback)",
        "why": "an arm contrast can be objected to as the models that "
               "noticed the evaluation behaving differently between arms "
               "rather than the arm itself. Answering again over the "
               "episodes where no awareness was found tests that objection. "
               "Awareness is measured during the episode, so this is a "
               "robustness reading and not an unbiased estimate of the "
               "arm's effect. See report/loading.py.",
    },
    EXCLUDE_AWARE_UNION: {
        "field": "aware_union",
        "words": "eval-aware episodes excluded - unaware episodes only "
                 "(secondary measure: grader OR keyword screen)",
        "why": "the same reading against the stricter of the two awareness "
               "screens: an episode counts as aware if either the grader or "
               "the keyword screen found awareness, so fewer episodes "
               "survive and an objection answered here is harder to argue "
               "with. Secondary, because no published rate uses this "
               "measure. See report/loading.py.",
    },
}


def exclude_aware_episodes(episodes: list,
                           exclusion: str = NO_AWARENESS_EXCLUSION) -> tuple:
    """
    The episode list with eval-aware episodes dropped, plus what went.

    Returns (episodes, stamp). Episodes only, deliberately - see the note
    above for why there is no summary-side counterpart, and why a caller
    under this reading has to rebuild arm rows from what survives.

    AN UNDETERMINED EPISODE IS DROPPED AND COUNTED APART. `None` means no
    awareness measure was available - the grader call failed and the keyword
    screen had nothing either - which is not the same fact as awareness having
    been looked for and not found. Keeping it would put an unmeasured episode
    into a corpus defined by a measurement, and it is exactly the
    absence-is-not-a-no error the rubric parser exists to prevent. Counted
    separately so the two reasons a row left are never conflated, the same
    way exclude_arm separates an excluded arm from an unattributable one.

    THE COUNTS ARE THE POINT OF THE RETURN VALUE, as in exclude_arm: an
    exclusion that silently matched everything renders a full report of
    "no data" rather than raising, and the stamp is what makes that visible
    in the document rather than only to whoever thinks to check.
    """
    spec = AWARENESS_EXCLUSIONS.get(exclusion)
    if spec is None:
        raise ValueError(
            f"unknown awareness exclusion {exclusion!r}; "
            f"expected one of {sorted(AWARENESS_EXCLUSIONS)}")
    field = spec["field"]
    stamp = {
        "excluded": exclusion,
        "field": field,
        "measure": ("primary" if exclusion == EXCLUDE_AWARE_PRIMARY else
                    "secondary" if exclusion == EXCLUDE_AWARE_UNION else None),
        "words": spec["words"],
        "why": spec["why"],
        "n_episodes_before": len(episodes),
    }
    if field is None:
        stamp.update(n_episodes_kept=len(episodes), n_episodes_dropped_aware=0,
                     n_episodes_dropped_undetermined=0)
        return episodes, stamp

    kept = [r for r in episodes if r.get(field) is False]
    stamp.update(
        n_episodes_kept=len(kept),
        n_episodes_dropped_aware=sum(1 for r in episodes
                                     if r.get(field) is True),
        n_episodes_dropped_undetermined=sum(1 for r in episodes
                                            if r.get(field) is None),
    )
    return kept, stamp
