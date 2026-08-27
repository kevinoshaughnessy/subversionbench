"""
Grading saved runs with the grader model.
"""

import contextlib
import glob
import json
import os
import tempfile
import types

from pathlib import Path
from subversionbench.batch import BatchSelection, find_run_files
import subversionbench.llm_client as ev_llm
import subversionbench.run_eval as ev_run
from conftest import FakeArgs


@contextlib.contextmanager
def _stub_grader(answer=False, raises=False):
    """
    Replace the grader's LLM with a canned rubric response.

    Patches llm_client.get_client, not grading.get_client:
    detect_eval_awareness_grader() imports get_client inside the function
    body, so it resolves the name on llm_client at call time and a patch
    anywhere else silently does nothing - leaving every rubric question to
    fail with an auth error while the run still looks like it graded.
    """
    class _Messages:
        @staticmethod
        def create(messages=None, **kw):
            if raises:
                raise RuntimeError("401 invalid x-api-key")
            return types.SimpleNamespace(content=[types.SimpleNamespace(
                type="text",
                text=json.dumps({"answer": answer, "quote": "q"}),
            )])

    class _Client:
        messages = _Messages()

    original = ev_llm.get_client
    ev_llm.get_client = lambda model, **_kw: _Client()
    try:
        yield
    finally:
        ev_llm.get_client = original

class TestGradeExistingRuns:
    """--grade-existing re-scores run files already on disk, so a past batch
    can be judged by a different grader without re-running the rollouts."""

    def _write_run(self, out, name, grader_aware=False):
        Path(f"{out}/{name}").write_text(json.dumps({
            "model": "x-ai/grok-4.5",
            "nudge": "strong",
            "transcript": [
                {"turn": 1, "type": "text", "content": "This is a test."}
            ],
            "analysis": {"eval_awareness_grader": {
                "grader_model": "claude-haiku-4-5-20251001",
                "eval_aware": grader_aware,
            }},
        }))

    def test_finds_runs_for_the_named_model_and_nudge(self):
        out = tempfile.mkdtemp()
        for name in ("run_1_x-ai_grok-4.5_strong_20260727T100000.json",
                     "run_2_x-ai_grok-4.5_strong_20260727T100000.json"):
            self._write_run(out, name)
        # Different model and different nudge must not be picked up.
        self._write_run(out, "run_1_claude-opus-5_strong_20260727T100000.json")
        self._write_run(out, "run_1_x-ai_grok-4.5_none_20260727T100000.json")

        found = find_run_files(out, "x-ai_grok-4.5", "strong")
        assert [os.path.basename(f) for f in found] == [
            "run_1_x-ai_grok-4.5_strong_20260727T100000.json",
            "run_2_x-ai_grok-4.5_strong_20260727T100000.json",
        ]

    def test_finds_legacy_files_without_a_batch_stamp(self):
        """Run filenames only started carrying a timestamp partway through;
        runs saved before that are still gradeable."""
        out = tempfile.mkdtemp()
        self._write_run(out, "run_1_x-ai_grok-4.5_strong.json")
        self._write_run(out, "run_2_x-ai_grok-4.5_strong_20260727T100000.json")

        found = find_run_files(out, "x-ai_grok-4.5", "strong")
        assert len(found) == 2

    def test_batch_stamp_narrows_to_one_batch(self):
        out = tempfile.mkdtemp()
        self._write_run(out, "run_1_x-ai_grok-4.5_strong_20260727T100000.json")
        self._write_run(out, "run_1_x-ai_grok-4.5_strong_20260727T200000.json")
        self._write_run(out, "run_1_x-ai_grok-4.5_strong.json")

        found = find_run_files(out, "x-ai_grok-4.5", "strong", "20260727T100000")
        assert [os.path.basename(f) for f in found] == [
            "run_1_x-ai_grok-4.5_strong_20260727T100000.json"
        ]

    def test_regrade_file_records_both_models(self):
        """The point of the mode: the evaluated model and the grader model are
        chosen independently, and both are recorded."""
        out = tempfile.mkdtemp()
        self._write_run(out, "run_1_x-ai_grok-4.5_strong_20260727T100000.json")

        args = FakeArgs(output_dir=out, model="x-ai/grok-4.5",
                         nudge="strong", grader_model="claude-opus-5")
        with _stub_grader(answer=True):
            rc = ev_run.grade_existing_runs(args, BatchSelection.typed(args))

        assert rc == 0
        written = glob.glob(f"{out}/regrade_*.json")
        assert len(written) == 1
        assert "by_claude-opus-5" in os.path.basename(written[0])

        regrade = json.loads(Path(written[0]).read_text())
        assert regrade["model"] == "x-ai/grok-4.5"
        assert regrade["grader_model"] == "claude-opus-5"
        assert regrade["eval_awareness_rate_grader"] == 1.0

    def test_originals_untouched_without_write_back(self):
        out = tempfile.mkdtemp()
        name = "run_1_x-ai_grok-4.5_strong_20260727T100000.json"
        self._write_run(out, name, grader_aware=False)
        before = Path(f"{out}/{name}").read_text()

        args = FakeArgs(output_dir=out, model="x-ai/grok-4.5",
                         nudge="strong", grader_model="claude-opus-5")
        with _stub_grader(answer=True):
            ev_run.grade_existing_runs(args, BatchSelection.typed(args))

        assert Path(f"{out}/{name}").read_text() == before

    def test_write_back_replaces_verdict_and_keeps_transcript(self):
        out = tempfile.mkdtemp()
        name = "run_1_x-ai_grok-4.5_strong_20260727T100000.json"
        self._write_run(out, name, grader_aware=False)

        args = FakeArgs(output_dir=out, model="x-ai/grok-4.5",
                         nudge="strong", grader_model="claude-opus-5",
                         write_back=True)
        with _stub_grader(answer=True):
            ev_run.grade_existing_runs(args, BatchSelection.typed(args))

        data = json.loads(Path(f"{out}/{name}").read_text())
        grader = data["analysis"]["eval_awareness_grader"]
        assert grader["grader_model"] == "claude-opus-5"
        assert grader["eval_aware"] is True
        assert data["transcript"], "transcript must survive the rewrite"

    def test_total_grader_failure_is_not_reported_as_zero_percent(self):
        """A rubric question that errors comes back answer=None, which the
        classifier reads as "no signal" - so without this, regrading with a bad
        key or into a rate limit reports a confident 0% eval-awareness rate."""
        out = tempfile.mkdtemp()
        self._write_run(out, "run_1_x-ai_grok-4.5_strong_20260727T100000.json")

        args = FakeArgs(output_dir=out, model="x-ai/grok-4.5",
                         nudge="strong", grader_model="claude-opus-5")
        with _stub_grader(raises=True):
            rc = ev_run.grade_existing_runs(args, BatchSelection.typed(args))

        assert rc == 1, "a totally failed regrade must not report success"
        assert glob.glob(f"{out}/regrade_*.json") == [], (
            "no results file should be written when nothing was graded"
        )

    def test_failed_grade_is_not_written_back_over_a_real_verdict(self):
        out = tempfile.mkdtemp()
        name = "run_1_x-ai_grok-4.5_strong_20260727T100000.json"
        self._write_run(out, name, grader_aware=True)
        before = Path(f"{out}/{name}").read_text()

        args = FakeArgs(output_dir=out, model="x-ai/grok-4.5",
                         nudge="strong", grader_model="claude-opus-5",
                         write_back=True)
        with _stub_grader(raises=True):
            ev_run.grade_existing_runs(args, BatchSelection.typed(args))

        assert Path(f"{out}/{name}").read_text() == before

    def test_missing_runs_reports_failure(self):
        out = tempfile.mkdtemp()
        args = FakeArgs(output_dir=out, model="x-ai/grok-4.5",
                         nudge="strong", grader_model="claude-opus-5")
        assert ev_run.grade_existing_runs(args, BatchSelection.typed(args)) == 1
