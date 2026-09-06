"""
Tests for subversionbench/tool_parsing.py.

Recovering tool calls a model emitted as prose. Some OpenRouter backends do not
support function calling and silently ignore `tools`; without this repair the
episode reads as a model that chose to talk rather than act, which is a
behavioural claim the harness would be making up.

Run: pytest test_tool_parsing.py -v
"""




from subversionbench.scenario import CLIENT_NAME

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
            f"To begin working on the {CLIENT_NAME} transport strategy, I will "
            "first review the README file to understand the project's "
            "context, objectives, and the structure of the available "
            "documentation and data.\n[bash(cmd='cat README.md')]"
        )
        leading, calls = self._parse(text)
        assert leading == (
            f"To begin working on the {CLIENT_NAME} transport strategy, I will "
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


class TestTheUnquotedKwargRecoveryKnowsWhenToDecline:
    """_parse_unquoted_single_kwarg, the fallback for an argument the model
    left unquoted - which is not valid Python and makes ast.parse reject the
    whole call.

    Guessing is safe for this eval's one-parameter `bash` tool and unsafe in
    general, so what matters as much as what it recovers is what it refuses
    to. A wrong guess here does not fail: it runs a DIFFERENT command from
    the one the model asked for, and records that as what the model did.
    """

    def _parse(self, args_str):
        from subversionbench.tool_parsing import _parse_unquoted_single_kwarg
        return _parse_unquoted_single_kwarg(args_str)

    def test_a_single_unquoted_argument_is_recovered(self):
        assert self._parse("cmd=cat README.md") == {"cmd": "cat README.md"}

    def test_text_that_is_not_a_keyword_argument_is_declined(self):
        """No name, no equals sign - there is nothing to recover, and
        returning a dict keyed on a guess would invent a call."""
        for text in ("just some prose", "", "   ", "=novalue",
                     "9lives=cat x"):
            assert self._parse(text) is None, text

    def test_a_second_equals_sign_is_declined_as_ambiguous(self):
        """It could be a second keyword argument or a literal `=` inside an
        unquoted value, and nothing in the text distinguishes them. The
        wrong reading runs a command the model did not write."""
        assert self._parse("cmd=ls, extra=foo") is None
        assert self._parse("cmd=export A=B") is None

    def test_a_quoted_value_has_its_quotes_removed_once(self):
        """Reached when the value is quoted but the call still failed to
        parse for some other reason. Leaving the quotes on would run a
        command that begins and ends with a quote character."""
        assert self._parse("cmd='ls -la'") == {"cmd": "ls -la"}
        assert self._parse('cmd="ls -la"') == {"cmd": "ls -la"}

    def test_mismatched_or_internal_quotes_are_left_alone(self):
        """Only a matching outer pair is stripped. A value that merely
        CONTAINS a quote is not a quoted value, and taking its first and
        last characters off would corrupt the command."""
        assert self._parse("cmd='ls -la") == {"cmd": "'ls -la"}
        assert self._parse("cmd=echo \"hi\" there") == {
            "cmd": 'echo "hi" there'}

    def test_a_value_of_one_character_is_not_treated_as_quotes(self):
        """len(value) >= 2 guards this: a single quote character is its own
        first and last character, and stripping it would leave nothing."""
        assert self._parse("cmd='") == {"cmd": "'"}


class TestAGarbledBracketKeepsTheCallsItCanRead:
    """The bracket contents are parsed by wrapping them in `f(...)`, which
    makes a comma-joined leak come back as a tuple. Anything in that tuple
    that is not a call is not a tool call, and the alternative to skipping it
    is losing the calls beside it - which ends the episode as though the model
    had finished, on a turn where it was mid-tool-loop.
    """

    def _parse(self, text, valid_names=frozenset({"bash"})):
        from subversionbench.tool_parsing import _parse_bracket_tool_calls
        return _parse_bracket_tool_calls(text, valid_names)

    def test_a_non_call_beside_a_real_call_does_not_cost_the_call(self):
        leading, calls = self._parse("[bash(cmd='ls'), (42)]")
        assert calls == [("bash", {"cmd": "ls"})]
        assert leading == ""

    def test_two_real_calls_in_the_same_shape_both_survive(self):
        """The control: the shape above is only interesting because this one
        parses as a tuple too, so the skip is about the element and not about
        the tuple."""
        _leading, calls = self._parse("[bash(cmd='ls'), (bash(cmd='pwd'))]")
        assert calls == [("bash", {"cmd": "ls"}), ("bash", {"cmd": "pwd"})]
