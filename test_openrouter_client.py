"""
Tests for subversionbench/openrouter_client.py.

Responses that are empty or not JSON. Both used to surface as an exception
several layers inside the SDK with no indication of what actually came back.

Run: pytest test_openrouter_client.py -v
"""


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
        from subversionbench.openrouter_client import OpenRouterClient

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
        from subversionbench.openrouter_client import OpenRouterClient

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
