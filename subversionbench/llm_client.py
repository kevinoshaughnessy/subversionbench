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
from collections import namedtuple

from .config import OPENROUTER_BASE_URL


def is_openrouter_model(model: str) -> bool:
    return "/" in model


# =========================================================================
# Anthropic reasoning-control surface, by model family
# =========================================================================
#
# Anthropic replaced the fixed thinking budget with adaptive thinking, and
# the old parameter is not merely deprecated on the newer models - it is
# rejected:
#
#   thinking={"type": "enabled", "budget_tokens": N}
#     HTTP 400 on Fable 5, Mythos 5, Opus 5, Opus 4.8, Opus 4.7, Sonnet 5.
#     Deprecated but still functional on Opus 4.6 / Sonnet 4.6.
#     Still the only way to turn thinking on at or below Sonnet 4.5 /
#     Haiku 4.5 / Opus 4.5.
#
#   thinking={"type": "adaptive"}
#     Supported from the 4.6 generation onwards; the model decides how much
#     to think. Depth is steered by output_config={"effort": ...} instead of
#     a token count.
#
# So the eval cannot send one reasoning config to every model. Sending the
# wrong one does not degrade gracefully - it fails the request, which is how
# this table came to exist.
#
# Fields:
#   mode         "adaptive" or "budget" - which thinking parameter is accepted
#   effort       effort levels this model accepts; empty means the
#                output_config.effort parameter itself errors (Sonnet 4.5,
#                Haiku 4.5 and older)
#   can_disable  accepts thinking={"type": "disabled"}. False for the Fable /
#                Mythos family, where thinking is always on and an explicit
#                "disabled" is a 400 - there, thinking has to be left unset.
#   display_omitted
#                the model's default thinking.display is "omitted", i.e. it
#                returns thinking blocks whose text is an empty string unless
#                display="summarized" is asked for. This is the whole reason
#                the eval saw empty reasoning from Opus 5.
_Surface = namedtuple(
    "_Surface", "mode effort can_disable display_omitted",
)

_EFFORT_FULL = frozenset({"low", "medium", "high", "xhigh", "max"})
_EFFORT_NO_XHIGH = frozenset({"low", "medium", "high", "max"})
_EFFORT_BASIC = frozenset({"low", "medium", "high"})
_EFFORT_NONE = frozenset()

EFFORT_LEVELS = _EFFORT_FULL

# Matched as prefixes against the model ID, first match winning, so a bare
# family name must come after every dated or dotted variant of it
# ("claude-opus-4" is a prefix of "claude-opus-4-8").
_MODEL_SURFACES = (
    ("claude-fable-5",        _Surface("adaptive", _EFFORT_FULL,     False, True)),
    ("claude-mythos-5",       _Surface("adaptive", _EFFORT_FULL,     False, True)),
    ("claude-mythos-preview", _Surface("adaptive", _EFFORT_FULL,     False, True)),
    ("claude-opus-5",         _Surface("adaptive", _EFFORT_FULL,     True,  True)),
    ("claude-opus-4-8",       _Surface("adaptive", _EFFORT_FULL,     True,  True)),
    ("claude-opus-4-7",       _Surface("adaptive", _EFFORT_FULL,     True,  True)),
    ("claude-opus-4-6",       _Surface("adaptive", _EFFORT_NO_XHIGH, True,  False)),
    ("claude-sonnet-5",       _Surface("adaptive", _EFFORT_FULL,     True,  True)),
    ("claude-sonnet-4-6",     _Surface("adaptive", _EFFORT_NO_XHIGH, True,  False)),
    ("claude-opus-4-5",       _Surface("budget",   _EFFORT_BASIC,    False, False)),
    ("claude-opus-4-1",       _Surface("budget",   _EFFORT_NONE,     False, False)),
    ("claude-opus-4",         _Surface("budget",   _EFFORT_NONE,     False, False)),
    ("claude-sonnet-4-5",     _Surface("budget",   _EFFORT_NONE,     False, False)),
    ("claude-sonnet-4",       _Surface("budget",   _EFFORT_NONE,     False, False)),
    ("claude-haiku-4-5",      _Surface("budget",   _EFFORT_NONE,     False, False)),
    ("claude-3",              _Surface("budget",   _EFFORT_NONE,     False, False)),
    ("claude-2",              _Surface("budget",   _EFFORT_NONE,     False, False)),
)

# Assumed for an unrecognised native model ID. Adaptive rather than budget,
# because every Anthropic model that predates adaptive thinking is already
# named in the table above - an ID that is not there is a model released
# after it was written, and those take adaptive.
_DEFAULT_SURFACE = _Surface("adaptive", _EFFORT_FULL, True, True)

# Opus 5 accepts thinking={"type": "disabled"} only at effort "high" or
# below; pairing it with "xhigh" or "max" is a 400.
_NO_DISABLE_ABOVE_HIGH = ("claude-opus-5",)

_HIGH_EFFORTS = ("xhigh", "max")


def _normalise_model(model: str) -> str:
    """Strip provider decoration so a Bedrock-style ID resolves to the same
    family as the first-party one."""
    return model.strip().lower().removeprefix("anthropic.")


def thinking_surface(model: str):
    """Which reasoning parameters this Anthropic model accepts. None for an
    OpenRouter model, which takes none of them."""
    if is_openrouter_model(model):
        return None
    name = _normalise_model(model)
    for prefix, surface in _MODEL_SURFACES:
        if name.startswith(prefix):
            return surface
    return _DEFAULT_SURFACE


def is_known_anthropic_model(model: str) -> bool:
    """Whether the ID matched the table rather than falling back to the
    assumed-modern default."""
    if is_openrouter_model(model):
        return False
    name = _normalise_model(model)
    return any(name.startswith(prefix) for prefix, _ in _MODEL_SURFACES)


# Anthropic's documented floor for budget_tokens, on the older models that
# still accept a budget at all.
MIN_THINKING_BUDGET = 1024

# On a model where thinking cannot be turned off, thinking tokens come out of
# the same max_tokens as the answer, so a 200-token grader call would spend
# its whole budget reasoning and return no verdict.
MIN_TOKENS_WHEN_THINKING_FORCED = 4096


def resolve_thinking_budget(requested, max_tokens: int):
    """
    Decide the extended-thinking budget for a model that takes one.

    Reasoning has to be captured by default, because whether it is captured
    silently changes what the eval measures. Both eval-awareness detectors
    read `thinking` entries, so a model whose reasoning is returned is scored
    on strictly more evidence than one whose is not - and the two are not
    comparable. In one pair of pilots an OpenRouter model contributed 102k
    characters of reasoning while native Anthropic runs contributed none,
    purely because extended thinking defaulted to off.

    There is no OpenRouter setting to copy here. That path sends no reasoning
    parameter; reasoning appears only when the model volunteers it, as
    always-reasoning models do. So the budget is chosen on its own terms:
    half the output budget for reasoning and half for the answer, which
    scales if --max-tokens is raised for a verbose model.

    `requested` of None means auto, 0 means off, anything else is explicit.
    Returns (budget, description).
    """
    if requested == 0:
        return 0, "disabled (--thinking-budget 0)"
    if requested is not None:
        return requested, f"explicit (--thinking-budget {requested})"

    budget = max_tokens // 2
    if budget < MIN_THINKING_BUDGET:
        # The API floor and room for a visible answer cannot both fit.
        return 0, (f"disabled automatically: --max-tokens {max_tokens} leaves "
                   f"no room for a {MIN_THINKING_BUDGET}-token minimum "
                   f"budget plus an answer")
    return budget, f"auto (half of --max-tokens {max_tokens})"


def reasoning_flag_error(model: str, requested_budget, effort):
    """
    The one flag combination that cannot be satisfied, as a message for the
    CLI to fail on - reported before a batch starts rather than as a 400 on
    run 1. Returns None if the request is satisfiable.
    """
    if effort and effort not in EFFORT_LEVELS:
        return (f"--effort must be one of "
                f"{', '.join(sorted(EFFORT_LEVELS))}; got {effort!r}.")

    surface = thinking_surface(model)
    if surface is None or surface.mode != "adaptive":
        return None
    if requested_budget != 0 or effort not in _HIGH_EFFORTS:
        return None
    if not _normalise_model(model).startswith(_NO_DISABLE_ABOVE_HIGH):
        return None
    return (
        f"{model} rejects thinking={{'type': 'disabled'}} at effort "
        f"{effort!r} - disabling thinking is only accepted at effort 'high' "
        f"or below. Either drop --thinking-budget 0 or use a lower --effort."
    )


# Substrings the SDKs use when no usable credential was found, or when the one
# supplied was rejected. Matched case-insensitively against str(exception).
_AUTH_ERROR_MARKERS = (
    "could not resolve authentication method",
    "authentication_error",
    "invalid x-api-key",
    "invalid api key",
    "no api key",
    "api key not found",
    "incorrect api key",
    "unauthorized",
    "401",
)


def is_auth_error(error) -> bool:
    """
    Whether `error` is a missing or rejected credential.

    Worth separating from every other API failure because it is the one class
    that cannot come right on retry and is never partial: an unexported key
    fails identically on call 1 and call 500. A caller that treats it as a
    transient error will grind through a whole batch producing fallbacks, so
    the honest response is to stop on the first one.
    """
    if not error:
        return False
    text = str(error).lower()
    return any(marker in text for marker in _AUTH_ERROR_MARKERS)


def resolve_thinking_kwargs(model: str, requested_budget=None,
                            max_tokens: int = 8192, effort=None):
    """
    Build the reasoning parameters for one model, whichever generation it is.

    `requested_budget` keeps the CLI's meaning - None is auto, 0 is off,
    anything else is an explicit token budget - but a token budget is only
    expressible on the older models. On an adaptive model the request is
    honoured in kind rather than refused: auto and any explicit budget both
    become adaptive thinking, since the point of the default is that
    reasoning is captured, not that it is capped at a particular number.

    Returns (kwargs, description, warnings): kwargs to merge into
    client.messages.create(...), one line describing what was sent for the
    console and the summary JSON, and any operator-facing warnings.
    """
    surface = thinking_surface(model)
    warnings = []

    if surface is None:
        if requested_budget:
            warnings.append(
                f"--thinking-budget {requested_budget} does not apply to "
                f"OpenRouter model {model}: that API takes no reasoning "
                f"parameter. Reasoning is captured when the backend "
                f"volunteers it."
            )
        if effort:
            warnings.append(
                f"--effort {effort} does not apply to OpenRouter model "
                f"{model}."
            )
        return {}, "not sent (OpenRouter takes no reasoning parameter)", warnings

    kwargs = {}
    effort_note = ""
    if effort:
        if effort in surface.effort:
            kwargs["output_config"] = {"effort": effort}
            effort_note = f", effort={effort}"
            if effort in _HIGH_EFFORTS and max_tokens < 32000:
                warnings.append(
                    f"--effort {effort} with --max-tokens {max_tokens}: at "
                    f"this effort the model is expected to think and act "
                    f"across many tokens, and thinking counts against "
                    f"max_tokens, so answers may truncate. Anthropic "
                    f"suggests at least 64000 here."
                )
        else:
            accepted = (", ".join(sorted(surface.effort)) if surface.effort
                        else "none - the parameter itself errors on this model")
            warnings.append(
                f"--effort {effort} is not accepted by {model} (accepted: "
                f"{accepted}); sending no effort and using the API default."
            )

    if surface.mode == "budget":
        budget, source = resolve_thinking_budget(requested_budget, max_tokens)
        if budget > 0:
            kwargs["thinking"] = {
                "type": "enabled", "budget_tokens": budget,
            }
        return (kwargs, f"budget_tokens={budget} - {source}{effort_note}",
                warnings)

    # Adaptive generation.
    if requested_budget == 0:
        if surface.can_disable:
            kwargs["thinking"] = {"type": "disabled"}
            return (kwargs,
                    f"disabled (--thinking-budget 0){effort_note}", warnings)
        warnings.append(
            f"--thinking-budget 0 cannot be honoured for {model}: thinking is "
            f"always on for this model family and an explicit disable is "
            f"rejected. Leaving the parameter unset."
        )
        return kwargs, f"always on for this model{effort_note}", warnings

    if requested_budget:
        warnings.append(
            f"--thinking-budget {requested_budget} is not accepted by {model} "
            f"- the fixed thinking budget was replaced by adaptive thinking, "
            f"and sending budget_tokens is an HTTP 400. Using adaptive "
            f"thinking instead; steer depth with --effort."
        )

    thinking = {"type": "adaptive"}
    detail = "adaptive"
    if surface.display_omitted:
        # Without this the model still returns thinking blocks, but their
        # text is empty - which is what made native Anthropic runs contribute
        # zero reasoning characters while OpenRouter runs contributed
        # thousands. The raw chain of thought is never returned by these
        # models; a summary is the most that is available.
        thinking["display"] = "summarized"
        detail = "adaptive (display=summarized)"
    kwargs["thinking"] = thinking
    return kwargs, f"{detail}{effort_note}", warnings


def short_call_thinking_kwargs(model: str, max_tokens: int):
    """
    Reasoning config for the short JSON-only grader and classifier calls.

    These ask for a couple of hundred tokens of JSON, and thinking is on by
    default from Sonnet 5 / Opus 5 onwards - so leaving the parameter unset
    lets a grader spend its entire max_tokens reasoning and return no verdict
    at all, which the eval would record as a grading failure. Turn thinking
    off for these calls where the model allows it, and give the answer room
    where it does not.

    Returns (kwargs, max_tokens).
    """
    surface = thinking_surface(model)
    if surface is None or surface.mode == "budget":
        # No reasoning parameter, or a model where unset already means off.
        return {}, max_tokens
    if surface.can_disable:
        return {"thinking": {"type": "disabled"}}, max_tokens
    return {}, max(max_tokens, MIN_TOKENS_WHEN_THINKING_FORCED)


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
