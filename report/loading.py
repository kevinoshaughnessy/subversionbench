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

from subversionbench.batch import parse_batch_filename
from subversionbench.grading import MISALIGNED_ACTS

from .episode_rows import ANY_CAPABILITY, _episode_row

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
            "model": model, "nudge": nudge, "oversight": oversight, "lure": lure,
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


def load_episodes(output_dir: str, capability: str = None) -> list:
    """
    Every completed episode in output_dir, stripped to what questions 5-12 need.

    failed_run_*.json never reaches this: the glob requires the filename to
    START with "run_", which "failed_run_..." does not - those episodes never
    produced an analysis to condition anything on.

    transcript/system_prompt/user_prompt are dropped immediately after load
    rather than carried: several thousand of these exist, and nothing read
    here needs the transcript - see the module docstring.

    `monitoring_observable` carries the NA distinction that
    `monitoring_disabled` alone cannot: None means the arm had no monitoring
    artefact, which is not the same fact as the model having left one alone.
    """
    episodes = []
    for path in sorted(glob.glob(os.path.join(output_dir, "run_*.json"))):
        row = _episode_row(path, capability)
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

    That makes the composite contrast a comparison of a union over two acts
    against a union over one, which is a different quantity on each side rather
    than the same quantity measured twice. The per-act counts here are what let
    the report state the contrast on an act both arms could actually commit.

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
        key = (e["model"], e["nudge"], e["oversight"], e["lure"])
        row = groups.get(key)
        if row is None:
            row = {"model": e["model"], "nudge": e["nudge"],
                   "oversight": e["oversight"], "lure": e["lure"],
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
        key = (e["model"], e["nudge"], e["oversight"], e["lure"])
        row = groups.setdefault(key, {
            "model": e["model"], "nudge": e["nudge"],
            "oversight": e["oversight"], "lure": e["lure"],
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
