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


class TestOpenRouterNoChoicesResponse:
    """A body that parses as valid JSON is not necessarily a completion - a
    moderation block, a rate limit, or a provider-side failure can all come
    back as a well-formed JSON object with no "choices" at all, which the
    SDK's typed model reports as None rather than raising itself.
    completion.choices[0] on that is a bare TypeError: 'NoneType' object is
    not subscriptable, three layers from anything that says what actually
    happened - moonshotai/kimi-k2-thinking hit this live, 30 clean turns
    into a real episode, with no other diagnostic in the failure."""

    def _make_client(self):
        from unittest.mock import MagicMock
        import os
        from subversionbench.openrouter_client import OpenRouterClient

        os.environ.setdefault("OPENROUTER_API_KEY", "dummy")
        client = OpenRouterClient()
        client._client = MagicMock()
        return client

    def _fake_raw(self, choices, status=200, body="{}"):
        from unittest.mock import MagicMock
        fake_raw = MagicMock()
        fake_raw.status_code = status
        fake_raw.text = body
        fake_completion = MagicMock()
        fake_completion.choices = choices
        fake_raw.parse.return_value = fake_completion
        return fake_raw

    def test_choices_none_raises_an_informative_error_not_a_bare_typeerror(self):
        client = self._make_client()
        fake_raw = self._fake_raw(
            None, status=200,
            body='{"error": {"message": "moderation_blocked"}}')
        client._client.chat.completions.with_raw_response.create.return_value = fake_raw

        try:
            client.create(
                model="moonshotai/kimi-k2-thinking", max_tokens=4096,
                tools=[{"name": "bash", "description": "d",
                        "input_schema": {"type": "object"}}],
                messages=[{"role": "user", "content": "hi"}],
            )
            assert False, "expected RuntimeError"
        except RuntimeError as e:
            assert "moonshotai/kimi-k2-thinking" in str(e)
            assert "200" in str(e)
            assert "moderation_blocked" in str(e)
        except TypeError:
            assert False, "a bare TypeError reached the caller"

    def test_choices_empty_list_is_also_caught(self):
        """An empty list previously raised IndexError instead of TypeError -
        a different but equally uninformative crash, from the same missing
        guard."""
        client = self._make_client()
        fake_raw = self._fake_raw([], status=429, body='{"error": "rate limited"}')
        client._client.chat.completions.with_raw_response.create.return_value = fake_raw

        try:
            client.create(
                model="moonshotai/kimi-k2-thinking", max_tokens=4096,
                tools=[{"name": "bash", "description": "d",
                        "input_schema": {"type": "object"}}],
                messages=[{"role": "user", "content": "hi"}],
            )
            assert False, "expected RuntimeError"
        except RuntimeError as e:
            assert "429" in str(e)
        except IndexError:
            assert False, "a bare IndexError reached the caller"


class TestProviderSortRouting:
    """--openrouter-sort ('price' or 'throughput') is opt-in per client and
    must reach OpenRouter as extra_body.provider.sort, independently of
    whether `tools` is also sending require_parameters - one must not imply
    or crowd out the other in the same provider dict."""

    def _make_client(self, provider_sort=None):
        from unittest.mock import MagicMock
        import os
        from subversionbench.openrouter_client import OpenRouterClient

        os.environ.setdefault("OPENROUTER_API_KEY", "dummy")
        client = OpenRouterClient(provider_sort=provider_sort)
        client._client = MagicMock()

        fake_message = MagicMock()
        fake_message.content = "ok"
        fake_message.tool_calls = None
        fake_message.reasoning = None
        fake_choice = MagicMock()
        fake_choice.message = fake_message
        fake_choice.finish_reason = "stop"
        fake_completion = MagicMock()
        fake_completion.choices = [fake_choice]
        fake_raw = MagicMock()
        fake_raw.parse.return_value = fake_completion
        client._client.chat.completions.with_raw_response.create.return_value = fake_raw
        return client

    def _sent_kwargs(self, client):
        return client._client.chat.completions.with_raw_response.create.call_args.kwargs

    def test_sort_is_sent_when_requested(self):
        client = self._make_client(provider_sort="throughput")
        client.create(model="qwen/qwen3.8-27b", max_tokens=4096,
                      messages=[{"role": "user", "content": "hi"}])
        assert self._sent_kwargs(client)["extra_body"]["provider"]["sort"] == "throughput"

    def test_no_provider_key_at_all_when_not_requested_and_no_tools(self):
        """The default (no flag, no tools) must reproduce the exact request
        shape from before --openrouter-sort existed - no empty provider dict
        sent where none was sent previously."""
        client = self._make_client(provider_sort=None)
        client.create(model="qwen/qwen3.8-27b", max_tokens=4096,
                      messages=[{"role": "user", "content": "hi"}])
        assert "extra_body" not in self._sent_kwargs(client)

    def test_sort_and_require_parameters_coexist_when_both_apply(self):
        client = self._make_client(provider_sort="price")
        client.create(
            model="qwen/qwen3.8-27b", max_tokens=4096,
            tools=[{"name": "bash", "description": "d",
                    "input_schema": {"type": "object"}}],
            messages=[{"role": "user", "content": "hi"}],
        )
        provider = self._sent_kwargs(client)["extra_body"]["provider"]
        assert provider == {"require_parameters": True, "sort": "price"}

    def test_require_parameters_alone_is_unaffected_by_no_sort(self):
        """Guards the pre-existing behaviour: tools with no sort requested
        must send exactly what it always sent."""
        client = self._make_client(provider_sort=None)
        client.create(
            model="qwen/qwen3.8-27b", max_tokens=4096,
            tools=[{"name": "bash", "description": "d",
                    "input_schema": {"type": "object"}}],
            messages=[{"role": "user", "content": "hi"}],
        )
        provider = self._sent_kwargs(client)["extra_body"]["provider"]
        assert provider == {"require_parameters": True}


class TestTheTranslationIntoChatCompletions:
    """The OpenRouter twin of test_openai_client.py's TestResponsesTranslation.

    The two adapters do the same job for different wire formats. Only the Responses
    one was tested, and this is the route r1-r3 were collected through, so the
    cross-family comparison rests on a translation nothing checked.

    Chat-completions differs from Responses in exactly the way that breaks a tool
    loop quietly: tool calls nest inside the assistant message and results come
    back as their own `tool` role message keyed by `tool_call_id`.
    """

    def test_a_string_content_passes_straight_through(self):
        from subversionbench.openrouter_client import _to_openai_messages
        assert _to_openai_messages({"role": "user", "content": "hello"}) == [
            {"role": "user", "content": "hello"}]

    def test_a_tool_call_nests_inside_the_assistant_message(self):
        """Unlike Responses, where it is a sibling item. One assistant message
        carrying its calls, or the model never sees that it made them."""
        from subversionbench.openrouter_client import _to_openai_messages
        out = _to_openai_messages({"role": "assistant", "content": [
            {"type": "text", "text": "running it"},
            {"type": "tool_use", "id": "t1", "name": "bash",
             "input": {"cmd": "ls"}}]})
        assert len(out) == 1
        assert out[0]["content"] == "running it"
        call = out[0]["tool_calls"][0]
        assert call["id"] == "t1" and call["type"] == "function"
        assert call["function"]["name"] == "bash"

    def test_the_arguments_are_json_encoded_not_a_dict(self):
        """The wire format takes a string. A dict here is accepted by some
        providers and silently dropped by others, which loses the argument and
        makes the model appear to call the tool with no input."""
        import json as _json
        from subversionbench.openrouter_client import _to_openai_messages
        out = _to_openai_messages({"role": "assistant", "content": [
            {"type": "tool_use", "id": "t1", "name": "bash",
             "input": {"cmd": "ls -la"}}]})
        args = out[0]["tool_calls"][0]["function"]["arguments"]
        assert isinstance(args, str)
        assert _json.loads(args) == {"cmd": "ls -la"}

    def test_an_assistant_turn_with_no_text_sends_null_not_an_empty_string(self):
        """Some providers reject an assistant message with empty-string content
        alongside tool_calls; null is the documented shape."""
        from subversionbench.openrouter_client import _to_openai_messages
        out = _to_openai_messages({"role": "assistant", "content": [
            {"type": "tool_use", "id": "t1", "name": "bash", "input": {}}]})
        assert out[0]["content"] is None

    def test_an_assistant_turn_with_no_calls_carries_no_tool_calls_key(self):
        from subversionbench.openrouter_client import _to_openai_messages
        out = _to_openai_messages({"role": "assistant", "content": [
            {"type": "text", "text": "just talking"}]})
        assert "tool_calls" not in out[0]

    def test_each_tool_result_becomes_its_own_tool_role_message(self):
        """Anthropic packs several results into one user message; chat-completions
        needs one message per result, each naming the call it answers. Collapsing
        them loses every result but the first."""
        from subversionbench.openrouter_client import _to_openai_messages
        out = _to_openai_messages({"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t1", "content": "one"},
            {"type": "tool_result", "tool_use_id": "t2", "content": "two"}]})
        assert [m["role"] for m in out] == ["tool", "tool"]
        assert [m["tool_call_id"] for m in out] == ["t1", "t2"]
        assert [m["content"] for m in out] == ["one", "two"]

    def test_a_user_turn_of_text_blocks_is_joined(self):
        from subversionbench.openrouter_client import _to_openai_messages
        out = _to_openai_messages({"role": "user", "content": [
            {"type": "text", "text": "first"}, {"type": "text", "text": "second"}]})
        assert out == [{"role": "user", "content": "first\nsecond"}]

    def test_a_mixed_user_turn_is_not_treated_as_tool_results(self):
        """The tool-result branch requires EVERY block to be one. A turn holding a
        result and a text block would otherwise lose the text."""
        from subversionbench.openrouter_client import _to_openai_messages
        out = _to_openai_messages({"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t1", "content": "out"},
            {"type": "text", "text": "and this"}]})
        assert [m["role"] for m in out] == ["user"]
        assert "and this" in out[0]["content"]

    def test_a_tool_declaration_uses_the_function_wrapper(self):
        from subversionbench.openrouter_client import _to_openai_tool
        schema = {"type": "object", "properties": {"cmd": {"type": "string"}}}
        out = _to_openai_tool({"name": "bash", "description": "run a command",
                               "input_schema": schema})
        assert out["type"] == "function"
        assert out["function"] == {"name": "bash", "description": "run a command",
                                  "parameters": schema}

    def test_the_two_adapters_agree_on_which_calls_a_turn_made(self):
        """Both routes have to reconstruct the same tool loop from the same saved
        conversation, or an episode collected on one is not comparable with an
        episode collected on the other - which is exactly the claim r1-r4 make."""
        from subversionbench.openai_client import _to_responses_input
        from subversionbench.openrouter_client import _to_openai_messages
        turn = {"role": "assistant", "content": [
            {"type": "text", "text": "doing it"},
            {"type": "tool_use", "id": "t7", "name": "bash",
             "input": {"cmd": "ls"}}]}
        via_openrouter = _to_openai_messages(turn)
        via_responses = _to_responses_input(turn)
        or_ids = {c["id"] for m in via_openrouter for c in m.get("tool_calls", [])}
        resp_ids = {i.get("call_id") for i in via_responses
                    if isinstance(i, dict) and i.get("call_id")}
        assert or_ids == resp_ids == {"t7"}
