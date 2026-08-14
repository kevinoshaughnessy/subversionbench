"""
OpenRouter adapter: OpenAI-compatible chat completions in, Anthropic-shaped
blocks out.

Reasoning appears here only when the backend volunteers it - this path sends no
reasoning parameter, because OpenRouter has none to send. That is why the same
model can return a full trace through one provider route and nothing through
another, and why `reasoning_config` is recorded per run.
"""

import json
import os
import uuid

from .blocks import _Block, _Response, _block_attr, _block_type, _reasoning_usage
from .config import OPENROUTER_BASE_URL
from .tool_parsing import (
    _BRACKET_TOOL_CALL_RE,
    _RAW_TOOL_CALL_START,
    _parse_bracket_tool_calls,
    _parse_raw_tool_call_text,
)

def _to_openai_messages(msg: dict) -> list:
    """Translate one Anthropic-style message (as built by run_eval.py) into
    zero or more OpenAI chat-completions-style messages."""
    role = msg["role"]
    content = msg["content"]

    if isinstance(content, str):
        return [{"role": role, "content": content}]

    if role == "assistant":
        text_parts = []
        tool_calls = []
        for block in content:
            btype = _block_type(block)
            if btype == "text":
                text_parts.append(_block_attr(block, "text"))
            elif btype == "tool_use":
                tool_calls.append({
                    "id": _block_attr(block, "id"),
                    "type": "function",
                    "function": {
                        "name": _block_attr(block, "name"),
                        "arguments": json.dumps(_block_attr(block, "input")),
                    },
                })
        oa_msg = {"role": "assistant", "content": "\n".join(text_parts) or None}
        if tool_calls:
            oa_msg["tool_calls"] = tool_calls
        return [oa_msg]

    # role == "user": either tool results (from execute_tool_sandboxed) or
    # plain text blocks.
    if content and all(_block_type(b) == "tool_result" for b in content):
        return [
            {
                "role": "tool",
                "tool_call_id": _block_attr(b, "tool_use_id"),
                "content": _block_attr(b, "content"),
            }
            for b in content
        ]

    text_parts = [_block_attr(b, "text") for b in content if _block_type(b) == "text"]
    return [{"role": "user", "content": "\n".join(text_parts)}]



def _to_openai_tool(tool: dict) -> dict:
    return {
        "type": "function",
        "function": {
            "name": tool["name"],
            "description": tool.get("description", ""),
            "parameters": tool["input_schema"],
        },
    }



class OpenRouterClient:
    """Adapter exposing an Anthropic-Messages-style `.messages.create(...)`
    interface, backed by OpenRouter's OpenAI-compatible chat completions
    API."""

    def __init__(self):
        import openai

        api_key = os.environ.get("OPENROUTER_API_KEY")
        if not api_key:
            raise RuntimeError(
                "OPENROUTER_API_KEY environment variable not set. "
                "Get a key from https://openrouter.ai/keys"
            )
        # Long agentic-loop requests (large max_tokens, slow reasoning
        # models) seem more prone to the connection being reset mid-response
        # than a typical short API call - the SDK's default of 2 retries
        # isn't always enough to ride that out.
        # The SDK default read timeout is 600s with no override here, so one
        # degraded call could stall up to max_retries x 600s before the batch
        # ever saw it - measured on a real batch as a single 16,945s (4.7hr)
        # episode. 240s is generous for even an 8192-token effort=max
        # completion from a slow model while bounding that worst case.
        self._client = openai.OpenAI(
            base_url=OPENROUTER_BASE_URL, api_key=api_key, max_retries=5,
            timeout=240,
        )
        self.messages = self

    def create(self, model, max_tokens, system=None, tools=None, messages=None,
               thinking=None, output_config=None):
        # `thinking` and `output_config` (Anthropic's reasoning controls) have
        # no OpenRouter equivalent - accepted here only so callers can use one
        # uniform interface across both clients. resolve_thinking_kwargs sends
        # neither for an OpenRouter model; OpenRouter reasoning models surface
        # their reasoning automatically via `message.reasoning`, captured
        # below regardless of these arguments.
        oa_messages = []
        if system:
            # `system` is usually a plain string, but callers may also pass
            # Anthropic-style content blocks (e.g. to attach `cache_control`
            # for prompt caching, which has no OpenRouter equivalent) -
            # collapse that down to plain text rather than forwarding a
            # block list of unknown shape to an OpenAI-compatible endpoint.
            if isinstance(system, str):
                system_text = system
            else:
                system_text = "\n".join(
                    _block_attr(b, "text") for b in system
                    if _block_type(b) == "text"
                )
            oa_messages.append({"role": "system", "content": system_text})
        for msg in messages or []:
            oa_messages.extend(_to_openai_messages(msg))

        kwargs = {"model": model, "max_tokens": max_tokens, "messages": oa_messages}
        if tools:
            kwargs["tools"] = [_to_openai_tool(t) for t in tools]
            # Some OpenRouter backends for a given model don't actually
            # support function calling - they silently ignore `tools` and
            # the model falls back to emitting its native tool-call syntax
            # as plain text (e.g. DeepSeek R1's "<|tool_calls_begin|>..."
            # tokens), which we can't parse. require_parameters restricts
            # routing to backends that support every parameter we sent.
            kwargs["extra_body"] = {"provider": {"require_parameters": True}}

        # Use the raw-response API rather than the auto-parsing
        # convenience method: if the body isn't valid JSON (an upstream
        # error page, a streaming/SSE body served when we asked for a
        # plain response, a connection dropped mid-response), a bare
        # json.JSONDecodeError three layers deep in the SDK/httpx gives no
        # way to tell what actually came back. Fetching the raw response
        # first means we can report the real HTTP status and body instead.
        raw_response = self._client.chat.completions.with_raw_response.create(**kwargs)
        try:
            completion = raw_response.parse()
        except json.JSONDecodeError:
            status = getattr(raw_response, "status_code", "?")
            body = getattr(raw_response, "text", None)
            if body is None:
                body = str(getattr(raw_response, "content", b""))
            raise RuntimeError(
                f"OpenRouter returned a non-JSON response for model "
                f"'{model}' (HTTP {status}). This usually means the "
                f"upstream provider returned an error page, a "
                f"streaming/SSE body when a plain response was "
                f"requested, or the connection was interrupted "
                f"mid-response. Response body (first 1000 chars):\n"
                f"{body[:1000]}"
            ) from None

        # A body that parses as valid JSON is not necessarily a completion -
        # a moderation block, a rate limit, or a provider-side failure can
        # all come back as a well-formed JSON object with no "choices" at
        # all, which the SDK's typed model then reports as None rather than
        # raising itself. completion.choices[0] on that is a bare
        # TypeError: 'NoneType' object is not subscriptable, three layers
        # from anything that says what actually happened - a real batch hit
        # this after 30 clean turns and reported that message alone. Same
        # status+body diagnostic as the non-JSON case above, since the raw
        # response is the only place an explanation might actually be.
        if not completion.choices:
            status = getattr(raw_response, "status_code", "?")
            body = getattr(raw_response, "text", None)
            if body is None:
                body = str(getattr(raw_response, "content", b""))
            raise RuntimeError(
                f"OpenRouter returned a response with no choices for model "
                f"'{model}' (HTTP {status}). This usually means the "
                f"upstream provider returned an error body that still "
                f"parses as valid JSON - a moderation block, a rate limit, "
                f"or a provider-side failure - rather than a completion. "
                f"Response body (first 1000 chars):\n{body[:1000]}"
            ) from None

        choice = completion.choices[0].message
        finish_reason = getattr(completion.choices[0], "finish_reason", None)
        reasoning = getattr(choice, "reasoning", None)

        blocks = []
        if reasoning:
            blocks.append(_Block("thinking", thinking=reasoning))

        if not choice.tool_calls and choice.content:
            if _RAW_TOOL_CALL_START in choice.content:
                leading_text, raw_calls = _parse_raw_tool_call_text(choice.content)
            else:
                valid_names = {t["name"] for t in (tools or [])}
                leading_text, raw_calls = _parse_bracket_tool_calls(
                    choice.content, valid_names
                )
            if raw_calls:
                if leading_text.strip():
                    blocks.append(_Block("text", text=leading_text.strip()))
                for name, args in raw_calls:
                    blocks.append(_Block(
                        "tool_use", id=f"call_{uuid.uuid4().hex[:8]}",
                        name=name, input=args,
                    ))
                return _Response(blocks, _reasoning_usage(completion),
                                 stop_reason=finish_reason)

        if choice.content:
            blocks.append(_Block("text", text=choice.content))
        for tc in (choice.tool_calls or []):
            try:
                args = json.loads(tc.function.arguments)
            except (json.JSONDecodeError, TypeError):
                args = {}
            blocks.append(_Block("tool_use", id=tc.id, name=tc.function.name, input=args))

        has_visible_output = any(b.type in ("text", "tool_use") for b in blocks)
        if not has_visible_output:
            # No visible text and no tool call. The most common cause is a
            # reasoning model (e.g. DeepSeek R1) spending its entire
            # max_tokens budget on internal reasoning before producing a
            # visible answer or tool call - reasoning tokens count against
            # max_tokens, so a small budget can be exhausted mid-thought.
            # Surface this instead of returning silently empty, which would
            # otherwise look to the caller like "the model is done".
            detail = f"finish_reason={finish_reason}"
            if reasoning:
                detail += f", reasoning_chars={len(reasoning)}"
            blocks.append(_Block(
                "text",
                text=(
                    f"[No visible output from the model this turn ({detail}). "
                    "If finish_reason is 'length', the model likely exhausted "
                    "max_tokens on internal reasoning before producing an "
                    "answer or tool call - try raising --max-tokens.]"
                ),
            ))

        return _Response(blocks, _reasoning_usage(completion),
                         stop_reason=finish_reason)


