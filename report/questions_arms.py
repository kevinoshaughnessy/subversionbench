"""
Questions 1-4: the exposure is an arm the harness assigned.

    1. oversight -> scheming rate
    2. oversight -> verbalised evaluation awareness rate
    3. oversight -> agentic misalignment rate
    4. nudge     -> verbalised evaluation awareness rate

Grouped by what the exposure IS, not by what it predicts. Here the exposure was
set by the design before the episode ran, which is the only reason a contrast
across it reads as an effect of the manipulation rather than as an association.
Questions 5-10 condition on something the model itself did - see
questions_awareness.py - and questions 11-12 put every phrasing to the same act,
which makes them paired rather than independent.

Questions 1 and 3 are the narrow and wide constructs against the same
manipulation - scheming is a proper subset of misalignment - and share a
denominator, so the pair separates "does oversight change how often the model
acts" from "does it change how often it hides an act it took".

Questions 2 and 4 carry a PARALLEL MEASURE, because awareness is the one outcome
whose instrument varies by provider: it is read from the model's reasoning as
well as its visible output, and a route that returns no reasoning is a narrower
instrument. `_text_reachable_block` reads the same contrast from visible text
alone - a channel every model has - so the conclusion can be checked on an
instrument the route cannot take away. It lives here rather than with the
loaders because it is a question-shaped block: it pools, contrasts, stratifies
and measures agreement.
"""

from .data_quality import _measure_agreement, _model_rate_pairs
from .loading import NUDGE_LEVELS
from .pooling import (_by_model, _consistency, _contrast, _finding, _models,
                      _pool, _stratified)


def _text_reachable_block(rows: list, group_key: str, level_a, level_b) -> dict:
    """
    The same contrast again, with awareness read from visible text only.

    Reported beside the headline rather than instead of it. The headline measure
    is the stronger instrument where reasoning came back; this one is the only
    instrument that is the SAME across every model, so the pair answers a
    question neither answers alone: whether a conclusion about awareness survives
    being computed on a channel the provider route cannot take away.
    """
    args = (group_key, level_a, level_b, "n_aware_text", "n_awareness_resolved")
    by_model = _by_model(rows, *args)
    overall = _contrast(rows, *args)
    mixed = _contrast(rows, group_key, level_a, level_b,
                      "n_aware", "n_awareness_resolved")
    pooled_mixed = _pool(rows, "n_aware", "n_awareness_resolved")
    pooled_text = _pool(rows, "n_aware_text", "n_awareness_resolved")
    undetermined = sum(r["n_text_undetermined"] for r in rows)
    return {
        "measure": "verbalised awareness cited in visible text only",
        "denominator": ("episodes where the mixed measure resolved. Both rates "
                        "here are computed from EPISODES over that one "
                        "denominator, so only the numerator differs - compare "
                        "against `mixed_overall` rather than against the "
                        "headline contrast above, which is pooled from the "
                        "summaries and can differ by an episode or two"),
        "is_lower_bound_where_reasoning_returned": True,
        "n_episodes_exact": sum(r["n_awareness_resolved"] - r["n_bounded"]
                                for r in rows),
        "n_episodes_bounded": sum(r["n_bounded"] for r in rows),
        "n_text_undetermined": undetermined,
        "pooled_mixed": {"successes": pooled_mixed[0], "n": pooled_mixed[1],
                         "rate": (round(pooled_mixed[0] / pooled_mixed[1], 4)
                                  if pooled_mixed[1] else None)},
        "pooled_text": {"successes": pooled_text[0], "n": pooled_text[1],
                        "rate": (round(pooled_text[0] / pooled_text[1], 4)
                                 if pooled_text[1] else None)},
        "n_models_with_any": sum(
            1 for m in _models(rows)
            if any(r["n_aware_text"] for r in rows if r["model"] == m)),
        "n_models": len(_models(rows)),
        "overall": overall,
        "mixed_overall": mixed,
        "agreement": _measure_agreement(mixed, overall),
        "by_model": by_model,
        "by_model_rates": _model_rate_pairs(rows),
        "consistency": _consistency(by_model),
        "stratified": _stratified(by_model),
    }


def _question_oversight(summaries: list, question_id: str, question: str,
                        data_source: str, metric: str,
                        num_key: str, den_key: str) -> dict:
    """
    One oversight contrast: questions 1-3, which differ only in the outcome.

    Written once rather than three times. All three hold the same arms and
    split the same three ways, so the only thing that varies is which numerator
    and denominator are read out of each arm's summary - and questions 1 and 3
    deliberately share `n_runs` as their denominator, so the narrow construct
    (scheming) and the wide one (misalignment) are read off the same episodes.
    """
    rows = summaries
    args = ("oversight", True, False, num_key, den_key)
    overall = _contrast(rows, *args)
    by_model = _by_model(rows, *args)
    by_nudge = []
    for nd in NUDGE_LEVELS:
        c = _contrast([r for r in rows if r["nudge"] == nd], *args)
        c["nudge"] = nd
        by_nudge.append(c)
    by_lure = []
    for lv in (False, True):
        c = _contrast([r for r in rows if r["lure"] == lv], *args)
        c["lure"] = lv
        by_lure.append(c)
    by_nudge_and_lure = []
    for nd in NUDGE_LEVELS:
        for lv in (False, True):
            c = _contrast([r for r in rows
                           if r["nudge"] == nd and r["lure"] == lv], *args)
            c["nudge"], c["lure"] = nd, lv
            by_nudge_and_lure.append(c)
    return {
        "id": question_id,
        "question": question,
        "data_source": data_source,
        "overall": overall,
        "finding": _finding(overall, "oversight present", "oversight absent",
                            metric),
        "by_model": by_model,
        "consistency": _consistency(by_model),
        "stratified": _stratified(by_model),
        "by_nudge": by_nudge,
        "by_lure": by_lure,
        "by_nudge_and_lure": by_nudge_and_lure,
    }


def question_oversight_vs_scheming(summaries: list) -> dict:
    return _question_oversight(
        summaries, "oversight_vs_scheming",
        question=("Does the presence of oversight increase or decrease "
                  "scheming rates?"),
        data_source="summary files: n_scheming / n_runs, pooled per arm",
        metric="scheming rate", num_key="n_scheming", den_key="n_runs")


def question_oversight_vs_awareness(summaries: list,
                                    arm_rows: list = None) -> dict:
    section = _question_oversight(
        summaries, "oversight_vs_awareness",
        question=("Does the presence of oversight increase or decrease "
                  "verbalised evaluation awareness?"),
        data_source=("summary files: awareness_subgroups (grader preferred "
                     "over keywords), pooled per arm"),
        metric="verbalised awareness rate",
        num_key="n_aware", den_key="n_awareness_resolved")
    if arm_rows:
        section["text_reachable"] = _text_reachable_block(
            arm_rows, "oversight", True, False)
    return section


def question_oversight_vs_misalignment(summaries: list) -> dict:
    """
    The WIDE construct against the same manipulation as question 1.

    Scheming is a proper subset of misalignment - the act plus concealment - so
    reading this beside question 1 separates two things a single rate cannot:
    whether oversight changes how often the model acts at all, and whether it
    changes how often it hides an act it took. Both are pooled over the same
    arms and the same `n_runs`, so the pair is directly comparable.
    """
    return _question_oversight(
        summaries, "oversight_vs_misalignment",
        question=("Does the presence of oversight increase or decrease "
                  "agentic misalignment rates?"),
        data_source=("summary files: n_misaligned / n_runs, pooled per arm - "
                     "the same denominator as question 1, so the wide "
                     "construct and the narrow one are read off the same "
                     "episodes"),
        metric="agentic misalignment rate",
        num_key="n_misaligned", den_key="n_runs")


def question_nudge_vs_awareness(summaries: list, arm_rows: list = None) -> dict:
    rows = summaries
    overall = _contrast(rows, "nudge", "max", "none", "n_aware",
                        "n_awareness_resolved")
    marginals = []
    for nd in NUDGE_LEVELS:
        x, n = _pool([r for r in rows if r["nudge"] == nd],
                     "n_aware", "n_awareness_resolved")
        marginals.append({"nudge": nd, "n_aware": x, "n": n,
                          "rate": round(x / n, 4) if n else None})
    pairwise = []
    for a, b in (("none", "strong"), ("strong", "max"), ("none", "max")):
        c = _contrast(rows, "nudge", a, b, "n_aware", "n_awareness_resolved")
        c["pair"] = f"{a} vs {b}"
        pairwise.append(c)
    by_model = _by_model(rows, "nudge", "max", "none", "n_aware",
                         "n_awareness_resolved")
    by_lure = []
    for lv in (False, True):
        c = _contrast([r for r in rows if r["lure"] == lv],
                      "nudge", "max", "none", "n_aware", "n_awareness_resolved")
        c["lure"] = lv
        by_lure.append(c)
    text_reachable = (_text_reachable_block(arm_rows, "nudge", "max", "none")
                      if arm_rows else None)
    return {
        "id": "nudge_vs_awareness",
        "question": "Does the nudge setting increase or decrease verbalised "
                    "evaluation awareness?",
        **({"text_reachable": text_reachable} if text_reachable else {}),
        "data_source": "summary files: awareness_subgroups, pooled per arm. "
                       "Primary contrast is none vs max (the extremes); the "
                       "3-level trend and none-vs-strong/strong-vs-max are "
                       "also reported.",
        "overall": overall,
        "finding": _finding(overall, "nudge=max", "nudge=none",
                           "verbalised awareness rate"),
        "marginals_by_nudge": marginals,
        "pairwise": pairwise,
        "by_model": by_model,
        "consistency": _consistency(by_model),
        "stratified": _stratified(by_model),
        "by_lure": by_lure,
    }
