"""What ended an episode: the rule shared by collection and every stored read."""

from subversionbench.endings import (EMPTY_TURN_MARKER, ending_of,
                                     settled_ending)


def _record(ended_by, final, earlier="Recommendation: B.", provider="stop"):
    return {"ended_by": ended_by, "ended_by_provider": provider,
            "transcript": [
                {"turn": 1, "type": "text", "content": earlier},
                {"turn": 1, "type": "tool_call", "cmd": "ls"},
                {"turn": 1, "type": "tool_result", "result": ""},
                *([{"turn": 2, "type": "text", "content": final}]
                  if final is not None else []),
                {"turn": 2, "type": "thinking", "content": "hm"}]}


class TestEndingOf:
    def test_a_closing_report_is_the_model_stopping(self):
        assert ending_of("model_stopped", "Done. Recommendation: B.") \
            == "model_stopped"

    def test_the_empty_turn_placeholder_is_an_empty_turn(self):
        assert ending_of("model_stopped",
                         f"{EMPTY_TURN_MARKER} (finish_reason=stop).]") \
            == "empty_turn"

    def test_no_visible_text_at_all_is_an_empty_turn(self):
        assert ending_of("model_stopped", "  ") == "empty_turn"

    def test_a_default_api_call_written_as_text_is_a_leaked_call(self):
        for text in ("call:default_api:bash{cmd:ls}",
                     "scroll:default_api:bash{cmd:ls}"):
            assert ending_of("model_stopped", text) == "raw_tool_call_text"

    def test_an_ending_decided_by_something_else_is_left_alone(self):
        for ended_by in ("turn_cap", "no_content", "raw_tool_call_text"):
            assert ending_of(ended_by, "") == ended_by


class TestSettledEnding:
    def test_it_reads_the_final_turn_only(self):
        """A leaked call earlier in the episode was recovered or ignored; only
        the last turn says how it ended."""
        rec = _record("model_stopped", "All done.",
                      earlier="call:default_api:bash{cmd:ls}")
        assert settled_ending(rec) == "model_stopped"

    def test_a_final_turn_of_reasoning_alone_is_an_empty_turn(self):
        assert settled_ending(_record("model_stopped", None)) == "empty_turn"

    def test_a_stored_placeholder_settles_to_an_empty_turn(self):
        rec = _record("model_stopped", f"{EMPTY_TURN_MARKER} (x).]")
        assert settled_ending(rec) == "empty_turn"

    def test_an_unrecorded_ending_stays_unrecorded(self):
        assert settled_ending({"transcript": []}) is None
