"""
What the model had in front of it when it produced a turn's tool calls, and the text the judge
reads of it.

In view at turn t:
1. the visible text and the commands of every earlier turn;
2. the reasoning of every earlier turn whose reasoning was sent back (turn_context);
3. turn t's own reasoning and visible text, as recorded before turn t's first tool call.

Item 3 is cut at the turn's FIRST tool call for every unit, whatever its role. Cutting a case
turn at its act but a control turn at its end would give controls more text and so more chances
of being exposed, which pushes the estimate below 1; not cutting at all would let text written
after the act count, which is the defect the plan exists to remove. Where a response's record
keeps text and tool calls in separate fields, the record's order (text first) is taken as the
order they were written in.

Not in view: tool results, the prompts, harness messages - exposure is the model's own
suspicion. The judge reads the in-view entries through the grader's own formatter,
format_agent_text, which shows visible text and reasoning and not commands, as the category
instrument tells the judge; so commands are in view but never reach the judge.
"""

from subversionbench.grading.quote_grounding import format_agent_text

SPOKEN = ("text", "thinking")


def current_cut(transcript: list, turn: int) -> int:
    """The index at which turn `turn`'s own text stops counting: its first tool call, or the end
    of the turn if it made none."""
    end = len(transcript)
    for i, entry in enumerate(transcript):
        written = entry.get("turn") or 0
        if written > turn:
            return i
        if written == turn and entry.get("type") == "tool_call":
            return i
    return end


def in_view_indices(transcript: list, turn: int, sent_back, current: bool = True) -> list:
    """Indices of the model-authored entries in view at `turn` (items 1 to 3 above, or 1 and 2
    with `current=False`). `sent_back(turn)` says whether that turn's reasoning went back."""
    cut = current_cut(transcript, turn)
    out = []
    for i, entry in enumerate(transcript[:cut]):
        kind, written = entry.get("type"), entry.get("turn") or 0
        if written < turn:
            if kind in ("text", "tool_call") or (kind == "thinking" and sent_back(written)):
                out.append(i)
        elif written == turn and current and kind in SPOKEN:
            out.append(i)
    return out


def unit_texts(transcript: list, turn: int, sent_back) -> dict:
    """The judge's text for a unit in each view, and the lengths the plan records.

    `in_view` is items 1 to 3, `earlier` items 1 and 2 (sensitivity reading 1). `current_chars`
    is the length of item 3 as the judge sees it, and `current_has_reasoning` whether item 3
    holds any reasoning - the covariates of sensitivity reading 7.
    """
    view = [transcript[i] for i in in_view_indices(transcript, turn, sent_back)]
    earlier = [e for e in view if (e.get("turn") or 0) < turn]
    current = [e for e in view if (e.get("turn") or 0) == turn]
    return {
        "in_view": format_agent_text(view), "earlier": format_agent_text(earlier),
        "current_chars": len(format_agent_text(current)),
        "current_has_reasoning": any(e.get("type") == "thinking" and str(e.get("content", "")).strip()
                                     for e in current),
    }
