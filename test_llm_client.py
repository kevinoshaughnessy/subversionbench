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


class TestThinkingSurface:
    """The reasoning parameter differs by model generation, and sending the
    wrong one does not degrade gracefully - it is an HTTP 400. Opus 5 batches
    failed outright on `thinking.type.enabled` until this table existed."""

    def test_budget_tokens_is_never_sent_to_an_adaptive_model(self):
        """The regression that started this: budget_tokens is rejected from
        Sonnet 5 / Opus 5 onwards, so no code path may emit it for them."""
        from subversionbench.llm_client import resolve_thinking_kwargs

        for model in ("claude-opus-5", "claude-sonnet-5", "claude-opus-4-8",
                      "claude-opus-4-7", "claude-fable-5"):
            for requested in (None, 4096):
                kwargs, _, _ = resolve_thinking_kwargs(model, requested, 8192)
                assert kwargs["thinking"]["type"] == "adaptive", model
                assert "budget_tokens" not in kwargs["thinking"], model

    def test_older_models_still_get_a_budget(self):
        """Adaptive thinking does not exist below the 4.6 generation, so the
        default grader model must keep the old parameter."""
        from subversionbench.llm_client import resolve_thinking_kwargs

        for model in ("claude-haiku-4-5-20251001", "claude-sonnet-4-5",
                      "claude-opus-4-5"):
            kwargs, desc, _ = resolve_thinking_kwargs(model, None, 8192)
            assert kwargs["thinking"] == {
                "type": "enabled", "budget_tokens": 4096,
            }, model
            assert "budget_tokens=4096" in desc

    def test_an_explicit_budget_on_an_adaptive_model_warns(self):
        """Silently ignoring the flag would leave the operator believing they
        had capped reasoning."""
        from subversionbench.llm_client import resolve_thinking_kwargs

        _, _, warnings = resolve_thinking_kwargs("claude-opus-5", 4096, 8192)
        assert any("adaptive" in w for w in warnings)

    def test_summarized_display_is_requested_where_the_default_is_omitted(self):
        """Without this the model returns thinking blocks whose text is empty,
        which is what made native Anthropic runs contribute zero reasoning
        characters while OpenRouter runs contributed thousands."""
        from subversionbench.llm_client import resolve_thinking_kwargs

        kwargs, _, _ = resolve_thinking_kwargs("claude-opus-5", None, 8192)
        assert kwargs["thinking"]["display"] == "summarized"

        # Opus 4.6 already defaults to summarized, so nothing needs asking
        # for - and not sending an unnecessary parameter cannot be rejected.
        kwargs, _, _ = resolve_thinking_kwargs("claude-opus-4-6", None, 8192)
        assert "display" not in kwargs["thinking"]

    def test_openrouter_gets_no_reasoning_parameter_at_all(self):
        from subversionbench.llm_client import resolve_thinking_kwargs

        kwargs, desc, _ = resolve_thinking_kwargs("x-ai/grok-4.5", None, 8192)
        assert kwargs == {}
        assert "OpenRouter" in desc

    def test_disable_uses_the_form_each_family_accepts(self):
        from subversionbench.llm_client import resolve_thinking_kwargs

        kwargs, _, _ = resolve_thinking_kwargs("claude-opus-5", 0, 8192)
        assert kwargs["thinking"] == {"type": "disabled"}

        # Fable/Mythos reject an explicit disable - thinking is always on
        # there, so the only legal way to express it is to send nothing.
        kwargs, desc, warnings = resolve_thinking_kwargs("claude-fable-5", 0, 8192)
        assert "thinking" not in kwargs
        assert "always on" in desc
        assert warnings

        # Below 4.6, unset already means no thinking.
        kwargs, _, _ = resolve_thinking_kwargs("claude-haiku-4-5", 0, 8192)
        assert "thinking" not in kwargs

    def test_effort_is_only_sent_where_it_is_accepted(self):
        from subversionbench.llm_client import resolve_thinking_kwargs

        kwargs, _, warnings = resolve_thinking_kwargs(
            "claude-opus-5", None, 64000, "medium")
        assert kwargs["output_config"] == {"effort": "medium"}
        assert not warnings

        # xhigh arrived after Opus 4.6, and the effort parameter itself
        # errors on Haiku 4.5 - neither may be sent.
        kwargs, _, warnings = resolve_thinking_kwargs(
            "claude-opus-4-6", None, 64000, "xhigh")
        assert "output_config" not in kwargs
        assert warnings

        kwargs, _, warnings = resolve_thinking_kwargs(
            "claude-haiku-4-5", None, 8192, "high")
        assert "output_config" not in kwargs
        assert warnings

    def test_disabling_thinking_above_high_effort_is_refused_up_front(self):
        """Opus 5 rejects that pair with a 400, so it has to fail at argument
        parsing rather than on run 1 of a batch."""
        from subversionbench.llm_client import reasoning_flag_error

        assert reasoning_flag_error("claude-opus-5", 0, "max")
        assert reasoning_flag_error("claude-opus-5", 0, "xhigh")
        assert reasoning_flag_error("claude-opus-5", 0, "high") is None
        assert reasoning_flag_error("claude-opus-5", None, "max") is None
        assert reasoning_flag_error("claude-sonnet-5", 0, "max") is None

    def test_dated_and_bedrock_ids_resolve_to_the_same_family(self):
        from subversionbench.llm_client import thinking_surface

        assert thinking_surface("claude-haiku-4-5-20251001").mode == "budget"
        assert thinking_surface("anthropic.claude-opus-5").mode == "adaptive"
        assert thinking_surface("Claude-Opus-5").mode == "adaptive"

    def test_family_prefixes_do_not_shadow_each_other(self):
        """"claude-opus-4" is a prefix of "claude-opus-4-8", so a careless
        table would classify the newer model as the older one."""
        from subversionbench.llm_client import thinking_surface

        assert thinking_surface("claude-opus-4-8").mode == "adaptive"
        assert thinking_surface("claude-opus-4-0").mode == "budget"
        assert thinking_surface("claude-sonnet-4-6").mode == "adaptive"
        assert thinking_surface("claude-sonnet-4-5").mode == "budget"

    def test_an_unknown_anthropic_model_is_assumed_modern(self):
        """Every model predating adaptive thinking is already in the table, so
        an unrecognised ID is a newer one - and guessing "budget" for it would
        fail every request."""
        from subversionbench.llm_client import (
            thinking_surface, is_known_anthropic_model,
        )

        assert thinking_surface("claude-opus-6").mode == "adaptive"
        assert not is_known_anthropic_model("claude-opus-6")
        assert is_known_anthropic_model("claude-opus-5")


class TestGraderThinking:
    """The grader asks for 200 tokens of JSON. Thinking is on by default from
    Sonnet 5 / Opus 5 onwards, so leaving the parameter unset lets a grader
    spend its whole budget reasoning and return no verdict - which the eval
    would record as a grading failure, not a configuration error."""

    def test_thinking_is_turned_off_for_short_grader_calls(self):
        from subversionbench.llm_client import short_call_thinking_kwargs

        kwargs, tokens = short_call_thinking_kwargs("claude-opus-5", 200)
        assert kwargs["thinking"] == {"type": "disabled"}
        assert tokens == 200

    def test_older_grader_models_are_left_alone(self):
        from subversionbench.llm_client import short_call_thinking_kwargs

        kwargs, tokens = short_call_thinking_kwargs(
            "claude-haiku-4-5-20251001", 200)
        assert kwargs == {}
        assert tokens == 200

    def test_a_forced_thinking_grader_gets_room_for_its_answer(self):
        """Fable/Mythos cannot turn thinking off, and thinking comes out of the
        same max_tokens as the answer."""
        from subversionbench.llm_client import short_call_thinking_kwargs

        kwargs, tokens = short_call_thinking_kwargs("claude-fable-5", 200)
        assert kwargs == {}
        assert tokens >= 4096

    def test_openrouter_grader_gets_no_parameter(self):
        from subversionbench.llm_client import short_call_thinking_kwargs

        kwargs, tokens = short_call_thinking_kwargs("x-ai/grok-4.5", 200)
        assert kwargs == {}
        assert tokens == 200
