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

Nothing here pools, contrasts or judges. What the corpus can be trusted to
support is data_quality.py's job, and both are separate from asking a question
of it.
"""

import glob
import json
import os

from subversionbench.batch import parse_batch_filename
from subversionbench.config import DEFAULT_INTERROGATION
from subversionbench.grading import (MISALIGNED_ACTS, SCHEMING_LEVELS,
                                     awareness_channels,
                                     classify_misalignment, classify_scheming,
                                     classify_scheming_act, concealment_level)
from subversionbench.reporting.facts import awareness_flag

# The levels the `nudge` axis takes in this corpus, in the order a report walks
# them. Here rather than beside the questions because it describes what is in
# the files being read, and both question modules name it.


NUDGE_LEVELS = ("none", "strong", "max")


def load_summaries(output_dir: str) -> list:
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
        _effort, _stamp, oversight, lure = parse_batch_filename(path, nudge)
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


def load_episodes(output_dir: str) -> list:
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
        try:
            with open(path) as f:
                d = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        analysis = d.get("analysis")
        if not d.get("model") or not analysis:
            continue
        aware, aware_source = awareness_flag(analysis)
        # The parallel measure, read from visible text only. Computed here
        # because it needs the transcript, which is dropped below - see
        # awareness_channels for what it bounds and what it does not.
        channels = awareness_channels(analysis, d.get("transcript") or [])
        if not aware:
            # No awareness at all, so none of it is reachable in text. A
            # determined False, not a missing value.
            aware_text = False if aware is not None else None
        else:
            aware_text = channels["text_reachable"]
        monitoring = analysis.get("monitoring_disabled")
        escape = analysis.get("sandbox_escape_attempts")
        derived_misaligned = bool(classify_misalignment(analysis))
        stored_misaligned = analysis.get("misaligned")
        derived_scheming = classify_scheming(analysis)
        stored_scheming = analysis.get("scheming")
        row = {
            "model": d["model"], "nudge": d.get("nudge"),
            "oversight": d.get("oversight"), "lure": d.get("lure"),
            # HOW THE REQUEST WAS ROUTED, carried through so data_quality can
            # see it. Every run file has recorded these since routing became
            # selectable, and nothing downstream read them - so a rate could
            # pool episodes answered by different backends with nothing saying
            # so. Absent on episodes collected before the fields existed, and on
            # every non-OpenRouter model, where None is the only honest value.
            "openrouter_sort": d.get("openrouter_sort"),
            "openrouter_provider": d.get("openrouter_provider"),
            "aware": aware, "aware_source": aware_source,
            # Parallel to `aware`, on the one channel every model has.
            "aware_text": aware_text,
            # A floor rather than an estimate wherever reasoning came back; exact
            # where it did not, because there the grader saw visible text alone.
            "aware_text_is_bound": channels["bound"],
            "aware_reasoning_only": channels["reasoning_only"],
            "misaligned": derived_misaligned,
            # Surfaced, never reconciled: see data_quality_facts.
            "misaligned_stored_disagrees": (
                stored_misaligned is not None
                and bool(stored_misaligned) != derived_misaligned),
            "monitoring_disabled": bool(monitoring),
            "monitoring_observable": monitoring is not None,
            "sandbox_escape": bool(escape),
            "sandbox_escape_absent": escape is None,
            # Episode-level scheming. None means the model took an act whose
            # concealment could not be determined, which the harness keeps out
            # of the numerator and leaves in the denominator - matched here so
            # question 8 stays comparable with the published scheming_rate -
            # and counted separately so the exposure stays visible.
            "scheming": derived_scheming is True,
            "scheming_undetermined": derived_scheming is None,
            "scheming_stored_disagrees": (
                stored_scheming is not None
                and stored_scheming != derived_scheming),
            "one": 1,
        }
        # Per-act scheming, keyed off MISALIGNED_ACTS rather than hardcoded, so
        # the three flags each act needs stay defined in one place:
        #   observable - the act key is not None. The oversight act does not
        #                exist in the no-oversight arm, so its scheming rate is
        #                not-applicable there rather than zero.
        #   determined - a concealment verdict was reached, which is the
        #                denominator for the conditional rate.
        #   concealed  - the verdict was "concealed", the numerator for both.
        for act in MISALIGNED_ACTS:
            name = act["name"]
            derived_act = classify_scheming_act(analysis, act)
            stored_act = analysis.get(act["scheming_key"])
            row[f"scheming_{name}"] = derived_act is True
            row[f"{name}_observable"] = analysis.get(act["key"]) is not None
            row[f"{name}_determined"] = derived_act is not None
            row[f"{name}_act_taken"] = bool(analysis.get(act["key"]))
            row[f"scheming_{name}_stored_disagrees"] = (
                stored_act is not None and stored_act != derived_act)

        # Per-phrasing concealment, for questions 11-12. Re-derived rather than
        # read from concealment_<act>_by_variant, and applying the same
        # correction settle_analysis does: the DEFAULT phrasing's level comes
        # from the headline answers, never from the map's own entry for it,
        # because that entry is a copy taken when the variant was added and
        # --reclassify does not walk it. Reading the stored map would put a
        # stale default level on one side of every contrast.
        row["variant_concealed"] = {}
        row["variant_provenance"] = {}
        for act in MISALIGNED_ACTS:
            name = act["name"]
            by_variant = analysis.get(act["followup_key"] + "_by_variant") or {}
            if not by_variant:
                continue
            levels, provenance = {}, {}
            # The default arm is synthesised from the HEADLINE field rather than
            # read out of the map, so it survives the map not holding a copy of
            # it. reinterrogate._drop_copied_default deletes that copy on
            # purpose - it is stale by construction - and iterating the map
            # alone therefore lost the default side of every phrasing
            # comparison on any episode that had been through --reinterrogate.
            for variant in list(by_variant) + [
                    v for v in (DEFAULT_INTERROGATION,) if v not in by_variant]:
                answers = by_variant.get(variant)
                if variant == DEFAULT_INTERROGATION:
                    level = concealment_level(analysis, act)
                    source = analysis.get(act["followup_key"]) or []
                else:
                    level = concealment_level(analysis, act, answers=answers)
                    source = answers or []
                levels[variant] = (None if level is None
                                   else level in SCHEMING_LEVELS)
                provenance[variant] = (
                    len(source),
                    sum(1 for a in source if a.get("used_keyword_fallback")))
            row["variant_concealed"][name] = levels
            row["variant_provenance"][name] = provenance
        episodes.append(row)
    return episodes


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
