"""
One rubric question, asked again when the route did not answer.

WHAT THIS IS FOR. A failed rubric question comes back answer=None, and
classify_awareness_from_rubric reads None as "no signal" - so a flaky call and
a confident negative are the same thing to the verdict. Across r10's 53,915
rubric questions 539 failed, 443 of them an empty reply from claude-opus-5
(0.82% of its calls).

The failures are transient, which the corpus showed rather than argued: three
episodes whose EVERY question had errored were re-asked once and recovered 1,
7 and 4 questions. Transcript-specific failures would have recurred
identically.

The distinction that matters here is not "did it retry" but WHAT it retries. A
reply that arrived and would not parse is the one failure mode indicating a
real problem with the prompt or the model rather than the route, and retrying
past it would hide exactly that.
"""

import types
import unittest

from subversionbench.grading import grader


def _client(*replies):
    """A grader whose successive calls return `replies` in order.

    Each reply is the raw text of a text block, or an Exception to raise.
    """
    calls = {"n": 0}

    class _Messages:
        @staticmethod
        def create(**kw):
            i = min(calls["n"], len(replies) - 1)
            calls["n"] += 1
            r = replies[i]
            if isinstance(r, Exception):
                raise r
            return types.SimpleNamespace(
                content=[types.SimpleNamespace(type="text", text=r)],
                usage=types.SimpleNamespace(input_tokens=1, output_tokens=1))

    class _Client:
        messages = _Messages()

    return _Client(), calls


GOOD = '{"answer": true, "quote": "said it"}'


def _ask(*replies, **kw):
    client, calls = _client(*replies)
    kw.setdefault("sleep", lambda _s: None)
    got = grader.ask_rubric_question("q?", "some agent text", "claude-opus-5",
                                     client=client, **kw)
    return got, calls["n"]


class TestATransientFailureIsAskedAgain(unittest.TestCase):

    def test_an_empty_reply_is_retried_and_the_answer_recovered(self):
        """The dominant failure: 443 of 539. The retry is the whole fix."""
        got, n = _ask("", GOOD)
        assert got["answer"] is True
        assert got["error"] is None
        assert n == 2

    def test_a_5xx_is_retried(self):
        got, n = _ask(RuntimeError("Error code: 529 - overloaded_error"), GOOD)
        assert got["answer"] is True
        assert n == 2

    def test_a_rate_limit_is_retried(self):
        got, n = _ask(RuntimeError("429 rate limit exceeded"), GOOD)
        assert got["answer"] is True and n == 2

    def test_a_timeout_is_retried(self):
        got, n = _ask(RuntimeError("Request timed out"), GOOD)
        assert got["answer"] is True and n == 2


class TestAnAnsweredButUnreadableReplyIsNotRetried(unittest.TestCase):
    """The distinction the retry exists around.

    An empty reply and a 5xx say the call did not happen. A reply that ARRIVED
    and would not parse says the grader produced something unreadable, which is
    the one failure mode pointing at the prompt or the model rather than the
    route. Retrying past it would hide it - and would double the cost of every
    genuinely broken question.
    """

    def test_a_non_empty_unparseable_reply_is_asked_once(self):
        got, n = _ask("I think the answer is probably yes, on balance.", GOOD)
        assert got["answer"] is None
        assert n == 1, "an arrived-but-unreadable reply must not be retried"

    def test_its_error_still_carries_the_reply(self):
        got, _n = _ask("not json at all", GOOD)
        assert "not json at all" in got["error"]

    def test_the_two_cases_are_told_apart_by_the_classifier(self):
        """Both are parse failures from the same code path; only the empty
        one is transient. If _is_transient stopped distinguishing them, one
        of these flips."""
        assert grader._is_transient("no JSON object in reply: ''")
        assert not grader._is_transient(
            "no JSON object in reply: 'I think yes' | raw reply (11 chars)")

    def test_an_empty_reply_the_api_explains_is_not_retried(self):
        """Out of room while thinking, or declined, recurs on the same call -
        the retry only buys a second full ceiling. An unexplained empty reply
        is still retried, which is the control."""
        empty = "no JSON object in reply: '' | raw reply (0 chars): ''"
        assert grader._is_transient(f"{empty} [stop_reason=None, blocks=[]]")
        for stop in ("max_tokens", "refusal", "incomplete:max_output_tokens"):
            assert not grader._is_transient(
                f"{empty} [stop_reason={stop!r}, blocks=['thinking']]"), stop


class TestTheRetryIsBounded(unittest.TestCase):

    def test_a_persistently_empty_route_stops_after_the_budget(self):
        """A route that is down fails every call. Without a bound this is an
        unbounded spend against an endpoint that cannot answer."""
        got, n = _ask("", "", "", "")
        assert got["answer"] is None
        assert n == grader._RUBRIC_ATTEMPTS

    def test_the_budget_is_more_than_one(self):
        """Otherwise the retry does not exist, and every test above passes
        for the wrong reason."""
        assert grader._RUBRIC_ATTEMPTS >= 2

    def test_attempts_can_be_capped_by_the_caller(self):
        got, n = _ask("", GOOD, attempts=1)
        assert n == 1 and got["answer"] is None


class TestTheNumberOfCallsIsReported(unittest.TestCase):
    """So a corpus can be asked afterwards how often the route needed asking
    twice, rather than the retry hiding a degrading endpoint."""

    def test_a_first_time_success_reports_one(self):
        got, _n = _ask(GOOD)
        assert got["attempts"] == 1

    def test_a_recovered_question_reports_two(self):
        got, _n = _ask("", GOOD)
        assert got["attempts"] == 2

    def test_a_failure_reports_what_it_spent(self):
        got, _n = _ask("", "")
        assert got["attempts"] == grader._RUBRIC_ATTEMPTS


class TestTheBackoffIsRealButInjectable(unittest.TestCase):
    """A retry fired inside an overloaded endpoint's own backoff window is a
    second failure rather than a second chance. The suite must not wait for
    it, which is why sleep is a parameter rather than a constant."""

    def test_it_waits_between_attempts(self):
        waited = []
        _ask("", GOOD, sleep=waited.append)
        assert waited == [grader._RETRY_BACKOFF_S]

    def test_it_does_not_wait_when_the_first_call_works(self):
        waited = []
        _ask(GOOD, sleep=waited.append)
        assert waited == []

    def test_it_does_not_wait_after_the_last_attempt(self):
        """A sleep after the final try delays the caller and paces nothing."""
        waited = []
        _ask("", "", sleep=waited.append)
        assert len(waited) == grader._RUBRIC_ATTEMPTS - 1


class TestTheCallCountReachesTheSTOREDCell(unittest.TestCase):
    """The claim v206 shipped with, which was false when it shipped.

    _ask_rubric_subset rebuilds every rubric cell field by field, so a key it
    does not name is dropped on the way to the run file. `attempts` came out
    of ask_rubric_question and never reached the corpus - and the tests above
    could not see it, because they assert on the function's return value and
    the claim was about what is persisted.

    So these assert on the rubric dict a grading actually produces.
    """

    def _rubric(self, *replies):
        from unittest import mock
        client, _calls = _client(*replies)
        with mock.patch.object(grader, "check_quote_grounding",
                               lambda *a, **k: "verbatim"):
            results, _cache = grader._ask_rubric_subset(
                [{"turn": 1, "type": "text", "content": "agent said this"}],
                ["mentioned_test"], "claude-opus-5", client=client)
        return results["mentioned_test"]

    def test_a_first_time_answer_records_one_attempt(self):
        assert self._rubric(GOOD)["attempts"] == 1

    def test_a_retried_answer_records_two(self):
        assert self._rubric("", GOOD)["attempts"] == 2

    def test_a_failed_question_records_what_it_spent(self):
        """The branch most worth knowing about, and a different code path -
        the failure branch builds its own dict."""
        cell = self._rubric("", "")
        assert cell["answer"] is None
        assert cell["attempts"] == grader._RUBRIC_ATTEMPTS
