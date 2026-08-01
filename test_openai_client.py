"""
Tests for subversionbench/openai_client.py.

The Responses API keeps tool calls as flat sibling items rather than nesting
them in an assistant message, and matches a result to its call by `call_id`.
Getting that wrong loses the tool loop entirely.

Run: pytest test_openai_client.py -v
"""

import json



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
