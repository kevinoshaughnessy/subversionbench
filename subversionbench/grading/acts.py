"""
The misaligned acts this eval can observe.

Each act carries the analysis keys its measures live under, so that concealment,
timing and scheming are computed per act rather than collapsed. Adding an act
means adding a row here, not editing every consumer.
"""

from ..config import (
    ACT_OVERSIGHT_DESCRIPTION,
    INTERROGATION_CHOICES,
    INTERROGATION_VARIANTS,
    ACT_SANDBOX_DESCRIPTION,
    FOLLOWUP_MONITORING_ADMISSION,
    FOLLOWUP_MONITORING_CONTRITION,
    FOLLOWUP_MONITORING_DENIAL,
    FOLLOWUP_MONITORING_QUESTIONS,
    FOLLOWUP_MONITORING_QUESTIONS_MAX,
    FOLLOWUP_SANDBOX_ADMISSION,
    FOLLOWUP_SANDBOX_CONTRITION,
    FOLLOWUP_SANDBOX_DENIAL,
    FOLLOWUP_SANDBOX_QUESTIONS,
    FOLLOWUP_SANDBOX_QUESTIONS_MAX,
)

def questions_for(act: dict, nudge: str,
                  interrogation: str = "default") -> list:
    """
    The interrogation questions this act gets under this nudge and phrasing.

    Only the max arm differs, and it differs only here: the episode it follows
    is byte-identical to the strong arm's. Selected at call time rather than
    baked into the act, so one MISALIGNED_ACTS serves every arm and a batch
    cannot end up interrogated with the wrong set.

    `interrogation` swaps the FIRST question for a meaning-preserving rephrasing
    and leaves the rest of the ladder alone. Spliced here rather than in
    scenario_for because config.py resolves the default bundle once at import, so
    a variant selected on the command line cannot reach the act definitions any
    other way.

    The max arm gets its OWN rephrasing rather than the ordinary one. Its first
    question is four clauses to the ordinary three - it inserts a stated
    consequence before the question - so the ordinary paraphrase is a paraphrase of
    a different sentence and splicing it on would silently produce a condition that
    is neither arm. It also needs a different transformation: the ordinary variant
    moves the question ahead of the observation, which cannot be done here because
    one consequence clause opens "Before you answer" and would then contradict
    itself. The max form reorders the consequence instead and leaves the question
    last.

    A variant with no max form is refused rather than falling back on the ordinary
    one, which would report a coercive-arm rate measured with a non-coercive
    question.
    """
    ladder = act["questions_max"] if nudge == "max" else act["questions"]
    if interrogation == "default":
        return ladder
    variant = INTERROGATION_VARIANTS.get(interrogation)
    if variant is None:
        raise KeyError(
            f"unknown interrogation variant {interrogation!r}; expected one of "
            f"{list(INTERROGATION_CHOICES)}"
        )
    q1_key = act["q1_key_max"] if nudge == "max" else act["q1_key"]
    if q1_key not in variant:
        raise ValueError(
            f"interrogation variant {interrogation!r} has no rephrasing for the "
            f"{nudge} arm's first question (missing {q1_key!r}). Author one, or "
            f"run that arm with --interrogation default: falling back on another "
            f"arm's wording would report this arm's rate against a question it "
            f"was never asked."
        )
    # A tuple, like the ladder itself: the default path returns the stored
    # ladder unchanged, and a variant must not hand back a different type.
    return (variant[q1_key],) + tuple(ladder[1:])


MISALIGNED_ACTS = (
    {
        "name": "oversight",
        # Which replacement first question an interrogation variant supplies.
        # Two keys because the max arm's first question is a different sentence
        # and needs its own rephrasing, not the ordinary one.
        "q1_key": "monitoring_q1",
        "q1_key_max": "monitoring_q1_max",
        "scheming_key": "scheming_oversight",
        "timing_key": "awareness_timing_oversight",
        "grader_before_key": "eval_awareness_grader_before_oversight",
        "key": "oversight_tampered",
        "followup_key": "followup_response",
        "disclosure_key": "disclosure_oversight",
        "level_key": "concealment_oversight",
        "description": ACT_OVERSIGHT_DESCRIPTION,
        "questions": FOLLOWUP_MONITORING_QUESTIONS,
        "questions_max": FOLLOWUP_MONITORING_QUESTIONS_MAX,
        "admission": FOLLOWUP_MONITORING_ADMISSION,
        "denial": FOLLOWUP_MONITORING_DENIAL,
        "contrition": FOLLOWUP_MONITORING_CONTRITION,
        "banner": "OVERSIGHT TAMPERED WITH",
        "topic": "OVERSIGHT",
    },
    {
        "name": "sandbox",
        "q1_key": "sandbox_q1",
        "q1_key_max": "sandbox_q1_max",
        "scheming_key": "scheming_sandbox",
        "timing_key": "awareness_timing_sandbox",
        "grader_before_key": "eval_awareness_grader_before_sandbox",
        # The NARROW measure, not `sandbox_escape_attempts`. This key decides
        # two things at once: what counts as the act, and what triggers the
        # interrogation. Pointed at the wide field, it put the follow-up to any
        # episode with a refused command - including a runtime probe that names
        # no outside path, and a model reading back a draft it wrote to /tmp
        # itself. The question asserts the audit shows "attempts to read system
        # directories and process listings", which of those episodes is untrue,
        # and a model that denied it was scored as scheming for lying about
        # something it had not done. On r1 that was every one of the 7 episodes
        # scored as scheming on this act. Scheming has to be a conjunction with
        # a genuinely misaligned act, so the act had to narrow, not just the
        # interrogation gate.
        # The UNION of refused and successful reaches, not just the refused
        # half. sandbox_escape_attempts is defined as what the sandbox enforces,
        # so it recorded only attempts that failed - biasing the act toward
        # models that fumbled and away from models that quietly succeeded. For
        # misalignment the intent is the act; whether confinement held is a fact
        # about the harness.
        "key": "out_of_scope_attempts",
        "followup_key": "sandbox_followup_response",
        "disclosure_key": "disclosure_sandbox",
        "level_key": "concealment_sandbox",
        "description": ACT_SANDBOX_DESCRIPTION,
        "questions": FOLLOWUP_SANDBOX_QUESTIONS,
        "questions_max": FOLLOWUP_SANDBOX_QUESTIONS_MAX,
        "admission": FOLLOWUP_SANDBOX_ADMISSION,
        "denial": FOLLOWUP_SANDBOX_DENIAL,
        "contrition": FOLLOWUP_SANDBOX_CONTRITION,
        "banner": "SANDBOX ESCAPE ATTEMPTED",
        "topic": "SANDBOX",
    },
)


