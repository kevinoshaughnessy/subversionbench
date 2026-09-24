"""
What jev was actually asked, and whether the saved run says so truthfully.

THE DEFECT CLASS THIS SUITE IS FOR. --wording was parsed, written into the
saved file's header and dropped before the call, so a full-corpus run came
back labelled "wording": "proposed" having asked the shipped question on
all 5,987 episodes. Every guard passed: wording_for was tested in
isolation, and the header was tested by reading the header back.

So nothing here asserts on a flag by reading it out of the file alone.
Each test either inspects what the CLIENT was handed, or ties the two
together - the recorded text must equal the text that was sent.
"""

import json
import os
import tempfile
import unittest
from unittest import mock

from grader_ab import jev_validate as jv

from .jev_fixtures import _episode, _jev_scoring, _rubric


class TestJevCanBeAskedACandidateWording(unittest.TestCase):
    """jev's instructions default to config's RUBRIC_QUESTIONS - the same
    words the LLM grader answers - which makes jev the cheap place to screen
    a rewrite. The same experiment on claude-opus-5 costs hundreds of times
    more."""

    def test_shipped_asks_exactly_what_the_grader_is_asked(self):
        from subversionbench.config import RUBRIC_QUESTIONS
        text, changed = jv.wording_for("shipped", ["mentioned_test"])
        assert text["mentioned_test"] == RUBRIC_QUESTIONS["mentioned_test"]
        assert changed == []

    def test_proposed_asks_the_candidate_where_one_exists(self):
        from subversionbench.config import RUBRIC_QUESTIONS
        text, changed = jv.wording_for("proposed", ["mentioned_test"])
        assert text["mentioned_test"] != RUBRIC_QUESTIONS["mentioned_test"]
        assert changed == ["mentioned_test"]

    def test_a_key_with_no_candidate_keeps_the_shipped_wording(self):
        """And is reported as unchanged, so a run does not silently ask a
        different question for one key and the shipped one for another."""
        from subversionbench.config import RUBRIC_QUESTIONS
        keys = ["mentioned_test", "referenced_system_prompt"]
        text, changed = jv.wording_for("proposed", keys)
        assert text["referenced_system_prompt"] == \
            RUBRIC_QUESTIONS["referenced_system_prompt"]
        assert "referenced_system_prompt" not in changed

    def test_the_wording_actually_reaches_the_call(self):
        """A flag that changed nothing on the wire would report the two
        wordings as identical and read as 'the question does not matter'."""
        seen = {}

        def ask(keys, corpus, threshold=0.5, instructions=None, **kw):
            seen.update(instructions or {})
            return {k: {"answer": False, "noul": 0.1, "quote": "",
                        "error": None} for k in keys}

        with tempfile.TemporaryDirectory() as out:
            _episode(out, 1, rubric=_rubric())
            candidates = jv.sampling.load_candidates(out)
            text, _ = jv.wording_for("proposed", ["mentioned_test"])
            jv.part_a(candidates, ["mentioned_test"], 0.5, ask=ask,
                      instructions=text)
        assert seen["mentioned_test"] == text["mentioned_test"]

    def _saved_run(self, out, wording):
        """main() with the client stubbed, returning both what was SAVED and
        what the client was HANDED - so the two can be compared.

        PINNED TO --primitive noul, which is what --wording actually affects.
        A score question carries its own instructions (JEV_SCORE_INSTRUCTIONS)
        and every key that has score levels has them, so the rubric wording
        never reaches the wire on a score run and this comparison would be
        between two different questions.

        That is also why the stub cannot police the score path: it captures
        the argument, and the substitution happens inside the client
        afterwards. TestTheRecordedQuestionIsTheOneOnTheWire in
        test_jev_client_score.py asserts against the built payload instead,
        which is the only place the two are comparable.
        """
        sent = {}

        def ask(keys, corpus, threshold=0.5, instructions=None, **kw):
            sent.update(instructions or {})
            return {k: {"answer": True, "noul": 0.9, "quote": "",
                        "error": None} for k in keys}

        _episode(out, 0, rubric=_rubric(mentioned_test=True))
        with mock.patch("sys.argv",
                        ["jev_validate", "--output-dir", out,
                         "--keys", "mentioned_test", "--no-part-b",
                         "--primitive", "noul",
                         "--wording", wording]), \
                mock.patch.dict(os.environ,
                                {"OPENROUTER_API_KEY": "x"}, clear=True), \
                mock.patch.object(jv, "ask_rubric_questions_jev", ask):
            assert jv.main() == 0
        saved = [f for f in os.listdir(out) if f.startswith("jev_validate_")]
        return json.load(open(os.path.join(out, saved[0]),
                              encoding="utf-8")), sent

    def test_the_saved_run_records_which_wording_it_asked(self):
        """Two runs differing only in wording are otherwise indistinguishable
        on disk, and comparing them is the whole point."""
        with tempfile.TemporaryDirectory() as out:
            data, _ = self._saved_run(out, "proposed")
        assert data["wording"] == "proposed"

    def test_the_saved_run_records_the_question_text_that_was_SENT(self):
        """The label alone is exactly what failed.

        jev_validate_n5987_20260921T161550.json carries "wording":
        "proposed" and asked the shipped question 5,987 times, because the
        flag was parsed, written to the header, and dropped before the call.
        Every guard on the label passed - including the one above. Recording
        the text closes it: a label and a re-derivation can both be wrong the
        same way, but the text handed to the client cannot disagree with
        itself.
        """
        with tempfile.TemporaryDirectory() as out:
            data, sent = self._saved_run(out, "proposed")
        assert data["asked"]["mentioned_test"] == sent["mentioned_test"]

    def test_the_recorded_text_is_the_proposed_one_under_that_name(self):
        """Tying the record to the wire is not sufficient alone - both would
        agree on the wrong question if the NAME resolved wrongly."""
        from subversionbench.config import RUBRIC_QUESTIONS
        with tempfile.TemporaryDirectory() as out:
            data, _ = self._saved_run(out, "proposed")
        assert (data["asked"]["mentioned_test"]
                != RUBRIC_QUESTIONS["mentioned_test"])
        assert data["wording_changed_keys"] == ["mentioned_test"]

    def test_a_shipped_run_records_the_shipped_text_and_no_change(self):
        """The other direction, so the guard can answer no: a run asking the
        shipped question must say so in its text as well as its name."""
        from subversionbench.config import RUBRIC_QUESTIONS
        with tempfile.TemporaryDirectory() as out:
            data, sent = self._saved_run(out, "shipped")
        assert (data["asked"]["mentioned_test"]
                == RUBRIC_QUESTIONS["mentioned_test"] == sent["mentioned_test"])
        assert data["wording_changed_keys"] == []


class TestTheShapeIsRecorded(unittest.TestCase):
    """Two runs differing only in call shape are otherwise indistinguishable
    on disk, and the shape is now known to move verdicts."""

    def test_per_question_reaches_the_client(self):
        seen = []

        def ask(keys, corpus, threshold=0.5, instructions=None,
                batched=True, **kw):
            seen.append(batched)
            return {k: {"answer": False, "noul": 0.1, "quote": "",
                        "error": None} for k in keys}

        with tempfile.TemporaryDirectory() as out:
            _episode(out, 0, rubric=_rubric(mentioned_test=True))
            with mock.patch("sys.argv",
                            ["jev_validate", "--output-dir", out,
                             "--keys", "mentioned_test", "--no-part-b",
                             "--per-question"]), \
                    mock.patch.dict(os.environ,
                                    {"OPENROUTER_API_KEY": "x"}, clear=True), \
                    mock.patch.object(jv, "ask_rubric_questions_jev", ask):
                assert jv.main() == 0
        assert seen and all(b is False for b in seen)

    def test_the_saved_run_names_its_shape(self):
        with tempfile.TemporaryDirectory() as out:
            _episode(out, 0, rubric=_rubric(mentioned_test=True))
            with mock.patch("sys.argv",
                            ["jev_validate", "--output-dir", out,
                             "--keys", "mentioned_test", "--no-part-b",
                             "--per-question"]), \
                    mock.patch.dict(os.environ,
                                    {"OPENROUTER_API_KEY": "x"}, clear=True), \
                    mock.patch.object(jv, "ask_rubric_questions_jev",
                                      _jev_scoring(mentioned_test=0.9)):
                assert jv.main() == 0
            saved = [f for f in os.listdir(out)
                     if f.startswith("jev_validate_")]
            data = json.load(open(os.path.join(out, saved[0]),
                                  encoding="utf-8"))
        assert data["shape"] == "per_question"


class TestEveryFlagReachesTheClientNotJustTheHeader(unittest.TestCase):
    """THE DEFECT THIS EXISTS FOR. --wording was parsed, recorded in the
    saved file's header, and never passed to part_a. A full-corpus run came
    back labelled "wording": "proposed" having asked the shipped question
    for every one of its 5,987 episodes.

    Nothing caught it: wording_for was tested in isolation, and the header
    field was tested by reading the header. Both passed. A flag is only
    real if it reaches the call, so these assert on what the CLIENT was
    handed rather than on what the file says was intended."""

    def _sent(self, argv):
        seen = {}

        def ask(keys, corpus, threshold=0.5, instructions=None,
                batched=True, **kw):
            seen["instructions"] = instructions
            seen["batched"] = batched
            return {k: {"answer": False, "noul": 0.1, "quote": "",
                        "error": None} for k in keys}

        with tempfile.TemporaryDirectory() as out:
            _episode(out, 0, rubric=_rubric(mentioned_test=True))
            with mock.patch("sys.argv",
                            ["jev_validate", "--output-dir", out,
                             "--keys", "mentioned_test", "--no-part-b",
                             *argv]), \
                    mock.patch.dict(os.environ,
                                    {"OPENROUTER_API_KEY": "x"}, clear=True), \
                    mock.patch.object(jv, "ask_rubric_questions_jev", ask):
                assert jv.main() == 0
            saved = [f for f in os.listdir(out)
                     if f.startswith("jev_validate_")]
            header = json.load(open(os.path.join(out, saved[0]),
                                    encoding="utf-8"))
        return seen, header

    def test_the_proposed_wording_actually_reaches_the_client(self):
        import rubric_ab
        sent, header = self._sent(["--wording", "proposed"])
        assert header["wording"] == "proposed"
        assert sent["instructions"]["mentioned_test"] == \
            rubric_ab.PROPOSED_WORDINGS["mentioned_test"], \
            "the header said proposed and the call sent something else"

    def test_the_shipped_wording_reaches_the_client_too(self):
        from subversionbench.config import RUBRIC_QUESTIONS
        sent, header = self._sent([])
        assert header["wording"] == "shipped"
        assert sent["instructions"]["mentioned_test"] == \
            RUBRIC_QUESTIONS["mentioned_test"]

    def test_the_call_shape_actually_reaches_the_client(self):
        sent, header = self._sent(["--per-question"])
        assert header["shape"] == "per_question"
        assert sent["batched"] is False

    def test_the_default_shape_reaches_the_client(self):
        sent, header = self._sent([])
        assert header["shape"] == "batched"
        assert sent["batched"] is True


class TestThePrimitiveReachesTheClientAndTheFile(unittest.TestCase):
    """--primitive is the third flag on this path, and the first two each
    failed once: --wording was parsed and dropped, and the call shape was
    recorded without being sent. So this is guarded the way those are now -
    on what the CLIENT was handed, never on the header alone."""

    def _run(self, argv):
        seen = []

        def ask(keys, corpus, threshold=0.5, instructions=None,
                batched=True, primitive="score", **kw):
            seen.append(primitive)
            return {k: {"answer": False, "primitive": primitive, "raw": 1.0,
                        "noul": None, "score": 1.0, "quote": "",
                        "error": None} for k in keys}

        with tempfile.TemporaryDirectory() as out:
            _episode(out, 0, rubric=_rubric(mentioned_test=True))
            with mock.patch("sys.argv",
                            ["jev_validate", "--output-dir", out,
                             "--keys", "mentioned_test", "--no-part-b",
                             *argv]), \
                    mock.patch.dict(os.environ,
                                    {"OPENROUTER_API_KEY": "x"}, clear=True), \
                    mock.patch.object(jv, "ask_rubric_questions_jev", ask):
                assert jv.main() == 0
            saved = [f for f in os.listdir(out)
                     if f.startswith("jev_validate_")]
            data = json.load(open(os.path.join(out, saved[0]),
                                  encoding="utf-8"))
        return data, seen

    def test_score_is_what_a_default_run_asks_for(self):
        data, seen = self._run([])
        assert seen == ["score"]
        assert data["primitive"] == "score"

    def test_asking_for_noul_reaches_the_client(self):
        data, seen = self._run(["--primitive", "noul"])
        assert seen == ["noul"]
        assert data["primitive"] == "noul"

    def test_the_record_carries_the_scale_each_number_is_on(self):
        """A column of numbers with no scale beside it is the thing that
        cost a day: 0.9 is near-certain on one scale and just below the
        first level on the other."""
        data, _ = self._run([])
        cell = data["part_a_records"][0]["per_key"]["mentioned_test"]
        assert cell["primitive"] == "score"
        assert cell["raw"] == 1.0


class TestTheSweepRunsOnTheScaleItWasScoredOn(unittest.TestCase):
    """The noul ladder is 0.05 to 0.95. JEV_SCORE_LEVELS runs 0 to 4, so
    every one of those cuts sits below level 1: a score run swept on it
    would print nineteen plausible rows that all say 'level 0 against
    everything else' and name the flattest of them the best cut."""

    def _records(self, primitive, raw):
        return [{"run": "run_1_m_strong_S.json", "model": "m",
                 "per_key": {"mentioned_test": {
                     "stored": True, "jev": True, "primitive": primitive,
                     "raw": raw, "jev_error": None}},
                 "other_stored": {}, "eval_aware": {"stored": True},
                 "goal_conflict_aware": {"stored": False}}]

    def test_a_score_run_is_swept_on_the_level_ladder(self):
        rows = jv.sweep_thresholds(self._records("score", 2.0),
                                   ["mentioned_test"])
        cuts = [r["threshold"] for r in rows]
        assert max(cuts) > 1.0, cuts
        assert cuts == list(jv.SWEEP_SCORE_THRESHOLDS)

    def test_a_noul_run_is_swept_on_the_probability_ladder(self):
        rows = jv.sweep_thresholds(self._records("noul", 0.4),
                                   ["mentioned_test"])
        assert [r["threshold"] for r in rows] == list(jv.SWEEP_THRESHOLDS)

    def test_a_record_saved_before_the_change_sweeps_as_a_noul_run(self):
        """Every full-corpus run on disk predates the score primitive and
        carries no `primitive` at all. Defaulting them to the score ladder
        would re-sweep real results on the wrong axis."""
        old = [{"run": "r.json", "model": "m",
                "per_key": {"mentioned_test": {"stored": True, "jev": True,
                                               "noul": 0.4, "jev_error": None}},
                "other_stored": {}, "eval_aware": {"stored": True},
                "goal_conflict_aware": {"stored": False}}]
        rows = jv.sweep_thresholds(old, ["mentioned_test"])
        assert [r["threshold"] for r in rows] == list(jv.SWEEP_THRESHOLDS)

    def test_the_ladders_actually_differ(self):
        """A guard comparing two identical tuples passes with the split
        removed."""
        assert set(jv.SWEEP_SCORE_THRESHOLDS) != set(jv.SWEEP_THRESHOLDS)


class TestTheDryRunDoesNotOverstateGraderSpend(unittest.TestCase):
    """The operator's stated constraint is opus-5 spend, not jev spend, so
    the Part B line is the only figure on this plan anyone is watching. It
    printed the full sample cost under --no-part-b, which is the wrong
    direction to be wrong in for that one number."""

    def _plan(self, argv):
        import contextlib
        import io
        with tempfile.TemporaryDirectory() as out:
            _episode(out, 0, rubric=_rubric(mentioned_test=True))
            buf = io.StringIO()
            with mock.patch("sys.argv",
                            ["jev_validate", "--output-dir", out,
                             "--keys", "mentioned_test", "--dry-run", *argv]), \
                    mock.patch.dict(os.environ,
                                    {"OPENROUTER_API_KEY": "x"}, clear=True), \
                    contextlib.redirect_stdout(buf):
                assert jv.main() == 0
            return buf.getvalue()

    def test_no_part_b_plans_zero_grader_calls(self):
        out = self._plan(["--no-part-b"])
        assert "Part B      0 claude-opus-5" in out, out

    def test_it_still_says_what_part_b_would_have_cost(self):
        """Zero with no context reads as 'Part B is free', which would make
        the flag look like it costs nothing to drop."""
        assert "would be needed without it" in self._plan(["--no-part-b"])

    def test_a_run_that_will_spend_says_so(self):
        out = self._plan([])
        assert "Part B      0 claude-opus-5" not in out
        assert "claude-opus-5 call(s)" in out

    def test_the_plan_names_the_primitive_it_will_ask(self):
        assert "asked as a score" in self._plan(["--no-part-b"])
        assert "asked as a noul" in self._plan(
            ["--no-part-b", "--primitive", "noul"])


class TestAScoreRunsHeaderNamesTheScoreQuestion(unittest.TestCase):
    """The gap the first attempt at this left open.

    The --wording guards are pinned to --primitive noul, where the resolver
    returns its argument unchanged - so reverting the header to the wording
    passed in is a no-op there and nothing goes red. On a score run it is not
    a no-op: the client sends JEV_SCORE_INSTRUCTIONS and the header would
    name the rubric question, which is the defect this was all about.
    """

    def _header(self, argv):
        def ask(keys, corpus, threshold=0.5, instructions=None, **kw):
            return {k: {"answer": True, "primitive": kw.get("primitive"),
                        "raw": 2.0, "noul": None, "score": 2.0,
                        "quote": "", "error": None} for k in keys}

        with tempfile.TemporaryDirectory() as out:
            _episode(out, 0, rubric=_rubric(mentioned_test=True))
            with mock.patch("sys.argv",
                            ["jev_validate", "--output-dir", out,
                             "--keys", "mentioned_test", "--no-part-b",
                             *argv]), \
                    mock.patch.dict(os.environ,
                                    {"OPENROUTER_API_KEY": "x"}, clear=True), \
                    mock.patch.object(jv, "ask_rubric_questions_jev", ask):
                assert jv.main() == 0
            saved = [f for f in os.listdir(out)
                     if f.startswith("jev_validate_")]
            return json.load(open(os.path.join(out, saved[0]),
                                  encoding="utf-8"))

    def test_it_records_the_score_instructions(self):
        from grader_ab.jev_client import JEV_SCORE_INSTRUCTIONS
        data = self._header(["--primitive", "score"])
        assert (data["asked"]["mentioned_test"]
                == JEV_SCORE_INSTRUCTIONS["mentioned_test"])

    def test_it_records_them_even_when_a_wording_was_requested(self):
        """--wording is inert on a score run, because every key with score
        levels has its own instructions. A header echoing the requested
        rubric wording would name a question that never went on the wire."""
        from subversionbench.config import RUBRIC_QUESTIONS
        from grader_ab.jev_client import JEV_SCORE_INSTRUCTIONS
        data = self._header(["--primitive", "score",
                             "--wording", "proposed"])
        assert (data["asked"]["mentioned_test"]
                == JEV_SCORE_INSTRUCTIONS["mentioned_test"])
        assert (data["asked"]["mentioned_test"]
                != RUBRIC_QUESTIONS["mentioned_test"])

    def test_a_noul_run_still_records_the_rubric_wording(self):
        """So the guard can answer no rather than always expecting the score
        text."""
        from subversionbench.config import RUBRIC_QUESTIONS
        data = self._header(["--primitive", "noul"])
        assert (data["asked"]["mentioned_test"]
                == RUBRIC_QUESTIONS["mentioned_test"])


class TestTheRunRecordsTheCutThatTookEffect(unittest.TestCase):
    """--threshold unset requests a different cut per key and per primitive,
    so a file recording only the request cannot say what its own booleans
    mean. jev_validate_n5987_20260921T224225.json records threshold 0.5 and
    is the run that defect produced."""

    def _header(self, argv):
        def ask(keys, corpus, threshold=None, instructions=None, **kw):
            return {k: {"answer": True, "primitive": kw.get("primitive"),
                        "raw": 2.0, "noul": None, "score": 2.0,
                        "quote": "", "error": None} for k in keys}

        with tempfile.TemporaryDirectory() as out:
            _episode(out, 0, rubric=_rubric(mentioned_test=True))
            with mock.patch("sys.argv",
                            ["jev_validate", "--output-dir", out,
                             "--keys", "mentioned_test", "--no-part-b",
                             *argv]), \
                    mock.patch.dict(os.environ,
                                    {"OPENROUTER_API_KEY": "x"}, clear=True), \
                    mock.patch.object(jv, "ask_rubric_questions_jev", ask):
                assert jv.main() == 0
            saved = [f for f in os.listdir(out)
                     if f.startswith("jev_validate_")]
            return json.load(open(os.path.join(out, saved[0]),
                                  encoding="utf-8"))

    def test_an_unset_threshold_records_the_level_cut_not_a_probability(self):
        from grader_ab.jev_client import JEV_SCORE_THRESHOLDS
        data = self._header(["--primitive", "score"])
        assert data["threshold"] is None
        assert (data["thresholds_applied"]["mentioned_test"]
                == JEV_SCORE_THRESHOLDS["mentioned_test"] >= 1.0)

    def test_a_noul_run_records_its_own_measured_cut(self):
        from grader_ab.jev_client import JEV_THRESHOLDS
        data = self._header(["--primitive", "noul"])
        assert (data["thresholds_applied"]["mentioned_test"]
                == JEV_THRESHOLDS["mentioned_test"])

    def test_an_explicit_threshold_is_recorded_as_applied(self):
        data = self._header(["--primitive", "score", "--threshold", "3.0"])
        assert data["threshold"] == 3.0
        assert data["thresholds_applied"]["mentioned_test"] == 3.0
