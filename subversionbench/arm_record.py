"""The fields that say which experiment an episode belongs to.

Its own module because there are TWO records carrying them - the one a
completed episode returns and the one attached to the error a died episode
raises - and they had already drifted while both were built by hand in the same
file. One function, read by both, is the whole point; a file boundary is what
stops a third record growing its own copy.
"""

from .config import (CANARY, DEFAULT_INTERROGATION, ROLLOUT_VERSION,
                     VERSION)
from .hostenv import toolchain_facts
from .isolation import DEFAULT_ISOLATION
from .rollout_pins import capability_fingerprint_for, fingerprint_for


def arm_identity(model, effort, nudge, oversight, lure, interrogations,
                 openrouter_sort, openrouter_provider,
                 isolation=DEFAULT_ISOLATION, max_turns=None,
                 capability=None) -> dict:
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
        "rollout_fingerprint": (fingerprint_for(oversight, lure)
                                if capability is None else
                                capability_fingerprint_for(capability,
                                                           oversight)),
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
    }
