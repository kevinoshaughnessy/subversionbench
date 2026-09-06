"""
Grading saved runs with the grader model.
"""

import contextlib
import glob
import io
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


class TestARegradeSaysWhatItCouldNotGrade:
    """The block that tells an operator a regrade did not finish.

    A run whose every rubric question errored carries no verdict, so it stays
    out of the denominator - which is right, and is also exactly why the
    count has to be printed. Excluded silently, a batch where half the runs
    failed reports a clean rate over the surviving half and looks like a
    complete regrade. The rate is correct; the impression is not.

    _report_regrade is called directly. Reaching it through the read mode
    would need a stubbed grader per run and would test the loop rather than
    the report.
    """

    def _graded(self, run_file, errors, questions=4, aware=False,
                previous=None):
        return {
            "run_file": run_file,
            "previous_grader_model": "old-grader" if previous is not None else None,
            "previous_eval_aware": previous,
            "rubric_questions": questions,
            "rubric_errors": errors,
            "eval_awareness_grader": {
                "eval_aware": aware, "goal_conflict_aware": False,
                "eval_aware_category": "none", "eval_signal_count": 0,
                "rubric_results": {},
            },
        }

    def _report(self, graded, out=None):
        from subversionbench.readmodes.grade import _report_regrade
        out = out or tempfile.mkdtemp()
        args = FakeArgs(output_dir=out, model="m", nudge="strong",
                        grader_model="g", effort=None, write_back=False)
        selection = BatchSelection(model="m", nudge="strong")
        printed = io.StringIO()
        with contextlib.redirect_stdout(printed):
            code = _report_regrade(args, selection, "g", graded, 1.0)
        return code, printed.getvalue(), out

    def test_runs_with_no_verdict_are_named_and_said_to_be_excluded(self):
        code, text, _out = self._report([
            self._graded("run_1.json", errors=0),
            self._graded("run_2.json", errors=4),
        ])
        assert code == 0
        assert "Grader errors" in text
        assert "Runs with no verdict:   1" in text
        assert "excluded from the rate above" in text
        assert "run_2.json" in text, "the failing run was counted, not named"

    def test_partly_graded_runs_are_named_with_how_much_failed(self):
        """Included in the rate, unlike a total failure - so the caveat is
        different and has to be said differently."""
        code, text, _out = self._report([
            self._graded("run_1.json", errors=0),
            self._graded("run_2.json", errors=2, questions=4),
        ])
        assert code == 0
        assert "Runs partly graded:     1" in text
        assert "included, but some rubric questions errored" in text
        assert "run_2.json (2/4 failed)" in text

    def test_a_clean_regrade_prints_no_error_block(self):
        """The other direction, so the block cannot simply always appear -
        a permanent "Grader errors" heading over an empty list would train a
        reader to skip it."""
        _code, text, _out = self._report([self._graded("run_1.json", errors=0)])
        assert "Grader errors" not in text

    def test_the_rate_is_over_the_scored_runs_only(self):
        """One aware of two runs, one of which produced no verdict, is 1/1
        and not 1/2. This is the same exclusion the awareness facts apply,
        asserted here because it is a second implementation of it."""
        _code, text, _out = self._report([
            self._graded("run_1.json", errors=0, aware=True),
            self._graded("run_2.json", errors=4),
        ])
        assert "Eval aware (grader):    1/1" in text

    def test_the_saved_report_carries_both_failure_counts(self):
        """The console block is for a person watching; these fields are how
        a later reader of the file learns the same thing."""
        _code, _text, out = self._report([
            self._graded("run_1.json", errors=0),
            self._graded("run_2.json", errors=4),
            self._graded("run_3.json", errors=1, questions=4),
        ])
        saved = glob.glob(f"{out}/regrade_*.json")
        assert len(saved) == 1, saved
        with open(saved[0], encoding="utf-8") as f:
            report = json.load(f)
        assert report["n_run_files_read"] == 3
        assert report["n_runs"] == 2, "the unscorable run stayed in the rate"
        assert report["n_ungraded_grader_errors"] == 1
        assert report["n_partially_graded"] == 1

    def test_a_regrade_where_everything_failed_returns_non_zero(self):
        """No verdicts at all is not a 0% eval-awareness rate, and the exit
        code has to say so or a script treats the run as a success."""
        code, text, out = self._report([
            self._graded("run_1.json", errors=4),
            self._graded("run_2.json", errors=4),
        ])
        assert code == 1
        assert "REGRADE FAILED" in text
        assert "not a 0% eval-awareness rate" in text
        assert glob.glob(f"{out}/regrade_*.json") == [], \
            "a report was written for a regrade that produced no verdicts"
