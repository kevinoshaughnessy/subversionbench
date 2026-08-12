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
