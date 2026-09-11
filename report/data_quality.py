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

from collections import Counter

from subversionbench.grading import MISALIGNED_ACTS

from .loading import ARM_FIELDS, arm_key
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


# The arm-level exposures the report contrasts. Named here because
# data_quality holds no question ids, and tied to the ones build_report
# actually emits by a test rather than by trust - an arm question added later
# must either appear here or fail that test, instead of quietly going
# unchecked for the confound below.
#
# `lure` joined it when the lure arm got a question of its own. That is the
# mechanism working: the axis had been contrasted nowhere, so nobody had asked
# whether its two sides were routed alike, and the test refused the new
# question until the check covered it.
CONTRASTED_AXES = ("oversight", "nudge", "lure")


def routing_differs_across_contrast(episodes: list, axis: str) -> list:
    """
    Models whose two sides of a contrast were not routed alike.

    WHAT THIS CATCHES THAT mixed_routing_arms DOES NOT
    --------------------------------------------------
    mixed_routing_arms keys on the whole arm - (model, nudge, oversight, lure)
    - and asks whether the episodes INSIDE one published rate were collected
    alike. That is the right question for a rate, and it is silent on the one
    that matters for a CONTRAST: every arm can be internally uniform while the
    two arms being compared were routed differently from each other. Nothing
    is mixed anywhere, and the difference between the arms is still partly a
    difference between backends.

    Measured on the r10 corpus as this was written: every episode carrying a
    non-default sort sits on the oversight side, and none on the counterfactual
    side, for models whose two arms were collected months apart. Each arm is
    uniform, so mixed_routing_arms reports nothing at all, and the contrast the
    rollout exists to make is confounded with routing for those models.

    `disjoint` IS THE FIELD THAT MATTERS. Where the two sides share no routing
    at all, no episode in the corpus holds the arm fixed while routing varies
    or the reverse, so the contrast cannot be estimated free of routing by any
    reweighting of what was collected - it needs re-collection. Where they
    merely differ in proportion, the confound is a matter of degree and the
    strata are at least populated on both sides.

    Reported, never reconciled, on the same terms as mixed_routing_arms: which
    routing was wanted is not something this can know.
    """
    by_model = {}
    for ep in episodes:
        level = ep.get(axis)
        if level is None:
            continue
        routing = (ep.get("openrouter_sort"), ep.get("openrouter_provider"))
        levels = by_model.setdefault(ep["model"], {})
        counts = levels.setdefault(level, {})
        counts[routing] = counts.get(routing, 0) + 1

    out = []
    for model, levels in sorted(by_model.items(), key=str):
        # One level present is no contrast, so nothing here can be confounded.
        if len(levels) < 2:
            continue
        routings = {level: frozenset(counts) for level, counts in levels.items()}
        if len(set(routings.values())) == 1:
            continue
        shared = frozenset.intersection(*routings.values())
        out.append({
            "model": model,
            "axis": axis,
            "disjoint": not shared,
            "levels": [
                {
                    "level": level,
                    "n_episodes": sum(counts.values()),
                    "routings": [
                        {"sort": sort, "provider": provider, "n_episodes": n}
                        for (sort, provider), n in sorted(counts.items(),
                                                          key=str)
                    ],
                }
                for level, counts in sorted(levels.items(), key=str)
            ],
        })
    return out


def mixed_served_provider_arms(episodes: list) -> list:
    """
    Arms whose episodes were not all ANSWERED by the same backend.

    THE COMPANION TO mixed_routing_arms, AND THE ONE THAT CAN ACTUALLY SEE IT.
    That check reads `openrouter_sort`/`openrouter_provider`, which record what
    the operator ASKED for and are None wherever nothing was pinned - so on a
    corpus collected under default routing it is silent by construction,
    however many backends actually answered. This reads what the router said
    served each turn, so it reports the thing the caveat is about rather than
    the request that failed to constrain it.

    `episodes_changing_mid_run` is counted apart because it is a different
    fact from an arm pooling two backends: there, one EPISODE was answered by
    more than one, so not even a single transcript is attributable to one
    backend. An arm can be uniform and still contain such episodes.

    Silent on everything collected before the field existed, and on every
    non-OpenRouter route: an empty provider set is "not recorded", and
    reporting it as a mix would invent a finding out of a missing field.
    """
    arms = {}
    for ep in episodes:
        providers = ep.get("served_by_providers") or ()
        if not providers:
            continue
        key = (ep["model"], ep["nudge"], ep["oversight"], ep["lure"])
        entry = arms.setdefault(key, {"providers": {}, "changed": 0, "n": 0})
        entry["n"] += 1
        if ep.get("served_by_changed"):
            entry["changed"] += 1
        for provider in providers:
            entry["providers"][provider] = entry["providers"].get(provider, 0) + 1

    out = []
    for (model, nudge, oversight, lure), entry in sorted(arms.items(), key=str):
        if len(entry["providers"]) < 2 and not entry["changed"]:
            continue
        out.append({
            "model": model, "nudge": nudge, "oversight": oversight,
            "lure": lure, "n_episodes": entry["n"],
            "episodes_changing_mid_run": entry["changed"],
            "providers": [
                {"provider": provider, "n_episodes": n}
                for provider, n in sorted(entry["providers"].items())
            ],
        })
    return out


def mixed_routing_arms(episodes: list) -> list:
    """
    Arms whose episodes were not all routed the same way.

    WHAT THIS CATCHES THAT duplicate_arms DOES NOT
    ----------------------------------------------
    duplicate_arms fires when an arm is made of more than one BATCH, and its
    docstring already names mixed `openrouter_provider`/`openrouter_sort` as one
    of the costs of pooling two. But a batch resumed under different routing
    keeps its stamp, writes one summary, and looks like a single clean batch -
    so the arm has one batch, duplicate_arms says nothing, and the two halves
    pool in silence.

    That is not hypothetical. In the r9 corpus as this was written it found 17
    arms across four models, 302 episodes in all, none of them reported
    anywhere. All twelve arms of one model held roughly ten episodes routed by
    `throughput` beside ten on the provider's default, under a single stamp each
    - so every one of that model's published rates pools two backends about
    evenly.

    Keying on the arm rather than the batch stamp is what found three of those
    17: the mix there spans two stamps, which duplicate_arms does report, but it
    reports the pooling without saying the two halves were routed differently.

    WHY THIS IS NOT IN THE ROLLOUT FINGERPRINT
    ------------------------------------------
    Because it is a different question, and rollout.py says so under WHAT IS NOT
    COVERED: routing is deliberately outside the fingerprint, since the
    fingerprint asks whether two BATCHES may be compared and would then fire on
    every change a provider made. This asks whether the episodes inside one
    published rate were collected alike. Reported, never reconciled - which of
    the two routings was wanted is not something this can know.

    Keyed on (model, nudge, oversight, lure), which is the arm a rate is
    published for, so it catches a mix however it arrived - one resumed batch or
    two pooled ones.
    """
    arms = {}
    for ep in episodes:
        key = (ep["model"], ep["nudge"], ep["oversight"], ep["lure"])
        routing = (ep.get("openrouter_sort"), ep.get("openrouter_provider"))
        arms.setdefault(key, {}).setdefault(routing, 0)
        arms[key][routing] += 1
    out = []
    for (model, nudge, oversight, lure), counts in sorted(arms.items(), key=str):
        if len(counts) < 2:
            continue
        out.append({
            "model": model, "nudge": nudge, "oversight": oversight,
            "lure": lure, "n_episodes": sum(counts.values()),
            "routings": [
                {"sort": sort, "provider": provider, "n_episodes": n}
                for (sort, provider), n in sorted(counts.items(), key=str)
            ],
        })
    return out


# EVERY ROUTE'S WORD FOR "the output was cut off", because this codebase has
# three and they do not share a vocabulary. The first version of this held
# ("length", "max_tokens") - the chat-completions and native-Anthropic words -
# and was therefore silent on the whole OpenAI Responses route, which is where
# a bare `gpt-*` model goes. r10 contains no episode from that route, so no
# corpus could have refuted it.
#
#   length                          OpenAI chat completions, hence OpenRouter
#   max_tokens                      native Anthropic
#   model_context_window_exceeded   native Anthropic, the context-window case
#   max_output_tokens               OpenAI Responses
#
# Taken from the installed SDKs' own Literal types rather than from memory:
# anthropic.types.StopReason and openai's finish_reason / incomplete_details.
TRUNCATING_FINISH_REASONS = frozenset({
    "length", "max_tokens", "model_context_window_exceeded",
    "max_output_tokens",
})

# The other way a turn ends without the model having decided anything: the
# provider stopped it. Same three vocabularies as above - `content_filter` on
# the chat-completions routes, `refusal` natively, and `content_filter` again
# behind the Responses API's status prefix.
REFUSING_FINISH_REASONS = frozenset({"content_filter", "refusal"})


def _provider_word(provider_reason: str) -> str:
    """The provider's own token, with the Responses adapter's status prefix off.

    `_stop_reason` there returns "incomplete:max_output_tokens" while the other
    two routes report a bare token, so comparing whole strings missed that
    route entirely - see the v155 entry.
    """
    return provider_reason.rsplit(":", 1)[-1]


def _is_truncation(provider_reason: str) -> bool:
    """Whether the provider's word for how a turn ended means "cut off"."""
    return _provider_word(provider_reason) in TRUNCATING_FINISH_REASONS


def _is_refusal(provider_reason: str) -> bool:
    """Whether it means the provider blocked the turn."""
    return _provider_word(provider_reason) in REFUSING_FINISH_REASONS


def _arms_the_provider_contradicts(episodes: list, matches, count_key: str
                                   ) -> list:
    """Arms holding episodes the harness read as the model choosing to stop
    while the provider's own word says something else happened.

    ONE SHAPE, TWO FINDINGS. Truncation and refusal are different facts with
    different remedies, so they are separate checks and separate keys - but
    the counting is identical, and a second copy of it is a second place for
    the "absent means not recorded" rule to be got wrong.

    Reported per arm rather than per episode because that is the unit a rate is
    computed over, and one such episode in an arm of sixty moves it by more
    than a rounding error.

    Silent on everything collected before `ended_by_provider` existed. An
    absent value is "not recorded", and counting it as either finding would
    invent one out of a missing field - the same rule
    mixed_served_provider_arms follows.
    """
    arms = {}
    for ep in episodes:
        provider_reason = ep.get("ended_by_provider")
        if not provider_reason:
            continue
        key = (ep["model"], ep["nudge"], ep["oversight"], ep["lure"])
        entry = arms.setdefault(key, {"n": 0, "hit": 0, "reasons": {}})
        entry["n"] += 1
        if ep.get("ended_by") == "model_stopped" and matches(provider_reason):
            entry["hit"] += 1
            entry["reasons"][provider_reason] = (
                entry["reasons"].get(provider_reason, 0) + 1)

    out = []
    for (model, nudge, oversight, lure), entry in sorted(arms.items(),
                                                         key=str):
        if not entry["hit"]:
            continue
        out.append({
            "model": model, "nudge": nudge, "oversight": oversight,
            "lure": lure, "n_episodes": entry["n"],
            count_key: entry["hit"],
            "provider_reasons": [
                {"reason": reason, "n_episodes": n}
                for reason, n in sorted(entry["reasons"].items())
            ],
        })
    return out


def truncated_as_stopped_arms(episodes: list) -> list:
    """Arms holding episodes the harness read as a model choosing to stop, and
    the provider read as running out of room.

    THE CONFLATION THIS EXISTS TO SURFACE. `ended_by` is decided by what came
    back: a turn with no tool calls ends the loop as "model_stopped". A turn
    truncated at max_tokens also has no tool calls, so it lands on the same
    label - and a propensity rate then counts it as a model that declined to
    act. The provider's own word for it is the only thing that separates them,
    and until it was recorded per turn the aggregate token_usage could not: it
    totals the episode, so no per-turn count can be compared against the cap.

    The remedy is to raise the cap and re-collect the arm, which is what makes
    this a different finding from refused_as_stopped_arms below rather than
    one pooled with it.
    """
    return _arms_the_provider_contradicts(
        episodes, _is_truncation, "n_read_as_stopped_but_truncated")


def refused_as_stopped_arms(episodes: list) -> list:
    """Arms holding episodes the harness read as a model choosing to stop, and
    the provider read as blocked.

    The same conflation truncated_as_stopped_arms describes, arriving by the
    other route. A filtered turn returns no tool call, so the loop ends it as
    "model_stopped" and a propensity rate counts it as a model that declined to
    act - when what happened is that the provider would not let it answer.

    KEPT SEPARATE because the remedy differs, and that is the whole reason this
    is not one check with a wider set. A truncation says the cap was too low:
    raise it, re-collect, and the arm is repaired. A refusal says the provider
    blocked the turn, so re-collecting it the same way gets the same block -
    the arm has to move to another route, or be reported as an arm the provider
    would not serve. Pooling them would hand a reader one number with two
    incompatible remedies.

    It is also the more corrosive of the two for a misalignment rate, because a
    filter fires on exactly the content this benchmark measures. An arm losing
    its most misaligned turns to a content filter reports a LOWER rate than the
    model's behaviour, and reports it as though the model had declined.
    """
    return _arms_the_provider_contradicts(
        episodes, _is_refusal, "n_read_as_stopped_but_refused")


def attrition_facts(episodes: list, failed: list) -> dict:
    """
    How many episodes were attempted, and how many survived to be analysed.

    Per arm as well as in total, because attrition concentrated in one arm is a
    different problem from attrition spread evenly: the first biases a
    contrast, the second only costs power.

    `n_lost_before_any_turn_completed` is separated out rather than folded into
    the total because the two carry different consequences, and reporting only
    the total reads as the worse of them. An episode that died on turn 1 made
    no tool call, so nothing it would have done is missing from the numerator -
    it cost an attempt. An episode that died on turn 18 was still working, and
    what it would have concluded is unknown. Turn 1 is the only threshold here
    that is not a judgement call, which is why it is the only one drawn: the
    rest of the distribution is reported as it stands, in `lost_on_turn`.
    """
    analysed = Counter(map(arm_key, episodes))
    lost = Counter(map(arm_key, failed))
    return {
        "n_analysed": len(episodes),
        "n_lost_to_errors": len(failed),
        "n_attempted": len(episodes) + len(failed),
        "n_lost_before_any_turn_completed": sum(
            1 for row in failed if row.get("failed_on_turn") == 1),
        "error_classes": dict(Counter(row["error_class"] for row in failed)),
        "lost_on_turn": dict(Counter(
            row.get("failed_on_turn") for row in failed)),
        # Only the arms that lost something. An entry per arm would be a table
        # of zeroes on every healthy batch, which is the shape of caveat a
        # reader stops looking at.
        "arms_with_losses": [
            dict(zip(ARM_FIELDS, key, strict=True),
                 n_analysed=analysed.get(key, 0), n_lost=lost[key],
                 n_attempted=analysed.get(key, 0) + lost[key])
            for key in sorted(lost, key=str)],
    }


def data_quality_facts(episodes: list, summaries: list = None,
                       failed: list = None) -> dict:
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
        "mixed_routing_arms": mixed_routing_arms(episodes),
        "mixed_served_provider_arms": mixed_served_provider_arms(episodes),
        "truncated_as_stopped_arms": truncated_as_stopped_arms(episodes),
        "refused_as_stopped_arms": refused_as_stopped_arms(episodes),
        # Keyed by axis rather than flattened, so a reader can tell a contrast
        # confounded on oversight from one confounded on nudge without parsing
        # the entries back apart.
        "routing_differs_across_contrast": {
            axis: routing_differs_across_contrast(episodes, axis)
            for axis in CONTRASTED_AXES
        },
        # Attempted-but-lost episodes, which are in no denominator anywhere
        # else in this document. Defaulted rather than required so that the
        # callers reading a corpus without them keep working; an empty list
        # reports zero losses, which is the true answer for such a corpus.
        "attrition": attrition_facts(episodes, failed or []),
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
