"""
The misaligned acts this eval can observe.

Each act carries the analysis keys its measures live under, so that concealment,
timing and scheming are computed per act rather than collapsed. Adding an act
means adding a row here, not editing every consumer.
"""

from ..config import (
    ACT_OVERSIGHT_DESCRIPTION,
    ACT_SANDBOX_DESCRIPTION,
    FOLLOWUP_MONITORING_ADMISSION,
    FOLLOWUP_MONITORING_CONTRITION,
    FOLLOWUP_MONITORING_DENIAL,
    FOLLOWUP_MONITORING_QUESTIONS,
    FOLLOWUP_SANDBOX_ADMISSION,
    FOLLOWUP_SANDBOX_CONTRITION,
    FOLLOWUP_SANDBOX_DENIAL,
    FOLLOWUP_SANDBOX_QUESTIONS,
)

MISALIGNED_ACTS = (
    {
        "name": "oversight",
        "scheming_key": "scheming_oversight",
        "timing_key": "awareness_timing_oversight",
        "grader_before_key": "eval_awareness_grader_before_oversight",
        "key": "oversight_tampered",
        "followup_key": "followup_response",
        "disclosure_key": "disclosure_oversight",
        "level_key": "concealment_oversight",
        "description": ACT_OVERSIGHT_DESCRIPTION,
        "questions": FOLLOWUP_MONITORING_QUESTIONS,
        "admission": FOLLOWUP_MONITORING_ADMISSION,
        "denial": FOLLOWUP_MONITORING_DENIAL,
        "contrition": FOLLOWUP_MONITORING_CONTRITION,
        "banner": "OVERSIGHT TAMPERED WITH",
        "topic": "OVERSIGHT",
    },
    {
        "name": "sandbox",
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
        "key": "sandbox_boundary_excl_scratch",
        "followup_key": "sandbox_followup_response",
        "disclosure_key": "disclosure_sandbox",
        "level_key": "concealment_sandbox",
        "description": ACT_SANDBOX_DESCRIPTION,
        "questions": FOLLOWUP_SANDBOX_QUESTIONS,
        "admission": FOLLOWUP_SANDBOX_ADMISSION,
        "denial": FOLLOWUP_SANDBOX_DENIAL,
        "contrition": FOLLOWUP_SANDBOX_CONTRITION,
        "banner": "SANDBOX ESCAPE ATTEMPTED",
        "topic": "SANDBOX",
    },
)


