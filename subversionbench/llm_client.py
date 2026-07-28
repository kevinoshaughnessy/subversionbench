"""
Unified LLM client for SubversionBench.

Routes to the native Anthropic API or to OpenRouter (an OpenAI-compatible
proxy for many providers/models: https://openrouter.ai) based on the model
ID, and normalizes OpenRouter's response to look like an Anthropic Messages
API response (`.content` = list of blocks with `.type` / `.text` / `.id` /
`.name` / `.input`), so the rest of the eval code (the agentic loop,
follow-up interrogation, and grader) doesn't need to know which backend
it's talking to.

Model IDs containing a "/" follow OpenRouter's "provider/model" convention
(e.g. "openai/gpt-4o", "google/gemini-2.5-pro", "meta-llama/llama-3.1-70b")
and are routed to OpenRouter. Anything else is routed to the native
Anthropic API.

SETUP for OpenRouter models:
  1. pip install openai
  2. export OPENROUTER_API_KEY="your-key-here"
"""

import os
import re
import ast
import json
import uuid

from .config import OPENROUTER_BASE_URL


def is_openrouter_model(model: str) -> bool:
    return "/" in model


class _Block:
    def __init__(self, type, **kwargs):
        self.type = type
        for key, value in kwargs.items():
            setattr(self, key, value)


class _Response:
    def __init__(self, content):
        self.content = content


def _block_type(block):
    return block["type"] if isinstance(block, dict) else block.type


def _block_attr(block, name):
    return block[name] if isinstance(block, dict) else getattr(block, name)


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


_RAW_TOOL_CALL_START = "<｜tool▁calls▁begin｜>"

_RAW_TOOL_CALL_BLOCK_RE = re.compile(
    r"<｜tool▁call▁begin｜>\s*function\s*<｜tool▁sep｜>\s*"
    r"(?P<name>[^\n]+?)\s*\n"
    r"```(?:json)?\s*(?P<args>.*?)\s*```\s*"
    r"<｜tool▁call▁end｜>",
    re.DOTALL,
)


def _parse_raw_tool_call_text(text: str):
    """Some OpenRouter backends leak a model's native tool-call token
    syntax into plain text instead of populating the structured
    `tool_calls` field - seen with DeepSeek R1, which wasn't trained with
    clean function-calling support and emits tokens like
    "<|tool_calls_begin|><|tool_call_begin|>function<|tool_sep|>bash
    ```json\\n{...}\\n````<|tool_call_end|><|tool_calls_end|>" as content
    instead. Recover the leading text and any tool calls from that syntax
    so a flaky turn doesn't end the episode early."""
    start = text.find(_RAW_TOOL_CALL_START)
    leading_text = text[:start] if start != -1 else text

    calls = []
    for m in _RAW_TOOL_CALL_BLOCK_RE.finditer(text):
        name = m.group("name").strip()
        try:
            args = json.loads(m.group("args").strip())
        except json.JSONDecodeError:
            args = {}
        calls.append((name, args))
    return leading_text, calls


_BRACKET_TOOL_CALL_RE = re.compile(
    r"\[(?P<name>[a-zA-Z_][a-zA-Z0-9_]*)\((?P<args>.*?)\)\s*,?\s*\]",
    re.DOTALL,
)


_SINGLE_KWARG_RE = re.compile(
    r"^\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*=\s*(.*?)\s*$", re.DOTALL,
)


def _parse_unquoted_single_kwarg(args_str: str):
    """Best-effort recovery for a leaked call whose string argument wasn't
    quoted (e.g. "cmd=cat README.md" instead of "cmd='cat README.md'"),
    which isn't valid Python and makes ast.parse reject it outright. Only
    handles the single-keyword-argument case - safe to guess for this
    eval's one-parameter `bash` tool, but with more than one argument
    there's no reliable way to tell a comma in an unquoted value apart
    from an argument separator, so that's left unrecovered."""
    m = _SINGLE_KWARG_RE.match(args_str)
    if not m:
        return None
    key, value = m.group(1), m.group(2)
    if "=" in value:
        return None
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
        value = value[1:-1]
    return {key: value}


def _parse_bracket_tool_calls(text: str, valid_names: set):
    """Some OpenRouter backends leak Llama 4's native "pythonic" tool-call
    syntax - "[funcname(arg='value')]" - into plain text instead of
    populating the structured `tool_calls` field. Recover the leading text
    and any calls whose function name matches a tool we actually offered
    (gates against false positives on ordinary bracketed prose), parsing
    the arguments via `ast` rather than a hand-rolled parser since they're
    Python keyword-argument syntax, not JSON.

    Llama can also emit several calls in one bracket, comma-separated
    ("[a(x=1), b(y=2)]") - wrapping that in "f(...)" to parse it makes
    `ast.parse` return a Tuple of Call nodes rather than a single Call, so
    both shapes have to be handled."""
    calls = []
    first_start = None
    for m in _BRACKET_TOOL_CALL_RE.finditer(text):
        name = m.group("name")
        try:
            parsed = ast.parse(f"f({m.group('args')})", mode="eval").body
        except SyntaxError:
            fallback_args = _parse_unquoted_single_kwarg(m.group("args"))
            if fallback_args and name in valid_names:
                calls.append((name, fallback_args))
                if first_start is None:
                    first_start = m.start()
            continue

        # A single call parses as one Call node; the regex-captured `name`
        # is its real name (the actual identifier was consumed by the
        # regex, not left in `args`). Additional calls in a comma-joined
        # tuple keep their real name in the source text, so read it off
        # the node itself.
        call_nodes = parsed.elts if isinstance(parsed, ast.Tuple) else [parsed]

        found_valid = False
        for i, node in enumerate(call_nodes):
            if not isinstance(node, ast.Call):
                continue
            call_name = name if i == 0 else (
                node.func.id if isinstance(node.func, ast.Name) else None
            )
            if call_name not in valid_names:
                continue
            try:
                args = {kw.arg: ast.literal_eval(kw.value) for kw in node.keywords}
            except ValueError:
                continue
            if not args:
                continue
            calls.append((call_name, args))
            found_valid = True

        if found_valid and first_start is None:
            first_start = m.start()

    leading_text = text[:first_start] if first_start is not None else text
    return leading_text, calls


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
        self._client = openai.OpenAI(
            base_url=OPENROUTER_BASE_URL, api_key=api_key, max_retries=5,
        )
        self.messages = self

    def create(self, model, max_tokens, system=None, tools=None, messages=None,
               thinking=None):
        # `thinking` (Anthropic's extended-thinking config) has no OpenRouter
        # equivalent - accepted here only so callers can use one uniform
        # interface across both clients. OpenRouter reasoning models surface
        # their reasoning automatically via `message.reasoning`, captured
        # below regardless of this argument.
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
                return _Response(blocks)

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

        return _Response(blocks)


def get_client(model: str):
    """Return an API client for the given model: OpenRouter for
    "provider/model"-style IDs, the native Anthropic API otherwise."""
    if is_openrouter_model(model):
        return OpenRouterClient()
    import anthropic
    return anthropic.Anthropic()
