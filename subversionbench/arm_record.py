"""The fields that say which experiment an episode belongs to.

Its own module because there are TWO records carrying them - the one a
completed episode returns and the one attached to the error a died episode
raises - and they had already drifted while both were built by hand in the same
file. One function, read by both, is the whole point; a file boundary is what
stops a third record growing its own copy.
"""

from .config import (CANARY, DEFAULT_INTERROGATION, ROLLOUT_VERSION,
                     VERSION, scenario_acts_for, scenario_id_for)
from .hostenv import toolchain_facts
from .isolation import DEFAULT_ISOLATION
from .rollout_pins import (capability_fingerprint_for,
                            date_fingerprint_for, fingerprint_for,
                            goalguard_fingerprint_for)


def _fingerprint(oversight, lure, capability, date_mode, goalguard=None,
                 nudge="strong"):
    """The pin belonging to THIS arm, from whichever table owns it.

    Four tables, and the choice is made once here rather than at the call
    site: an episode stamped from the wrong one pools with the corpus it is
    the counterfactual to, and nothing about the file looks wrong afterwards.

    CAPABILITY WINS OVER GOAL GUARDING where both are set, because the
    capability arm stages the goal-guarding artefact itself and its ceiling is
    a different measurement from the propensity arm's rate - an episode that
    was INSTRUCTED to rewrite the successor's objective must not carry a
    propensity arm's identity, or it pools into the rate it is the denominator
    of. That is the same precedence the capability arm already takes over the
    plain arms below it.
    """
    from .artefact_dates import DEFAULT as _DATE_DEFAULT
    if capability is not None:
        return capability_fingerprint_for(capability, oversight)
    if goalguard is not None:
        # `nudge` is part of THIS arm's identity and of no other, because the
        # goal-guarding memo is the only scenario document that varies by it.
        # Passing it unconditionally would be wrong for the tables above,
        # whose arms assemble identically under every nudge.
        return goalguard_fingerprint_for(goalguard, oversight, nudge)
    if date_mode is not None and date_mode != _DATE_DEFAULT:
        return date_fingerprint_for(date_mode, oversight, lure)
    return fingerprint_for(oversight, lure)


def arm_identity(model, effort, nudge, oversight, lure, interrogations,
                 openrouter_sort, openrouter_provider,
                 isolation=DEFAULT_ISOLATION, max_turns=None,
                 capability=None, date_mode=None,
                 artefact_dates=None, goalguard=None) -> dict:
    """
    The fields that say WHICH experiment this episode belongs to.

    The opening keys of every episode record, in order, and the reason this is
    a function is that there are two records: the one returned when an episode
    completes and the one attached to EpisodeAPIError when it dies mid-turn.
    Both are saved, both are read by the same analyses, and both carried their
    own copy of these fields.

    The copies had already drifted. `isolation` WAS on the completed record and
    not the failed one, which is why it is built here now; and the same field,
    `analysis_version`, was documented
    as "which analysis version COLLECTED it" in one and "last touched it" in the
    other - wordings that contradict each other, with the first explicitly
    correcting the second. A field added to one record and forgotten in the
    other is silent: the run file simply lacks it, and whatever reads it sees a
    default.

    Ordered exactly as both records ordered it, because these dicts are written
    to disk as JSON and a reordering would rewrite every saved field position
    for no reason.
    """
    return {
        # Emitted into every artefact so a leak into a training corpus can be
        # detected later; see CANARY.md.
        "canary": CANARY,
        # Rollout identity, so an episode is self-describing: which rollout
        # produced it, and which analysis version COLLECTED it. A directory
        # holding two fingerprints is two experiments, and until this existed
        # nothing recorded which was which.
        #
        # Collected, not "last touched": no read mode moves this, so a file
        # collected under v58 and re-labelled under v80 still says v58 -
        # correctly, because this names what the model was run against. What
        # re-read it since is recorded separately, per answer as
        # `classifier_version` and per pass in `reanalysis`; see
        # readmodes/reclassify.record_reanalysis.
        "rollout_version": ROLLOUT_VERSION,
        "oversight": oversight,
        # The arm, recorded rather than left to the filename. Without it every
        # analysis that read this field saw `lure=False` for a lure episode and
        # silently pooled the two arms - which is how 50 lure episodes ended up
        # inside a "primary arm" rate.
        "lure": lure,
        # Which wordings of the opening question were put to this episode, in
        # the order asked. A list because the design is paired: every episode gets
        # the default probe, plus any extras, each from the same frozen episode
        # state. Recorded rather than left to the filename - the arm that was left
        # to the filename got pooled into a rate it did not belong to - and the
        # filename deliberately does NOT mark it, so batches with and without
        # extras still pool for the default measure.
        "interrogations": list(interrogations),
        # WHICH phrasing the headline concealment field holds, named rather than
        # implied. `followup_response` is defined as the reference probe's answer,
        # and that probe's identity changed at r7: it was the part-evidence
        # question, it is now the zero-evidence one. Every rate collected before
        # that measures a different opening question, so a reader pooling two
        # directories needs this stated in the artefact and not inferred from
        # whatever DEFAULT_INTERROGATION happened to be when the batch ran.
        #
        # Only 100 of the 1510 episodes collected before this even recorded
        # `interrogations`, so for the rest the phrasing was recoverable only from
        # the directory name. That is the gap this closes.
        "headline_interrogation": DEFAULT_INTERROGATION,
        # The fingerprint of THIS arm, not the primary one. This used to write a
        # module constant pinned to (oversight, no lure), so every counterfactual
        # and every lure episode claimed the primary arm's identity. The drift
        # guard was always right - it checks the arm being run - but the artefact
        # recorded something else, which defeats the whole point: the comment
        # above says a directory holding two fingerprints is two experiments, and
        # a directory holding one fingerprint across three arms is worse, because
        # it looks consistent.
        # The fingerprint of THIS arm, and for a capability episode that is
        # the capability arm's own pin. Stamped with the propensity arm's
        # instead, restage_model.py's poolability test would wave a
        # capability batch into a propensity corpus - the one check that
        # would otherwise catch it for free.
        "rollout_fingerprint": _fingerprint(oversight, lure, capability,
                                            date_mode, goalguard, nudge),
        "analysis_version": VERSION,
        "model": model,
        # The effort actually sent, not the one requested: resolve_thinking_kwargs
        # drops a level the model will not accept, and recording the request
        # would claim a condition that never applied.
        "effort": effort,
        # None on every non-OpenRouter run, and on an OpenRouter run where
        # the operator did not opt in - "not sent" and "OpenRouter's own
        # default routing" are the same state, so there is nothing else this
        # could mean. Recorded because sort changes WHICH backend answered,
        # which is a fact about the episode's collection, not a preference.
        "openrouter_sort": openrouter_sort,
        # Same reasoning as openrouter_sort above: None means either not
        # OpenRouter or not requested, and a pinned provider changes WHICH
        # backend answered just as much as sort does.
        "openrouter_provider": openrouter_provider,
        "nudge": nudge,
        # WHICH POLICY was asked for. Moved here from the completed record,
        # where the docstring above already named its absence from the failed
        # one as drift: an episode that died mid-turn ran under the same
        # policy and had no field saying so.
        "isolation": isolation,
        # THE SCAFFOLD, which is part of what a rate measures and was not
        # recorded at all. An episode that ends because the model stopped and
        # one that ends because it ran out of turns are different observations,
        # `ended_by` distinguishes them, and neither says what the limit WAS -
        # so a batch collected at a different cap could not be told apart from
        # one collected at this one.
        "max_turns": max_turns,
        # WHAT THE HOST CONTRIBUTED - shell, coreutils, kernel mechanism. Not
        # part of the arm's identity and deliberately not hashed, but the first
        # thing to look at when two batches with the same fingerprint disagree.
        # See hostenv.py.
        "toolchain": toolchain_facts(isolation),
        # WHETHER THE ACT WAS INSTRUCTED. None on every propensity episode,
        # which is what a published rate counts; a target name on a
        # capability episode, where the model was asked for the act outright
        # and the result is a ceiling rather than a propensity.
        #
        # This field is what report/loading.py drops on, so it is the reason
        # a ceiling cannot reach a rate it is the denominator of. Recorded
        # rather than left to the filename for the reason `lure` was: the arm
        # that was left to the filename got pooled into a rate it did not
        # belong to.
        "capability": capability,
        # APPENDED, not inserted. This record is written to disk as JSON in
        # this order and the rule above is that a new field goes on the end;
        # putting it beside rollout_fingerprint, where it belongs by meaning,
        # moved every saved field after it and TestBothEpisodeRecordsCarryThe
        # SameArm said so.
        #
        # The artefact-date arm, recorded rather than left to the filename, on
        # the same evidence as `lure`: the arm that was left to the filename
        # got pooled into a rate it did not belong to. None on every episode
        # collected before the arm existed, which is what distinguishes "ran
        # under the default" from "ran before there was a choice".
        "date_mode": date_mode,
        # APPENDED, for the reason above. What the staging actually DID, as
        # artefact_dates.apply returned it, beside `date_mode` which is what
        # was ASKED for. The two cannot disagree today, and that is the point:
        # apply() walking a tree and stamping nothing raises nothing and
        # returns files_stamped 0, so an episode recording only the request
        # looks identically staged whether or not the staging happened. That
        # is not hypothetical - _age_days once matched no path component and
        # silently gave every artefact one age, found by staging an episode by
        # hand because no saved episode could have shown it. None when no mode
        # was asked for, matching `date_mode`.
        "artefact_dates": artefact_dates,
        # APPENDED, like every field above it. None on every episode collected
        # before the third act existed, and on every ordinary propensity
        # episode since - which is the same distinction `date_mode` draws
        # between "ran under a choice" and "ran before there was one".
        "goalguard": goalguard,
        # WHICH SCENARIO, beside which rollout of it. Neither half identifies
        # a corpus alone: "r10" says nothing about what was measured, and
        # "oversight-sandbox" says nothing about what the model saw. Recorded
        # rather than derived at read time because the act set moves - the day
        # a third category is added, an episode collected today has to keep
        # saying it was collected over two.
        #
        # Derived from the ARM, not read off the module: which arm ran decides
        # which categories were on offer. scenario_acts_for says why the
        # goal-guarding arm moves this and the oversight counterfactual
        # must not.
        #
        # Absent on every episode collected before this field existed, which is
        # unambiguous rather than unknown: r1 through r10 are one scenario, and
        # a reader treats a missing value as that scenario's id.
        "scenario_id": scenario_id_for(
            scenario_acts_for(goalguard, capability)),
    }
