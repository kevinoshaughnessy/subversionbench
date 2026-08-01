"""
Recovering tool calls a model emitted as plain text instead of calling a tool.

Not a normalisation concern but a repair one: some OpenRouter backends do not
support function calling and silently ignore the `tools` parameter, at which
point the model falls back to its own tool-call syntax as prose. Without this
the episode looks like a model that chose to say something rather than act.
"""

import ast
import json
import re
import uuid

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


