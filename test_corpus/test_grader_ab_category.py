"""
The awareness category instrument in grader_ab, and choosing episodes by name.

Three properties, each a way the screen and the grid in
docs/grader-selection.md would mislead if it broke:

  An unreadable category reply is unanswered, never "false". A refusal falls
  where the answer is yes, so scoring it as a no biases the rate - the
  unanswered count is the number the refusal screen decides on.

  The category question reads the agent's WHOLE text, the rubric its capped
  view. Asking the new instrument over the old excerpt would compare the
  rubric with itself on less evidence.

  A runs file grades exactly the episodes it names, or nothing. The blind
  sample and the test sets are fixed lists; a list that silently loses
  entries makes the labels and the verdicts disagree about which episodes
  were graded.
"""

import contextlib
import io
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace

import grader_ab as ab
import subversionbench.llm_client as ev_llm
from grader_ab import readout, sampling, shapes
from subversionbench.config import (AWARENESS_CATEGORY_QUESTION,
                                    AWARENESS_CATEGORY_SYSTEM_PROMPT,
                                    RUBRIC_QUESTIONS)
from subversionbench.grading.grader_io import _GRADER_TRANSCRIPT_CHAR_BUDGET

from test_corpus.grader_ab_fixtures import _graded_episode, _run_main


def _reply(text):
    return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)],
                           usage=None, stop_reason="end_turn")


class _Client:
    def __init__(self, text):
        self.calls, self._text = [], text
        self.messages = self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return _reply(self._text)


def _category_reply(category, quote="", competing=""):
    return json.dumps({"category": category, "quote": quote,
                       "competing_reading": competing})


class TestAnUnreadableReplyIsUnanswered:
    def test_each_category_parses_and_only_two_are_aware(self):
        for category in shapes.CATEGORIES:
            got = shapes.ask_category("text", "m", _Client(
                _category_reply(category)))[shapes.CATEGORY_KEY]
            assert got["category"] == category and got["error"] is None
            assert got["answer"] is (category in shapes.AWARE_CATEGORIES)
        assert set(shapes.AWARE_CATEGORIES) == {"true", "ambiguous_true"}

    def test_a_reply_with_no_recognised_category_is_unanswered(self):
        for text in ('{"quote": "x"}', '{"category": "yes"}',
                     '{"category": false}', "I think false.",
                     '{"category": "false", "quote": 3}'):
            got = shapes.ask_category("text", "m", _Client(text))[
                shapes.CATEGORY_KEY]
            assert got["answer"] is None, text
            assert got["category"] is None, text
            assert got["error_kind"] == "reply", text

    def test_a_transport_failure_is_unanswered_too(self):
        class Broken:
            messages = None

            def __init__(self):
                self.messages = self

            def create(self, **kwargs):
                raise RuntimeError("connection reset")
        got = shapes.ask_category("text", "m", Broken())[shapes.CATEGORY_KEY]
        assert got["answer"] is None and got["error_kind"] == "other"

    def test_the_question_is_asked_outside_the_fence_with_its_own_prompt(self):
        client = _Client(_category_reply("false"))
        shapes.ask_category("the agent text", "m", client)
        sent = client.calls[0]
        assert sent["system"][0]["text"] == AWARENESS_CATEGORY_SYSTEM_PROMPT
        fenced, asked = sent["messages"][0]["content"]
        assert "the agent text" in fenced["text"]
        assert AWARENESS_CATEGORY_QUESTION not in fenced["text"]
        assert AWARENESS_CATEGORY_QUESTION in asked["text"]


@contextlib.contextmanager
def _recording_shapes():
    """Every shape replaced by a stub that records the corpus it was given
    and answers in that shape's own form; the client factory stubbed too, on
    a command whose purpose is to spend money."""
    seen = {}
    saved, factory = dict(shapes.SHAPES), ev_llm.get_client

    def stub_for(shape):
        def asker(corpus, model, client=None, channel_id=None, delay=0,
                  usage_sink=None, unmeasured_sink=None):
            seen.setdefault(shape, []).append(corpus)
            if shape == "category":
                return {shapes.CATEGORY_KEY: {
                    "answer": True, "category": "ambiguous_true",
                    "quote": "", "competing_reading": "", "error": None,
                    "error_kind": None}}
            return {k: {"answer": False, "quote": "", "error": None,
                        "error_kind": None} for k in RUBRIC_QUESTIONS}
        return asker

    for shape in shapes.SHAPES:
        shapes.SHAPES[shape] = stub_for(shape)
    ev_llm.get_client = lambda model, **kw: object()
    try:
        yield seen
    finally:
        shapes.SHAPES.clear()
        shapes.SHAPES.update(saved)
        ev_llm.get_client = factory


def _long_episode(out, n):
    path = _graded_episode(out, n)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["transcript"] = [{"turn": 1, "type": "text",
                           "content": "w" * (_GRADER_TRANSCRIPT_CHAR_BUDGET * 2)}]
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


class TestTheCategoryQuestionReadsTheWholeText:
    def test_category_gets_the_whole_text_and_the_rubric_its_capped_view(self):
        with tempfile.TemporaryDirectory() as out:
            _long_episode(out, 1)
            with _recording_shapes() as seen:
                code, text = _run_main(["--output-dir", out, "--per-model", "1",
                                        "--graders", "m", "--shapes",
                                        "per_question", "category"])
        assert code == 0, text
        assert len(seen["category"][0]) > _GRADER_TRANSCRIPT_CHAR_BUDGET * 2
        assert len(seen["per_question"][0]) < _GRADER_TRANSCRIPT_CHAR_BUDGET * 2
        assert "CATEGORY INSTRUMENT" in text

    def test_the_default_shapes_do_not_include_the_new_instrument(self):
        """A run that names no shape should not start paying for a call per
        episode it did not ask for."""
        with tempfile.TemporaryDirectory() as out:
            _graded_episode(out, 1)
            with _recording_shapes() as seen:
                code, text = _run_main(["--output-dir", out, "--per-model", "1",
                                        "--graders", "m"])
        assert code == 0, text
        assert "category" not in seen


class TestARunsFileGradesExactlyWhatItNames:
    def test_the_named_episodes_are_graded_in_the_order_named(self):
        with tempfile.TemporaryDirectory() as out:
            names = [_graded_episode(out, n).name for n in (1, 2, 3)]
            listed = Path(out, "runs.jsonl")
            listed.write_text(
                f'{{"file": "{names[2]}", "sets": "x"}}\n\n{names[0]}\n',
                encoding="utf-8")
            with _recording_shapes():
                code, text = _run_main(["--output-dir", out, "--graders", "m",
                                        "--shapes", "category",
                                        "--runs-file", str(listed)])
            saved = json.loads(next(Path(out).glob("grader_ab_*.json"))
                               .read_text(encoding="utf-8"))
        assert code == 0, text
        assert [s["run"] for s in saved["sample"]] == [names[2], names[0]]

    def test_a_name_the_directory_cannot_grade_refuses_before_any_call(self):
        with tempfile.TemporaryDirectory() as out:
            _graded_episode(out, 1)
            failed = _graded_episode(out, 2, failed=True).name
            listed = Path(out, "runs.txt")
            listed.write_text(f"{failed}\n", encoding="utf-8")
            with _recording_shapes() as seen:
                code, text = _run_main(["--output-dir", out, "--graders", "m",
                                        "--shapes", "category",
                                        "--runs-file", str(listed)])
        assert code == 1
        assert "Refusing rather than grading the rest" in text
        assert not seen, "a grader was called for a list that did not match"

    def test_a_line_naming_no_run_file_is_refused(self):
        with tempfile.TemporaryDirectory() as out:
            listed = Path(out, "runs.txt")
            for bad in ("summary_x.json", '{"model": "m"}', "../run_1.json"):
                listed.write_text(bad + "\n", encoding="utf-8")
                try:
                    sampling.read_runs_file(str(listed))
                except ValueError:
                    continue
                raise AssertionError(f"{bad!r} was accepted")


class TestTheReadOutKeepsTheInstrumentsApart:
    def test_a_category_cell_is_reported_without_entering_the_rubric_tables(
            self):
        entry = {"answer": None, "category": None, "quote": "",
                 "competing_reading": "", "error": "x", "error_kind": "reply"}
        results = {"m|category": {"run_1.json": {shapes.CATEGORY_KEY: entry}}}
        stored = {"run_1.json": {k: {"answer": False, "quote": ""}
                                 for k in RUBRIC_QUESTIONS}}
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            readout.report(results, [], list(RUBRIC_QUESTIONS), stored)
        text = buf.getvalue()
        assert "CATEGORY INSTRUMENT" in text
        assert "PER-QUESTION RATES" not in text
        assert "  1 100.0%" in text, "the unanswered episode was not counted"

    def test_the_category_verdict_is_the_categorys_not_the_classifiers(self):
        rubric = {shapes.CATEGORY_KEY: {"answer": True}}
        assert readout.cell_verdict(rubric) is True
        assert readout.cell_verdict(
            {shapes.CATEGORY_KEY: {"answer": None}}) is None


def test_the_package_still_exposes_the_category_shape():
    assert "category" in ab.SHAPES
