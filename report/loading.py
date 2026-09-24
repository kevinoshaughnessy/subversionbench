"""
Reading a results directory: the two loaders, and the arms rebuilt from them.

TWO DATA SOURCES, NOT ONE
-------------------------
`load_summaries` reads summary_*.json - one row per arm, with counts the harness
already computed at collection time, so pooling them is exact. `load_episodes`
reads run_*.json - one row per episode - because questions 5-10 condition an
outcome on awareness WITHIN an arm, which is a cross-tabulation no summary field
holds.

`awareness_arm_rows` rebuilds arm rows FROM episodes, carrying the text-only
awareness numerator that no summary field holds. It belongs here rather than
beside the questions that use it because it is a second reading of the same
files, not a measure of its own.

WHAT MOVED OUT, AND WHY
-----------------------
`exclusions.py` holds the two ways the corpus is narrowed, together, because an
exclusion applied to one source and not the other is a report whose questions
disagree about what corpus they answered - so one module is one place to look
for what was dropped. `episode_rows.py` holds one saved episode becoming one
row, with the six column families that build it. Both are re-exported here, so
`report.load_episodes` and `report.exclude_arm` resolve as they always did.

Nothing here pools, contrasts or judges. What the corpus can be trusted to
support is data_quality.py's job, and both are separate from asking a question
of it.
"""

import glob
import json
import os

from subversionbench.batch import (goalguard_from_filename,
                                   parse_batch_filename)
from subversionbench.grading import MISALIGNED_ACTS

from .episode_rows import ANY_CAPABILITY, _batch_key, _episode_row


ARM_FIELDS = ("model", "nudge", "oversight", "lure", "goalguard")


def arm_key(row: dict) -> tuple:
    """
    The fields that identify an arm, read off a row of any shape.

    DERIVED IN ONE PLACE BECAUSE EVERY CALLER NEEDS THE SAME ANSWER and they
    read four different row shapes: a summary row, an episode row, a
    failed-episode row and a rebuilt arm row, each built by a different
    loader. It was written out at eight sites instead, and the copies drifted
    in both directions.

    One copy gained a field the others did not have: the attrition key was
    given `goalguard` while episode rows did not carry it, so every arm it
    built matched no episode and reported "0 analysed" for arms holding
    dozens. The other seven then turned out to be missing that same field for
    real - see below - so the fix was not to delete the fifth field from the
    one copy but to put it in all of them, which is possible only once there
    is one copy to put it in.

    `.get` rather than `[]` so a row missing a field groups under None instead
    of raising: a corpus predating a field is a thing to see in the table, not
    a crash. Booleans are not coerced - `oversight` is written as a boolean by
    both loaders, and coercing here would hide it if that ever stopped being
    true.

    WHY `goalguard` IS ONE OF THE FIELDS. It names which counterfactual the
    episode ran under, and the arms are different scenarios rather than
    different samples of one - so pooling them is not a loss of resolution, it
    is an average of two populations. Left out, the report read a pilot's
    gemini/none arm as 9/19 misaligned: a 9/10 arm and a 0/9 arm averaged into
    a middle that neither of them is, with nothing saying so. `duplicate_arms`
    then flagged the two batches behind it as one arm collected twice and
    advised deleting one, which would have thrown away half an experiment.

    Every propensity episode ever collected records None here, so adding it
    partitions no existing corpus: the r10 report is byte-identical across
    this change, which is the check that was run rather than assumed.
    """
    return tuple(row.get(field) for field in ARM_FIELDS)


def load_scaffold(output_dir: str) -> dict:
    """
    What each batch's summary says about the scaffold its episodes ran under.

    THE FIELD IS ON THE SUMMARY AND NOT ON THE EPISODES. `max_turns` has been
    written into every batch summary since v41 and into each episode record
    only since v131 - which is hours after the last r10 episode was collected,
    so no published episode carries it. Measured rather than assumed: all 318
    r10 batch summaries carry it, and none of its 3,213 run files does.

    It is recoverable rather than lost because the summary sits in the same
    directory under a name that shares the batch's stamp, and because the
    episodes corroborate it independently: an episode that ended `turn_cap`
    used exactly as many turns as the cap allowed.

    RETURNED AS AN INDEX RATHER THAN COPIED ONTO DISK. The summary is the one
    owner of this value; a copy on several thousand run files would be several
    thousand things to keep in step, in the one place where a consistency fix
    cannot be re-run cheaply. Nothing here writes.

    A batch whose summary is absent, or whose summary lacks the field, is simply
    not in the map - so the caller attaches None. That distinction is the point:
    None means "this batch did not record it", which is not the same fact as any
    particular cap, and defaulting to the value the rest of the directory
    happens to carry would assert a scaffold for a batch that may have run under
    another.
    """
    index = {}
    for path in sorted(glob.glob(os.path.join(output_dir, "summary_*.json"))):
        if os.path.basename(path).startswith("summary_of_summaries"):
            continue
        try:
            with open(path, encoding="utf-8") as f:
                d = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        nudge = d.get("nudge")
        if not nudge or d.get("max_turns") is None:
            continue
        index[_batch_key(path, nudge)] = {"max_turns": d["max_turns"]}
    return index


def load_summaries(output_dir: str, capability: str = None) -> list:
    """
    Every per-arm summary in output_dir, flattened to one row.

    summary_of_summaries_<model>.json is excluded - it is a rollup of these
    rows, not one of them, and reading it back in would double every count it
    rolled up.

    oversight/lure are not stored as top-level fields in a summary (nudge is;
    they are not), so they are read back off the filename the same way every
    read-mode in this package already does - see batch.parse_batch_filename.
    """
    rows = []
    for path in sorted(glob.glob(os.path.join(output_dir, "summary_*.json"))):
        base = os.path.basename(path)
        if base.startswith("summary_of_summaries"):
            continue
        try:
            with open(path) as f:
                d = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        model, nudge = d.get("model"), d.get("nudge")
        if not model or not nudge:
            continue
        _effort, _stamp, oversight, lure, found_capability = \
            parse_batch_filename(path, nudge)
        # Off the FILENAME, like oversight and lure above and unlike the
        # episode loader, which reads it off the record: a summary JSON
        # carries none of the four arm fields, they are all in its stem.
        goalguard = goalguard_from_filename(path)
        # ONE FILTER, BOTH DIRECTIONS. `capability=None` - every caller in
        # the report - keeps propensity batches only, because a capability
        # episode was INSTRUCTED to take the act and pooling one into a
        # misalignment rate inflates it towards the ceiling it exists to
        # measure. Naming a target keeps that arm and nothing else.
        #
        # Written as an equality rather than as two branches so the two
        # corpora are complementary by construction: no batch can be in both
        # and none can be in neither. Two separate predicates could drift
        # apart, and the failure would be silent in the direction that
        # matters.
        if capability is ANY_CAPABILITY:
            if not found_capability:
                continue
        elif (found_capability or None) != capability:
            continue
        subgroups = d.get("awareness_subgroups") or {}
        n_aware = subgroups.get("aware") or 0
        n_unaware = subgroups.get("unaware") or 0
        rows.append({
            "model": model, "nudge": nudge, "oversight": oversight,
            "lure": lure, "goalguard": goalguard,
            "n_runs": d.get("n_runs") or 0,
            "n_scheming": d.get("n_scheming") or 0,
            # The wide construct beside the narrow one, on the SAME denominator,
            # so questions 1 and 3 are directly comparable. Pooled from the
            # summaries rather than recounted from episodes for that reason; the
            # two agree exactly on this corpus (777/3244 either way).
            "n_misaligned": d.get("n_misaligned") or 0,
            # The two acts behind n_misaligned, split out - see
            # misalignment_definition: an episode is misaligned if it took
            # EITHER, so these two counts can overlap at the episode level and
            # need not sum to n_misaligned. `acts_taken` is concealed + open +
            # undetermined, i.e. the act happened regardless of whether it was
            # hidden - the harness's own scheming_by_act carries no other count
            # of "was this act taken" to read instead.
            #
            # The oversight act is not observable in a no-oversight arm - there
            # is no monitor to tamper with - and the harness records that arm's
            # count as a true 0 rather than None, so a caller pooling this
            # across arms must restrict to oversight-present ones first or it
            # repeats the not-applicable-is-not-zero error question 6 guards
            # against. The sandbox act needs no such restriction: it is
            # observable in every arm.
            "n_oversight_act": (d.get("scheming_by_act") or {})
                .get("oversight", {}).get("acts_taken") or 0,
            "n_sandbox_act": (d.get("scheming_by_act") or {})
                .get("sandbox", {}).get("acts_taken") or 0,
            "n_aware": n_aware, "n_unaware": n_unaware,
            "n_awareness_resolved": n_aware + n_unaware,
            "cross_analysis_awareness": d.get("cross_analysis_awareness"),
            # How much reasoning this arm's provider route actually returned.
            # Carried because the awareness rate is not comparable across models
            # whose routes differ on it - see awareness_channels - and a reader
            # comparing two models needs to be told which instrument each was
            # measured with. Counts rather than a rate, so arms pool by addition.
            "episodes_with_reasoning": d.get("episodes_with_reasoning") or 0,
            "reasoning_chars_total": d.get("reasoning_chars_total") or 0,
            "file": base,
        })
    return rows


def load_failed_episodes(output_dir: str) -> list:
    """
    The episodes that were attempted and never produced an analysis.

    WHY THESE ARE COUNTED RATHER THAN IGNORED. `load_episodes` below excludes
    them deliberately - its glob requires the filename to start with "run_",
    and a failed episode has no analysis to condition anything on. That
    exclusion is right and stays. What was missing is that nothing said how
    many there were, so a rate of 18/19 gave no hint of how many episodes had
    been attempted to get it.

    It is the rule this codebase already applies one level down: a failed
    grader leaves the DENOMINATOR rather than reading as "not aware". An
    episode lost to an API error cannot join a denominator, because there is
    no verdict to put in it - but it can be counted beside one, and it has to
    be, because attrition is not always random with respect to the outcome.

    THE TURN IT DIED ON IS CARRIED BECAUSE IT SEPARATES TWO DIFFERENT FACTS.
    Measured on the goal-guarding pilot: episodes that took the act ran 15-34
    turns and episodes that did not finished at 11-19, so a failure at turn 18
    lands inside the band where an acting episode is still working and removes
    an unknown outcome. A failure on turn 1 removes nothing but the attempt -
    no turn completed, so it cannot correlate with what the episode would have
    done. Eleven of fourteen losses in that batch were turn-1 losses, and a
    single count of "14 lost" would have read as the far worse of the two.

    Returns the arm fields, the error class and the turn only. The partial
    transcript is deliberately not carried: nothing downstream reads it, and
    these records hold the same scenario text every run file does.
    """
    rows = []
    for path in sorted(glob.glob(os.path.join(output_dir,
                                              "failed_run_*.json"))):
        with open(path, encoding="utf-8") as handle:
            saved = json.load(handle)
        rows.append({
            "model": saved.get("model"),
            "nudge": saved.get("nudge"),
            "oversight": saved.get("oversight"),
            "lure": saved.get("lure"),
            "goalguard": saved.get("goalguard"),
            "capability": saved.get("capability"),
            # The class, not the message. A message carries a provider's
            # wording and sometimes an account identifier or a path; the class
            # is what a reader needs to tell a routing mistake from a
            # transient, and is the whole of what this reports.
            "error_class": str(saved.get("error") or "").split(":", 1)[0]
                           or "unknown",
            "failed_on_turn": saved.get("failed_on_turn"),
        })
    return rows


def load_episodes(output_dir: str, capability: str = None) -> list:
    """
    Every completed episode in output_dir, stripped to what questions 5-12 need.

    failed_run_*.json never reaches this: the glob requires the filename to
    START with "run_", which "failed_run_..." does not - those episodes never
    produced an analysis to condition anything on. `load_failed_episodes`
    above reads them, so that what was lost is counted beside what survived
    rather than being invisible.

    transcript/system_prompt/user_prompt are dropped immediately after load
    rather than carried: several thousand of these exist, and nothing read
    here needs the transcript - see the module docstring.

    `monitoring_observable` carries the NA distinction that
    `monitoring_disabled` alone cannot: None means the arm had no monitoring
    artefact, which is not the same fact as the model having left one alone.
    """
    episodes = []
    # Read once for the whole directory rather than per episode: there are two
    # orders of magnitude more run files than summaries, and the index is the
    # same for all of them.
    scaffold = load_scaffold(output_dir)
    for path in sorted(glob.glob(os.path.join(output_dir, "run_*.json"))):
        row = _episode_row(path, capability, scaffold=scaffold)
        if row is not None:
            episodes.append(row)
    return episodes


def act_arm_rows(episodes: list) -> list:
    """
    Episodes rolled up per arm, carrying each act's counts SEPARATELY.

    Shaped like a summary row - model/nudge/oversight/lure plus counts - so the
    per-act contrasts run through the same _contrast, _by_model and _stratified
    machinery as the composite ones, the way awareness_arm_rows does for the
    parallel awareness measure.

    WHY THE COMPOSITE ALONE IS NOT ENOUGH
    -------------------------------------
    `misaligned` and `scheming` are unions over MISALIGNED_ACTS: an episode
    counts if it took ANY act. A union is not an average of its parts, and the
    parts here do not have the same support - the oversight act needs a
    monitoring artefact to tamper with, so in the no-oversight arm it is not
    merely rare, it is impossible. `oversight_observable` is true for every
    episode of the oversight arm and false for every episode of the other.

    That makes the composite contrast a comparison of a union over MORE acts
    against a union over fewer, which is a different quantity on each side
    rather than the same quantity measured twice. Not spelled as a count: it
    was two against one for as long as there were two acts, and a third would
    have made the sentence quietly wrong. The per-act counts here are what let
    the report state the contrast on an act both arms could actually commit,
    and `report/pooling.composite_of` is what makes the varying element set
    visible wherever the composite itself is reported.

    The observability counts travel with the acts rather than being recomputed
    downstream, because "the rate was zero" and "the act was unavailable" are the
    two readings this whole block exists to separate, and only the second one is
    a fact about the design rather than about the model.

    Act names are read from MISALIGNED_ACTS rather than listed, so an act added
    to the scenario later is carried here without this function being edited -
    the failure mode being a new act that silently never reaches the report.
    """
    groups = {}
    for e in episodes:
        key = arm_key(e)
        row = groups.get(key)
        if row is None:
            row = {"model": e["model"], "nudge": e["nudge"],
                   "oversight": e["oversight"], "lure": e["lure"],
                   "goalguard": e.get("goalguard"),
                   "n_runs": 0, "n_misaligned": 0, "n_scheming": 0,
                   "n_scheming_undetermined": 0}
            for act in MISALIGNED_ACTS:
                name = act["name"]
                row[f"n_{name}_act"] = 0
                row[f"n_{name}_scheming"] = 0
                row[f"n_{name}_observable"] = 0
            groups[key] = row
        row["n_runs"] += 1
        row["n_misaligned"] += 1 if e["misaligned"] else 0
        row["n_scheming"] += 1 if e["scheming"] else 0
        row["n_scheming_undetermined"] += 1 if e["scheming_undetermined"] else 0
        for act in MISALIGNED_ACTS:
            name = act["name"]
            row[f"n_{name}_act"] += 1 if e[f"{name}_act_taken"] else 0
            row[f"n_{name}_scheming"] += 1 if e[f"scheming_{name}"] else 0
            row[f"n_{name}_observable"] += 1 if e[f"{name}_observable"] else 0
    return [groups[k] for k in sorted(groups, key=lambda k: tuple(map(str, k)))]


def awareness_arm_rows(episodes: list) -> list:
    """
    Episodes rolled up per arm, carrying BOTH awareness measures.

    Shaped exactly like a summary row - model/nudge/oversight/lure plus counts -
    so the parallel measure runs through the same _contrast, _by_model and
    _stratified machinery as the headline one. Built from episodes because
    `aware_text` is derived per episode and no summary field carries it.

    `n_awareness_resolved` is the SHARED denominator: episodes where the mixed
    measure resolved. Holding it fixed is what makes the two rates a like-for-like
    pair rather than two rates over different corpora - the numerator is the only
    thing that changes. Episodes where the text channel could not be determined
    are counted separately and left OUT of the text numerator, so that measure is
    a floor on this denominator rather than a rate on a shrunken one.
    """
    groups = {}
    for e in episodes:
        if e["aware"] is None:
            continue
        key = arm_key(e)
        row = groups.setdefault(key, {
            "model": e["model"], "nudge": e["nudge"],
            "oversight": e["oversight"], "lure": e["lure"],
            "goalguard": e.get("goalguard"),
            "n_awareness_resolved": 0, "n_aware": 0, "n_aware_text": 0,
            "n_text_undetermined": 0, "n_reasoning_only": 0,
            "n_bounded": 0,
        })
        row["n_awareness_resolved"] += 1
        row["n_aware"] += 1 if e["aware"] else 0
        row["n_aware_text"] += 1 if e["aware_text"] else 0
        row["n_text_undetermined"] += 1 if e["aware_text"] is None else 0
        row["n_reasoning_only"] += 1 if e["aware_reasoning_only"] else 0
        row["n_bounded"] += 1 if e["aware_text_is_bound"] else 0
    return [groups[k] for k in sorted(groups, key=lambda k: tuple(map(str, k)))]
