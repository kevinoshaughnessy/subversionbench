"""
OpenAI adapter: the Responses API in, Anthropic-shaped blocks out.

Exists because chat completions returns no reasoning for the gpt-5 family, and
both awareness measures read reasoning. The Responses API returns a reasoning
SUMMARY when asked - never the trace, which OpenAI does not expose to anyone -
so this moves such a model from "withheld" to "summarised" and no further.
"""

import json
import os

from .blocks import _Block, _Response, _block_attr, _block_type, _reasoning_usage
from .routing import is_openai_model, is_openrouter_model

#
# WHY A SECOND OPENAI-SHAPED CLIENT
# ---------------------------------
# The OpenRouter path already speaks OpenAI's chat-completions dialect, so a
# native OpenAI client looks redundant. It is not, and the reason is the whole
# point of adding it: chat completions does not return reasoning for the gpt-5
# family, and OpenRouter can only pass on what the backend gives it. Across ten
# episodes each, openai/gpt-5.4 and x-ai/grok-4.20 returned zero characters of
# reasoning through OpenRouter while openai/gpt-5.5 returned 25,553 - and both
# awareness measures read reasoning, so those models were scored on strictly
# less evidence than the rest.
#
# The Responses API can return a reasoning SUMMARY, requested with
# reasoning={"summary": "auto"}. That is the only route to any reasoning
# content from these models.
#
# WHAT THIS DOES NOT GET YOU
# --------------------------
# Not the chain of thought. OpenAI does not expose it to anyone: "reasoning
# tokens are not visible via the API". A summary moves a model from
# "withheld" to "summarised", which is the same regime the Anthropic models
# are already in - it does not make it comparable with a model that returns a
# full trace, and a batch run this way is not comparable with one run through
# OpenRouter. `reasoning_config` records which was used.

def _to_responses_input(msg: dict) -> list:
    """
    Translate one Anthropic-style message into Responses API input items.

    The Responses API does not nest tool calls inside an assistant message the
    way chat completions does; each is a sibling item in one flat list, and a
    result is matched to its call by `call_id`.
    """
    role = msg["role"]
    content = msg["content"]

    if isinstance(content, str):
        return [{"role": role, "content": content}]

    items = []
    if role == "assistant":
        text_parts = []
        for block in content:
            btype = _block_type(block)
            if btype == "text":
                text_parts.append(_block_attr(block, "text"))
            elif btype == "tool_use":
                items.append({
                    "type": "function_call",
                    "call_id": _block_attr(block, "id"),
                    "name": _block_attr(block, "name"),
                    "arguments": json.dumps(_block_attr(block, "input")),
                })
        if any(t.strip() for t in text_parts):
            items.insert(0, {"role": "assistant",
                             "content": "\n".join(text_parts)})
        return items

    # role == "user": tool results, or ordinary text.
    text_parts = []
    for block in content:
        if _block_type(block) == "tool_result":
            result = _block_attr(block, "content")
            if not isinstance(result, str):
                result = json.dumps(result, default=str)
            items.append({
                "type": "function_call_output",
                "call_id": _block_attr(block, "tool_use_id"),
                "output": result,
            })
        elif _block_type(block) == "text":
            text_parts.append(_block_attr(block, "text"))
    if any(t.strip() for t in text_parts):
        items.append({"role": "user", "content": "\n".join(text_parts)})
    return items


def _to_responses_tool(tool: dict) -> dict:
    """Anthropic tool definition to the Responses API's flat shape."""
    return {
        "type": "function",
        "name": tool["name"],
        "description": tool.get("description", ""),
        "parameters": tool.get("input_schema", {}),
    }


class OpenAIClient:
    """Adapter exposing an Anthropic-Messages-style `.messages.create(...)`,
    backed by OpenAI's Responses API so that reasoning summaries are
    available."""

    def __init__(self):
        import openai

        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError(
                "OPENAI_API_KEY environment variable not set. Get a key from "
                "https://platform.openai.com/api-keys, or run the model "
                "through OpenRouter instead by prefixing the ID with "
                "'openai/' - note that route returns no reasoning for the "
                "gpt-5 family."
            )
        # The SDK default read timeout is 600s with no override here, so one
        # degraded call could stall up to max_retries x 600s before the batch
        # ever saw it - measured on a real batch as a single 16,945s (4.7hr)
        # episode. 240s is generous for even an 8192-token effort=max
        # completion from a slow model while bounding that worst case.
        self._client = openai.OpenAI(api_key=api_key, max_retries=5, timeout=240)
        self.messages = self

    def create(self, model, max_tokens, system=None, tools=None, messages=None,
               thinking=None, output_config=None):
        # `thinking` is Anthropic's control and has no counterpart here;
        # `output_config.effort` does map, since the Responses API takes an
        # effort of its own. Accepted and translated rather than ignored, so
        # one --effort flag means the same thing on both native paths.
        system_text = system
        if system is not None and not isinstance(system, str):
            system_text = "\n".join(
                _block_attr(b, "text") for b in system
                if _block_type(b) == "text")

        items = []
        for msg in messages or []:
            items.extend(_to_responses_input(msg))

        reasoning = {"summary": "auto"}
        effort = (output_config or {}).get("effort")
        if effort:
            reasoning["effort"] = effort

        kwargs = {
            "model": model,
            "max_output_tokens": max_tokens,
            "input": items,
            "reasoning": reasoning,
        }
        if system_text:
            kwargs["instructions"] = system_text
        if tools:
            kwargs["tools"] = [_to_responses_tool(t) for t in tools]

        response = self._client.responses.create(**kwargs)
        return _Response(_from_responses_output(response),
                         _reasoning_usage(response),
                         stop_reason=_stop_reason(response))


def _stop_reason(response) -> str:
    """
    Why the Responses API stopped, as a plain string.

    `status` is "completed" or "incomplete"; when incomplete the useful part is
    `incomplete_details.reason` (e.g. "max_output_tokens"). Flattened here
    because this is written into saved run files and has to stay JSON.
    """
    status = getattr(response, "status", None)
    detail = getattr(response, "incomplete_details", None)
    reason = getattr(detail, "reason", None) if detail is not None else None
    if status and reason:
        return f"{status}:{reason}"
    return status or reason or None


def _from_responses_output(response) -> list:
    """
    Responses API output items to Anthropic-style blocks.

    A reasoning item carries a list of summary parts rather than a string, and
    the list is empty when the model reasoned but produced no summary - which
    is a different fact from not reasoning, and must not become an empty
    thinking block. The loop drops empty reasoning for the same reason the
    native Anthropic path does: it would feed the grader a hollow [REASONING]
    section and make the transcript claim evidence it does not have.
    """
    blocks = []
    for item in getattr(response, "output", None) or []:
        itype = getattr(item, "type", None)
        if itype == "reasoning":
            parts = [getattr(p, "text", "") for p in
                     (getattr(item, "summary", None) or [])]
            text = "\n".join(p for p in parts if p and p.strip())
            if text.strip():
                blocks.append(_Block("thinking", thinking=text))
        elif itype == "function_call":
            try:
                args = json.loads(getattr(item, "arguments", "") or "{}")
            except json.JSONDecodeError:
                args = {}
            blocks.append(_Block("tool_use",
                                 id=getattr(item, "call_id", None),
                                 name=getattr(item, "name", ""),
                                 input=args))
        elif itype == "message":
            for part in getattr(item, "content", None) or []:
                text = getattr(part, "text", None)
                if text and text.strip():
                    blocks.append(_Block("text", text=text))
    return blocks
