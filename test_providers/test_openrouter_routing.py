"""
What was asked of the router, what answered, and how a turn is translated.

Chat-completions differs from the Responses API in exactly the way that breaks
a tool loop quietly: tool calls nest inside the assistant message and results
come back as their own `tool` role message keyed by `tool_call_id`. This is the
route r1-r3 were collected through, so the cross-family comparison rests on a
translation that had nothing checking it.
"""



class TestProviderSortRouting:
    """--openrouter-sort ('price' or 'throughput') is opt-in per client and
    must reach OpenRouter as extra_body.provider.sort, independently of
    whether `tools` is also sending require_parameters - one must not imply
    or crowd out the other in the same provider dict."""

    def setup_method(self, method):
        """`openai` is an optional extra, imported lazily by the client. Without
        this these tests raised ModuleNotFoundError instead of skipping, so a
        clean `pip install -e .[test]` could not produce a green suite."""
        from conftest import skip_without
        skip_without("openai", "needed by the OpenRouter/OpenAI routes")


    def _make_client(self, provider_sort=None, provider_name=None):
        from unittest.mock import MagicMock
        import os
        from subversionbench.openrouter_client import OpenRouterClient

        os.environ.setdefault("OPENROUTER_API_KEY", "dummy")
        client = OpenRouterClient(provider_sort=provider_sort,
                                  provider_name=provider_name)
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


class TestProviderPinning:
    """--openrouter-provider pins routing to one named backend, e.g. to route
    around a provider that is misbehaving for a given model even though it is
    the cheapest/fastest (what --openrouter-sort would otherwise pick)."""

    def setup_method(self, method):
        """`openai` is an optional extra, imported lazily by the client. Without
        this these tests raised ModuleNotFoundError instead of skipping, so a
        clean `pip install -e .[test]` could not produce a green suite."""
        from conftest import skip_without
        skip_without("openai", "needed by the OpenRouter/OpenAI routes")


    def _make_client(self, provider_sort=None, provider_name=None):
        from unittest.mock import MagicMock
        import os
        from subversionbench.openrouter_client import OpenRouterClient

        os.environ.setdefault("OPENROUTER_API_KEY", "dummy")
        client = OpenRouterClient(provider_sort=provider_sort,
                                  provider_name=provider_name)
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

    def test_order_and_allow_fallbacks_are_sent_when_requested(self):
        client = self._make_client(provider_name="deepinfra")
        client.create(model="inclusionai/ling-3.0-flash", max_tokens=4096,
                      messages=[{"role": "user", "content": "hi"}])
        provider = self._sent_kwargs(client)["extra_body"]["provider"]
        assert provider == {"order": ["deepinfra"], "allow_fallbacks": False}

    def test_no_provider_key_at_all_when_not_requested_and_no_tools(self):
        client = self._make_client(provider_name=None)
        client.create(model="inclusionai/ling-3.0-flash", max_tokens=4096,
                      messages=[{"role": "user", "content": "hi"}])
        assert "extra_body" not in self._sent_kwargs(client)

    def test_coexists_with_sort_and_require_parameters(self):
        client = self._make_client(provider_sort="price", provider_name="deepinfra")
        client.create(
            model="inclusionai/ling-3.0-flash", max_tokens=4096,
            tools=[{"name": "bash", "description": "d",
                    "input_schema": {"type": "object"}}],
            messages=[{"role": "user", "content": "hi"}],
        )
        provider = self._sent_kwargs(client)["extra_body"]["provider"]
        assert provider == {
            "require_parameters": True,
            "sort": "price",
            "order": ["deepinfra"],
            "allow_fallbacks": False,
        }


class TestWhichBackendActuallyAnswered:
    """`openrouter_provider` on an episode records what the operator ASKED
    for, and is None wherever nothing was pinned - which is most of a corpus
    collected under default routing. It therefore cannot say which backend
    answered, and the README's own caveat about the router moving between
    backends mid-batch was unfalsifiable from the run files. This reads the
    router's own account off the response instead.
    """

    def setup_method(self, method):
        from conftest import skip_without
        skip_without("openai", "needed by the OpenRouter/OpenAI routes")

    def _make_client(self, provider_name=None):
        from unittest.mock import MagicMock
        import os
        from subversionbench.openrouter_client import OpenRouterClient

        os.environ.setdefault("OPENROUTER_API_KEY", "dummy")
        client = OpenRouterClient(provider_name=provider_name)
        client._client = MagicMock()
        return client

    def _set_completion(self, client, fake_completion):
        from unittest.mock import MagicMock
        fake_raw = MagicMock()
        fake_raw.parse.return_value = fake_completion
        client._client.chat.completions.with_raw_response.create.return_value = fake_raw

    def _completion(self, provider=...):
        from unittest.mock import MagicMock
        message = MagicMock()
        message.content = "done"
        message.tool_calls = None
        message.reasoning = None
        message.reasoning_details = None
        choice = MagicMock()
        choice.message = message
        choice.finish_reason = "stop"
        completion = MagicMock()
        completion.choices = [choice]
        # A MagicMock answers to every attribute, so "the router sent no
        # provider" has to be spelled out - left unset, the double would supply
        # a value the API never did, which is how a mock leaks into a run file.
        completion.provider = None if provider is ... else provider
        return completion

    def _create(self, client):
        return client.create(model="deepseek/deepseek-r1", max_tokens=4096,
                             messages=[{"role": "user", "content": "hi"}])

    def test_the_serving_backend_reaches_the_response(self):
        client = self._make_client()
        self._set_completion(client, self._completion(provider="Fireworks"))
        assert self._create(client).provider == "Fireworks"

    def test_a_response_that_names_no_backend_is_not_an_error(self):
        """Absence must read as "not recorded", never as a provider name."""
        client = self._make_client()
        self._set_completion(client, self._completion())
        assert self._create(client).provider is None

    def test_it_is_read_off_the_response_not_the_request(self):
        """The whole point of the field. A client that pinned one provider and
        was served by another must report what ANSWERED - reporting the request
        back would only restate `openrouter_provider`, which already exists."""
        client = self._make_client(provider_name="deepinfra")
        self._set_completion(client, self._completion(provider="Fireworks"))
        assert self._create(client).provider == "Fireworks", (
            "the response's provider was overwritten by the requested one")


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


class TestASystemPromptGivenAsBlocksReachesAnOpenAiEndpointAsText:
    """The harness builds its system prompt as Anthropic content blocks so it
    can attach `cache_control`, which has no OpenRouter equivalent. Forwarding
    that block list to an OpenAI-compatible endpoint sends a `content` of
    unknown shape: some providers reject it, and at least as bad, some accept
    it and drop it - which runs the whole episode with no system prompt at all
    and reports nothing.
    """

    def setup_method(self, method):
        from conftest import skip_without
        skip_without("openai", "needed by the OpenRouter/OpenAI routes")

    def _sent(self, system):
        """The messages create() actually put on the wire."""
        from unittest.mock import MagicMock
        import os
        from subversionbench.openrouter_client import OpenRouterClient

        os.environ.setdefault("OPENROUTER_API_KEY", "dummy")
        client = OpenRouterClient()
        client._client = MagicMock()
        message = MagicMock()
        message.content = "ok"
        message.tool_calls = None
        message.reasoning = None
        choice = MagicMock()
        choice.message = message
        choice.finish_reason = "stop"
        completion = MagicMock()
        completion.choices = [choice]
        raw = MagicMock()
        raw.parse.return_value = completion
        create = client._client.chat.completions.with_raw_response.create
        create.return_value = raw
        client.create(model="p/m", max_tokens=64, system=system,
                      messages=[{"role": "user", "content": "hi"}])
        return create.call_args.kwargs["messages"]

    def test_a_block_list_is_collapsed_into_one_string(self):
        sent = self._sent([
            {"type": "text", "text": "first line",
             "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": "second line"}])
        system = [m for m in sent if m["role"] == "system"]
        assert len(system) == 1
        assert isinstance(system[0]["content"], str), (
            "a block list reached an OpenAI-compatible endpoint unchanged")
        assert system[0]["content"] == "first line\nsecond line"

    def test_a_non_text_block_is_dropped_rather_than_stringified(self):
        """An image or a cache marker has no place in a chat-completions
        system string, and str() of it would be sent to the model as prose."""
        sent = self._sent([
            {"type": "text", "text": "keep me"},
            {"type": "image", "source": {"data": "..."}}])
        system = next(m for m in sent if m["role"] == "system")
        assert system["content"] == "keep me"

    def test_a_plain_string_still_passes_through(self):
        """The control: without it the two tests above would pass against a
        client that rebuilt every system prompt from scratch."""
        sent = self._sent("just a string")
        system = next(m for m in sent if m["role"] == "system")
        assert system["content"] == "just a string"


class TestAToolCallLeakedAsPlainText:
    """Some backends emit a model's native tool-call tokens as CONTENT
    instead of populating the structured `tool_calls` field - seen with
    DeepSeek R1, which was not trained with clean function-calling support.

    The recovery has to happen, because the alternative is an episode that
    ends early: the harness sees a turn with text and no tool call, concludes
    the model is done, and records it as having taken no action on a turn
    where it asked to run a command. tool_parsing.py is tested on its own;
    what is asserted here is that create() actually routes through it and
    turns the result into blocks.
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

    def _reply(self, client, content, tool_calls=None, provider=None):
        from unittest.mock import MagicMock
        message = MagicMock()
        message.content = content
        message.tool_calls = tool_calls
        message.reasoning = None
        message.reasoning_details = None
        choice = MagicMock()
        choice.message = message
        choice.finish_reason = "stop"
        completion = MagicMock()
        completion.choices = [choice]
        completion.provider = provider
        raw = MagicMock()
        raw.parse.return_value = completion
        client._client.chat.completions.with_raw_response.create.return_value = raw

    def _raw_text(self, name="bash", args='{"cmd": "ls -la"}'):
        """The token syntax those backends emit.

        Assembled from the module's own start marker rather than restated.
        The tokens are built from two full-width characters that are easy to
        mistype and impossible to tell apart from their ASCII lookalikes in
        a diff - and a fixture that failed to match would leave every test
        below passing against a recovery path that never ran.
        """
        from subversionbench.tool_parsing import _RAW_TOOL_CALL_START
        bar, low = _RAW_TOOL_CALL_START[1], _RAW_TOOL_CALL_START[6]

        def token(*parts):
            return "<" + bar + low.join(parts) + bar + ">"

        return (_RAW_TOOL_CALL_START
                + token("tool", "call", "begin") + "function"
                + token("tool", "sep") + f"{name}\n```json\n{args}\n```"
                + token("tool", "call", "end")
                + token("tool", "calls", "end"))

    def _create(self, client):
        return client.create(
            model="deepseek/deepseek-r1", max_tokens=4096,
            tools=[{"name": "bash", "description": "d",
                    "input_schema": {"type": "object"}}],
            messages=[{"role": "user", "content": "hi"}])

    def test_the_leaked_call_becomes_a_real_tool_use_block(self):
        client = self._client()
        self._reply(client, self._raw_text())
        blocks = self._create(client).content
        assert [b.type for b in blocks] == ["tool_use"]
        assert blocks[0].name == "bash"
        assert blocks[0].input == {"cmd": "ls -la"}

    def test_the_recovered_call_is_given_an_id_the_loop_can_match(self):
        """The tool result is matched back to its call by id, so a recovered
        call with none would break the pairing on the next turn."""
        client = self._client()
        self._reply(client, self._raw_text())
        block = self._create(client).content[0]
        assert block.id and isinstance(block.id, str)

    def test_two_leaked_calls_both_survive(self):
        client = self._client()
        self._reply(client, self._raw_text() + self._raw_text(args='{"cmd": "id"}'))
        blocks = self._create(client).content
        assert [b.type for b in blocks] == ["tool_use", "tool_use"]
        assert [b.input["cmd"] for b in blocks] == ["ls -la", "id"]

    def test_text_written_before_the_call_is_kept_and_kept_first(self):
        """That text is the model's own reasoning about what it is about to
        do, and the graders read it. Dropping it would remove evidence from
        the transcript; putting it after the call would misreport the order
        in which the model said and did things."""
        client = self._client()
        self._reply(client, "Let me look at the directory.\n" + self._raw_text())
        blocks = self._create(client).content
        assert [b.type for b in blocks] == ["text", "tool_use"]
        assert blocks[0].text == "Let me look at the directory."

    def test_whitespace_before_the_call_does_not_become_a_block(self):
        client = self._client()
        self._reply(client, "   \n" + self._raw_text())
        assert [b.type for b in self._create(client).content] == ["tool_use"]

    def test_the_recovered_turn_still_records_which_backend_answered(self):
        """This path returns EARLY, before the ordinary assembly below it, so
        every field carried on the response has to be carried here too - and
        the serving backend is the one a later reader cannot recover from
        anywhere else."""
        client = self._client()
        self._reply(client, self._raw_text(), provider="Fireworks")
        response = self._create(client)
        assert [b.type for b in response.content] == ["tool_use"]
        assert response.provider == "Fireworks"
        assert response.stop_reason == "stop"

    def test_content_with_no_call_in_it_is_left_alone(self):
        """The other direction. Ordinary prose must not be routed through the
        recovery and come back as an empty tool call."""
        client = self._client()
        self._reply(client, "I have finished the recommendation.")
        blocks = self._create(client).content
        assert [b.type for b in blocks] == ["text"]
        assert blocks[0].text == "I have finished the recommendation."

    def test_a_structured_call_is_not_second_guessed(self):
        """The recovery only runs when `tool_calls` is empty. A backend that
        populated it properly must be taken at its word."""
        from unittest.mock import MagicMock
        client = self._client()
        call = MagicMock()
        call.id = "call_real"
        call.function.name = "bash"
        call.function.arguments = '{"cmd": "pwd"}'
        self._reply(client, self._raw_text(), tool_calls=[call])
        blocks = self._create(client).content
        ids = [b.id for b in blocks if b.type == "tool_use"]
        assert ids == ["call_real"]

    def test_unparseable_structured_arguments_give_an_empty_input(self):
        """A model that emits malformed JSON for its arguments is one bad
        turn, not a failed episode - and the sandbox refuses an empty command
        on its own terms."""
        from unittest.mock import MagicMock
        client = self._client()
        call = MagicMock()
        call.id = "call_1"
        call.function.name = "bash"
        call.function.arguments = "{not json"
        self._reply(client, None, tool_calls=[call])
        blocks = self._create(client).content
        assert [b.type for b in blocks] == ["tool_use"]
        assert blocks[0].input == {}
