"""
The OpenRouter route: what comes back, and what to say when it is not a
completion.

Responses that are empty or not JSON both used to surface as an exception
several layers inside the SDK with no indication of what actually came back. A
reasoning model can spend its whole budget thinking and return no content and
no tool call, and an upstream provider can answer with an error page or a body
that parses as JSON and holds no choices - each needs its own diagnosis.

Run: pytest test_openrouter_client.py -v
"""



class TestOpenRouterEmptyCompletion:
    """A reasoning model (e.g. deepseek-r1) can spend its whole max_tokens
    budget on internal reasoning and return no content and no tool call.
    That must surface as a diagnostic message, not silently end the
    episode with no explanation."""

    def setup_method(self, method):
        """`openai` is an optional extra, imported lazily by the client. Without
        this these tests raised ModuleNotFoundError instead of skipping, so a
        clean `pip install -e .[test]` could not produce a green suite."""
        from conftest import skip_without
        skip_without("openai", "needed by the OpenRouter/OpenAI routes")


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

    def test_the_reasoning_label_reaches_the_response(self):
        """`reasoning` gives the text; `reasoning_details` says whether that text
        is a trace or a summary. Both awareness measures read the difference, so
        the label has to survive as far as the run file."""
        from unittest.mock import MagicMock

        client = self._make_client()

        fake_message = MagicMock()
        fake_message.content = "done"
        fake_message.tool_calls = None
        fake_message.reasoning = "step one, step two"
        fake_message.reasoning_details = [
            {"type": "reasoning.summary", "summary": "step one, step two"},
        ]

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

        assert response.reasoning_details["types"] == ["reasoning.summary"]
        assert response.reasoning_details["chars"] == len(fake_message.reasoning)
        # And it stays off the thinking block, which is sent back to the API.
        assert not hasattr(response.content[0], "reasoning_details")

    def test_a_provider_that_sends_no_label_is_not_an_error(self):
        """Only some backends report the field. Its absence must read as "no
        label", not as a failure - and not as a MagicMock leaking into a run
        file, which is how a test double would show up here."""
        from unittest.mock import MagicMock

        client = self._make_client()

        fake_message = MagicMock()
        fake_message.content = "done"
        fake_message.tool_calls = None
        fake_message.reasoning = None
        fake_message.reasoning_details = None

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

        assert response.reasoning_details == {}

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


class TestAnEmptyTurnOnlyClaimsTheThinkingItCanSee:
    """The diagnostic names the reasoning length because on this route that is
    usually where the whole budget went. A route that returns no reasoning
    field at all is a different situation, and reporting `reasoning_chars=0`
    for it would say the model thought nothing when what happened is that
    nobody was told."""

    def setup_method(self, method):
        from conftest import skip_without
        skip_without("openai", "needed by the OpenRouter/OpenAI routes")

    def _diagnostic(self, reasoning):
        from unittest.mock import MagicMock
        import os
        from subversionbench.openrouter_client import OpenRouterClient

        os.environ.setdefault("OPENROUTER_API_KEY", "dummy")
        client = OpenRouterClient()
        client._client = MagicMock()
        message = MagicMock()
        message.content = None
        message.tool_calls = None
        message.reasoning = reasoning
        choice = MagicMock()
        choice.message = message
        choice.finish_reason = "length"
        completion = MagicMock()
        completion.choices = [choice]
        raw = MagicMock()
        raw.parse.return_value = completion
        client._client.chat.completions.with_raw_response.create.return_value = raw
        response = client.create(model="p/m", max_tokens=64,
                                 messages=[{"role": "user", "content": "hi"}])
        return next(b.text for b in response.content if b.type == "text")

    def test_a_route_that_reported_no_reasoning_is_not_credited_with_zero(self):
        text = self._diagnostic(None)
        assert "finish_reason=length" in text
        assert "reasoning_chars" not in text

    def test_a_route_that_did_report_it_has_the_count_named(self):
        """The control, and the reason the branch above is worth having."""
        text = self._diagnostic("x" * 42)
        assert "reasoning_chars=42" in text


class TestOpenRouterNonJsonResponse:
    """If the upstream provider returns a non-JSON body (an error page, a
    streaming/SSE body served when a plain response was requested, a
    connection dropped mid-response), the raw json.JSONDecodeError from
    deep inside the SDK/httpx gives no way to tell what happened. create()
    must surface the actual HTTP status and body instead."""

    def setup_method(self, method):
        """`openai` is an optional extra, imported lazily by the client. Without
        this these tests raised ModuleNotFoundError instead of skipping, so a
        clean `pip install -e .[test]` could not produce a green suite."""
        from conftest import skip_without
        skip_without("openai", "needed by the OpenRouter/OpenAI routes")


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
            raise AssertionError("expected RuntimeError")
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

    def setup_method(self, method):
        """`openai` is an optional extra, imported lazily by the client. Without
        this these tests raised ModuleNotFoundError instead of skipping, so a
        clean `pip install -e .[test]` could not produce a green suite."""
        from conftest import skip_without
        skip_without("openai", "needed by the OpenRouter/OpenAI routes")


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
            raise AssertionError("expected RuntimeError")
        except RuntimeError as e:
            assert "moonshotai/kimi-k2-thinking" in str(e)
            assert "200" in str(e)
            assert "moderation_blocked" in str(e)
        except TypeError as e:
            raise AssertionError(
                "a bare TypeError reached the caller") from e

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
            raise AssertionError("expected RuntimeError")
        except RuntimeError as e:
            assert "429" in str(e)
        except IndexError as e:
            raise AssertionError(
                "a bare IndexError reached the caller") from e


class TestADiagnosticWithNoTextBodyStillSaysWhatCameBack:
    """Both failure diagnostics quote the response body, because the body is
    the only place an explanation might be. `raw_response.text` decodes bytes
    for a known charset and is None when it cannot - which is precisely the
    case where the body is a binary error page and most needs quoting. Falling
    through to nothing there would leave the operator the HTTP status alone.
    """

    def setup_method(self, method):
        from conftest import skip_without
        skip_without("openai", "needed by the OpenRouter/OpenAI routes")

    def _client(self):
        from unittest.mock import MagicMock
        import os
        from subversionbench.openrouter_client import OpenRouterClient

        os.environ.setdefault("OPENROUTER_API_KEY", "dummy")
        client = OpenRouterClient()
        client._client = MagicMock()
        return client

    def _raise(self, raw):
        client = self._client()
        client._client.chat.completions.with_raw_response.create.return_value = raw
        try:
            client.create(model="p/m", max_tokens=64,
                          messages=[{"role": "user", "content": "hi"}])
        except RuntimeError as e:
            return str(e)
        raise AssertionError("create() did not refuse the response")

    def test_an_undecodable_non_json_body_is_quoted_from_its_bytes(self):
        from unittest.mock import MagicMock
        import json
        raw = MagicMock()
        raw.status_code = 503
        raw.text = None
        raw.content = b"<html>upstream unavailable</html>"
        raw.parse.side_effect = json.JSONDecodeError("Expecting value", "", 0)
        message = self._raise(raw)
        assert "503" in message
        assert "upstream unavailable" in message, (
            "the body was dropped, leaving the status code as the only clue")

    def test_an_undecodable_no_choices_body_is_quoted_from_its_bytes(self):
        """The same fallback on the other diagnostic. Two call sites, so two
        chances to have written it only once."""
        from unittest.mock import MagicMock
        raw = MagicMock()
        raw.status_code = 200
        raw.text = None
        raw.content = b'{"error": {"message": "moderation block"}}'
        completion = MagicMock()
        completion.choices = None
        raw.parse.return_value = completion
        message = self._raise(raw)
        assert "no choices" in message
        assert "moderation block" in message
