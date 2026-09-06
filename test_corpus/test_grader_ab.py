"""
The grader model x call shape experiment: what it asks, and what it costs.

THE BATCHED REPLY IS PARSED AS STRICTLY AS THE SHIPPED ONE. The whole point of
the experiment is to find out whether batching costs accuracy, so a lenient
parser here would answer the question in batching's favour by turning its
malformed replies into confident verdicts. Every answer goes through the
shipped `parse_boolean_verdict`, and these pin that: a missing answer field, a
string "false", a non-string quote and an omitted question are each an error
rather than a False.

Cost is measured, never guessed. Three kinds of not-knowing are kept apart - an
unpriced model, a shape that hides its output tokens, and calls that errored
before any usage record existed - and none is ever reported as zero.
"""


import json

import grader_ab as ab
import subversionbench.llm_client as ev_llm
from subversionbench.config import RUBRIC_QUESTIONS
from test_corpus.grader_ab_fixtures import (
    _rubric)


class TestTheBatchedReplyIsParsedStrictly:
    """A reply the harness could not read is a measurement that did not happen.
    These are the same three defects parse_boolean_verdict was written for, put
    to the batched path, plus the one the batched shape adds on its own."""

    def _client(self, text):
        class Block:
            type = "text"

            def __init__(self, t):
                self.text = t

        class Messages:
            def create(self, **kwargs):
                class R:
                    content = [Block(text)]
                    usage = None
                return R()

        class Client:
            messages = Messages()
        return Client()

    def _ask(self, text):
        return ab.ask_rubric_batch("agent text", "test-model",
                                   client=self._client(text))

    def test_a_well_formed_reply_is_read(self):
        keys = list(RUBRIC_QUESTIONS)
        body = {k: {"answer": k == keys[0], "quote": "q" if k == keys[0] else ""}
                for k in keys}
        got = self._ask(json.dumps(body))
        assert got[keys[0]]["answer"] is True
        assert got[keys[1]]["answer"] is False
        assert all(v["error"] is None for v in got.values())

    def test_every_question_is_present_even_when_the_reply_omits_one(self):
        """Absence must be visible as an error, not as a missing key a caller
        could mistake for a question that was never asked."""
        keys = list(RUBRIC_QUESTIONS)
        body = {k: {"answer": False, "quote": ""} for k in keys[1:]}
        got = self._ask(json.dumps(body))
        assert set(got) == set(keys)
        assert got[keys[0]]["answer"] is None
        assert keys[0] in got[keys[0]]["error"]

    def test_a_missing_answer_field_is_an_error_not_a_false(self):
        keys = list(RUBRIC_QUESTIONS)
        body = {k: {"quote": "no answer field"} for k in keys}
        got = self._ask(json.dumps(body))
        assert all(v["answer"] is None for v in got.values())

    def test_the_string_false_is_not_read_as_true(self):
        """bool("false") is True. The shipped parser handles the word forms and
        this path must inherit that rather than coerce."""
        keys = list(RUBRIC_QUESTIONS)
        got = self._ask(json.dumps({k: {"answer": "false", "quote": ""}
                                    for k in keys}))
        assert all(v["answer"] is False for v in got.values())

    def test_a_non_string_quote_is_refused(self):
        keys = list(RUBRIC_QUESTIONS)
        got = self._ask(json.dumps({k: {"answer": True, "quote": ["a", "b"]}
                                    for k in keys}))
        assert all(v["answer"] is None for v in got.values())

    def test_prose_around_the_json_is_tolerated(self):
        keys = list(RUBRIC_QUESTIONS)
        body = json.dumps({k: {"answer": False, "quote": ""} for k in keys})
        got = self._ask(f"Here is my assessment:\n{body}\nLet me know.")
        assert all(v["answer"] is False for v in got.values())

    def test_a_brace_inside_a_quote_does_not_truncate_the_object(self):
        """Brace counting rather than a regex, because a cited quote can contain
        one - and a truncated parse would score every answer as an error."""
        keys = list(RUBRIC_QUESTIONS)
        body = {k: {"answer": True, "quote": 'the dict {"a": 1} appeared'}
                for k in keys}
        got = self._ask(json.dumps(body))
        assert all(v["answer"] is True for v in got.values()), \
            [v["error"] for v in got.values() if v["error"]]

    def test_one_unreadable_reply_costs_every_answer(self):
        """Inherent to the shape rather than a flaw, and one of the things the
        experiment measures - so it must be recorded on all nine keys rather
        than raising."""
        got = self._ask("I would rather not answer in JSON.")
        assert len(got) == len(RUBRIC_QUESTIONS)
        assert all(v["answer"] is None for v in got.values())

    def test_an_api_exception_is_reported_not_raised(self):
        class Boom:
            class messages:
                @staticmethod
                def create(**kwargs):
                    raise RuntimeError("rate limited")
        got = ab.ask_rubric_batch("text", "m", client=Boom())
        assert all(v["answer"] is None for v in got.values())
        assert all("rate limited" in v["error"] for v in got.values())


class TestTheBatchedCallRefusesAReplyItCannotRead:
    """Every one of these lands as an error on all nine keys rather than as a
    confident False, which is the property the shape is being measured on."""

    def _client(self, content):
        class Client:
            class messages:
                @staticmethod
                def create(**kwargs):
                    class R:
                        pass
                    R.content = content
                    R.usage = None
                    return R()
        return Client()

    def _block(self, text):
        class Block:
            type = "text"
        Block.text = text
        return Block()

    def test_a_reply_with_no_text_block_is_a_reply_problem(self):
        """A thinking-only reply, or a tool block and nothing else. Labelled
        `reply` rather than `other`, because it is the batched shape's own
        fragility being measured and not the transport's."""
        class Thinking:
            type = "thinking"
        got = ab.ask_rubric_batch("text", "m", client=self._client([Thinking()]))
        assert all(v["answer"] is None for v in got.values())
        assert all(v["error_kind"] == "reply" for v in got.values())
        assert all("no text block" in v["error"] for v in got.values())

    def test_a_reply_that_is_a_bare_array_is_a_parse_failure(self):
        """Not a rubric and not an object, so there is nothing to key answers
        off. Reported as a parse failure rather than as nine omitted questions,
        because those say different things about the grader: one ignored the
        keys, this one ignored the shape entirely."""
        keys = list(RUBRIC_QUESTIONS)
        got = ab.ask_rubric_batch(
            "text", "m", client=self._client([self._block("[true, false]")]))
        assert set(got) == set(keys), (
            "every question must be present even when the reply was unusable")
        assert all(v["answer"] is None for v in got.values())
        assert all("did not parse" in v["error"] for v in got.values())

    def test_the_asker_builds_its_own_client_when_given_none(self):
        """main always passes one. The rubric harness and rubric_ab do not, so
        the no-client path is a supported entry rather than dead code."""
        asked = []
        original = ev_llm.get_client
        ev_llm.get_client = lambda model, **kw: asked.append(model) or self._client(
            [self._block('{"x": 1}')])
        try:
            ab.ask_rubric_batch("text", "grader/xyz", client=None)
        finally:
            ev_llm.get_client = original
        assert asked == ["grader/xyz"], (
            "the asker either reached a real client or never built one")


class TestAThrottledCallCannotBeMistakenForAFragileShape:
    """The failure-granularity read-out counts unanswered questions, and a
    rate-limited call is unanswered in exactly the same way a malformed reply
    is. Batched, one throttled call costs all nine answers - which would read as
    the batched SHAPE being fragile, the experiment concluding against batching
    for a reason with nothing to do with batching."""

    def test_an_auth_failure_is_classified_apart_from_a_bad_reply(self):
        auth = ("Could not resolve authentication method. Expected one of "
                "api_key, auth_token, or credentials to be set")
        assert ab.classify_error(auth) == "auth"
        assert ab.classify_error("batched reply did not parse: x",
                                 from_reply=True) == "reply"

    def test_a_reply_problem_is_not_labelled_transport(self):
        """The distinction the batched path exists to make. Labelling its own
        parse failures as transport would hide the fragility being measured."""
        assert ab.classify_error("reply carried no text block",
                                 from_reply=True) == "reply"
        assert ab.classify_error("something odd") == "other"

    def test_no_error_is_no_kind(self):
        assert ab.classify_error(None) is None

    def test_a_fatal_kind_is_recognised_from_a_whole_rubric(self):
        keys = list(RUBRIC_QUESTIONS)
        auth = {k: {"answer": None, "quote": "", "error": "401 unauthorized",
                    "error_kind": "auth"} for k in keys}
        assert ab.fatal_error_kind(auth) == "auth"

    def test_an_ordinary_reply_failure_is_not_fatal(self):
        """A grader that could not produce readable JSON for one episode is a
        measurement, not a reason to stop the run."""
        keys = list(RUBRIC_QUESTIONS)
        bad = {k: {"answer": None, "quote": "", "error": "did not parse",
                   "error_kind": "reply"} for k in keys}
        assert ab.fatal_error_kind(bad) is None

    def test_a_clean_rubric_is_not_fatal(self):
        keys = list(RUBRIC_QUESTIONS)
        assert ab.fatal_error_kind(_rubric(keys, [True] * len(keys))) is None

    def test_the_batched_asker_labels_an_auth_failure_as_auth(self):
        """End to end through the real asker, because the label has to survive
        the failure path that produces it."""
        class Boom:
            class messages:
                @staticmethod
                def create(**kwargs):
                    raise RuntimeError(
                        "Could not resolve authentication method. Expected one "
                        "of api_key, auth_token, or credentials to be set")
        got = ab.ask_rubric_batch("text", "m", client=Boom())
        assert ab.fatal_error_kind(got) == "auth"

    def test_the_batched_asker_labels_a_malformed_reply_as_reply(self):
        class Block:
            type = "text"
            text = "no JSON here at all"

        class Client:
            class messages:
                @staticmethod
                def create(**kwargs):
                    class R:
                        content = [Block()]
                    return R()
        got = ab.ask_rubric_batch("text", "m", client=Client())
        assert all(v["error_kind"] == "reply" for v in got.values())
        assert ab.fatal_error_kind(got) is None


class TestTheDelayPacesCallsRatherThanEpisodes:
    """Nine calls fired back to back is the burst a per-minute limit catches, so
    a delay that only runs between episodes does not pace the thing that trips
    the limit."""

    def test_the_per_question_shape_sleeps_between_its_calls(self):
        keys = list(RUBRIC_QUESTIONS)
        slept, asked = [], []
        original_sleep, original_ask = ab.shapes.time.sleep, ab.shapes.ask_rubric_question
        ab.shapes.time.sleep = slept.append
        ab.shapes.ask_rubric_question = lambda q, c, m, cl, channel_id=None: (
            asked.append(q), {"answer": False, "quote": "", "error": None})[1]
        try:
            ab.ask_per_question("corpus", "m", client=object(), delay=0.25)
        finally:
            ab.shapes.time.sleep, ab.shapes.ask_rubric_question = original_sleep, original_ask
        assert len(asked) == len(keys)
        # One sleep BETWEEN each pair, not after the last.
        assert slept == [0.25] * (len(keys) - 1)

    def test_no_delay_means_no_sleeping(self):
        original_sleep, original_ask = ab.shapes.time.sleep, ab.shapes.ask_rubric_question
        slept = []
        ab.shapes.time.sleep = slept.append
        ab.shapes.ask_rubric_question = lambda *a, **k: {
            "answer": False, "quote": "", "error": None}
        try:
            ab.ask_per_question("corpus", "m", client=object(), delay=0)
        finally:
            ab.shapes.time.sleep, ab.shapes.ask_rubric_question = original_sleep, original_ask
        assert slept == []

    def test_both_shapes_accept_the_delay(self):
        """The runner passes it positionally to whichever shape is selected, so
        a shape that did not accept it would raise mid-run."""
        import inspect
        for name, fn in ab.SHAPES.items():
            assert "delay" in inspect.signature(fn).parameters, name

    def test_both_shapes_actually_SLEEP_for_the_delay(self):
        """Accepting it is not honouring it, and this test used to check only
        the signature. `ask_rubric_batch` took `delay` and never slept, so
        --delay was inert for that whole shape - and the report's own
        remediation text tells the operator to re-run with --delay to clear
        the transport errors that only the batched shape can distinguish. The
        advice was a no-op exactly where it was given.

        Timed as a DIFFERENCE against the same shape run with no delay, so
        per-call overhead and the stub's own cost cancel and nothing here is
        tuned to one machine."""
        import time

        class Boom:
            """Fails the call, because the failing path is the one that
            matters: a throttled call is what pacing exists to stop
            recurring, and it returns through an error branch."""
            class messages:
                @staticmethod
                def create(**kw):
                    raise RuntimeError("rate limited")

        def elapsed(shape, name, d):
            """Bound as arguments rather than closed over: a nested function
            capturing the loop variable reads the LAST one at call time, which
            is a latent defect even where the call happens to be inside the
            iteration."""
            start = time.monotonic()
            out = shape("corpus", "claude-opus-5", Boom(), "ch", delay=d,
                        usage_sink=[], unmeasured_sink=[])
            assert out, name
            return time.monotonic() - start

        delay = 0.15
        for name, fn in sorted(ab.SHAPES.items()):
            without = elapsed(fn, name, 0)
            with_delay = elapsed(fn, name, delay)
            assert with_delay - without >= delay * 0.8, (
                f"{name} took {with_delay:.2f}s with delay={delay} against "
                f"{without:.2f}s without it - the delay is accepted and "
                f"ignored, so --delay does nothing for this shape")

    def test_the_batched_shape_paces_once_per_call_not_once_per_question(self):
        """The two shapes make a different NUMBER of calls, so the same
        --delay lands differently: nine calls within an episode against one.
        Asserted so the asymmetry is a recorded consequence of the flag's
        documented meaning - seconds after every API call - rather than
        something a later reader might "fix" into a discrepancy."""
        import time

        class Boom:
            class messages:
                @staticmethod
                def create(**kw):
                    raise RuntimeError("rate limited")

        delay = 0.1
        timings = {}
        for name, fn in ab.SHAPES.items():
            start = time.monotonic()
            fn("corpus", "claude-opus-5", Boom(), "ch", delay=delay,
               usage_sink=[], unmeasured_sink=[])
            timings[name] = time.monotonic() - start
        # One sleep against eight, so the per-question shape must be the
        # slower of the two by several multiples of the delay.
        assert timings["per_question"] > timings["batched"] + delay * 3, timings

    def test_every_shape_accepts_everything_the_runner_passes_it(self):
        """The rule, not one keyword of it.

        `delay` was guarded by name above and `unmeasured_sink` was not, so
        adding the second broke every caller of a shape that had not been
        updated - including this suite's own test double - as a TypeError on
        the first episode, hours into nothing. The argument list is READ OUT
        OF main() rather than restated here, so a keyword added there is
        covered by this guard on the same commit that adds it.
        """
        import ast
        import inspect
        # cli, not the package: `inspect.getsource` of a package returns only
        # its __init__, so reading the argument list off `ab` stopped finding
        # anything the moment the script became one - the empty scope this
        # assertion's own message warns about.
        source = inspect.getsource(ab.cli)
        calls = [node for node in ast.walk(ast.parse(source))
                 if isinstance(node, ast.Call)
                 and isinstance(node.func, ast.Name)
                 and node.func.id == "asker"]
        assert calls, ("no asker(...) call found in grader_ab.cli - this guard "
                       "reads the runner's argument list from it, and an "
                       "empty scope would make every assertion below vacuous")
        for call in calls:
            n_positional = len(call.args)
            keywords = {kw.arg for kw in call.keywords if kw.arg}
            for name, fn in ab.SHAPES.items():
                params = inspect.signature(fn).parameters
                positional = [p for p in params.values()
                              if p.kind in (p.POSITIONAL_ONLY,
                                            p.POSITIONAL_OR_KEYWORD)]
                assert len(positional) >= n_positional, (
                    f"{name} takes {len(positional)} positional arg(s), the "
                    f"runner passes {n_positional}")
                missing = keywords - set(params)
                assert not missing, f"{name} does not accept {sorted(missing)}"
class TestCostIsMeasuredNotGuessed:
    """A killed run was priced from a call count with no dollar figure behind
    it, twice, because nothing in the harness tracked real spend. These pin the
    primitives that replace guessing: real token counts off the response, and a
    price table that says None rather than $0 for a model it does not know."""

    def _usage(self, output=None, read=0, written=0, uncached=1000):
        return {"read": read, "written": written, "uncached": uncached,
               "output": output}

    def test_a_known_model_prices_input_and_output(self):
        usage = self._usage(output=100, uncached=1000)
        got = ab.usage_cost_usd(usage, "claude-opus-5")
        expected = 1000 * 5.0 / 1e6 + 100 * 25.0 / 1e6
        assert got == expected

    def test_cache_read_and_write_carry_their_own_multipliers(self):
        """0.1x read, 1.25x write - the same discount structure production's
        own cache accounting uses. Getting this wrong would silently mis-price
        every cached call, which is most of them."""
        usage = self._usage(output=0, read=10_000, written=1_000, uncached=0)
        got = ab.usage_cost_usd(usage, "claude-opus-5")
        expected = (10_000 * 0.1 + 1_000 * 1.25) * 5.0 / 1e6
        assert abs(got - expected) < 1e-12

    def test_an_unpriced_model_is_none_not_zero(self):
        """A missing price is an unknown cost. Reporting it as free would be
        worse than not reporting it - the harness would show $0.00 while real
        money was spent."""
        assert ab.usage_cost_usd(self._usage(output=10), "some-new-model") is None

    def test_missing_output_refuses_the_exact_total(self):
        """The per_question shape's signature gap: usage_cost_usd will not
        silently treat an unmeasured output as zero and understate the total."""
        assert ab.usage_cost_usd(self._usage(output=None), "claude-opus-5") is None

    def test_the_floor_prices_input_only_regardless_of_output(self):
        usage = self._usage(output=None, uncached=1000)
        expected = 1000 * 5.0 / 1e6
        assert ab.usage_cost_floor_usd(usage, "claude-opus-5") == expected

    def test_the_floor_is_also_none_for_an_unpriced_model(self):
        assert ab.usage_cost_floor_usd(self._usage(), "some-new-model") is None


class TestCellCostAccumulates:
    def test_it_sums_exact_records(self):
        usages = [{"read": 0, "written": 0, "uncached": 1000, "output": 100}] * 3
        got = ab.cell_cost(usages, "claude-opus-5")
        assert got["is_floor"] is False
        assert abs(got["usd"] - 3 * (1000*5.0/1e6 + 100*25.0/1e6)) < 1e-9

    def test_a_mix_of_exact_and_floor_records_is_flagged_as_floor(self):
        """One per_question-shaped record with no measured output is enough to
        make the WHOLE cell total a floor, not an average of the two."""
        usages = [{"read": 0, "written": 0, "uncached": 1000, "output": 100},
                  {"read": 0, "written": 0, "uncached": 1000, "output": None}]
        got = ab.cell_cost(usages, "claude-opus-5")
        assert got["is_floor"] is True
        assert got["usd"] is not None

    def test_an_unpriced_model_reports_the_call_count_it_could_not_price(self):
        usages = [{"read": 0, "written": 0, "uncached": 1, "output": 1}] * 4
        got = ab.cell_cost(usages, "some-new-model")
        assert got["usd"] is None
        assert got["n_unpriced"] == 4

    def test_zero_calls_is_zero_dollars_not_unknown(self):
        """An empty cell is a real, known amount - nothing was spent - which is
        a different case from a model this harness cannot price at all."""
        got = ab.cell_cost([], "claude-opus-5")
        assert got["usd"] == 0.0


class TestTheAskersRecordUsageWhenGivenAPlaceToPutIt:
    def test_the_batched_asker_captures_output_tokens(self):
        """The one place in this script that can measure a forced-thinking
        model's real output spend, because this call is built from scratch
        rather than routed through a production function that discards it."""
        class Usage:
            cache_read_input_tokens = 500
            cache_creation_input_tokens = 0
            input_tokens = 200
            output_tokens = 4000     # a lot, as a forced-thinking model might

        class Block:
            type = "text"
            text = json.dumps({k: {"answer": False, "quote": ""}
                               for k in RUBRIC_QUESTIONS})

        class Client:
            class messages:
                @staticmethod
                def create(**kwargs):
                    class R:
                        content = [Block()]
                        usage = Usage()
                    return R()

        sink = []
        ab.ask_rubric_batch("corpus", "m", client=Client(), usage_sink=sink)
        assert len(sink) == 1
        assert sink[0]["output"] == 4000
        assert sink[0]["uncached"] == 200

    def test_a_failed_batched_call_records_no_usage(self):
        """No response came back, so there is nothing to have billed - an
        empty sink is correct, not a bug to paper over with a zero record."""
        class Boom:
            class messages:
                @staticmethod
                def create(**kwargs):
                    raise RuntimeError("network error")
        sink = []
        ab.ask_rubric_batch("corpus", "m", client=Boom(), usage_sink=sink)
        assert sink == []

    def test_the_per_question_asker_records_input_only_per_call(self):
        """Nine calls, nine records, each with output=None - the shipped
        ab.shapes.ask_rubric_question does not expose output_tokens, and this must not
        paper over that with a guess."""
        keys = list(RUBRIC_QUESTIONS)
        original = ab.shapes.ask_rubric_question
        ab.shapes.ask_rubric_question = lambda q, c, m, cl, channel_id=None: {
            "answer": False, "quote": "", "error": None,
            "cache": {"read": 10, "written": 0, "uncached": 5}}
        try:
            sink = []
            ab.ask_per_question("corpus", "m", client=object(), usage_sink=sink)
        finally:
            ab.shapes.ask_rubric_question = original
        assert len(sink) == len(keys)
        assert all(r["output"] is None for r in sink)
        assert all(r["read"] == 10 and r["uncached"] == 5 for r in sink)

    def test_a_failed_per_question_call_records_no_usage_for_that_question(self):
        original = ab.shapes.ask_rubric_question
        ab.shapes.ask_rubric_question = lambda q, c, m, cl, channel_id=None: {
            "answer": None, "quote": "", "error": "boom", "cache": None}
        try:
            sink = []
            ab.ask_per_question("corpus", "m", client=object(), usage_sink=sink)
        finally:
            ab.shapes.ask_rubric_question = original
        assert sink == []

    def test_neither_asker_requires_a_sink(self):
        """usage_sink is optional - a caller that does not care about cost must
        not be forced to pass one."""
        keys = list(RUBRIC_QUESTIONS)
        original = ab.shapes.ask_rubric_question
        ab.shapes.ask_rubric_question = lambda q, c, m, cl, channel_id=None: {
            "answer": False, "quote": "", "error": None, "cache": None}
        try:
            got = ab.ask_per_question("corpus", "m", client=object())
        finally:
            ab.shapes.ask_rubric_question = original
        assert set(got) == set(keys)


class TestTheShapesAreBothOffered:
    def test_the_shipped_shape_is_one_of_them(self):
        """The experiment is a comparison, so the control has to be runnable
        through the same code path as the thing being tested."""
        assert "per_question" in ab.SHAPES and "batched" in ab.SHAPES

    def test_the_reference_cell_names_a_real_shape_and_the_shipped_grader(self):
        from subversionbench.config import DEFAULT_GRADER_MODEL
        grader, shape = ab.REFERENCE
        assert shape in ab.SHAPES
        assert grader == DEFAULT_GRADER_MODEL, (
            "the reference cell must be what the corpus was actually graded "
            "with, or the comparison has no baseline")
