"""
The Anthropic-shaped response objects every adapter normalises to.

The rest of the harness - the agentic loop, the interrogation, the grader -
reads `.content` as a list of blocks with `.type`, and must not know which
provider produced them. These are the types that promise holds.
"""

class _Block:
    def __init__(self, type, **kwargs):
        self.type = type
        for key, value in kwargs.items():
            setattr(self, key, value)


class _Response:
    def __init__(self, content, usage=None, stop_reason=None,
                 reasoning_details=None):
        self.content = content
        # Why the model stopped, normalised to the provider's own word for it
        # (`finish_reason` on the OpenAI-shaped routes). Carried because a
        # response with no text block is otherwise indistinguishable from
        # several unrelated causes: reasoning that ran out of budget, a tool
        # call offered instead of an answer, or a refusal. That ambiguity is
        # what made 42 empty interrogation answers unexplainable after the
        # fact - see NO_ANSWER in grading/interrogation.py.
        self.stop_reason = stop_reason
        # Token accounting, when the provider reports it. Carried because a
        # reasoning-token count is the only way to tell a model that did not
        # reason from one whose reasoning was withheld: gpt-5.4 and grok-4.20
        # both returned zero reasoning TEXT across ten episodes, and nothing in
        # the transcript distinguishes "no chain of thought" from "chain of
        # thought not returned". Those are opposite facts about the model, and
        # the awareness measure reads the difference.
        self.usage = usage or {}
        # The provider's own label for the reasoning it just returned - a trace, a
        # summary, or an encrypted payload. Carried beside usage rather than on the
        # thinking block because it describes the message, not one block of it, and
        # because the block is sent back to the API while this is only recorded.
        # See _reasoning_detail_summary.
        self.reasoning_details = reasoning_details or {}


def serialise_messages(messages: list) -> list:
    """
    The API conversation as plain JSON, faithfully enough to send back.

    WHY THIS EXISTS
    ---------------
    The interrogation starts from `messages` - the conversation as the episode
    left it - and until now only `transcript` was saved. The transcript keeps the
    TEXT of each turn but not what the API needs to accept it back: tool_use ids,
    and above all the signatures on thinking blocks. `replayable_content` says why
    those matter - "they carry signatures the API verifies and have to go back
    exactly as they came".

    So a saved episode could not be re-interrogated with a second phrasing. The
    text could be reassembled, but the model would answer from a conversation with
    its own reasoning stripped out, which is a different conversation - and the
    high-awareness models are precisely the ones whose awareness lives in those
    thinking blocks.

    Two block shapes reach this: pydantic models from the Anthropic SDK, and the
    plain _Block above from the adapters. model_dump() is preferred because it
    round-trips every field the provider set, including ones this file does not
    know about; __dict__ is the fallback.

    NOT BACKFILLABLE. The signatures of already-collected episodes are gone. This
    only helps episodes recorded from here on.
    """
    def one(block):
        if isinstance(block, (str, int, float, bool)) or block is None:
            return block
        if isinstance(block, dict):
            return {k: one(v) for k, v in block.items()}
        if isinstance(block, (list, tuple)):
            return [one(b) for b in block]
        dump = getattr(block, "model_dump", None)
        if callable(dump):
            try:
                return dump(mode="json")
            except TypeError:          # older pydantic
                return dump()
        if hasattr(block, "__dict__"):
            return {k: one(v) for k, v in vars(block).items()}
        return str(block)

    out = []
    for message in messages or []:
        if not isinstance(message, dict):
            out.append(one(message))
            continue
        out.append({k: one(v) for k, v in message.items()})
    return out


def _reasoning_usage(completion) -> dict:
    """
    Reasoning-token accounting from an OpenAI-shaped completion.

    Returns {} when the provider reports nothing, which is itself information:
    an absent count and a zero count are not the same claim.
    """
    usage = getattr(completion, "usage", None)
    if usage is None:
        return {}
    out = {}
    # Chat completions and the Responses API name the same quantities
    # differently, and reading only one set silently loses the other. The first
    # native gpt-5.4 batch recorded total_tokens alone for exactly this reason.
    for field in ("prompt_tokens", "completion_tokens", "total_tokens",
                  "input_tokens", "output_tokens"):
        value = getattr(usage, field, None)
        if value is not None:
            out[field] = value
    # OpenAI-compatible providers nest this; OpenRouter passes it through from
    # whichever backend served the request, so it is present for some models
    # and absent for others.
    details = (getattr(usage, "completion_tokens_details", None)
               or getattr(usage, "output_tokens_details", None))
    tokens = getattr(details, "reasoning_tokens", None) if details else None
    if tokens is not None:
        out["reasoning_tokens"] = tokens
    return out


# Keys a reasoning-detail part carries its content under, whichever type it is.
# Summed for a character count rather than stored: the text is already saved once,
# as the thinking block built from `message.reasoning`, and an encrypted part
# carries an opaque blob no measure here reads.
_DETAIL_CONTENT_KEYS = ("text", "summary", "data")

# Scalars worth keeping per part. `type` is the whole point - it is the provider
# saying whether what it returned is a trace, a summary, or an encrypted payload.
_DETAIL_LABEL_KEYS = ("type", "format")


def _reasoning_detail_summary(details) -> dict:
    """
    What the provider said its reasoning WAS, from `message.reasoning_details`.

    WHY THIS IS NOT INFERRED FROM THE ROUTE
    --------------------------------------
    Awareness is read from reasoning, so whether a model returned a full trace, a
    compressed summary, or nothing at all is part of the instrument rather than a
    detail of transport. Until now that could only be guessed at from
    `reasoning_config` - i.e. from the model ID and what was sent - and the guess
    is wrong in both directions: `openai/gpt-5.6-luna` returns reasoning through a
    route documented as returning none, while five OpenRouter models return none
    through a route that suppresses nothing. This is the provider's own answer,
    per response.

    WHY THE TEXT IS NOT STORED
    --------------------------
    `message.reasoning` already carries it, and it is saved as the thinking block.
    Copying it here would roughly double the reasoning bulk of every run file to
    say nothing new; a `chars` count is enough to check the two agree.

    Returns {} when the provider sends nothing, which is itself information - an
    absent field and an empty list are not the same claim. Never raises: this is a
    read-only diagnostic, and it must not be the thing that fails an episode.
    """
    try:
        parts = list(details or [])
    except TypeError:
        return {}
    if not parts:
        return {}

    labels, chars, keys = {k: [] for k in _DETAIL_LABEL_KEYS}, 0, set()
    for part in parts:
        get = part.get if isinstance(part, dict) else (
            lambda name, _p=part: getattr(_p, name, None))
        if isinstance(part, dict):
            keys |= set(part)
        for key in _DETAIL_LABEL_KEYS:
            value = get(key)
            if isinstance(value, str) and value not in labels[key]:
                labels[key].append(value)
        for key in _DETAIL_CONTENT_KEYS:
            value = get(key)
            if isinstance(value, str):
                chars += len(value)

    out = {"n_parts": len(parts), "chars": chars}
    for key in _DETAIL_LABEL_KEYS:
        if labels[key]:
            out[f"{key}s"] = labels[key]
    if keys:
        # The shape that actually arrived, for a field the SDK has no model for
        # and whose documented keys may grow.
        out["keys"] = sorted(keys)
    return out


def _block_type(block):
    return block["type"] if isinstance(block, dict) else block.type


def _block_attr(block, name):
    return block[name] if isinstance(block, dict) else getattr(block, name)

# =========================================================================
# The inverse: a saved run back into a conversation
# =========================================================================
#
# serialise_messages above writes the conversation out; this reads one back. They
# are kept together because they must agree, and because the failure when they do
# not is quiet: a reconstruction that drops a field the API verifies produces a
# request that is rejected, or worse accepted against a conversation missing the
# model's own reasoning - which is a different conversation than the one saved.

def reconstruct_messages(run: dict):
    """
    The conversation to interrogate a saved episode from, or a reason it cannot be.

    Returns (messages, None) or (None, reason).

    Prefers the saved `messages`, which is exact: it carries the tool_use ids and
    the thinking-block signatures the API verifies. Episodes recorded before that
    field existed have only the transcript, which keeps the text of every turn but
    neither of those.

    An episode whose transcript contains thinking is REFUSED rather than replayed
    without it. Dropping the thinking would put the model in a conversation where
    its own reasoning never happened - a different conversation, so an answer to a
    second phrasing would not be paired with the first, and the difference would be
    confounded with the removal. It fails worst exactly where it matters: the
    models that verbalise awareness most do it in those blocks.

    Where there is no thinking to lose, the reconstruction is faithful and the
    episode is allowed. Tool ids are synthesised, which is sound because the API
    only requires each tool_result to name a tool_use above it.
    """
    saved = run.get("messages")
    if saved:
        return saved, None

    transcript = run.get("transcript") or []
    if any(e.get("type") == "thinking" and (e.get("content") or "").strip()
           for e in transcript):
        return None, ("transcript contains thinking whose signatures were not "
                      "saved; replaying without it would change the conversation")
    if not run.get("user_prompt"):
        return None, "no user prompt recorded"

    messages = [{"role": "user", "content": run["user_prompt"]}]
    pending_text, pending_calls, results, n = [], [], [], 0
    def flush():
        content = ([{"type": "text", "text": x} for x in pending_text]
                   + pending_calls)
        if content:
            messages.append({"role": "assistant", "content": content})
        if results:
            messages.append({"role": "user", "content": list(results)})
        pending_text.clear(); pending_calls.clear(); results.clear()

    for entry in transcript:
        kind = entry.get("type")
        if kind == "text":
            if results:
                flush()
            if (entry.get("content") or "").strip():
                pending_text.append(entry["content"])
        elif kind == "tool_call":
            n += 1
            pending_calls.append({"type": "tool_use", "id": f"replay_{n}",
                                  "name": "bash",
                                  "input": {"cmd": entry.get("cmd") or ""}})
        elif kind == "tool_result":
            # Refused, not indexed past the end. A transcript with more results
            # than calls in a turn raised IndexError and killed the whole mode
            # rather than skipping the one episode.
            if len(results) >= len(pending_calls):
                return None, ("more tool results than tool calls, so they "
                              "cannot be paired")
            results.append({"type": "tool_result",
                            "tool_use_id": pending_calls[len(results)]["id"],
                            "content": entry.get("result") or ""})
    # A tool call with no result left over means the episode was cut short mid
    # turn. The API requires every tool_use to be answered by a tool_result in
    # the next message, so replaying this would be rejected - refuse here, where
    # the reason can be stated, rather than at the provider.
    if len(results) < len(pending_calls):
        return None, ("the last tool call has no recorded result, so the "
                      "conversation cannot be replayed")
    flush()
    if len(messages) < 2:
        return None, "nothing the model said was recorded"
    return messages, None
