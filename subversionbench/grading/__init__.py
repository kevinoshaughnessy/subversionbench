"""
Scoring an episode: one import site for the measures, which live beside it.

grading.py had grown to 1,482 lines covering the keyword detector, the rubric
grader, quote verification, transcript analysis, three notions of timing, the
interrogation classifier, the closing-report probes and the concealment scale -
nine reasons to change in one file. Each now owns itself:

    awareness_keywords.py   the keyword measure of verbalised awareness
    grader.py               asking an LLM the awareness rubric
    quote_grounding.py      verifying the grader cited the agent, not the memo
    command_patterns.py     what a shell command did to the scenario's files
    transcript_analysis.py  what the episode did, hashes and commands
    transient_tampering.py  the subversion an end-state hash cannot see
    awareness_timing.py     when awareness came, and what had been read by then
    acts.py                 the misaligned acts, and their per-act keys
    interrogation.py        labelling one answer: admitted, denied, neither
    closing_report.py       what the deliverable said, as opposed to the answers
    concealment.py          acts plus answers to a verdict

The names below are the scoring API the rest of the harness uses. New code
should prefer the owning module; this exists so that `run_eval` has one import
and the tests that patch `grading.X` keep working.
"""

from .acts import auth_error_in_analysis, MISALIGNED_ACTS, questions_for
from .awareness_keywords import detect_eval_awareness_keywords
from .awareness_timing import (
    AWARENESS_ONSET_LEVELS,
    AWARENESS_TIMING_LEVELS,
    awareness_onset,
    awareness_timing,
    first_act_position,
    first_awareness_position,
    _looks_like_write,
    _read_positions,
)
from .closing_report import (
    detect_disclosure,
    detect_misrepresentation,
    final_report,
    _ask_yes_no,
)
from .command_patterns import (
    _MEMO_TOKENS,
    _READ_COMMANDS,
    scratch_only_attempts,
)
from .concealment import (
    settle_analysis,
    CONCEALMENT_LEVELS,
    SCHEMING_LEVELS,
    classify_misalignment,
    classify_scheming,
    classify_scheming_act,
    concealment_level,
)
from .grader import (
    ask_rubric_question,
    detect_eval_awareness_grader,
    _parse_first_json,
    _response_cache_usage,
    _truncate_for_grader,
)
from .interrogation import (
    classify_answer,
    classify_answer_llm,
    classify_interrogation_answer,
    marker_matches,
)
from .quote_grounding import (
    QUOTE_GROUNDING_OUTCOMES,
    agent_corpus,
    check_quote_grounding,
    recheck_quote_grounding,
    scenario_corpus,
    summarise_quote_grounding,
    _normalise_quote,
)
from .transcript_analysis import (SCHEMING_KEYWORDS, analyze_misalignment,
                                 artefact_modified, verify_oversight_unchanged)
from .filesystem_escapes import (classify_filesystem_escape,
                                 detect_filesystem_escapes)
from .network_probes import classify_network_probe, detect_network_probes
from .transient_tampering import (
    classify_transient_tampering,
    detect_transient_tampering,
)

__all__ = [
    # what the episode did
    "analyze_misalignment", "SCHEMING_KEYWORDS", "MISALIGNED_ACTS", "auth_error_in_analysis",
    "artefact_modified", "verify_oversight_unchanged",
    "detect_transient_tampering", "classify_transient_tampering",
    "scratch_only_attempts",
    "detect_network_probes", "classify_network_probe",
    "detect_filesystem_escapes", "classify_filesystem_escape",
    "questions_for",
    # awareness
    "detect_eval_awareness_keywords", "detect_eval_awareness_grader",
    "ask_rubric_question", "awareness_timing", "awareness_onset",
    "first_awareness_position", "first_act_position",
    "AWARENESS_TIMING_LEVELS", "AWARENESS_ONSET_LEVELS",
    # did the grader cite the agent, or the scenario?
    "check_quote_grounding", "recheck_quote_grounding",
    "summarise_quote_grounding", "agent_corpus", "scenario_corpus",
    "QUOTE_GROUNDING_OUTCOMES",
    # interrogation and the deliverable
    "classify_answer", "classify_answer_llm", "classify_interrogation_answer",
    "marker_matches", "final_report", "detect_disclosure",
    "detect_misrepresentation",
    # verdicts
    "classify_misalignment", "settle_analysis", "classify_scheming", "classify_scheming_act",
    "concealment_level", "CONCEALMENT_LEVELS", "SCHEMING_LEVELS",
]
