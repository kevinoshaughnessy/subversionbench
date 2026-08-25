"""
Which result answered which command.

Three measures had written this walk separately and two were wrong, in
different ways. The cases below are the ones that distinguish the correct
pairing from each of those: a multi-call turn, and a turn whose results have
already been consumed.
"""

from subversionbench.grading.transcript_pairs import paired_results


class TestOneCallPerTurn:
    """The easy shape, and the only one the three private copies were ever
    tested on - which is how both defects survived."""

    def test_the_call_is_paired_with_its_result(self):
        transcript = [
            {"turn": 1, "type": "tool_call", "cmd": "ls"},
            {"turn": 1, "type": "tool_result", "result": "a"},
        ]
        assert paired_results(transcript) == {0: "a"}

    def test_a_later_turns_result_is_not_borrowed(self):
        transcript = [
            {"turn": 1, "type": "tool_call", "cmd": "ls"},
            {"turn": 1, "type": "tool_result", "result": "a"},
            {"turn": 2, "type": "tool_call", "cmd": "pwd"},
            {"turn": 2, "type": "tool_result", "result": "b"},
        ]
        assert paired_results(transcript) == {0: "a", 2: "b"}


class TestSeveralCallsInOneTurn:
    """The shape adjacency gets wrong. A turn emits every call and THEN every
    result, so 'the next entry' is the first result for all of them."""

    def test_the_kth_call_takes_the_kth_result(self):
        transcript = [
            {"turn": 1, "type": "tool_call", "cmd": "one"},
            {"turn": 1, "type": "tool_call", "cmd": "two"},
            {"turn": 1, "type": "tool_call", "cmd": "three"},
            {"turn": 1, "type": "tool_result", "result": "r1"},
            {"turn": 1, "type": "tool_result", "result": "r2"},
            {"turn": 1, "type": "tool_result", "result": "r3"},
        ]
        assert paired_results(transcript) == {0: "r1", 1: "r2", 2: "r3"}

    def test_text_and_thinking_entries_do_not_shift_the_pairing(self):
        """The model's own turns sit between the calls and the results, and
        counting entries rather than calls would slide the whole mapping."""
        transcript = [
            {"turn": 1, "type": "thinking", "content": "hm"},
            {"turn": 1, "type": "tool_call", "cmd": "one"},
            {"turn": 1, "type": "text", "content": "checking"},
            {"turn": 1, "type": "tool_call", "cmd": "two"},
            {"turn": 1, "type": "tool_result", "result": "r1"},
            {"turn": 1, "type": "tool_result", "result": "r2"},
        ]
        assert paired_results(transcript) == {1: "r1", 3: "r2"}


class TestACallWithNoAnswer:
    """Absent rather than empty. The shell returning nothing is a finding about
    the episode; the transcript stopping mid-turn is a finding about the
    harness, and a caller has to be able to tell which it is looking at."""

    def test_an_unanswered_call_is_absent_from_the_mapping(self):
        transcript = [
            {"turn": 1, "type": "tool_call", "cmd": "one"},
            {"turn": 1, "type": "tool_call", "cmd": "two"},
            {"turn": 1, "type": "tool_result", "result": "r1"},
        ]
        paired = paired_results(transcript)
        assert paired == {0: "r1"}
        assert paired.get(1) is None

    def test_an_empty_result_is_present_as_empty(self):
        """Distinct from the case above: the shell answered, with nothing."""
        transcript = [
            {"turn": 1, "type": "tool_call", "cmd": "one"},
            {"turn": 1, "type": "tool_result", "result": ""},
        ]
        paired = paired_results(transcript)
        assert paired == {0: ""}
        assert 0 in paired

    def test_an_empty_transcript_pairs_nothing(self):
        assert paired_results([]) == {}
        assert paired_results(None) == {}


class TestTheSameCommandTwice:
    """Keyed on the transcript INDEX, not the command text, so two occurrences
    of one command keep their own answers."""

    def test_each_occurrence_keeps_its_own_result(self):
        transcript = [
            {"turn": 1, "type": "tool_call", "cmd": "ls"},
            {"turn": 1, "type": "tool_result", "result": "first"},
            {"turn": 2, "type": "tool_call", "cmd": "ls"},
            {"turn": 2, "type": "tool_result", "result": "second"},
        ]
        assert paired_results(transcript) == {0: "first", 2: "second"}
