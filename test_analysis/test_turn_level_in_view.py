"""
What the model had in front of it at a turn (turn_level/in_view.py, turn_context.reasoning_sent_back).

What matters: earlier visible text and commands are always in view, earlier reasoning only where
it was sent back, tool results never; the unit's own turn counts only up to its FIRST tool call,
for every unit alike; and the judge's text is the grader's formatter's, so commands and tool
output never reach it.
"""

from subversionbench.turn_context import reasoning_sent_back
from turn_level.in_view import current_cut, in_view_indices, unit_texts

TR = [
    {"type": "thinking", "turn": 1, "content": "R1 earlier reasoning"},      # 0
    {"type": "text", "turn": 1, "content": "V1 earlier visible"},            # 1
    {"type": "tool_call", "turn": 1, "cmd": "C1 command"},                   # 2
    {"type": "tool_result", "turn": 1, "result": "O1 tool output"},          # 3
    {"type": "thinking", "turn": 2, "content": "R2 own reasoning"},          # 4
    {"type": "text", "turn": 2, "content": "V2 own visible"},                # 5
    {"type": "tool_call", "turn": 2, "cmd": "C2a first call"},               # 6
    {"type": "thinking", "turn": 2, "content": "R2b after the first call"},  # 7
    {"type": "tool_call", "turn": 2, "cmd": "C2b second call"},              # 8
    {"type": "tool_result", "turn": 2, "result": "O2 tool output"},          # 9
    {"type": "thinking", "turn": 3, "content": "R3 later reasoning"},        # 10
]
NOT_SENT = frozenset().__contains__


class TestInViewIndices:
    def test_without_send_back(self):
        assert in_view_indices(TR, 2, NOT_SENT) == [1, 2, 4, 5]

    def test_with_send_back(self):
        assert in_view_indices(TR, 2, {1}.__contains__) == [0, 1, 2, 4, 5]

    def test_earlier_view_drops_the_own_turn(self):
        assert in_view_indices(TR, 2, NOT_SENT, current=False) == [1, 2]

    def test_own_turn_stops_at_its_first_tool_call_whichever_call_is_the_act(self):
        """The cut is one rule for every unit: nothing written after the turn's first call counts,
        so a case whose act is the second call gains nothing from what came between."""
        assert current_cut(TR, 2) == 6
        assert 7 not in in_view_indices(TR, 2, NOT_SENT)

    def test_a_turn_with_no_call_counts_to_its_end(self):
        assert in_view_indices(TR, 3, NOT_SENT) == [1, 2, 5, 6, 8, 10]


class TestUnitTexts:
    def test_the_judge_sees_text_and_reasoning_only(self):
        texts = unit_texts(TR, 2, {1}.__contains__)
        for shown in ("R1 earlier reasoning", "V1 earlier visible", "R2 own reasoning", "V2 own visible"):
            assert shown in texts["in_view"]
        for hidden in ("C1 command", "O1 tool output", "R2b after", "R3 later"):
            assert hidden not in texts["in_view"]
        assert "R2 own reasoning" not in texts["earlier"] and "V1 earlier visible" in texts["earlier"]
        assert texts["current_has_reasoning"] and texts["current_chars"] > 0


class TestReasoningSentBack:
    def test_per_turn_marks(self):
        sent = reasoning_sent_back({"model": "moonshotai/kimi-k2.6", "reasoning_details": [
            {"turn": 1, "sent_back": True}, {"turn": 2}, {"turn": 3, "sent_back": False}]})
        assert sent(1) and not sent(2) and not sent(3)

    def test_native_anthropic_returns_every_block(self):
        assert reasoning_sent_back({"model": "claude-opus-5-5"})(7)
