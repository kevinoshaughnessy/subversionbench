"""One API response becoming a transcript and the next request.

No API call is made here, which is what separates it from episode.py: this is
the bookkeeping either side of one, and it is the part with rules that are easy
to get subtly wrong. Both empty-block rules were bugs, the cache breakpoints
have a cap the API enforces, and what goes BACK to the model is a different
shape from what is recorded.
"""

from .api_errors import api_error_message, warn_usage_limit_once
from .sandbox import tool_input_cmd


# How many cache breakpoints to keep alive in the conversation at once. A
# breakpoint searches back at most 20 content blocks for a prior cache entry,
# and a turn adds roughly two (the assistant's reply, then its tool results),
# so a single rolling breakpoint would stop finding its predecessor around turn
# ten and silently degrade to no caching. Two keeps the lookback short. The API
# allows four; the extra two buy nothing here and cost a write each.
_CACHE_BREAKPOINTS = 2

def roll_cache_breakpoints(messages: list, keep: int = _CACHE_BREAKPOINTS):
    """
    Move the prompt-cache breakpoints onto the newest turn.

    The agentic loop re-sends the entire conversation every turn, and without a
    breakpoint every token is reprocessed at full price: a median episode
    re-sends about 22,400 input tokens across its eight turns, of which only
    ~5,000 are new. Marking the latest tool results cacheable makes each turn
    read what came before at a tenth of the price and write only the increment.

    Marks tool_result blocks specifically because those are dicts this module
    builds. The assistant turns are SDK response objects, which cannot carry an
    extra key, and the opening user turn is a bare string.

    Only the newest `keep` breakpoints are left in place; older ones are
    removed, since a cached prefix stays readable by content and does not need
    its marker to persist.
    """
    marked = [block
              for message in messages
              if isinstance(message.get("content"), list)
              for block in message["content"]
              if isinstance(block, dict) and "cache_control" in block]
    for block in marked[:-keep] if keep else marked:
        block.pop("cache_control", None)


def report_grader_failure(result: dict, what: str = "awareness grader") -> bool:
    """
    Say WHY the awareness grader failed, not just that it did.

    The grader's own result was printed with `rubric_results` excluded - which is
    where every per-question error lives - so a batch showed `"grading_failed":
    true, "rubric_errors": 9` with no reason attached, for every episode. On a
    spend cap that is the whole diagnosis, withheld: the operator sees only that
    grading failed, on a run whose rollout was perfectly fine.

    Returns whether anything was reported, so a caller can stay quiet on the
    ordinary case.
    """
    rubric = (result or {}).get("rubric_results") or {}
    errors = []
    for answer in rubric.values():
        error = (answer or {}).get("error")
        if error and error not in errors:
            errors.append(error)
    if not errors:
        return False
    for error in errors:
        # Once per process, however many questions or episodes hit it.
        warn_usage_limit_once(error, what)
    # `errors` holds DISTINCT messages; the per-question count is separate,
    # because nine questions failing for one reason is one fact and not nine.
    failed = sum(1 for a in rubric.values() if (a or {}).get("error"))
    print(f"  [{what}] {failed} of {len(rubric)} rubric question(s) failed: "
          f"{api_error_message(errors[0], limit=160)}")
    if len(errors) > 1:
        print(f"  [{what}] and {len(errors) - 1} other distinct error(s)")
    return True


def cache_usage(response) -> dict:
    """
    Read the cache counters off one response, tolerating their absence.

    OpenRouter responses carry no `usage` in the shape this returns, and a
    missing counter is reported as zero rather than guessed at.
    """
    usage = getattr(response, "usage", None)
    return {
        "read": int(getattr(usage, "cache_read_input_tokens", 0) or 0),
        "written": int(getattr(usage, "cache_creation_input_tokens", 0) or 0),
        "uncached": int(getattr(usage, "input_tokens", 0) or 0),
    }


def replayable_content(blocks: list) -> list:
    """
    Drop the blocks the API will not accept back in a later request.

    An assistant turn is echoed into `messages` and re-sent on the next turn,
    and Anthropic rejects a text block whose text is empty:

        messages: text content blocks must be non-empty

    Newer models do emit one - a turn that goes from reasoning straight to a
    tool call can open a text block and put nothing in it. The response is
    valid; sending it back is not, so the episode dies on the *following*
    turn with the whole transcript still in memory.

    Thinking blocks are passed through untouched, including empty ones. They
    carry signatures the API verifies and have to go back exactly as they
    came; the copy the grader reads is the transcript, which drops empty
    thinking separately.
    """
    kept = []
    for block in blocks:
        if getattr(block, "type", None) == "text":
            if not (getattr(block, "text", "") or "").strip():
                continue
        kept.append(block)
    return kept


def record_turn_blocks(blocks: list, turn: int, transcript: list,
                       red) -> tuple:
    """
    One turn's content blocks into the transcript. Returns (tool_calls,
    reasoning_chars) - the calls to execute, and how much thinking arrived.

    Every block reaching the transcript goes through `red` first, so no
    host-specific path ends up in a shareable artifact. What goes BACK to the
    model is not redacted; see the tool-result comment in run_evaluation.

    Split out because this is where the two empty-block rules live, and both
    were bugs: an empty thinking block and an empty text block are placeholders
    the API returns rather than content, and recording either makes a transcript
    claim evidence it does not have. That mattered - both awareness measures read
    the transcript.
    """
    tool_calls = []
    reasoning_chars = 0
    for block in blocks:
        if block.type == "thinking":
            thinking = red(block.thinking)
            # An empty thinking block is a placeholder for reasoning the
            # API did not return - it happens on the native path whenever
            # extended thinking is off. Recording it makes a transcript
            # claim reasoning was captured when none was, and feeds the
            # grader empty [REASONING] sections. The OpenRouter path has
            # always guarded this (`if reasoning:`); the native path did
            # not, which left 243 hollow entries in the pilot data.
            if not thinking.strip():
                continue
            reasoning_chars += len(thinking)
            print(f"[Turn {turn+1} THINKING]\n{thinking}\n")
            transcript.append({
                "turn": turn + 1,
                "type": "thinking",
                "content": thinking
            })
        elif block.type == "redacted_thinking":
            print(f"[Turn {turn+1} THINKING] (redacted by provider's safety systems)\n")
            transcript.append({
                "turn": turn + 1,
                "type": "thinking",
                "content": "[redacted]"
            })
        elif block.type == "text":
            text = red(block.text)
            # Empty for the same reason it is dropped from the
            # conversation: a block the model opened and put nothing in.
            # Recording it feeds the grader a hollow [AGENT] section.
            if not text.strip():
                continue
            print(f"[Turn {turn+1} TEXT]\n{text}\n")
            transcript.append({
                "turn": turn + 1,
                "type": "text",
                "content": text
            })
        elif block.type == "tool_use":
            tool_calls.append(block)
            cmd = red(tool_input_cmd(block.input))
            print(f"[Turn {turn+1} TOOL] bash: {cmd}")
            transcript.append({
                "turn": turn + 1,
                "type": "tool_call",
                "cmd": cmd
            })
    return tool_calls, reasoning_chars
