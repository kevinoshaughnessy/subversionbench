"""
jev's client: the threshold, the error contract, and the absent quote.

Every test here stubs the transport. Nothing may reach a real socket or read
a real credential, which is the same rule the rest of the suite holds for the
paid routes.
"""

import json
import os
import unittest
from unittest import mock

from grader_ab import jev_client as jev


def _reply(**scores):
    """A jev response carrying a noul score per question."""
    return {"model": "jev-1.13.0",
            "answers": {k: {"type": "noul", "noul": v}
                        for k, v in scores.items()},
            "usage": {"input_tokens": 384, "output_tokens": 22}}


class TestTheNoulThresholdDecidesTheAnswer(unittest.TestCase):
    """jev returns a probability, not a decision, so the boundary is this
    code's own and has to be pinned rather than assumed."""

    def _answer(self, score, threshold=0.5):
        out = jev.ask_rubric_questions_jev(
            ["mentioned_test"], "some text", threshold=threshold,
            post=lambda payload: _reply(mentioned_test=score))
        return out["mentioned_test"]["answer"]

    def test_a_score_above_the_threshold_is_true(self):
        assert self._answer(0.9) is True

    def test_a_score_below_the_threshold_is_false(self):
        assert self._answer(0.1) is False

    def test_a_score_exactly_at_the_threshold_is_true(self):
        """At-or-above, not above: a score that lands exactly on the
        threshold has to fall on a stated side rather than whichever way
        the comparison happens to have been written."""
        assert self._answer(0.5) is True

    def test_the_threshold_is_honoured_rather_than_hardcoded(self):
        assert self._answer(0.6, threshold=0.9) is False
        assert self._answer(0.95, threshold=0.9) is True


class TestTheQuoteIsNeverFabricated(unittest.TestCase):
    """jev cannot cite a span. quote_grounding.py's whole job is catching a
    grader that cites something it was not shown; a synthesized quote here
    would be the same defect wearing a different hat."""

    def test_a_true_answer_carries_an_empty_quote(self):
        out = jev.ask_rubric_questions_jev(
            ["mentioned_test"], "the agent said this is a test",
            post=lambda payload: _reply(mentioned_test=0.99))
        assert out["mentioned_test"]["answer"] is True
        assert out["mentioned_test"]["quote"] == ""

    def test_every_error_path_also_carries_an_empty_quote(self):
        def boom(payload):
            raise OSError("connection reset")

        out = jev.ask_rubric_questions_jev(["mentioned_test"], "text",
                                           post=boom)
        assert out["mentioned_test"]["quote"] == ""


class TestAFailureBecomesAnUnansweredQuestion(unittest.TestCase):
    """The contract ask_per_question already uses: answer None with a reason,
    never a confident False. A transport failure read as "not aware" is the
    absence-is-a-no error the rubric parser exists to prevent."""

    def test_a_transport_failure_answers_none_with_the_reason(self):
        def boom(payload):
            raise OSError("connection reset")

        out = jev.ask_rubric_questions_jev(
            ["mentioned_test", "referenced_system_prompt"], "text", post=boom)
        for key in ("mentioned_test", "referenced_system_prompt"):
            assert out[key]["answer"] is None
            assert "connection reset" in out[key]["error"]

    def test_a_reply_with_no_answers_object_answers_none(self):
        out = jev.ask_rubric_questions_jev(
            ["mentioned_test"], "text", post=lambda payload: {"usage": {}})
        assert out["mentioned_test"]["answer"] is None
        assert out["mentioned_test"]["error"]

    def test_a_missing_question_in_the_reply_answers_none(self):
        """Asked two, answered one: the missing one must not inherit the
        other's verdict, nor quietly disappear from the result."""
        out = jev.ask_rubric_questions_jev(
            ["mentioned_test", "referenced_system_prompt"], "text",
            post=lambda payload: _reply(mentioned_test=0.9))
        assert out["mentioned_test"]["answer"] is True
        assert out["referenced_system_prompt"]["answer"] is None
        assert "referenced_system_prompt" in \
            out["referenced_system_prompt"]["error"]

    def test_a_non_numeric_score_answers_none(self):
        out = jev.ask_rubric_questions_jev(
            ["mentioned_test"], "text",
            post=lambda payload: {"answers": {
                "mentioned_test": {"type": "noul", "noul": "high"}}})
        assert out["mentioned_test"]["answer"] is None

    def test_a_boolean_score_answers_none_rather_than_comparing_as_one(self):
        """bool is an int subclass, so `True` would otherwise pass a numeric
        check and compare against the threshold as 1."""
        out = jev.ask_rubric_questions_jev(
            ["mentioned_test"], "text",
            post=lambda payload: {"answers": {
                "mentioned_test": {"type": "noul", "noul": True}}})
        assert out["mentioned_test"]["answer"] is None


class TestTheRequestJevActuallyReceives(unittest.TestCase):

    def _sent(self, keys=("mentioned_test",), corpus="text"):
        captured = {}

        def post(payload):
            captured.update(payload)
            return _reply(**dict.fromkeys(keys, 0.1))

        jev.ask_rubric_questions_jev(list(keys), corpus, post=post)
        return captured

    def test_every_asked_key_carries_its_instructions_and_criteria(self):
        sent = self._sent(("mentioned_test", "referenced_system_prompt"))
        from subversionbench.config import RUBRIC_QUESTIONS
        for key in ("mentioned_test", "referenced_system_prompt"):
            question = sent["questions"][key]
            assert question["type"] == "noul"
            assert question["instructions"] == RUBRIC_QUESTIONS[key]
            assert set(question["criteria"]) == {"true", "false"}

    def test_both_questions_go_in_ONE_call_by_default(self):
        """Which is cheap and which COUPLES the answers - see
        TestTheCallShapeIsAChoiceBecauseBatchingCouples below. Asserted as
        the default rather than as the right answer: pass batched=False when
        a comparison varies a question, because a payload carrying both
        cannot attribute a change to either."""
        calls = []

        def post(payload):
            calls.append(payload)
            return _reply(mentioned_test=0.1, referenced_system_prompt=0.1)

        jev.ask_rubric_questions_jev(
            ["mentioned_test", "referenced_system_prompt"], "text", post=post)
        assert len(calls) == 1

    def test_the_state_is_truncated_the_way_every_grader_call_is(self):
        """The same budget the LLM graders are held to, reused rather than
        reinvented - and well inside jev's own context limit."""
        from subversionbench.grading.grader_io import (
            _GRADER_TRANSCRIPT_CHAR_BUDGET)
        sent = self._sent(corpus="x" * (_GRADER_TRANSCRIPT_CHAR_BUDGET * 3))
        assert len(sent["state"]) <= _GRADER_TRANSCRIPT_CHAR_BUDGET + 200
        assert "[... middle truncated ...]" in sent["state"]


class TestAKeyWithNoCriteriaIsRefused(unittest.TestCase):
    """jev is scoped to the questions whose criteria have been written and
    reviewed. Falling back to bare instructions for the other seven would
    silently grade them on wording nobody checked."""

    def test_an_unscoped_rubric_key_raises(self):
        with self.assertRaises(ValueError):
            jev.ask_rubric_questions_jev(["suspects_safety_eval"], "text",
                                         post=lambda payload: _reply())

    def test_the_scoped_set_excludes_every_span_dependent_question(self):
        """classify_awareness_kind disambiguates its two purpose questions by
        comparing CITED SPANS, and jev never returns one - so those two can
        never be in this set, however good its criteria wording gets."""
        assert "suspects_safety_eval" not in jev.JEV_CRITERIA
        assert "suspects_capability_eval" not in jev.JEV_CRITERIA

    def test_every_scoped_key_is_a_real_rubric_question(self):
        from subversionbench.config import RUBRIC_QUESTIONS
        for key in jev.JEV_CRITERIA:
            assert key in RUBRIC_QUESTIONS


class TestTheCredentialIsCheckedNotRead(unittest.TestCase):

    def test_missing_credential_names_the_variable_when_absent(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            assert jev.missing_credential() == "OPENROUTER_API_KEY"

    def test_missing_credential_is_none_when_set(self):
        with mock.patch.dict(os.environ, {"OPENROUTER_API_KEY": "x"},
                             clear=True):
            assert jev.missing_credential() is None

    def test_a_variable_set_to_empty_reads_as_missing(self):
        """`export OPENROUTER_API_KEY=` leaves it set and empty. Counting
        that as present would pass the pre-flight check and then fail every
        call of the run - the exact shape llm_client.missing_credential
        exists to stop, where a batch ran every episode against a key it
        never had."""
        with mock.patch.dict(os.environ, {"OPENROUTER_API_KEY": ""},
                             clear=True):
            assert jev.missing_credential() is not None
            assert jev._api_key() is None

    def test_a_typesafe_key_is_not_consulted_for_an_openrouter_host(self):
        """A credential is accepted by the host that issued it and refused
        by any other. Sending an OpenRouter key to api.typesafe.ai returned
        401 on every call of a 5,987-episode pass; honouring TYPESAFE_API_KEY
        now that the route IS OpenRouter would reproduce that inverted."""
        with mock.patch.dict(os.environ, {"TYPESAFE_API_KEY": "wrong-host"},
                             clear=True):
            assert jev._api_key() is None
            assert jev.missing_credential() == "OPENROUTER_API_KEY"

    def test_the_real_transport_refuses_before_opening_a_socket(self):
        """No key, no request: the failure has to happen here rather than as
        an opaque 401 from the other end."""
        with mock.patch.dict(os.environ, {}, clear=True), \
                mock.patch("urllib.request.urlopen") as urlopen:
            with self.assertRaises(RuntimeError):
                jev._post({"model": "m", "state": "s", "questions": {}})
            urlopen.assert_not_called()

    def test_the_real_transport_sends_a_bearer_token_and_json(self):
        class _Body:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def read(self):
                return json.dumps(_reply(mentioned_test=0.2)).encode("utf-8")

        with mock.patch.dict(os.environ, {"OPENROUTER_API_KEY": "secret"},
                               clear=True), \
                mock.patch("urllib.request.urlopen",
                           return_value=_Body()) as urlopen:
            jev._post({"model": "m", "state": "s", "questions": {}})
        request = urlopen.call_args[0][0]
        assert request.full_url == jev.JEV_BASE_URL
        assert request.get_method() == "POST"
        assert request.headers["Authorization"] == "Bearer secret"
        assert request.headers["Content-type"] == "application/json"


class TestTheMeasuredCutIsWhatGetsUsed(unittest.TestCase):
    """0.5 was where the probability got cut when nobody had looked, and it
    cost 32% and 20% of the LLM grader's positives. The tuning run put the
    best cut for these two questions in different places, so the default is
    per-key rather than one number."""

    def _score(self, key, score, **kw):
        return jev.ask_rubric_questions_jev(
            [key], "text", post=lambda payload: _reply(**{key: score}),
            **kw)[key]

    def test_each_key_uses_its_own_measured_cut(self):
        # 0.30 is above mentioned_test's cut and below the other's, so one
        # number could not produce both of these answers.
        assert self._score("mentioned_test", 0.30)["answer"] is True
        assert self._score("referenced_system_prompt", 0.30)["answer"] is False

    def test_the_cut_actually_applied_travels_with_the_answer(self):
        """So a saved result says what it was thresholded at rather than
        leaving a reader to assume 0.5."""
        assert self._score("mentioned_test", 0.9)["threshold"] == \
            jev.JEV_THRESHOLDS["mentioned_test"]

    def test_an_explicit_threshold_still_overrides_every_key(self):
        assert self._score("mentioned_test", 0.30, threshold=0.5)["answer"] \
            is False
        assert self._score("referenced_system_prompt", 0.30,
                           threshold=0.1)["answer"] is True

    def test_every_scoped_key_has_a_measured_cut(self):
        assert set(jev.JEV_THRESHOLDS) == set(jev.JEV_CRITERIA)

    def test_a_key_with_no_entry_falls_back_to_the_default(self):
        with mock.patch.dict(jev.JEV_THRESHOLDS, {}, clear=True):
            answer = self._score("mentioned_test", 0.6)
        assert answer["threshold"] == jev.DEFAULT_JEV_THRESHOLD


class TestTheCredentialMatchesTheHostItIsSentTo(unittest.TestCase):
    """The defect that cost a 5,987-episode pass: the base URL named one
    host and the credential was issued by another, so every call 401'd.

    These two facts have to move together, which is why they are asserted
    together rather than each being obviously right on its own."""

    def test_the_gateway_is_openrouter_not_typesafes_own_host(self):
        from subversionbench.config import OPENROUTER_BASE_URL
        assert jev.JEV_BASE_URL.startswith(OPENROUTER_BASE_URL)

    def test_the_credential_is_the_one_that_gateway_issues(self):
        assert jev._CREDENTIAL_ENV == "OPENROUTER_API_KEY", (
            "the key must be the one the host in JEV_BASE_URL issued - a "
            "mismatch here is a 401 on every call, not a failure at startup")

    def test_the_base_url_is_not_rebuilt_by_hand(self):
        """Derived from the shared constant, so jev cannot drift onto a
        different gateway than the rest of the harness."""
        from subversionbench.config import OPENROUTER_BASE_URL
        assert jev.JEV_BASE_URL == f"{OPENROUTER_BASE_URL}/systemone"


class TestJevNeverRoutesThroughTheModelFactory(unittest.TestCase):
    """Jev shares OpenRouter's gateway but NOT its protocol: get_client
    returns an OpenAI-chat client, which would have no idea what to do with
    jev's `state`/`questions` body."""

    def test_the_model_id_really_is_an_openrouter_shaped_one(self):
        from subversionbench.routing import is_openrouter_model
        assert is_openrouter_model(jev.DEFAULT_JEV_MODEL)

    def test_asking_jev_never_reaches_the_factory(self):
        """Asserted by running it, not by grepping the source: a guard that
        reads this module's text goes stale the moment the call moves into a
        helper, and would not notice a callee reaching the factory either."""
        import subversionbench.llm_client as ev_llm
        with mock.patch.object(ev_llm, "get_client") as get_client:
            jev.ask_rubric_questions_jev(
                ["mentioned_test"], "text",
                post=lambda payload: _reply(mentioned_test=0.9))
        get_client.assert_not_called()


class TestTheCallShapeIsAChoiceBecauseBatchingCouples(unittest.TestCase):
    """Batching is what makes a corpus pass cost pennies, and it couples the
    answers. Measured, not suspected: changing only mentioned_test's wording
    moved 2,249 referenced_system_prompt scores and flipped 29 of its
    verdicts corpus-wide, on a question whose text never changed. jev is
    deterministic, so a shared payload is the only thing that can do it."""

    def _calls(self, keys, **kw):
        seen = []

        def post(payload):
            seen.append(sorted(payload["questions"]))
            return {"answers": {k: {"type": "noul", "noul": 0.3}
                                for k in payload["questions"]}}

        out = jev.ask_rubric_questions_jev(keys, "text", post=post, **kw)
        return seen, out

    def test_batched_sends_every_question_in_one_payload(self):
        seen, _ = self._calls(["mentioned_test", "referenced_system_prompt"])
        assert seen == [["mentioned_test", "referenced_system_prompt"]]

    def test_per_question_sends_each_alone(self):
        """The only way to attribute a change to the question it was made
        to - a payload carrying both cannot."""
        seen, _ = self._calls(["mentioned_test", "referenced_system_prompt"],
                              batched=False)
        assert seen == [["mentioned_test"], ["referenced_system_prompt"]]

    def test_both_shapes_answer_every_key(self):
        for batched in (True, False):
            _, out = self._calls(["mentioned_test",
                                  "referenced_system_prompt"],
                                 batched=batched)
            assert set(out) == {"mentioned_test", "referenced_system_prompt"}
            assert all(v["answer"] is not None for v in out.values())

    def test_one_key_is_one_call_either_way(self):
        """Nothing is gained by splitting a single question, and a second
        call would be paid for nothing."""
        for batched in (True, False):
            seen, _ = self._calls(["mentioned_test"], batched=batched)
            assert seen == [["mentioned_test"]]

    def test_per_question_still_applies_each_keys_own_cut(self):
        """The split must not quietly lose the per-key thresholds."""
        def post(payload):
            return {"answers": {k: {"type": "noul", "noul": 0.30}
                                for k in payload["questions"]}}

        out = jev.ask_rubric_questions_jev(
            ["mentioned_test", "referenced_system_prompt"], "text",
            post=post, batched=False)
        # 0.30 is above mentioned_test's cut and below the other's.
        assert out["mentioned_test"]["answer"] is True
        assert out["referenced_system_prompt"]["answer"] is False

    def test_a_failure_in_one_question_does_not_lose_the_other(self):
        """Batched, one bad reply costs every answer. Split, it should not."""
        def post(payload):
            if "mentioned_test" in payload["questions"]:
                raise OSError("connection reset")
            return {"answers": {k: {"type": "noul", "noul": 0.9}
                                for k in payload["questions"]}}

        out = jev.ask_rubric_questions_jev(
            ["mentioned_test", "referenced_system_prompt"], "text",
            post=post, batched=False)
        assert out["mentioned_test"]["answer"] is None
        assert out["referenced_system_prompt"]["answer"] is True
