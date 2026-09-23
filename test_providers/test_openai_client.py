"""
Tests for subversionbench/openai_client.py.

The Responses API keeps tool calls as flat sibling items rather than nesting
them in an assistant message, and matches a result to its call by `call_id`.
Getting that wrong loses the tool loop entirely.

Run: pytest test_openai_client.py -v
"""

import json
import types

import pytest



class TestResponsesTranslation:
    """The Responses API keeps tool calls as siblings in one flat list rather
    than nested inside an assistant message, and matches a result to its call
    by call_id. Getting that wrong loses the tool loop entirely."""

    def test_a_tool_call_becomes_a_sibling_item(self):
        from subversionbench.openai_client import _to_responses_input
        items = _to_responses_input({"role": "assistant", "content": [
            {"type": "text", "text": "Checking."},
            {"type": "tool_use", "id": "call_1", "name": "bash",
             "input": {"command": "ls"}},
        ]})
        assert items[0] == {"role": "assistant", "content": "Checking."}
        assert items[1]["type"] == "function_call"
        assert items[1]["call_id"] == "call_1"
        assert json.loads(items[1]["arguments"]) == {"command": "ls"}

    def test_a_tool_result_carries_the_matching_call_id(self):
        from subversionbench.openai_client import _to_responses_input
        items = _to_responses_input({"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "call_1", "content": "ok"},
        ]})
        assert items == [{"type": "function_call_output",
                          "call_id": "call_1", "output": "ok"}]

    def test_an_assistant_turn_with_no_text_emits_no_empty_message(self):
        from subversionbench.openai_client import _to_responses_input
        items = _to_responses_input({"role": "assistant", "content": [
            {"type": "tool_use", "id": "c", "name": "bash", "input": {}}]})
        assert all(i.get("type") == "function_call" for i in items)

    def test_tools_use_the_flat_responses_shape(self):
        from subversionbench.openai_client import _to_responses_tool
        out = _to_responses_tool({"name": "bash", "description": "run",
                                  "input_schema": {"type": "object"}})
        # Responses puts name/parameters at the top level, unlike chat
        # completions which nests them under "function".
        assert out == {"type": "function", "name": "bash",
                       "description": "run",
                       "parameters": {"type": "object"}}

    def test_reasoning_summary_becomes_a_thinking_block(self):
        import types
        from subversionbench.openai_client import _from_responses_output
        response = types.SimpleNamespace(output=[
            types.SimpleNamespace(type="reasoning", summary=[
                types.SimpleNamespace(type="summary_text", text="I considered X.")]),
            types.SimpleNamespace(type="message", content=[
                types.SimpleNamespace(text="Done.")]),
        ])
        blocks = _from_responses_output(response)
        assert [b.type for b in blocks] == ["thinking", "text"]
        assert blocks[0].thinking == "I considered X."

    def test_a_structured_tool_result_is_encoded_rather_than_stringified(self):
        """The Responses API takes `output` as a string. A dict reaching it
        raw is a request the API rejects, and repr() of one is not something
        the model can read back - so it is JSON, chosen here rather than left
        to whatever str() happens to produce."""
        from subversionbench.openai_client import _to_responses_input
        items = _to_responses_input({"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "call_1",
             "content": {"stdout": "ok", "exit_code": 0}},
        ]})
        assert items[0]["call_id"] == "call_1"
        assert json.loads(items[0]["output"]) == {"stdout": "ok",
                                                  "exit_code": 0}

    def test_a_user_turn_of_text_blocks_becomes_one_user_message(self):
        """The user side is not always a tool result: the opening prompt and
        every follow-up arrive as text blocks. Dropping them would send the
        model a turn with no instruction in it."""
        from subversionbench.openai_client import _to_responses_input
        items = _to_responses_input({"role": "user", "content": [
            {"type": "text", "text": "First."},
            {"type": "text", "text": "Second."},
        ]})
        assert items == [{"role": "user", "content": "First.\nSecond."}]

    def test_a_user_turn_mixing_a_result_and_text_keeps_both(self):
        """The result comes first, as its own item; the text follows as a
        message. A tool result and the sentence that accompanies it are two
        items to the Responses API, not one."""
        from subversionbench.openai_client import _to_responses_input
        items = _to_responses_input({"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "c1", "content": "ok"},
            {"type": "text", "text": "Now finish."},
        ]})
        assert [i.get("type") or i["role"] for i in items] == \
            ["function_call_output", "user"]
        assert items[1]["content"] == "Now finish."

    def test_a_user_turn_of_whitespace_emits_no_message(self):
        """Same rule the assistant side already follows: an empty turn is not
        a turn. Sending one spends a request to say nothing."""
        from subversionbench.openai_client import _to_responses_input
        assert _to_responses_input(
            {"role": "user", "content": [{"type": "text", "text": "   "}]}) == []

    def test_a_function_call_comes_back_as_a_tool_use_block(self):
        """The inbound half of the tool loop. Without it the harness sees a
        turn with no tool call, ends the episode, and records the model as
        having done nothing - on the route where it in fact acted."""
        import types
        from subversionbench.openai_client import _from_responses_output
        response = types.SimpleNamespace(output=[
            types.SimpleNamespace(type="function_call", call_id="call_7",
                                  name="bash",
                                  arguments='{"command": "ls -la"}')])
        blocks = _from_responses_output(response)
        assert [b.type for b in blocks] == ["tool_use"]
        assert blocks[0].id == "call_7"
        assert blocks[0].name == "bash"
        assert blocks[0].input == {"command": "ls -la"}

    def test_unparseable_arguments_give_an_empty_input_not_a_crash(self):
        """A model that emits malformed JSON for its arguments is one bad
        turn. Raising here would end the whole episode instead, and the
        sandbox refuses an empty command on its own terms."""
        import types
        from subversionbench.openai_client import _from_responses_output
        response = types.SimpleNamespace(output=[
            types.SimpleNamespace(type="function_call", call_id="c",
                                  name="bash", arguments="{not json")])
        blocks = _from_responses_output(response)
        assert blocks[0].type == "tool_use" and blocks[0].input == {}

    def test_a_reasoned_tool_call_keeps_both_in_order(self):
        """The shape a thinking model actually returns, and the one the
        grader reads: the reasoning has to stay attached to the call it
        preceded."""
        import types
        from subversionbench.openai_client import _from_responses_output
        response = types.SimpleNamespace(output=[
            types.SimpleNamespace(type="reasoning", summary=[
                types.SimpleNamespace(text="I should look first.")]),
            types.SimpleNamespace(type="function_call", call_id="c",
                                  name="bash", arguments='{"command": "ls"}'),
        ])
        assert [b.type for b in _from_responses_output(response)] == \
            ["thinking", "tool_use"]

    def test_an_empty_reasoning_summary_is_dropped(self):
        """The model reasoned but returned no summary. Recording an empty
        thinking block would make the transcript claim evidence it does not
        have and feed the grader a hollow [REASONING] section - the same bug
        that left 243 hollow entries in the pilot data."""
        import types
        from subversionbench.openai_client import _from_responses_output
        for summary in ([], [types.SimpleNamespace(text="")],
                        [types.SimpleNamespace(text="   ")]):
            response = types.SimpleNamespace(output=[
                types.SimpleNamespace(type="reasoning", summary=summary)])
            assert _from_responses_output(response) == []


class _FakeResponsesEndpoint:
    """Records the request instead of sending it, and returns a shaped reply."""

    def __init__(self, reply=None):
        self.requests = []
        self.reply = reply

    def create(self, **kwargs):
        self.requests.append(kwargs)
        return self.reply if self.reply is not None else types.SimpleNamespace(
            status="completed", incomplete_details=None, output=[], usage=None)


def _client(reply=None):
    """An OpenAIClient with the SDK replaced.

    Built without running __init__ on purpose: __init__ reads OPENAI_API_KEY and
    constructs the real SDK client, and neither is what `create` is being tested
    for. The key check gets its own test below.
    """
    from subversionbench.openai_client import OpenAIClient
    client = OpenAIClient.__new__(OpenAIClient)
    client._client = types.SimpleNamespace(responses=_FakeResponsesEndpoint(reply))
    client.messages = client
    return client


class TestTheRequestTheResponsesApiIsSent:
    """`create` had no test at all, and it is where the effort arm is applied.

    An effort that fails to reach the request is not a wrong number in a report -
    it is a batch whose filename says `max` while the model reasoned at the
    default. That is the same defect class as BatchIdentity.collecting defaulting
    the effort, which is why it is asserted rather than assumed.
    """

    def test_the_effort_reaches_the_reasoning_parameter(self):
        c = _client()
        c.create(model="gpt-5", max_tokens=100, output_config={"effort": "high"})
        assert c._client.responses.requests[0]["reasoning"]["effort"] == "high"

    def test_no_effort_sends_no_effort_rather_than_a_default(self):
        """A default invented here would be reported as the arm that was asked
        for, and this route's own default would silently become the measurement."""
        c = _client()
        c.create(model="gpt-5", max_tokens=100, output_config=None)
        assert "effort" not in c._client.responses.requests[0]["reasoning"]

    def test_a_reasoning_summary_is_always_requested(self):
        """The whole reason this route exists rather than OpenRouter: without it
        the transcript has no reasoning to grade."""
        c = _client()
        c.create(model="gpt-5", max_tokens=100)
        assert c._client.responses.requests[0]["reasoning"]["summary"] == "auto"

    def test_thinking_is_accepted_and_not_forwarded(self):
        """Anthropic's control has no counterpart here. Accepted so one flag means
        the same thing on both native paths; dropped rather than passed through."""
        c = _client()
        c.create(model="gpt-5", max_tokens=100,
                 thinking={"type": "adaptive"})
        assert "thinking" not in c._client.responses.requests[0]

    def test_a_system_block_list_is_flattened_into_instructions(self):
        """The loop builds a list of blocks for cache control. This route takes a
        string, so a list arriving unflattened would send the repr of a list as
        the system prompt."""
        c = _client()
        c.create(model="gpt-5", max_tokens=100, system=[
            {"type": "text", "text": "first"}, {"type": "text", "text": "second"}])
        assert c._client.responses.requests[0]["instructions"] == "first\nsecond"

    def test_a_plain_system_string_is_passed_through(self):
        c = _client()
        c.create(model="gpt-5", max_tokens=100, system="be careful")
        assert c._client.responses.requests[0]["instructions"] == "be careful"

    def test_an_empty_system_prompt_sends_no_instructions_key(self):
        c = _client()
        c.create(model="gpt-5", max_tokens=100, system="")
        assert "instructions" not in c._client.responses.requests[0]

    def test_max_tokens_becomes_max_output_tokens(self):
        c = _client()
        c.create(model="gpt-5", max_tokens=4096)
        assert c._client.responses.requests[0]["max_output_tokens"] == 4096

    def test_tools_are_translated_not_forwarded_verbatim(self):
        c = _client()
        c.create(model="gpt-5", max_tokens=100, tools=[
            {"name": "bash", "description": "run", "input_schema":
             {"type": "object", "properties": {"cmd": {"type": "string"}}}}])
        sent = c._client.responses.requests[0]["tools"][0]
        assert sent["name"] == "bash"
        assert "input_schema" not in sent, "the Anthropic key name reached the wire"

    def test_no_tools_sends_no_tools_key(self):
        c = _client()
        c.create(model="gpt-5", max_tokens=100, tools=None)
        assert "tools" not in c._client.responses.requests[0]

    def test_messages_are_flattened_into_input_items(self):
        c = _client()
        c.create(model="gpt-5", max_tokens=100, messages=[
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": [
                {"type": "tool_use", "id": "t1", "name": "bash",
                 "input": {"cmd": "ls"}}]},
            {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "t1", "content": "out"}]},
        ])
        items = c._client.responses.requests[0]["input"]
        assert len(items) >= 3
        assert any(i.get("call_id") == "t1" for i in items if isinstance(i, dict))


class TestWhyTheApiStopped:
    """Written into saved run files, so it has to stay JSON, and read to decide
    whether an episode produced a closing report at all - which decides whether
    disclosure is gradeable."""

    def test_a_completed_response_reports_its_status(self):
        from subversionbench.openai_client import _stop_reason
        assert _stop_reason(types.SimpleNamespace(
            status="completed", incomplete_details=None)) == "completed"

    def test_an_incomplete_response_carries_the_reason(self):
        """A turn cap that reads as 'incomplete' with no reason cannot be told
        apart from a refusal."""
        from subversionbench.openai_client import _stop_reason
        got = _stop_reason(types.SimpleNamespace(
            status="incomplete",
            incomplete_details=types.SimpleNamespace(reason="max_output_tokens")))
        assert got == "incomplete:max_output_tokens"

    def test_it_is_a_string_or_none_never_an_sdk_object(self):
        """It is serialised into the run file. An SDK object there would make the
        file unreadable by every read mode."""
        from subversionbench.openai_client import _stop_reason
        for response in (types.SimpleNamespace(status=None,
                                               incomplete_details=None),
                         types.SimpleNamespace(status="completed",
                                               incomplete_details=None),
                         types.SimpleNamespace()):
            got = _stop_reason(response)
            assert got is None or isinstance(got, str), got


class TestTheKeyIsCheckedBeforeAnythingIsSent:
    def setup_method(self, method):
        """`openai` is an optional extra, imported lazily by the client. Without
        this these tests raised ModuleNotFoundError instead of skipping, so a
        clean `pip install -e .[test]` could not produce a green suite."""
        from conftest import skip_without
        skip_without("openai", "needed by the OpenRouter/OpenAI routes")

    def test_a_missing_key_raises_with_the_alternative_route(self):
        """The Anthropic SDK constructs with no key and defers the failure to the
        first call, which is how a whole rollout came to fail one classifier call
        at a time. This route raises at construction, and says what else to do."""
        import os
        from subversionbench.openai_client import OpenAIClient
        saved = os.environ.pop("OPENAI_API_KEY", None)
        try:
            with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
                OpenAIClient()
        finally:
            if saved is not None:
                os.environ["OPENAI_API_KEY"] = saved


class TestExplicitPromptCaching:
    """Anthropic reads 98.5% of its input back from cache on this corpus and
    this route read 56%, because the `cache_control` markers already in every
    request were dropped on the way out. GPT-5.6 and later take an explicit
    breakpoint of their own; earlier models reject the parameters, so the gate
    has to be right in both directions.
    """

    _MARKED = [{"type": "text", "text": "TRANSCRIPT",
                "cache_control": {"type": "ephemeral"}},
               {"type": "text", "text": "QUESTION"}]

    def _sent(self, model, content=None, messages=None):
        from subversionbench.openai_client import OpenAIClient
        captured = {}

        class _Fake:
            class responses:
                @staticmethod
                def create(**kwargs):
                    captured.update(kwargs)
                    return types.SimpleNamespace(output=[], usage=None,
                                                 status="completed")

        client = OpenAIClient.__new__(OpenAIClient)
        client._client = _Fake()
        client.create(model=model, max_tokens=300, system="SYS",
                      messages=messages or [{"role": "user", "content": content}])
        return captured

    def test_the_floor_is_read_off_the_version_in_both_directions(self):
        """Derived from the version rather than a list of model names, and
        checked below the floor as well as above it: sending these parameters
        to a model that does not take them is a 400 on every call."""
        from subversionbench.openai_client import _supports_explicit_cache

        for model in ("gpt-5.6-luna", "gpt-6-sol", "gpt-6-astra", "gpt-7"):
            assert _supports_explicit_cache(model) is True, model
        for model in ("gpt-5.4", "gpt-5", "gpt-4o", "gpt-4.1"):
            assert _supports_explicit_cache(model) is False, model

    def test_an_unreadable_id_falls_back_to_implicit_caching(self):
        """Fails CLOSED. An ID this cannot parse gets what every call on this
        route had before explicit mode existed, rather than a parameter the
        model may reject."""
        from subversionbench.openai_client import _supports_explicit_cache

        for model in ("o3", "", "some-new-model", "claude-opus-5"):
            assert _supports_explicit_cache(model) is False, model

    def test_a_marked_block_carries_a_breakpoint(self):
        sent = self._sent("gpt-6-sol", self._MARKED)
        assert sent["prompt_cache_options"] == {"mode": "explicit",
                                                "ttl": "30m"}
        parts = sent["input"][0]["content"]
        assert parts[0]["prompt_cache_breakpoint"] == {"mode": "explicit"}
        assert parts[0]["text"] == "TRANSCRIPT"
        assert "prompt_cache_breakpoint" not in parts[1], (
            "the varying suffix must stay outside the cached prefix")

    def test_an_older_model_is_sent_neither_parameter(self):
        sent = self._sent("gpt-5.4", self._MARKED)
        assert "prompt_cache_options" not in sent
        assert sent["input"][0]["content"] == "TRANSCRIPT\nQUESTION", (
            "below the floor the request must keep the shape it always had")

    def test_an_unmarked_request_keeps_the_joined_string(self):
        """The shape changes only where a breakpoint is added to it, so a
        caller that never asked for caching sends what it always sent."""
        sent = self._sent("gpt-6-sol", [{"type": "text", "text": "A"},
                                        {"type": "text", "text": "B"}])
        assert sent["input"][0]["content"] == "A\nB"

    def test_the_text_survives_the_translation_either_way(self):
        """The breakpoint must not cost, reorder or re-space any of the prompt
        - the same text reaches the model whichever shape carries it. Compared
        EXACTLY: an earlier version stripped every newline from both sides
        before comparing, and so passed while the parts dropped the separator
        the joined string had between blocks."""
        marked = self._sent("gpt-6-sol", self._MARKED)["input"][0]["content"]
        plain = self._sent("gpt-5.4", self._MARKED)["input"][0]["content"]
        assert "".join(p["text"] for p in marked) == plain

    def test_an_episode_turn_keeps_implicit_caching(self):
        """An episode marks its newest tool_result, which becomes a
        function_call_output with no breakpoint on this route. Explicit mode
        with no breakpoint would switch the model under test off implicit
        prefix caching and cache nothing instead."""
        sent = self._sent("gpt-6-sol", messages=[
            {"role": "user", "content": "the opening turn"},
            {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "c1", "content": "ok",
                 "cache_control": {"type": "ephemeral"}}]},
        ])
        assert "prompt_cache_options" not in sent

    def test_a_bare_string_request_keeps_implicit_caching(self):
        """The interrogation classifier's shape: its only marker is on the
        system prompt, which travels as `instructions`."""
        sent = self._sent("gpt-6-sol", "a plain prompt")
        assert "prompt_cache_options" not in sent
