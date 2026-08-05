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
    def __init__(self, content, usage=None, stop_reason=None):
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


def _block_type(block):
    return block["type"] if isinstance(block, dict) else block.type


def _block_attr(block, name):
    return block[name] if isinstance(block, dict) else getattr(block, name)


