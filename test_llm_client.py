"""
Tests for subversionbench/llm_client.py.

Covers recovery of tool calls emitted as raw text, and OpenRouter
responses that are empty or not JSON.

Run: pytest test_llm_client.py -v
"""

import os
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
        from subversionbench.llm_client import _parse_raw_tool_call_text
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

class TestBracketToolCallParsing:
    """Tests for llm_client._parse_bracket_tool_calls().

    Some OpenRouter backends (seen with llama-4-maverick) leak the model's
    native pythonic "[funcname(arg='value')]" tool-call syntax into plain
    text instead of populating the structured `tool_calls` field, which
    would otherwise look like "the model is done" and end the episode
    early.
    """

    def _parse(self, text, valid_names=frozenset({"bash"})):
        from subversionbench.llm_client import _parse_bracket_tool_calls
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

class TestOpenRouterEmptyCompletion:
    """A reasoning model (e.g. deepseek-r1) can spend its whole max_tokens
    budget on internal reasoning and return no content and no tool call.
    That must surface as a diagnostic message, not silently end the
    episode with no explanation."""

    def _make_client(self):
        from unittest.mock import MagicMock
        import os
        from subversionbench.llm_client import OpenRouterClient

        os.environ.setdefault("OPENROUTER_API_KEY", "dummy")
        client = OpenRouterClient()
        client._client = MagicMock()
        return client

    def _set_completion(self, client, fake_completion):
        """create() fetches the raw HTTP response and calls .parse() on it
        (rather than the auto-parsing convenience method) so a non-JSON
        body can be diagnosed - route the mock through that same shape."""
        from unittest.mock import MagicMock
        fake_raw = MagicMock()
        fake_raw.parse.return_value = fake_completion
        client._client.chat.completions.with_raw_response.create.return_value = fake_raw

    def test_empty_completion_yields_diagnostic_text(self):
        from unittest.mock import MagicMock

        client = self._make_client()

        fake_message = MagicMock()
        fake_message.content = None
        fake_message.tool_calls = None
        fake_message.reasoning = "thinking..." * 100

        fake_choice = MagicMock()
        fake_choice.message = fake_message
        fake_choice.finish_reason = "length"

        fake_completion = MagicMock()
        fake_completion.choices = [fake_choice]
        self._set_completion(client, fake_completion)

        response = client.create(
            model="deepseek/deepseek-r1", max_tokens=4096, system="sys",
            tools=[{"name": "bash", "description": "d",
                    "input_schema": {"type": "object"}}],
            messages=[{"role": "user", "content": "hi"}],
        )

        # The reasoning is still captured as a thinking block, followed by
        # the diagnostic explaining why there's no visible answer/tool call.
        assert len(response.content) == 2
        assert response.content[0].type == "thinking"
        assert response.content[1].type == "text"
        assert "finish_reason=length" in response.content[1].text
        assert "reasoning_chars" in response.content[1].text

    def test_normal_completion_unaffected(self):
        from unittest.mock import MagicMock

        client = self._make_client()

        fake_message = MagicMock()
        fake_message.content = "Here is my answer."
        fake_message.tool_calls = None
        fake_message.reasoning = None

        fake_choice = MagicMock()
        fake_choice.message = fake_message
        fake_choice.finish_reason = "stop"

        fake_completion = MagicMock()
        fake_completion.choices = [fake_choice]
        self._set_completion(client, fake_completion)

        response = client.create(
            model="deepseek/deepseek-r1", max_tokens=4096,
            messages=[{"role": "user", "content": "hi"}],
        )

        assert len(response.content) == 1
        assert response.content[0].text == "Here is my answer."

    def test_reasoning_captured_as_thinking_block(self):
        """The core ask: chain-of-thought reasoning from OpenRouter models
        should be captured and recorded, not discarded."""
        from unittest.mock import MagicMock

        client = self._make_client()

        fake_tool_call = MagicMock()
        fake_tool_call.id = "call_1"
        fake_tool_call.function.name = "bash"
        fake_tool_call.function.arguments = '{"cmd": "ls"}'

        fake_message = MagicMock()
        fake_message.content = None
        fake_message.tool_calls = [fake_tool_call]
        fake_message.reasoning = "I should check the directory listing first."

        fake_choice = MagicMock()
        fake_choice.message = fake_message
        fake_choice.finish_reason = "tool_calls"

        fake_completion = MagicMock()
        fake_completion.choices = [fake_choice]
        self._set_completion(client, fake_completion)

        response = client.create(
            model="deepseek/deepseek-r1", max_tokens=4096,
            tools=[{"name": "bash", "description": "d",
                    "input_schema": {"type": "object"}}],
            messages=[{"role": "user", "content": "hi"}],
        )

        assert len(response.content) == 2
        assert response.content[0].type == "thinking"
        assert response.content[0].thinking == (
            "I should check the directory listing first."
        )
        assert response.content[1].type == "tool_use"
        assert response.content[1].input == {"cmd": "ls"}
# =========================================================================
# Tests: OpenRouter non-JSON response diagnostics
# =========================================================================

class TestOpenRouterNonJsonResponse:
    """If the upstream provider returns a non-JSON body (an error page, a
    streaming/SSE body served when a plain response was requested, a
    connection dropped mid-response), the raw json.JSONDecodeError from
    deep inside the SDK/httpx gives no way to tell what happened. create()
    must surface the actual HTTP status and body instead."""

    def _make_client(self):
        from unittest.mock import MagicMock
        import os
        from subversionbench.llm_client import OpenRouterClient

        os.environ.setdefault("OPENROUTER_API_KEY", "dummy")
        client = OpenRouterClient()
        client._client = MagicMock()
        return client

    def test_non_json_body_raises_informative_error(self):
        from unittest.mock import MagicMock
        import json

        client = self._make_client()

        fake_raw = MagicMock()
        fake_raw.status_code = 502
        fake_raw.text = "data: {\"partial\": true}\n\n" * 5
        fake_raw.parse.side_effect = json.JSONDecodeError(
            "Expecting value", fake_raw.text, 0
        )
        client._client.chat.completions.with_raw_response.create.return_value = fake_raw

        try:
            client.create(
                model="openai/gpt-5.5", max_tokens=4096,
                tools=[{"name": "bash", "description": "d",
                        "input_schema": {"type": "object"}}],
                messages=[{"role": "user", "content": "hi"}],
            )
            assert False, "expected RuntimeError"
        except RuntimeError as e:
            assert "openai/gpt-5.5" in str(e)
            assert "502" in str(e)
            assert "partial" in str(e)
