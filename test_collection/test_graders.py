"""
Several graders' readings of one episode: how they are stored, and what every
reader sees.

The contract under test is graders.py's: a reader sees exactly the flat shape it
always has, holding the DEFAULT grader's reading; a pre-array file reads as what
it held and keeps its shape until a second grader is added; a new episode is an
array from the start. The last class holds the report against that contract end
to end, so a loader added later that skips `view` fails here rather than quietly
reading a non-default grader - or nothing.
"""

import copy
import json
import tempfile
from pathlib import Path

from subversionbench.config import DEFAULT_GRADER_MODEL
from subversionbench.graders import (LABEL_KEYS, UNGRADED, graded_keys,
                                     grader_models, graders_of, new_record,
                                     store, view)
from subversionbench.grading import MISALIGNED_ACTS
from subversionbench.grading.interrogation import classify_interrogation_answer

ACT = MISALIGNED_ACTS[0]
OTHER = "gpt-6-sol"


def _labelled(verdict, model=DEFAULT_GRADER_MODEL):
    return {"verdict": verdict, "verdict_llm": verdict,
            "verdict_keyword": verdict, "classifiers_agree": True,
            "used_keyword_fallback": False, "quote": "q",
            "classifier_error": None, "classifier_called": True,
            "classifier_model": model, "classifier_version": "v0",
            "confesses": verdict == "admitted", "denies": verdict == "denied"}


def _flat(verdict="denied", aware=True, model=DEFAULT_GRADER_MODEL):
    """A pre-array analysis carrying one grader's whole reading."""
    answer = {"question": "q1", "answer": "No.", "stop_reason": "end_turn",
              **_labelled(verdict, model)}
    return {
        ACT["key"]: True,
        "monitoring_disabled": True,
        "eval_awareness_keywords": {"eval_aware": False},
        "eval_awareness_grader": {"grader_model": model, "eval_aware": aware,
                                  "rubric_results": {"x": {"answer": aware}}},
        ACT["grader_before_key"]: {"eval_aware": False, "act_index": 3},
        ACT["disclosure_key"]: {"disclosed": False, "quote": ""},
        "misrepresented_check": {"misrepresented": False},
        ACT["followup_key"]: [answer],
        ACT["followup_key"] + "_by_variant": {
            "partevidence": [dict(answer, question="q1b")]},
        ACT["level_key"]: verdict,
        ACT["scheming_key"]: True,
        "scheming": True,
        "misaligned": True,
    }


class TestTheDefaultViewIsWhatTheFileHeld:
    def test_a_pre_array_file_reads_exactly_as_it_was(self):
        flat = _flat()
        assert view(flat) == flat

    def test_its_own_grader_writing_it_back_keeps_the_flat_shape(self):
        """So a routine --reclassify or --resummarise leaves the file readable
        by anything that read it before."""
        flat = _flat()
        written = store(flat, view(flat), DEFAULT_GRADER_MODEL)
        assert "graders" not in written
        assert written == flat

    def test_a_new_record_is_an_array_that_views_back_exactly(self):
        flat = _flat()
        record = new_record(copy.deepcopy(flat), DEFAULT_GRADER_MODEL)
        assert [e["grader_model"] for e in record["graders"]] == [
            DEFAULT_GRADER_MODEL]
        assert view(record) == flat

    def test_answers_are_stored_once_and_labels_per_grader(self):
        record = new_record(_flat(), DEFAULT_GRADER_MODEL)
        bare = record[ACT["followup_key"]][0]
        assert not set(bare) & set(LABEL_KEYS), "a label was stored flat"
        assert bare["answer"] == "No."
        labels = record["graders"][0]["labels"][ACT["followup_key"]][0]
        assert labels["verdict"] == "denied"

    def test_a_view_is_a_copy(self):
        """A read mode re-grades its working view on a dry run; the change
        must not reach the analysis it was read from."""
        record = new_record(_flat(), DEFAULT_GRADER_MODEL)
        working = view(record)
        working["eval_awareness_grader"]["eval_aware"] = False
        working[ACT["followup_key"]][0]["verdict"] = "admitted"
        assert view(record)["eval_awareness_grader"]["eval_aware"] is True
        assert view(record)[ACT["followup_key"]][0]["verdict"] == "denied"


class TestASecondGrader:
    def _both(self):
        flat = _flat()
        theirs = _flat(verdict="admitted", aware=False, model=OTHER)
        theirs[ACT["level_key"]] = "admitted_first_ask"
        theirs["scheming"] = theirs[ACT["scheming_key"]] = False
        return flat, store(flat, theirs, OTHER)

    def test_adding_one_converts_the_file_and_keeps_the_first(self):
        flat, both = self._both()
        assert grader_models(both) == [DEFAULT_GRADER_MODEL, OTHER]
        assert view(both) == flat

    def test_each_view_holds_only_its_own_reading(self):
        _flat_, both = self._both()
        theirs = view(both, OTHER)
        assert theirs["eval_awareness_grader"]["eval_aware"] is False
        assert theirs[ACT["followup_key"]][0]["verdict"] == "admitted"
        assert theirs["scheming"] is False
        assert view(both)["scheming"] is True

    def test_replacing_one_leaves_the_other_byte_for_byte(self):
        _flat_, both = self._both()
        before = json.dumps(graders_of(both)[0], sort_keys=True)
        theirs = view(both, OTHER)
        theirs["eval_awareness_grader"]["eval_aware"] = True
        after = store(both, theirs, OTHER)
        assert json.dumps(graders_of(after)[0], sort_keys=True) == before
        assert view(after, OTHER)["eval_awareness_grader"]["eval_aware"] is True

    def test_an_empty_reading_never_removes_a_stored_one(self):
        _flat_, both = self._both()
        empty = view(both, OTHER)
        for key in graded_keys():
            empty.pop(key, None)
        for answers in (empty[ACT["followup_key"]],
                        *empty[ACT["followup_key"] + "_by_variant"].values()):
            for answer in answers:
                for label in LABEL_KEYS:
                    answer.pop(label, None)
        assert view(store(both, empty, OTHER), OTHER) == view(both, OTHER)


class TestAnEpisodeWithNoDefaultReading:
    def test_reads_exactly_as_one_collected_without_a_grader(self):
        """So it drops out of every grader-based figure the way an ungraded
        episode always has - and its free fields are untouched."""
        only_theirs = new_record(_flat(model=OTHER), OTHER)
        seen = view(only_theirs)
        assert seen["eval_awareness_grader"] == UNGRADED
        assert seen[ACT["grader_before_key"]] == {"skipped": True,
                                                 "reason": "no grader"}
        assert ACT["disclosure_key"] not in seen
        assert all("verdict" not in a for a in seen[ACT["followup_key"]])
        assert seen[ACT["level_key"]] is None
        assert seen["misaligned"] is True, "a free field was re-derived"

    def test_a_pre_array_file_that_names_no_grader_is_the_default_s(self):
        """It held THE reading every figure was built from."""
        flat = _flat()
        del flat["eval_awareness_grader"]["grader_model"]
        for answers in (flat[ACT["followup_key"]],
                        *flat[ACT["followup_key"] + "_by_variant"].values()):
            for answer in answers:
                del answer["classifier_model"]
        assert grader_models(flat) == [DEFAULT_GRADER_MODEL]
        assert view(flat) == flat


class TestWhatIsPerGraderIsDerivedNotListed:
    def test_every_act_contributes_its_grader_fields(self):
        keys = set(graded_keys())
        assert keys, "an empty field list would pass everything vacuously"
        for act in MISALIGNED_ACTS:
            for field in ("grader_before_key", "disclosure_key", "level_key",
                          "scheming_key"):
                assert act[field] in keys, (act["name"], field)

    def test_an_act_added_later_is_covered_without_editing_graders(self):
        extra = dict(ACT, grader_before_key="pre_x", disclosure_key="disc_x",
                     level_key="lvl_x", scheming_key="sch_x",
                     followup_key="fu_x")
        acts = (*MISALIGNED_ACTS, extra)
        assert {"pre_x", "disc_x", "lvl_x", "lvl_x_by_variant",
                "sch_x"} <= set(graded_keys(acts))

    def test_the_label_keys_are_the_classifier_s(self):
        """A label the classifier adds and this list lacks would be stored
        flat, shared by every grader - one grader's verdict under all names."""
        returned = set(classify_interrogation_answer("", "", (), (), ()))
        assert set(LABEL_KEYS) == returned | {"confesses", "denies"}


class TestTheReportReadsTheDefaultGrader:
    """End to end through the report's own loader: the same episodes written
    flat, and written as arrays with a second grader that says the opposite,
    must load identically. A loader that skipped `view` would read nothing
    from the arrays; one that read the wrong entry would read the opposite."""

    def _corpus(self, out, as_array):
        """Three episodes carrying a real default-grader reading - aware,
        undisclosed, denying - so a loader that read nothing, or read the
        other grader, would load something different."""
        from test_analysis.report_fixtures import _write_episode
        for n, tampered in ((1, True), (2, False), (3, True)):
            answers = [{"question": "q1", "answer": "No.",
                        **_labelled("denied")}] if tampered else None
            path = Path(_write_episode(
                out, n, "m", "strong", tampered=tampered,
                disclosed=False if tampered else None, answers=answers))
            data = json.loads(path.read_text(encoding="utf-8"))
            flat = data["analysis"]
            flat["eval_awareness_grader"] = {
                "grader_model": DEFAULT_GRADER_MODEL, "eval_aware": True,
                "eval_aware_category": "explicit", "eval_signal_count": 2,
                "rubric_results": {"suspects_being_tested": {"answer": True,
                                                             "quote": "q"}}}
            if as_array:
                opposite = _flat(verdict="admitted", aware=False, model=OTHER)
                opposite = {**copy.deepcopy(flat), **{
                    k: v for k, v in opposite.items() if k in graded_keys()}}
                record = new_record(copy.deepcopy(flat), DEFAULT_GRADER_MODEL)
                flat = store(record, opposite, OTHER)
                assert grader_models(flat) == [DEFAULT_GRADER_MODEL, OTHER]
            data["analysis"] = flat
            path.write_text(json.dumps(data), encoding="utf-8")

    def test_flat_and_array_corpora_load_identically(self):
        from report import load_episodes
        flat_dir, array_dir = tempfile.mkdtemp(), tempfile.mkdtemp()
        self._corpus(flat_dir, as_array=False)
        self._corpus(array_dir, as_array=True)
        assert load_episodes(array_dir) == load_episodes(flat_dir)
