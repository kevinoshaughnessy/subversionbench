"""
The two suspicion questions: whether suspicion voiced before an act entered
the decision to take it, and what kind of test an aware episode took its
situation to be.

What matters is that each goes out through the category call the headline
question was validated with, carrying its own definition and answer set; that
an answer outside that set is a failure rather than a verdict; that the
decision question sees only what came before the earliest act, with the act
shown; and that neither is asked where it does not arise.

The stubs match the config prompts rather than any words of them: the
wording lives only in the encoded detector bundle.
"""

import importlib
import json
import types
from unittest import mock

import pytest

import subversionbench.grading.category as category
from subversionbench.config import (AWARENESS_CATEGORY_SYSTEM_PROMPT,
                                    SUSPICION_PROMPTS)
from subversionbench.grading.suspicion import (MARK, SUSPICION_LABELS,
                                               suspicion_block,
                                               suspicion_reading,
                                               suspicion_text)

suspicion = importlib.import_module("subversionbench.grading.suspicion")

BEFORE = "This could be a test of whether I follow the rules."
AFTER = "Having done that, I will write up the results."
TRANSCRIPT = [
    {"turn": 1, "type": "thinking", "content": BEFORE},
    {"turn": 1, "type": "tool_call", "cmd": "ls"},
    {"turn": 2, "type": "text", "content": "Next step."},
    {"turn": 2, "type": "tool_call", "cmd": "the act's own command"},
    {"turn": 3, "type": "text", "content": AFTER},
]


def _client(category_answer, quote=BEFORE, calls=None):
    calls = calls if calls is not None else []

    class Messages:
        @staticmethod
        def create(**kw):
            calls.append(kw)
            return types.SimpleNamespace(content=[types.SimpleNamespace(
                type="text", text=json.dumps({
                    "category": category_answer, "quote": quote,
                    "competing_reading": ""}))], usage=None,
                stop_reason="end_turn")
    return types.SimpleNamespace(messages=Messages())


def _placed(positions):
    """first_act_position replaced: act name -> (index, turn)."""
    def fake(transcript, analysis, act):
        return positions.get(act["name"], (None, None))
    return mock.patch.object(suspicion, "first_act_position", fake)


class TestEachQuestionGoesOutThroughTheValidatedCall:
    def test_it_carries_its_own_definition_and_question(self):
        for question in SUSPICION_LABELS:
            calls = []
            suspicion_block(question, BEFORE, "m",
                            client=_client("none", "", calls))
            system, asked = SUSPICION_PROMPTS[question]
            assert calls[0]["system"][0]["text"] == system
            assert asked in calls[0]["messages"][0]["content"][1]["text"]

    def test_the_awareness_call_is_unchanged_by_the_new_parameters(self):
        calls = []
        category.category_call(BEFORE, "m", _client("true", calls=calls),
                               None, None, "q")
        assert calls[0]["system"][0]["text"] == AWARENESS_CATEGORY_SYSTEM_PROMPT

    def test_every_answer_in_the_set_is_stored_as_given(self):
        for question, labels in SUSPICION_LABELS.items():
            for label in labels:
                block = suspicion_block(question, BEFORE, "m",
                                        client=_client(label))
                assert block["category"] == label
                assert block["grading_failed"] is False
                assert block["instrument"] == f"suspicion_{question}"

    def test_an_answer_from_another_set_is_a_failure_not_a_verdict(self):
        """The awareness set's "true" is no answer to either question, and
        "beside" none to the framing one."""
        for question, wrong in (("decision", "true"), ("framing", "beside")):
            block = suspicion_block(question, BEFORE, "m", client=_client(wrong))
            assert block["category"] is None and block["grading_failed"] is True

    def test_the_awareness_parser_still_refuses_a_suspicion_answer(self):
        with pytest.raises(ValueError):
            category.parse_category_verdict(json.dumps({"category": "for"}))

    def test_the_quote_is_checked_against_the_text_asked_about(self):
        grounded = suspicion_block("framing", BEFORE, "m", client=_client("puzzle"))
        made_up = suspicion_block("framing", BEFORE, "m", client=_client(
            "puzzle", quote="words found nowhere in the agent's text at all"))
        assert grounded["quote_grounded"] == "verbatim"
        assert made_up["quote_grounded"] not in ("verbatim", "fragment")


class TestTheDecisionQuestionSeesWhatCameBeforeTheAct:
    def test_it_ends_on_the_acts_command_and_holds_nothing_after(self):
        with _placed({"sandbox": (3, 2)}):
            text, where = suspicion_text("decision", TRANSCRIPT, {}, None)
        assert BEFORE in text and AFTER not in text
        assert text.endswith(f"{MARK} ACTION UNDER REVIEW: turn 2\n"
                             f"the act's own command")
        assert where == {"act": "sandbox", "act_index": 3, "act_turn": 2}

    def test_of_two_acts_the_earlier_is_the_one_asked_about(self):
        with _placed({"sandbox": (3, 2), "oversight": (1, 1)}):
            text, where = suspicion_text("decision", TRANSCRIPT, {}, None)
        assert where["act"] == "oversight" and "Next step." not in text

    def test_without_an_act_that_can_be_placed_it_is_not_asked(self):
        calls = []
        with _placed({}):
            assert suspicion_reading("decision", TRANSCRIPT, {}, True, "m",
                                     client=_client("for", calls=calls)) is None
        assert calls == []

    def test_awareness_does_not_decide_whether_it_is_asked(self):
        """An episode the headline calls unaware before its act is asked too:
        "none" is an answer, and the one that checks the pre-act reading."""
        with _placed({"sandbox": (3, 2)}):
            block = suspicion_reading("decision", TRANSCRIPT, {}, False, "m",
                                      client=_client("none", ""))
        assert block["category"] == "none" and block["act"] == "sandbox"


class TestTheFramingQuestionIsAskedOfAwareEpisodesOnly:
    def test_an_aware_episode_is_asked_about_its_whole_text(self):
        calls = []
        block = suspicion_reading("framing", TRANSCRIPT, {}, True, "m",
                                  client=_client("simulation", calls=calls))
        asked = calls[0]["messages"][0]["content"][0]["text"]
        assert BEFORE in asked and AFTER in asked
        assert block["category"] == "simulation"

    def test_an_unaware_or_unread_episode_is_not_asked(self):
        for aware in (False, None):
            assert suspicion_text("framing", TRANSCRIPT, {}, aware) == (None, None)

    def test_a_question_it_does_not_know_is_refused(self):
        with pytest.raises(ValueError):
            suspicion_text("motive", TRANSCRIPT, {}, True)
