"""
What ended an episode, read from its final turn.

The loop ends when a turn comes back with no tool call, and until v287 it called
every such turn "model_stopped" unless the text carried one of three leaked-call
markers. Two other endings land there and are not a model deciding it is done:

  - an EMPTY TURN: nothing visible came back - only reasoning, or nothing at
    all, which the OpenRouter route replaces with a bracketed placeholder so
    the transcript says so. 953 stored episodes ended on that placeholder as
    "model_stopped"; 431 of them with the provider's own finish reason `stop`,
    which no data-quality check flagged, since a stop is what a decision
    looks like too.
  - a TOOL CALL WRITTEN AS TEXT in a form the markers missed. gemini-3.5-flash
    writes `call:default_api:bash{cmd:...}`: 60 stored episodes ended on one,
    mid-task, nine of them in the impossible-task scenario's fourth pilot.

One rule, used where an episode is collected and where a stored one is read,
so the two cannot disagree. Stored files are not rewritten: the report reads
the settled ending beside the recorded one.
"""

import re

from .tool_parsing import _BRACKET_TOOL_CALL_RE

EMPTY_TURN_MARKER = "[No visible output from the model this turn"

_LEAKED_CALL_MARKERS = ("tool_calls_begin", "tool▁calls▁begin",
                        "<function_calls>")
_DEFAULT_API_CALL_RE = re.compile(r"default_api:\w+\{")

# Endings that are not the model finishing: no closing turn was written.
UNFINISHED_ENDINGS = frozenset({"empty_turn", "raw_tool_call_text",
                                "no_content"})


def is_leaked_tool_call(text: str) -> bool:
    """Whether a turn's text is a tool call the backend did not parse."""
    return (any(marker in text for marker in _LEAKED_CALL_MARKERS)
            or bool(_BRACKET_TOOL_CALL_RE.search(text))
            or bool(_DEFAULT_API_CALL_RE.search(text)))


def ending_of(ended_by: str, final_text: str) -> str:
    """`ended_by` settled against the final turn's visible text.

    Only "model_stopped" is re-read: every other ending was decided by
    something other than the text, and the text cannot overturn it.
    """
    if ended_by != "model_stopped":
        return ended_by
    if not final_text.strip() or final_text.startswith(EMPTY_TURN_MARKER):
        return "empty_turn"
    if is_leaked_tool_call(final_text):
        return "raw_tool_call_text"
    return ended_by


def settled_ending(record: dict):
    """The settled ending of a stored episode; None where none was recorded."""
    ended_by = record.get("ended_by")
    transcript = record.get("transcript") or []
    if ended_by is None or not transcript:
        return ended_by
    last = max(item.get("turn", 0) for item in transcript)
    final_text = "".join(item.get("content") or "" for item in transcript
                         if item.get("turn") == last
                         and item.get("type") == "text")
    return ending_of(ended_by, final_text)


def ending_columns(record: dict) -> dict:
    """An episode row's ending fields: the provider's, the harness's as
    recorded, and the harness's settled by the rule above."""
    return {"ended_by_provider": record.get("ended_by_provider"),
            "ended_by": record.get("ended_by"),
            "ending": settled_ending(record)}
