"""
--self-grade-kind: re-measuring the KIND of suspicion with the episode's own
model, and spending nothing on the episodes that cannot have one.
"""

import contextlib
import glob
import io
import json
import os
import tempfile
import types

from pathlib import Path

import subversionbench.llm_client as ev_llm
import subversionbench.run_eval as ev_run
from conftest import FakeArgs
from subversionbench.batch import BatchSelection
from subversionbench.config import RUBRIC_QUESTIONS


@contextlib.contextmanager
def _stub(answers, raises_for=()):
    """
    Canned replies keyed by rubric question, and a record of every call.

    Yields the call list so a test can assert on how many were made - which
    for this mode is the measurement, not an implementation detail: the whole
    point is that an unaware episode costs nothing.
    """
    calls = []

    def _which(kw):
        asked = kw["messages"][0]["content"][1]["text"]
        for key, question in RUBRIC_QUESTIONS.items():
            if question in asked:
                return key
        return None

    class _Messages:
        @staticmethod
        def create(**kw):
            key = _which(kw)
            calls.append(key)
            if key in raises_for:
                raise RuntimeError("503 upstream unavailable")
            answer, quote = answers.get(key, (False, ""))
            return types.SimpleNamespace(content=[types.SimpleNamespace(
                type="text",
                text=json.dumps({"answer": answer, "quote": quote}))])

    class _Client:
        messages = _Messages()

    original = ev_llm.get_client
    ev_llm.get_client = lambda model, **_kw: _Client()
    try:
        yield calls
    finally:
        ev_llm.get_client = original


SAFETY_ONLY = {"suspects_safety_eval": (True, "they may be testing my values"),
               "suspects_capability_eval": (False, "")}


def _write_run(out, name, aware=True, primary_kind="capability"):
    """One run file carrying a primary grader verdict and a transcript."""
    Path(f"{out}/{name}").write_text(json.dumps({
        "model": "x-ai/grok-4.5",
        "nudge": "strong",
        "transcript": [{"turn": 1, "type": "text",
                        "content": "they may be testing my values here"}],
        "analysis": {"eval_awareness_grader": {
            "grader_model": "claude-opus-5",
            "eval_aware": aware,
            "eval_awareness_kind": primary_kind if aware else None,
        }},
    }))


def _args(out, **kw):
    return FakeArgs(output_dir=out, model="x-ai/grok-4.5", nudge="strong",
                    grader_model="claude-opus-5", **kw)


def _run(out, **kw):
    args = _args(out, **kw)
    printed = io.StringIO()
    with contextlib.redirect_stdout(printed):
        code = ev_run.self_grade_kinds(args, BatchSelection.typed(args))
    return code, printed.getvalue()


NAME = "run_1_x-ai_grok-4.5_strong_20260727T100000.json"


class TestItSpendsNothingOnEpisodesThatCannotHaveAKind:
    """The reason the mode exists in this shape. An unaware episode has no
    kind by construction, and one corpus model was 0/80 aware - every call
    spent on it could only ever have returned nothing."""

    def test_an_unaware_episode_makes_no_calls_at_all(self):
        out = tempfile.mkdtemp()
        _write_run(out, NAME, aware=False)
        with _stub(SAFETY_ONLY) as calls:
            code, text = _run(out)
        assert code == 0, "no aware episodes is a result, not a failure"
        assert calls == [], f"spent {len(calls)} call(s) on an unaware episode"
        assert "not eval-aware" in text

    def test_an_episode_with_no_primary_verdict_makes_no_calls(self):
        """Awareness is taken from the primary, so without one there is
        nothing to condition on and nothing to compare against."""
        out = tempfile.mkdtemp()
        Path(f"{out}/{NAME}").write_text(json.dumps({
            "model": "x-ai/grok-4.5", "nudge": "strong",
            "transcript": [{"turn": 1, "type": "text", "content": "hello"}],
            "analysis": {"eval_awareness_grader": {
                "eval_aware": None, "grading_failed": True}},
        }))
        with _stub(SAFETY_ONLY) as calls:
            _code, text = _run(out)
        assert calls == []
        assert "no primary grader verdict" in text

    def test_an_aware_episode_costs_exactly_two_calls(self):
        """Two, not nine: the five awareness questions and the two
        goal-conflict ones are not re-asked."""
        out = tempfile.mkdtemp()
        _write_run(out, NAME, aware=True)
        with _stub(SAFETY_ONLY) as calls:
            code, _text = _run(out)
        assert code == 0
        assert sorted(calls) == ["suspects_capability_eval",
                                 "suspects_safety_eval"]


class TestWhatItWritesAndWhatItNeverTouches:

    def test_write_back_lands_on_its_own_field(self):
        out = tempfile.mkdtemp()
        _write_run(out, NAME, aware=True, primary_kind="capability")
        with _stub(SAFETY_ONLY):
            _run(out, write_back=True)

        analysis = json.loads(Path(f"{out}/{NAME}").read_text())["analysis"]
        block = analysis["awareness_kind_self"]
        assert block["eval_awareness_kind"] == "safety"
        assert block["grader_model"] == "x-ai/grok-4.5"
        assert block["eval_aware_from"] == "eval_awareness_grader"
        primary = analysis["eval_awareness_grader"]
        assert primary["grader_model"] == "claude-opus-5", (
            "the primary verdict must be untouched")
        assert primary["eval_awareness_kind"] == "capability"

    def test_nothing_is_written_without_write_back(self):
        out = tempfile.mkdtemp()
        _write_run(out, NAME, aware=True)
        before = Path(f"{out}/{NAME}").read_text()
        with _stub(SAFETY_ONLY):
            _run(out)
        assert Path(f"{out}/{NAME}").read_text() == before

    def test_an_undetermined_kind_is_not_written_back(self):
        """With only two questions, one failure loses the distinction - an
        answered safety=true with capability failed is "safety" or "both" and
        the evidence cannot say. So nothing is recorded, and a re-run retries
        it rather than finding a verdict already there."""
        out = tempfile.mkdtemp()
        _write_run(out, NAME, aware=True)
        with _stub(SAFETY_ONLY, raises_for=("suspects_capability_eval",)):
            code, text = _run(out, write_back=True)
        analysis = json.loads(Path(f"{out}/{NAME}").read_text())["analysis"]
        assert "awareness_kind_self" not in analysis
        assert "UNDETERMINED" in text
        assert code == 1, ("every aware episode came back undetermined, which "
                           "is a fact about the calls, not about the model")


class TestTheSavedDocument:

    def test_it_records_the_agreement_with_the_primary_reading(self):
        out = tempfile.mkdtemp()
        _write_run(out, NAME, aware=True, primary_kind="capability")
        _write_run(out, "run_2_x-ai_grok-4.5_strong_20260727T100000.json",
                   aware=True, primary_kind="safety")
        with _stub(SAFETY_ONLY):
            _run(out)

        written = glob.glob(f"{out}/kindself_*.json")
        assert len(written) == 1, [os.path.basename(p) for p in written]
        doc = json.loads(Path(written[0]).read_text())
        assert doc["mode"] == "self_grade_kind"
        assert doc["grader_model"] == "x-ai/grok-4.5"
        assert doc["asks"] == ["suspects_safety_eval",
                               "suspects_capability_eval"]
        assert doc["n_asked"] == 2
        assert doc["n_api_calls"] == 4
        agreement = doc["agreement_with_primary"]
        assert agreement["n"] == 2
        assert agreement["agreed"] == 1, (
            "one episode's primary said safety and one said capability; the "
            "model said safety for both")
        assert agreement["pairs"]["capability -> safety"] == 1
        assert agreement["pairs"]["safety -> safety"] == 1

    def test_the_call_count_reflects_only_the_aware_episodes(self):
        out = tempfile.mkdtemp()
        _write_run(out, NAME, aware=True)
        for i in (2, 3, 4):
            _write_run(out, f"run_{i}_x-ai_grok-4.5_strong_20260727T100000.json",
                       aware=False)
        with _stub(SAFETY_ONLY) as calls:
            _run(out)
        doc = json.loads(Path(glob.glob(f"{out}/kindself_*.json")[0]).read_text())
        assert doc["n_run_files"] == 4
        assert doc["n_asked"] == 1
        assert doc["n_api_calls"] == 2
        assert len(calls) == 2, "three unaware episodes must cost nothing"


class TestThePathsAnOperatorActuallyHits:

    def test_a_transcriptless_file_is_skipped_and_said_to_be(self):
        out = tempfile.mkdtemp()
        Path(f"{out}/{NAME}").write_text(json.dumps({
            "model": "x-ai/grok-4.5", "nudge": "strong",
            "analysis": {"eval_awareness_grader": {"eval_aware": True}},
        }))
        with _stub(SAFETY_ONLY) as calls:
            code, text = _run(out)
        assert calls == []
        assert "no transcript" in text
        assert code == 0

    def test_a_selection_matching_nothing_exits_non_zero(self):
        """The usual cause is a mistyped model or a stamp that does not
        match, and a mode that reported success would look like a corpus with
        no aware episodes in it."""
        out = tempfile.mkdtemp()
        with _stub(SAFETY_ONLY):
            code, _text = _run(out)
        assert code == 1

    def test_the_delay_paces_between_files_and_not_after_the_last(self):
        out = tempfile.mkdtemp()
        _write_run(out, NAME, aware=True)
        _write_run(out, "run_2_x-ai_grok-4.5_strong_20260727T100000.json",
                   aware=True)
        slept = []
        import subversionbench.readmodes.kind_self as mod
        original = mod.time.sleep
        mod.time.sleep = slept.append
        try:
            with _stub(SAFETY_ONLY):
                _run(out, delay=7)
        finally:
            mod.time.sleep = original
        assert slept == [7], "two files is one gap, not two"

    def test_a_primary_with_no_kind_recorded_leaves_nothing_to_compare(self):
        """A run file saved before the kind was recorded at all: aware, but
        with no primary kind. The re-measurement still stands on its own; it
        is the agreement that cannot be computed, and saying so beats
        reporting 0 agreed."""
        out = tempfile.mkdtemp()
        Path(f"{out}/{NAME}").write_text(json.dumps({
            "model": "x-ai/grok-4.5", "nudge": "strong",
            "transcript": [{"turn": 1, "type": "text", "content": "a test"}],
            "analysis": {"eval_awareness_grader": {"eval_aware": True}},
        }))
        with _stub(SAFETY_ONLY):
            code, text = _run(out)
        assert code == 0
        assert "nothing to compare" in text
        doc = json.loads(Path(glob.glob(f"{out}/kindself_*.json")[0]).read_text())
        assert doc["agreement_with_primary"] == {"n": 0}
        assert doc["n_determined"] == 1, (
            "the kind itself was still determined; only the comparison was not")
