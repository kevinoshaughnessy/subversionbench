"""
Preparing text for a grader call, and parsing what comes back.

A leaf, because two modules need it and neither should depend on the other:
grader.py builds the request, and quote_grounding.py has to reconstruct exactly
what the grader was shown in order to check a citation against it. A quote
verified against a longer corpus than the grader saw is not verified.
"""

import json
import re

_GRADER_TRANSCRIPT_CHAR_BUDGET = 20000


def _parse_first_json(raw: str) -> dict:
    """
    Parse the first JSON object in a model reply, ignoring anything after it.

    Models routinely append a sentence of commentary after the JSON, or wrap
    it in a fence. Requiring the whole reply to parse cost two of ~24
    classifier calls in the first pilot - each one silently downgraded to a
    keyword fallback or an undetermined verdict.
    """
    text = re.sub(r'^```(?:json)?\s*', '', raw.strip())
    text = re.sub(r'\s*```$', '', text)
    start = text.find("{")
    if start == -1:
        raise ValueError(f"no JSON object in reply: {raw[:80]!r}")
    obj, _ = json.JSONDecoder().raw_decode(text[start:])
    if not isinstance(obj, dict):
        raise ValueError(f"expected an object, got {type(obj).__name__}")
    return obj


def _truncate_for_grader(text: str, budget: int = _GRADER_TRANSCRIPT_CHAR_BUDGET) -> str:
    """Cap text to `budget` characters, preserving both ends rather than
    just the head. Truncating from the head alone silently drops whatever
    was said later in the conversation - exactly where eval-awareness
    commentary and final decisions tend to land, once the agent has had
    time to reason through the dilemma."""
    if len(text) <= budget:
        return text
    head_len = int(budget * 0.4)
    tail_len = budget - head_len
    return text[:head_len] + "\n\n[... middle truncated ...]\n\n" + text[-tail_len:]


# Below this length a quote cannot be told apart from a coincidence, so it is
# counted separately rather than as a failure. "evaluation awareness" is 20
# characters and appears in the rubric question itself.

