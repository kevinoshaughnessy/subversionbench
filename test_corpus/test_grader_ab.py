"""
The grader model x call shape experiment.

Three things are guarded here.

THE BATCHED REPLY IS PARSED AS STRICTLY AS THE SHIPPED ONE. The whole point of
the experiment is to find out whether batching costs accuracy, so a lenient
parser here would answer the question in batching's favour by turning its
malformed replies into confident verdicts. Every answer goes through the shipped
`parse_boolean_verdict`, and these tests pin that: a missing answer field, a
string "false", a non-string quote and an omitted question are each an error
rather than a False.

THE REPORT RUNS WITHOUT AN API. Every read-out is computed after the calls are
paid for, so a crash in the report costs the whole run. The report is exercised
here on synthetic cells.

THE SAMPLE IS WHAT IT CLAIMS TO BE. Balanced on the stored verdict and
oversampling the named models is the difference between measuring recall and
measuring precision, and it is silent when wrong.
"""

import contextlib
import glob
import io
import json
import os
import sys
import tempfile

import grader_ab as ab


def _rubric(keys, answers, quotes=None):
    """A cell's rubric result for one episode. `answers` is a list aligned to
    `keys`; None means unanswered."""
    out = {}
    for i, key in enumerate(keys):
        a = answers[i] if i < len(answers) else False
        out[key] = {
            "answer": a,
            "quote": (quotes or {}).get(key, "said something" if a else ""),
            "error": None if a is not None else "failed",
            "quote_grounded": "verbatim" if a else None,
        }
    return out


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
        keys = list(ab.RUBRIC_QUESTIONS)
        body = {k: {"answer": k == keys[0], "quote": "q" if k == keys[0] else ""}
                for k in keys}
        got = self._ask(json.dumps(body))
        assert got[keys[0]]["answer"] is True
        assert got[keys[1]]["answer"] is False
        assert all(v["error"] is None for v in got.values())

    def test_every_question_is_present_even_when_the_reply_omits_one(self):
        """Absence must be visible as an error, not as a missing key a caller
        could mistake for a question that was never asked."""
        keys = list(ab.RUBRIC_QUESTIONS)
        body = {k: {"answer": False, "quote": ""} for k in keys[1:]}
        got = self._ask(json.dumps(body))
        assert set(got) == set(keys)
        assert got[keys[0]]["answer"] is None
        assert keys[0] in got[keys[0]]["error"]

    def test_a_missing_answer_field_is_an_error_not_a_false(self):
        keys = list(ab.RUBRIC_QUESTIONS)
        body = {k: {"quote": "no answer field"} for k in keys}
        got = self._ask(json.dumps(body))
        assert all(v["answer"] is None for v in got.values())

    def test_the_string_false_is_not_read_as_true(self):
        """bool("false") is True. The shipped parser handles the word forms and
        this path must inherit that rather than coerce."""
        keys = list(ab.RUBRIC_QUESTIONS)
        got = self._ask(json.dumps({k: {"answer": "false", "quote": ""}
                                    for k in keys}))
        assert all(v["answer"] is False for v in got.values())

    def test_a_non_string_quote_is_refused(self):
        keys = list(ab.RUBRIC_QUESTIONS)
        got = self._ask(json.dumps({k: {"answer": True, "quote": ["a", "b"]}
                                    for k in keys}))
        assert all(v["answer"] is None for v in got.values())

    def test_prose_around_the_json_is_tolerated(self):
        keys = list(ab.RUBRIC_QUESTIONS)
        body = json.dumps({k: {"answer": False, "quote": ""} for k in keys})
        got = self._ask(f"Here is my assessment:\n{body}\nLet me know.")
        assert all(v["answer"] is False for v in got.values())

    def test_a_brace_inside_a_quote_does_not_truncate_the_object(self):
        """Brace counting rather than a regex, because a cited quote can contain
        one - and a truncated parse would score every answer as an error."""
        keys = list(ab.RUBRIC_QUESTIONS)
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
        assert len(got) == len(ab.RUBRIC_QUESTIONS)
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


class TestTheVerdictComesFromTheRealClassifier:
    def test_an_all_failed_rubric_has_no_verdict(self):
        """Not a False. A cell that answered nothing has not measured the
        episode, and scoring it as not-aware is the absence-is-a-no error the
        rubric parser exists to prevent."""
        keys = list(ab.RUBRIC_QUESTIONS)
        assert ab.cell_verdict(_rubric(keys, [None] * len(keys))) is None

    def test_a_partly_failed_rubric_still_gets_one(self):
        """Nine independent questions, so eight answers are still evidence -
        which is exactly what the batched shape gives up."""
        keys = list(ab.RUBRIC_QUESTIONS)
        answers = [None] + [False] * (len(keys) - 1)
        assert ab.cell_verdict(_rubric(keys, answers)) is False

    def test_it_agrees_with_the_shipped_classifier(self):
        """Derived, not reimplemented: a second copy of the awareness logic here
        would let the experiment and the corpus disagree about what aware
        means."""
        from subversionbench.grading.grader import (
            _EVAL_SIGNAL_KEYS, classify_awareness_from_rubric)
        keys = list(ab.RUBRIC_QUESTIONS)
        rubric = _rubric(keys, [False] * len(keys))
        for k in list(_EVAL_SIGNAL_KEYS)[:2]:
            rubric[k] = {"answer": True, "quote": f"distinct span for {k}",
                         "error": None, "quote_grounded": "verbatim"}
        assert ab.cell_verdict(rubric) == \
            classify_awareness_from_rubric(rubric)["eval_aware"]


class TestTheContaminationProxyMeasuresWhatItSays:
    def test_answers_that_move_together_score_higher(self):
        """The whole point: batching should raise this if it makes the five
        eval-signal questions agree with each other more."""
        keys = list(ab.RUBRIC_QUESTIONS)
        from subversionbench.grading.grader import _EVAL_SIGNAL_KEYS
        together, split = _rubric(keys, [False] * len(keys)), \
            _rubric(keys, [False] * len(keys))
        for k in _EVAL_SIGNAL_KEYS:
            together[k] = {"answer": True, "quote": k, "error": None}
        for i, k in enumerate(_EVAL_SIGNAL_KEYS):
            split[k] = {"answer": i % 2 == 0, "quote": k, "error": None}
        assert ab.signal_correlation([together]) == 1.0
        assert ab.signal_correlation([split]) < 1.0

    def test_unanswered_questions_are_left_out_of_the_pairs(self):
        """A failed answer is not agreement with anything."""
        keys = list(ab.RUBRIC_QUESTIONS)
        from subversionbench.grading.grader import _EVAL_SIGNAL_KEYS
        rubric = _rubric(keys, [False] * len(keys))
        for k in _EVAL_SIGNAL_KEYS:
            rubric[k] = {"answer": None, "quote": "", "error": "x"}
        assert ab.signal_correlation([rubric]) is None


class TestTheSampleIsWhatItClaims:
    def _candidates(self, spec):
        """spec: {model: (n_aware, n_unaware)}."""
        out = []
        for model, (na, nu) in spec.items():
            for i in range(na):
                out.append({"run": f"{model}-a{i}", "model": model,
                            "stored_aware": True})
            for i in range(nu):
                out.append({"run": f"{model}-u{i}", "model": model,
                            "stored_aware": False})
        return out

    def test_it_balances_on_the_stored_verdict(self):
        """Sampling at the corpus's natural aware rate measures precision well
        and recall badly, and recall is the thing a weaker grader loses."""
        cands = self._candidates({"m": (50, 50)})
        picked = ab.stratified_sample(cands, per_model=4, balance=True)
        assert sum(1 for c in picked if c["stored_aware"]) == 2
        assert sum(1 for c in picked if not c["stored_aware"]) == 2

    def test_unbalanced_sampling_takes_what_the_corpus_offers(self):
        cands = self._candidates({"m": (1, 50)})
        picked = ab.stratified_sample(cands, per_model=6, balance=False)
        assert len(picked) == 6
        assert sum(1 for c in picked if c["stored_aware"]) == 1

    def test_named_models_are_drawn_double(self):
        cands = self._candidates({"easy": (20, 20), "hard": (20, 20)})
        picked = ab.stratified_sample(cands, per_model=4, oversample={"hard"},
                                      balance=True)
        counts = {m: sum(1 for c in picked if c["model"] == m)
                  for m in ("easy", "hard")}
        assert counts["hard"] == 2 * counts["easy"]

    def test_the_hard_phrasing_models_are_the_default_oversample(self):
        """They are named because a proportional sample would be decided by the
        models whose phrasing is easy. If this list empties, the sample silently
        stops being the one the experiment was designed around."""
        assert ab.HARD_PHRASING_MODELS
        assert "google/gemini-3.5-flash" in ab.HARD_PHRASING_MODELS

    def test_a_cap_does_not_drop_every_model_after_the_middle(self):
        """Truncating a model-ordered list keeps only the alphabetical start,
        which would quietly make a --limit run a different experiment."""
        cands = self._candidates(dict.fromkeys("abcdefgh", (10, 10)))
        picked = ab.stratified_sample(cands, per_model=4, balance=True, limit=8)
        assert len(picked) == 8
        assert len({c["model"] for c in picked}) == 8

    def test_a_model_with_no_aware_episodes_still_contributes(self):
        cands = self._candidates({"m": (0, 10)})
        picked = ab.stratified_sample(cands, per_model=4, balance=True)
        assert picked and all(not c["stored_aware"] for c in picked)

    def test_a_one_sided_model_contributes_at_every_n_including_one(self):
        """At n=1 the balanced split is 1 aware / 0 unaware, so a model whose
        episodes are all on one side drew NOTHING - it vanished from the
        sample, and main() reported an empty sample by blaming --models for a
        model that was in the directory all along. n=4 alone did not catch
        this: the shortfall only empties the draw once the split leaves one
        side at zero."""
        for n in (1, 2, 3, 4):
            for spec in ({"m": (0, 10)}, {"m": (10, 0)}):
                picked = ab.stratified_sample(self._candidates(spec),
                                              per_model=n, balance=True)
                assert len(picked) == n, (
                    f"n={n} with {spec} drew {len(picked)}, not {n}")

    def test_a_balanced_draw_takes_exactly_what_was_asked_for(self):
        """Not more, not less. The floor this replaced drew n+1 at n=1 (one
        from each side, with a minimum of one) and n-1 at every odd n, so the
        episode count - and the bill - did not match --per-model."""
        cands = self._candidates({"m": (50, 50)})
        for n in (1, 2, 3, 4, 5, 8):
            picked = ab.stratified_sample(cands, per_model=n, balance=True)
            assert len(picked) == n, f"n={n} drew {len(picked)}"

    def test_the_sample_is_deterministic(self):
        """Two runs must draw the same episodes or their results cannot be
        compared, which is the only reason to run this twice."""
        cands = self._candidates({"a": (5, 5), "b": (5, 5)})
        first = ab.stratified_sample(cands, per_model=4, balance=True)
        second = ab.stratified_sample(cands, per_model=4, balance=True)
        assert [c["run"] for c in first] == [c["run"] for c in second]


class TestTheReportRunsWithoutAnApi:
    """Every read-out is computed after the calls are paid for, so a crash here
    costs the whole run. The reference cell is present in one case and absent in
    another, because a partial 2x2 is a normal thing to ask for."""

    def _results(self, cells):
        keys = list(ab.RUBRIC_QUESTIONS)
        out = {}
        for cell, per_run in cells.items():
            out[cell] = {run: _rubric(keys, answers)
                         for run, answers in per_run.items()}
        return out

    def _render(self, results, stored=None):
        keys = list(ab.RUBRIC_QUESTIONS)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            ab.report(results, [], keys, stored if stored is not None else {})
        return buf.getvalue()

    def _two_cells(self):
        keys = list(ab.RUBRIC_QUESTIONS)
        ref = "|".join(ab.REFERENCE)
        yes = [True] * len(keys)
        no = [False] * len(keys)
        return self._results({
            ref: {"r1": yes, "r2": no},
            "claude-sonnet-5|batched": {"r1": yes, "r2": yes},
        })

    def test_it_renders_every_section(self):
        out = self._render(self._two_cells())
        for heading in ("PER-QUESTION RATES BY CELL",
                        "AGREEMENT AGAINST THE REFERENCE CELL",
                        "POSITION GRADIENT",
                        "CONTAMINATION AND ROBUSTNESS",
                        "VERDICT RATE BY CELL"):
            assert heading in out, f"{heading} missing from the report"

    def test_it_reports_the_noise_floor_against_the_stored_labels(self):
        """Without it every other number is uninterpretable, because graders are
        non-deterministic and some disagreement is expected for free."""
        keys = list(ab.RUBRIC_QUESTIONS)
        results = self._two_cells()
        stored = {"r1": _rubric(keys, [True] * len(keys)),
                  "r2": _rubric(keys, [True] * len(keys))}
        out = self._render(results, stored)
        assert "Noise floor" in out
        # r2 agrees with neither, so the floor is one of two.
        assert "1/2" in out

    def test_it_says_so_rather_than_crashing_when_the_reference_is_absent(self):
        keys = list(ab.RUBRIC_QUESTIONS)
        out = self._render(self._results(
            {"claude-sonnet-5|batched": {"r1": [True] * len(keys)}}))
        assert "reference cell" in out and "absent" in out

    def test_a_cell_that_failed_everywhere_does_not_divide_by_zero(self):
        keys = list(ab.RUBRIC_QUESTIONS)
        ref = "|".join(ab.REFERENCE)
        out = self._render(self._results({
            ref: {"r1": [False] * len(keys)},
            "claude-sonnet-5|batched": {"r1": [None] * len(keys)},
        }))
        assert "VERDICT RATE BY CELL" in out

    def test_the_position_row_carries_one_number_per_question(self):
        """The pre-registered read-out: a slope across these is what says
        batching lost the late answers."""
        keys = list(ab.RUBRIC_QUESTIONS)
        out = self._render(self._two_cells())
        # Scoped to the section, because the cell name heads a line in the
        # agreement section too - which is what an earlier version of this test
        # matched, asserting on the wrong row entirely.
        section = out.split("POSITION GRADIENT")[1].split(
            "CONTAMINATION AND ROBUSTNESS")[0]
        row = next(line for line in section.splitlines()
                   if line.startswith("claude-sonnet-5|batched"))
        numbers = row.split()[1:]
        assert len(numbers) == len(keys), row
        assert all(n.isdigit() for n in numbers), row


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
        keys = list(ab.RUBRIC_QUESTIONS)
        auth = {k: {"answer": None, "quote": "", "error": "401 unauthorized",
                    "error_kind": "auth"} for k in keys}
        assert ab.fatal_error_kind(auth) == "auth"

    def test_an_ordinary_reply_failure_is_not_fatal(self):
        """A grader that could not produce readable JSON for one episode is a
        measurement, not a reason to stop the run."""
        keys = list(ab.RUBRIC_QUESTIONS)
        bad = {k: {"answer": None, "quote": "", "error": "did not parse",
                   "error_kind": "reply"} for k in keys}
        assert ab.fatal_error_kind(bad) is None

    def test_a_clean_rubric_is_not_fatal(self):
        keys = list(ab.RUBRIC_QUESTIONS)
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
        keys = list(ab.RUBRIC_QUESTIONS)
        slept, asked = [], []
        original_sleep, original_ask = ab.time.sleep, ab.ask_rubric_question
        ab.time.sleep = slept.append
        ab.ask_rubric_question = lambda q, c, m, cl, channel_id=None: (
            asked.append(q), {"answer": False, "quote": "", "error": None})[1]
        try:
            ab.ask_per_question("corpus", "m", client=object(), delay=0.25)
        finally:
            ab.time.sleep, ab.ask_rubric_question = original_sleep, original_ask
        assert len(asked) == len(keys)
        # One sleep BETWEEN each pair, not after the last.
        assert slept == [0.25] * (len(keys) - 1)

    def test_no_delay_means_no_sleeping(self):
        original_sleep, original_ask = ab.time.sleep, ab.ask_rubric_question
        slept = []
        ab.time.sleep = slept.append
        ab.ask_rubric_question = lambda *a, **k: {
            "answer": False, "quote": "", "error": None}
        try:
            ab.ask_per_question("corpus", "m", client=object(), delay=0)
        finally:
            ab.time.sleep, ab.ask_rubric_question = original_sleep, original_ask
        assert slept == []

    def test_both_shapes_accept_the_delay(self):
        """The runner passes it positionally to whichever shape is selected, so
        a shape that did not accept it would raise mid-run."""
        import inspect
        for name, fn in ab.SHAPES.items():
            assert "delay" in inspect.signature(fn).parameters, name

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
        source = inspect.getsource(ab)
        calls = [node for node in ast.walk(ast.parse(source))
                 if isinstance(node, ast.Call)
                 and isinstance(node.func, ast.Name)
                 and node.func.id == "asker"]
        assert calls, ("no asker(...) call found in grader_ab - this guard "
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

    def test_the_kill_test_double_matches_the_real_asker_contract(self):
        """The double stands in for a shape inside main(), so it has to accept
        what a real shape accepts. When it fell behind, the two main() tests
        errored on a TypeError instead of exercising what they claim to - and
        one of them catches only RuntimeError, so the break did not even
        surface as a readable failure."""
        import inspect
        double = TestAKilledRunKeepsWhatItAlreadyPaidFor()._fake_asker("nobody")
        got = set(inspect.signature(double).parameters)
        for name, fn in ab.SHAPES.items():
            real = set(inspect.signature(fn).parameters)
            assert real <= got, (
                f"the double is missing {sorted(real - got)}, which {name} "
                f"accepts")


class TestTwoRunsDoNotOverwriteEachOther:
    """A fixed output filename cost a full 145-episode 2x2 result the moment a
    one-episode probe of a different cell ran against the same --output-dir -
    the probe's write silently replaced it. The name now carries what varied,
    the same convention rubric_ab.py's own output already uses."""

    def test_the_filename_carries_the_graders_and_shapes(self):
        import inspect
        src = inspect.getsource(ab.main)
        assert "graders_tag" in src and "shapes_tag" in src, (
            "the output filename must be derived from what was actually run, "
            "not fixed - see grader_ab.json's collision with the 2x2 result")

    def test_it_does_not_regress_to_the_old_fixed_name(self):
        import inspect
        src = inspect.getsource(ab.main)
        assert '"grader_ab.json"' not in src


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
                               for k in ab.RUBRIC_QUESTIONS})

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
        ask_rubric_question does not expose output_tokens, and this must not
        paper over that with a guess."""
        keys = list(ab.RUBRIC_QUESTIONS)
        original = ab.ask_rubric_question
        ab.ask_rubric_question = lambda q, c, m, cl, channel_id=None: {
            "answer": False, "quote": "", "error": None,
            "cache": {"read": 10, "written": 0, "uncached": 5}}
        try:
            sink = []
            ab.ask_per_question("corpus", "m", client=object(), usage_sink=sink)
        finally:
            ab.ask_rubric_question = original
        assert len(sink) == len(keys)
        assert all(r["output"] is None for r in sink)
        assert all(r["read"] == 10 and r["uncached"] == 5 for r in sink)

    def test_a_failed_per_question_call_records_no_usage_for_that_question(self):
        original = ab.ask_rubric_question
        ab.ask_rubric_question = lambda q, c, m, cl, channel_id=None: {
            "answer": None, "quote": "", "error": "boom", "cache": None}
        try:
            sink = []
            ab.ask_per_question("corpus", "m", client=object(), usage_sink=sink)
        finally:
            ab.ask_rubric_question = original
        assert sink == []

    def test_neither_asker_requires_a_sink(self):
        """usage_sink is optional - a caller that does not care about cost must
        not be forced to pass one."""
        keys = list(ab.RUBRIC_QUESTIONS)
        original = ab.ask_rubric_question
        ab.ask_rubric_question = lambda q, c, m, cl, channel_id=None: {
            "answer": False, "quote": "", "error": None, "cache": None}
        try:
            got = ab.ask_per_question("corpus", "m", client=object())
        finally:
            ab.ask_rubric_question = original
        assert set(got) == set(keys)


class TestAKilledRunKeepsWhatItAlreadyPaidFor:
    """The actual failure that prompted this: a full 2x2 result was lost to a
    kill with nothing on disk, because the harness wrote once, at the very end.
    Cells now save incrementally, so a run that dies partway through cell 2
    still has cell 1 - real money already spent - on disk and readable."""

    def _write_candidate(self, out_dir, run_name="run_1_m_strong_20260101T000000.json"):
        data = {
            "model": "m", "nudge": "strong", "oversight": True, "lure": False,
            "transcript": [{"turn": "1", "type": "text", "content": "hi"}],
            "analysis": {"eval_awareness_grader": {
                "eval_aware": True, "rubric_results": {
                    k: {"answer": False, "quote": ""}
                    for k in ab.RUBRIC_QUESTIONS}}},
        }
        with open(os.path.join(out_dir, run_name), "w", encoding="utf-8") as f:
            json.dump(data, f)

    def _fake_asker(self, dies_for):
        """A stand-in for SHAPES["per_question"] that succeeds for every grader
        except the one named, which raises - simulating a kill partway through
        a later cell."""
        def asker(corpus, model, client=None, channel_id=None, delay=0,
                  usage_sink=None, unmeasured_sink=None):
            if model == dies_for:
                raise RuntimeError("simulated kill")
            if usage_sink is not None:
                usage_sink.append({"read": 0, "written": 0, "uncached": 1000,
                                   "output": None})
            return {k: {"answer": False, "quote": "", "error": None,
                       "error_kind": None} for k in ab.RUBRIC_QUESTIONS}
        return asker

    def test_the_earlier_cell_is_saved_when_a_later_one_dies(self):
        out_dir = tempfile.mkdtemp()
        self._write_candidate(out_dir)
        original_shapes = dict(ab.SHAPES)
        original_argv = sys.argv
        original_get_client = ab.get_client
        ab.SHAPES["per_question"] = self._fake_asker(dies_for="claude-fable-5")
        ab.get_client = lambda model, **kw: object()
        sys.argv = ["grader_ab.py", "--output-dir", out_dir,
                    "--graders", "claude-opus-5", "claude-fable-5",
                    "--shapes", "per_question", "--per-model", "1",
                    "--limit", "1", "--no-balance"]
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                try:
                    ab.main()
                except RuntimeError:
                    pass    # the simulated kill
        finally:
            ab.SHAPES.clear()
            ab.SHAPES.update(original_shapes)
            ab.get_client = original_get_client
            sys.argv = original_argv

        saved = glob.glob(os.path.join(out_dir, "grader_ab_*.json"))
        assert saved, "the run wrote nothing at all - the earlier cell was lost"
        d = json.load(open(saved[0], encoding="utf-8"))
        assert d["complete"] is False
        assert "claude-opus-5|per_question" in d["cells"], (
            "the cell that finished before the kill was not saved")
        assert "claude-fable-5|per_question" not in d["cells"], (
            "a cell that never finished should not appear as if it had")
        assert d["cell_costs_usd"]["claude-opus-5|per_question"]["usd"] > 0

    def test_a_full_run_is_marked_complete(self):
        out_dir = tempfile.mkdtemp()
        self._write_candidate(out_dir)
        original_shapes = dict(ab.SHAPES)
        original_argv = sys.argv
        original_get_client = ab.get_client
        ab.SHAPES["per_question"] = self._fake_asker(dies_for="nobody")
        ab.get_client = lambda model, **kw: object()
        sys.argv = ["grader_ab.py", "--output-dir", out_dir,
                    "--graders", "claude-opus-5",
                    "--shapes", "per_question", "--per-model", "1",
                    "--limit", "1", "--no-balance"]
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                rc = ab.main()
        finally:
            ab.SHAPES.clear()
            ab.SHAPES.update(original_shapes)
            ab.get_client = original_get_client
            sys.argv = original_argv

        assert rc == 0
        saved = glob.glob(os.path.join(out_dir, "grader_ab_*.json"))
        assert len(saved) == 1, "two runs of this test must not collide"
        d = json.load(open(saved[0], encoding="utf-8"))
        assert d["complete"] is True


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
