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
        what the client was HANDED - so the two can be compared."""
        sent = {}

        def ask(keys, corpus, threshold=0.5, instructions=None, **kw):
            sent.update(instructions or {})
            return {k: {"answer": True, "noul": 0.9, "quote": "",
                        "error": None} for k in keys}

        _episode(out, 0, rubric=_rubric(mentioned_test=True))
        with mock.patch("sys.argv",
                        ["jev_validate", "--output-dir", out,
                         "--keys", "mentioned_test", "--no-part-b",
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

        def ask(keys, corpus, threshold=0.5, instructions=None, batched=True):
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
