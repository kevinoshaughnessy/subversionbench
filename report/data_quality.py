"""
Whether the corpus can support the questions asked of it.

Separate from loading because it is a different claim. The loaders say what the
files hold; this says where they disagree with each other, where an arm was
collected twice, and where a rate rests on too few episodes to read. A nonzero
count in `data_quality_facts` means the corpus wants `--resummarise` before its
numbers are quoted.

WHAT IS RE-DERIVED, AND WHAT IS CROSS-CHECKED
---------------------------------------------
The verdicts the report derives - misalignment, episode scheming, and per-act
scheming - are each checked against the episode's own stored copy, and any
disagreement is surfaced here rather than averaged away. Averaging would make a
stale derived key invisible, which is the one failure this file exists to make
loud.
"""

from subversionbench.grading import MISALIGNED_ACTS

from .pooling import _models


def _model_rate_pairs(rows: list) -> list:
    """
    Both awareness rates per model, over one shared denominator.

    The parallel COLUMN, as opposed to the parallel contrast: not oversight vs
    no-oversight, but the model's overall awareness rate measured two ways. The
    gap is how much of its measured awareness exists only because its provider
    returned reasoning, and is the figure a single cross-model rate hides.
    """
    out = []
    for model in _models(rows):
        mine = [r for r in rows if r["model"] == model]
        n = sum(r["n_awareness_resolved"] for r in mine)
        if not n:
            continue
        mixed = sum(r["n_aware"] for r in mine)
        text = sum(r["n_aware_text"] for r in mine)
        bounded = sum(r["n_bounded"] for r in mine)
        out.append({
            "model": model, "n": n,
            "n_aware": mixed, "n_aware_text": text,
            "mixed_rate": round(mixed / n, 4),
            "text_rate": round(text / n, 4),
            "gap": round((mixed - text) / n, 4),
            # No reasoning came back anywhere in this model's episodes, so the
            # grader was shown visible text alone and the text rate is exact.
            "text_rate_is_exact": bounded == 0,
            "n_text_undetermined": sum(r["n_text_undetermined"] for r in mine),
        })
    return sorted(out, key=lambda r: -r["gap"])


def _measure_agreement(mixed: dict, text: dict) -> dict:
    """
    How the two awareness measures relate on the same contrast.

    Sign alone is not enough, and reading it alone would have misreported r9
    question 4: the mixed measure is a null there (-1.2%, p=0.54) and the
    text-only measure separates in the other direction (+3.4%, p=0.018).
    "Opposite direction" is true but says the weaker thing - one measure finds
    nothing and the other finds an effect, which is the finding.

    So separation is classified alongside direction. Sizes are deliberately not
    compared: the text measure is a floor wherever reasoning came back, so it is
    expected to be smaller and that carries no information.
    """
    dm, dt = mixed.get("difference"), text.get("difference")
    if dm is None or dt is None:
        return {"code": "no_data", "direction_same": None,
                "description": "one measure has no estimate - nothing to compare"}
    same = (dm > 0) == (dt > 0) if dm and dt else dm == dt
    sm, st = bool(mixed.get("separated")), bool(text.get("separated"))
    if sm and st:
        return {
            "code": "agree" if same else "contradict",
            "direction_same": same,
            "description": (
                "both measures separate in the SAME direction - the conclusion "
                "does not depend on the reasoning channel"
                if same else
                "both measures separate in OPPOSITE directions - the conclusion "
                "reverses when awareness is read from visible text alone"),
        }
    if st and not sm:
        return {"code": "text_only_separates", "direction_same": same,
                "description": ("the text-only measure separates where the mixed "
                                "measure does not: awareness verbalised in "
                                "visible output moves even though total measured "
                                "awareness does not")}
    if sm and not st:
        return {"code": "mixed_only_separates", "direction_same": same,
                "description": ("the mixed measure separates and the text-only "
                                "measure does not - the effect is carried by "
                                "awareness that appears in reasoning, so it "
                                "rests on the channel that varies by provider")}
    return {"code": "both_null", "direction_same": same,
            "description": "neither measure separates"}


def duplicate_arms(summaries: list) -> list:
    """
    Arms represented by more than one batch, which this script POOLS.

    Pooling two batches of the same condition is legitimate when both are
    wanted - they are independent episodes of one arm. It is not what an
    operator wants when the second batch was collected to REPLACE the first:
    a partial batch lost to a provider outage, re-run to full n, leaves both
    on disk and both are read here, double-weighting that arm and mixing
    collection conditions the run files themselves distinguish
    (`openrouter_provider`, `openrouter_sort`). Neither case can be told from
    the other by looking, so this reports rather than decides. Delete or move
    the superseded batch if pooling is not what was meant.
    """
    seen = {}
    for r in summaries:
        seen.setdefault(
            (r["model"], r["nudge"], r["oversight"], r["lure"]), []).append(r)
    out = []
    for (model, nudge, oversight, lure), rows in sorted(seen.items(), key=str):
        if len(rows) < 2:
            continue
        out.append({
            "model": model, "nudge": nudge, "oversight": oversight, "lure": lure,
            "n_batches": len(rows),
            "pooled_n_runs": sum(r["n_runs"] for r in rows),
            "batches": [{"file": r["file"], "n_runs": r["n_runs"]} for r in rows],
        })
    return out


def data_quality_facts(episodes: list, summaries: list = None) -> dict:
    """
    The things that would make the figures above mean less than they say.

    Reported unconditionally rather than checked with an assert, because each
    is a property of the corpus rather than of this script: a keyword-sourced
    awareness verdict is legitimate but under-detects badly (0/20 in one pilot
    arm the grader scored 15/20), so a run whose awareness rates rest partly
    on it is measuring something else than one that does not - the harness
    itself refuses to pool them silently, and neither does this.
    """
    sources = {}
    for ep in episodes:
        key = ep["aware_source"] or "unresolved"
        sources[key] = sources.get(key, 0) + 1
    return {
        "awareness_verdict_sources": sources,
        "awareness_all_from_grader": (
            bool(episodes) and set(sources) == {"grader"}),
        "n_misalignment_verdict_disagreements": sum(
            1 for ep in episodes if ep["misaligned_stored_disagrees"]),
        "n_scheming_verdict_disagreements": sum(
            1 for ep in episodes if ep["scheming_stored_disagrees"]),
        "n_scheming_act_verdict_disagreements": sum(
            1 for ep in episodes
            if any(ep[f"scheming_{a['name']}_stored_disagrees"]
                   for a in MISALIGNED_ACTS)),
        # Episodes that took an act whose concealment could not be determined.
        # They sit in the scheming denominator without being able to reach the
        # numerator, so a large count here biases every scheming rate downward
        # and is worth seeing before the rates are quoted.
        "n_scheming_undetermined": sum(
            1 for ep in episodes if ep["scheming_undetermined"]),
        "n_monitoring_not_applicable": sum(
            1 for ep in episodes if not ep["monitoring_observable"]),
        "n_oversight_act_not_applicable": sum(
            1 for ep in episodes if not ep["oversight_observable"]),
        "n_sandbox_escape_field_absent": sum(
            1 for ep in episodes if ep["sandbox_escape_absent"]),
        "duplicate_arms": duplicate_arms(summaries or []),
    }


def cross_analysis_rows(summaries: list) -> list:
    """
    Misalignment-conditioned-on-awareness, one row per arm per awareness side.

    Reuses each summary's own cross_analysis_awareness rather than
    recomputing it - it is already exactly "of the episodes verbalising
    awareness in this arm, how many were misaligned", the harness's own
    figure, not a new one built here.
    """
    rows = []
    for s in summaries:
        c = s["cross_analysis_awareness"]
        if not c:
            continue
        for flag, side in ((True, "aware"), (False, "unaware")):
            rows.append({
                "model": s["model"], "nudge": s["nudge"],
                "oversight": s["oversight"], "lure": s["lure"],
                "aware": flag,
                "misaligned": c[side]["misaligned"], "n": c[side]["n"],
            })
    return rows
