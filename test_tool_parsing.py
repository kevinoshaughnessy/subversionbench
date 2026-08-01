"""
Tests for subversionbench/tool_parsing.py.

Recovering tool calls a model emitted as prose. Some OpenRouter backends do not
support function calling and silently ignore `tools`; without this repair the
episode reads as a model that chose to talk rather than act, which is a
behavioural claim the harness would be making up.

Run: pytest test_tool_parsing.py -v
"""

import json



# =========================================================================
# Tests: OpenRouter raw tool-call token recovery
# =========================================================================

class TestRawToolCallParsing:
    """Tests for llm_client._parse_raw_tool_call_text().

    Some OpenRouter backends (seen with deepseek/deepseek-r1) leak the
    model's native tool-call token syntax into plain text instead of
    populating the structured `tool_calls` field, which would otherwise
    look like "the model is done" and end the episode early.
    """

    def _parse(self, text):
        from subversionbench.tool_parsing import _parse_raw_tool_call_text
        return _parse_raw_tool_call_text(text)

    def test_recovers_single_tool_call(self):
        text = (
            "Let's start by examining the comms directory."
            "<｜tool▁calls▁begin｜><｜tool▁call▁begin｜>function<｜tool▁sep｜>bash\n"
            "```json\n{\"cmd\": \"ls comms\"}\n```"
            "<｜tool▁call▁end｜><｜tool▁calls▁end｜>"
        )
        leading, calls = self._parse(text)
        assert leading == "Let's start by examining the comms directory."
        assert calls == [("bash", {"cmd": "ls comms"})]

    def test_recovers_args_with_quotes_and_pipes(self):
        """Regression case from an actual deepseek-r1 run: quotes and a
        shell pipe inside the command argument must not break parsing."""
        text = (
            "Let me refine the recommendation:"
            "<｜tool▁calls▁begin｜><｜tool▁call▁begin｜>function<｜tool▁sep｜>bash\n"
            "```json\n"
            "{\"cmd\": \"echo 'Strategy A' | ./scripts/check_recommendation.sh\"}\n"
            "```<｜tool▁call▁end｜><｜tool▁calls▁end｜>"
        )
        leading, calls = self._parse(text)
        assert leading == "Let me refine the recommendation:"
        assert calls == [
            ("bash", {"cmd": "echo 'Strategy A' | ./scripts/check_recommendation.sh"})
        ]

    def test_no_markers_returns_full_text_and_no_calls(self):
        leading, calls = self._parse("Just a normal response, no tool calls here.")
        assert leading == "Just a normal response, no tool calls here."
        assert calls == []
# =========================================================================
# Tests: OpenRouter bracket-style tool-call recovery (Llama 4)
# =========================================================================


# =========================================================================
# Tests: OpenRouter bracket-style tool-call recovery (Llama 4)
# =========================================================================

class TestBracketToolCallParsing:
    """Tests for llm_client._parse_bracket_tool_calls().

    Some OpenRouter backends (seen with llama-4-maverick) leak the model's
    native pythonic "[funcname(arg='value')]" tool-call syntax into plain
    text instead of populating the structured `tool_calls` field, which
    would otherwise look like "the model is done" and end the episode
    early.
    """

    def _parse(self, text, valid_names=frozenset({"bash"})):
        from subversionbench.tool_parsing import _parse_bracket_tool_calls
        return _parse_bracket_tool_calls(text, valid_names)

    def test_recovers_real_failure_case(self):
        """Regression case from an actual llama-4-maverick run."""
        text = (
            "To begin working on the Millbrook transport strategy, I will "
            "first review the README file to understand the project's "
            "context, objectives, and the structure of the available "
            "documentation and data.\n[bash(cmd='cat README.md')]"
        )
        leading, calls = self._parse(text)
        assert leading == (
            "To begin working on the Millbrook transport strategy, I will "
            "first review the README file to understand the project's "
            "context, objectives, and the structure of the available "
            "documentation and data.\n"
        )
        assert calls == [("bash", {"cmd": "cat README.md"})]

    def test_recovers_multiple_calls(self):
        text = "Checking both files.[bash(cmd='ls')] [bash(cmd='pwd')]"
        leading, calls = self._parse(text)
        assert leading == "Checking both files."
        assert calls == [("bash", {"cmd": "ls"}), ("bash", {"cmd": "pwd"})]

    def test_recovers_multiple_calls_in_one_bracket(self):
        """Regression case from an actual llama-4-maverick crash: Llama can
        emit several calls comma-separated inside a single bracket
        ("[a(...), b(...)]"), which parses as a Tuple of Call nodes rather
        than a single Call and must not raise."""
        text = (
            "Let me check both directories.\n"
            "[bash(cmd='ls comms'), bash(cmd='ls data')]"
        )
        leading, calls = self._parse(text)
        assert leading == "Let me check both directories.\n"
        assert calls == [("bash", {"cmd": "ls comms"}), ("bash", {"cmd": "ls data"})]

    def test_recovers_one_bracket_call_with_trailing_comma(self):
        leading, calls = self._parse("Checking.\n[bash(cmd='ls'),]")
        assert leading == "Checking.\n"
        assert calls == [("bash", {"cmd": "ls"})]

    def test_recovers_unquoted_argument(self):
        """Regression case from an actual llama-4-maverick run: the model
        left the string argument unquoted ("cmd=cat README.md" instead of
        "cmd='cat README.md'"), which isn't valid Python and makes
        ast.parse raise SyntaxError outright - must fall back rather than
        give up."""
        text = (
            "Let's begin by reading the README file.\n\n"
            "[bash(cmd=cat README.md)]"
        )
        leading, calls = self._parse(text)
        assert leading == "Let's begin by reading the README file.\n\n"
        assert calls == [("bash", {"cmd": "cat README.md"})]

    def test_does_not_recover_ambiguous_multi_kwarg_unquoted(self):
        """More than one unquoted kwarg is genuinely ambiguous (no way to
        tell a comma in a value apart from an argument separator) - must
        not guess."""
        _, calls = self._parse("[bash(cmd=ls, extra=foo)]")
        assert calls == []

    def test_ignores_unrecognized_function_names(self):
        """Ordinary bracketed prose that happens to look call-shaped (but
        doesn't match an offered tool) must not be misread as a call."""
        leading, calls = self._parse("See [reference(2023)] for details.")
        assert leading == "See [reference(2023)] for details."
        assert calls == []

    def test_ignores_calls_with_no_args(self):
        _, calls = self._parse("Running [bash()] now.")
        assert calls == []

    def test_no_brackets_returns_full_text_and_no_calls(self):
        leading, calls = self._parse("Just a normal response, no tool calls here.")
        assert leading == "Just a normal response, no tool calls here."
        assert calls == []
# =========================================================================
# Tests: OpenRouter empty-completion diagnostics
# =========================================================================
