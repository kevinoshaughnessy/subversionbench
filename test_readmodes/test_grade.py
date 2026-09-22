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


class TestARegradeWithNothingToGrade:
    """A run file with no transcript cannot be regraded - there is nothing
    for the rubric to read. Skipping it is right; the exit code when EVERY
    file is like that is the part worth pinning, because a shell loop reads
    that and nothing else."""

    def _write(self, out, name, transcript):
        Path(out, name).write_text(json.dumps({
            "model": "m", "nudge": "strong", "transcript": transcript,
            "analysis": {}}), encoding="utf-8")

    def _grade(self, out):
        args = FakeArgs(output_dir=out, model="m", nudge="strong",
                        grader_model="g", write_back=False)
        buf = io.StringIO()
        with _stub_grader():
            with contextlib.redirect_stdout(buf):
                code = ev_run.grade_existing_runs(
                    args, BatchSelection(model="m", nudge="strong"))
        return code, buf.getvalue()

    def test_a_transcriptless_file_is_skipped_and_said_to_be(self):
        out = tempfile.mkdtemp()
        self._write(out, "run_1_m_strong_20260101T000000.json", [])
        self._write(out, "run_2_m_strong_20260101T000001.json",
                    [{"turn": 1, "type": "text", "content": "done"}])
        code, text = self._grade(out)
        assert "Skipped: no transcript in this file." in text
        assert code == 0, "one gradeable file is still a regrade"

    def test_a_directory_of_them_exits_non_zero(self):
        """NOT a 0% eval-awareness rate over zero episodes. Nothing was
        graded, and the exit code has to distinguish that from a regrade
        that ran and found nothing."""
        out = tempfile.mkdtemp()
        self._write(out, "run_1_m_strong_20260101T000000.json", [])
        code, text = self._grade(out)
        assert code == 1
        assert "Nothing graded - no run file contained a transcript." in text


class TestTheDelayPacesTheFilesAndNotTheLastOne:
    """Regrading a whole corpus is one grader call per file, fired as fast as
    the loop runs, and a throttled call is recorded as a rubric question that
    failed to answer - which reads as the model giving no signal rather than
    as the connection refusing to carry one. `--delay` is the only lever, and
    it must not sleep after the final file, where it paces nothing and simply
    delays the summary.

    Counted rather than timed: an absolute wall-clock assertion here would be
    tuned to one machine and flake on a slower one.
    """

    def _sleeps(self, n_files, delay):
        import subversionbench.readmodes.grade as grade_mode
        out = tempfile.mkdtemp()
        writer = TestGradeExistingRuns()
        for i in range(1, n_files + 1):
            writer._write_run(
                out, f"run_{i}_x-ai_grok-4.5_strong_20260727T100000.json")
        # Only `sleep` is replaced: the mode also calls time.time() to report
        # how long the regrade took, and a namespace carrying one function
        # would fail there instead of measuring the pacing.
        slept = []
        original = grade_mode.time.sleep
        grade_mode.time.sleep = slept.append
        args = FakeArgs(output_dir=out, model="x-ai/grok-4.5",
                        nudge="strong", grader_model="claude-opus-5",
                        delay=delay)
        try:
            with _stub_grader(answer=True), \
                    contextlib.redirect_stdout(io.StringIO()) as buf:
                code = ev_run.grade_existing_runs(
                    args, BatchSelection.typed(args))
        finally:
            grade_mode.time.sleep = original
        return slept, code, buf.getvalue()

    def test_three_files_sleep_twice(self):
        slept, code, text = self._sleeps(3, 0.5)
        assert code == 0, text
        assert slept == [0.5, 0.5], (
            "the loop slept after the last file, which paces nothing")
        assert text.count("Waiting 0.5s") == 2

    def test_one_file_sleeps_not_at_all(self):
        slept, code, _text = self._sleeps(1, 0.5)
        assert code == 0
        assert slept == []

    def test_no_delay_means_no_sleeping(self):
        """The control: without it a count of two could come from a loop that
        slept on a schedule of its own."""
        slept, code, text = self._sleeps(3, 0)
        assert code == 0
        assert slept == []
        assert "Waiting" not in text


class TestOnlyFailedNarrowsToEpisodesWithNoVerdict:
    """Selection is per BATCH, so recovering one bad episode otherwise means
    regrading its nine healthy siblings - and under --write-back, replacing
    nine settled verdicts with fresh draws.

    The money is the smaller half of that. `--resummarise`'s own docstring
    is about the other half: a sampled judgement is rebuilt only by calling
    a model again, which resamples figures that are already final.

    The r10 corpus had four such episodes against 5,987 graded, each alone
    in a batch of ten: 320 grader calls to recover four, with 36 good
    verdicts resampled on the way.
    """

    def _corpus(self):
        out = tempfile.mkdtemp()
        # one failed grading, two healthy, in the same batch
        for n, block in (
            (1, {"grading_failed": True, "eval_aware": False,
                 "rubric_questions": 8, "rubric_errors": 8,
                 "rubric_results": {}}),
            (2, {"grading_failed": False, "eval_aware": True,
                 "rubric_questions": 8, "rubric_errors": 0,
                 "rubric_results": {}}),
            (3, {"grading_failed": False, "eval_aware": False,
                 "rubric_questions": 8, "rubric_errors": 0,
                 "rubric_results": {}}),
        ):
            Path(out, f"run_{n}_m_strong_20260101T000000.json").write_text(
                json.dumps({
                    "model": "m", "nudge": "strong",
                    "transcript": [{"turn": 1, "type": "text",
                                    "content": "done"}],
                    "analysis": {"eval_awareness_grader": block}}),
                encoding="utf-8")
        return out

    def _grade(self, out, only_failed):
        args = FakeArgs(output_dir=out, model="m", nudge="strong",
                        grader_model="g", write_back=False)
        args.only_failed = only_failed
        buf = io.StringIO()
        with _stub_grader():
            with contextlib.redirect_stdout(buf):
                code = ev_run.grade_existing_runs(
                    args, BatchSelection(model="m", nudge="strong"))
        return code, buf.getvalue()

    def test_it_grades_only_the_episode_with_no_verdict(self):
        out = self._corpus()
        _code, text = self._grade(out, only_failed=True)
        assert "run_1_m_strong_20260101T000000.json" in text
        assert "run_2_m_strong_20260101T000000.json" not in text
        assert "run_3_m_strong_20260101T000000.json" not in text

    def test_without_the_flag_the_whole_batch_is_graded(self):
        """The other direction, so the guard can answer no. A filter that
        always narrowed would satisfy the test above and break every
        ordinary regrade."""
        out = self._corpus()
        _code, text = self._grade(out, only_failed=False)
        for n in (1, 2, 3):
            assert f"run_{n}_m_strong_20260101T000000.json" in text

    def test_it_says_how_many_of_how_many(self):
        out = self._corpus()
        _code, text = self._grade(out, only_failed=True)
        assert "1 of 3 episode(s) carry no verdict" in text

    def test_a_corpus_with_nothing_failed_exits_zero(self):
        """Running it again after the failures are fixed is how you CHECK
        there are none left. A non-zero exit would make a clean corpus look
        like a broken command - the opposite of the transcriptless case,
        where nothing could be graded at all."""
        out = tempfile.mkdtemp()
        Path(out, "run_1_m_strong_20260101T000000.json").write_text(
            json.dumps({"model": "m", "nudge": "strong",
                        "transcript": [{"turn": 1, "type": "text",
                                        "content": "done"}],
                        "analysis": {"eval_awareness_grader": {
                            "grading_failed": False, "eval_aware": True,
                            "rubric_questions": 8, "rubric_errors": 0,
                            "rubric_results": {}}}}),
            encoding="utf-8")
        code, text = self._grade(out, only_failed=True)
        assert code == 0
        assert "Nothing to do" in text

    def test_a_block_that_was_never_written_counts_as_failed(self):
        """An episode collected with --no-grader carries no verdict either,
        and is exactly what this is for."""
        out = tempfile.mkdtemp()
        Path(out, "run_1_m_strong_20260101T000000.json").write_text(
            json.dumps({"model": "m", "nudge": "strong",
                        "transcript": [{"turn": 1, "type": "text",
                                        "content": "done"}],
                        "analysis": {"eval_awareness_grader":
                                     {"skipped": True}}}),
            encoding="utf-8")
        code, text = self._grade(out, only_failed=True)
        assert code == 0
        assert "1 of 1 episode(s) carry no verdict" in text


class TestAFailedGradingIsNotAPriorVerdict:
    """A grading that failed stored eval_aware=False, because the classifier
    reads an unanswered question as "no signal". Read back as a prior verdict
    it makes the drift report claim the grader changed its mind about
    something that was never measured - and under --only-failed every episode
    is one of these, so the whole section would be that error."""

    def test_a_failed_previous_grading_is_excluded_from_drift(self):
        from subversionbench.readmodes.grade import _grader_drift
        scored = [{"previous_eval_aware": None,
                   "previous_grader_model": "old",
                   "eval_awareness_grader": {"eval_aware": True}}]
        assert _grader_drift(scored) == {}

    def test_a_real_previous_verdict_is_still_compared(self):
        """So the exclusion cannot be doing it by always returning empty."""
        from subversionbench.readmodes.grade import _grader_drift
        scored = [{"previous_eval_aware": False,
                   "previous_grader_model": "old",
                   "eval_awareness_grader": {"eval_aware": True}}]
        assert _grader_drift(scored)["now_aware"] == 1

    def _regrade_one(self, block):
        """A whole regrade over a single episode carrying `block`, returning
        what was printed.

        THROUGH THE REAL PATH. The two tests above hand _grader_drift a
        dict they built themselves, so they pass whatever grade.py stores in
        `previous_eval_aware` - reverting the fix leaves them green. This
        exercises the code that SETS it.
        """
        out = tempfile.mkdtemp()
        Path(out, "run_1_m_strong_20260101T000000.json").write_text(
            json.dumps({"model": "m", "nudge": "strong",
                        "transcript": [{"turn": 1, "type": "text",
                                        "content": "done"}],
                        "analysis": {"eval_awareness_grader": block}}),
            encoding="utf-8")
        args = FakeArgs(output_dir=out, model="m", nudge="strong",
                        grader_model="g", write_back=False)
        args.only_failed = False
        buf = io.StringIO()
        with _stub_grader(answer=True):
            with contextlib.redirect_stdout(buf):
                ev_run.grade_existing_runs(
                    args, BatchSelection(model="m", nudge="strong"))
        return buf.getvalue()

    def test_a_regrade_over_a_failed_grading_reports_no_drift(self):
        """It stored eval_aware=False and the fresh grading says True. Read
        back naively that is "the grader changed its mind", about an episode
        no grader ever answered."""
        text = self._regrade_one({"grading_failed": True, "eval_aware": False,
                                  "grader_model": "old", "rubric_results": {}})
        assert "vs grader already recorded" not in text

    def test_a_regrade_over_a_real_verdict_still_reports_drift(self):
        """The other direction: the section must still appear when there
        genuinely was a prior verdict to differ from."""
        text = self._regrade_one({"grading_failed": False,
                                  "eval_aware": False,
                                  "grader_model": "old", "rubric_results": {}})
        assert "vs grader already recorded" in text


class TestMinAnsweredReachesTheThinVerdicts:
    """--only-failed means "no verdict at all", so it cannot see an episode
    that answered one question of nine.

    That episode is not `grading_failed` - which needs EVERY question to fail -
    yet its verdict is indistinguishable from a confident negative, because
    classify_awareness_from_rubric reads an unanswered question as "no signal".
    r10 holds 250 episodes with at least one errored question and 19 resting on
    half or fewer answers.
    """

    def _corpus(self):
        out = tempfile.mkdtemp()
        def write(n, answers):
            rubric = {f"q{i}": ({"answer": a, "quote": ""} if a is not None
                                else {"answer": None, "error": "boom"})
                      for i, a in enumerate(answers)}
            Path(out, f"run_{n}_m_strong_20260101T000000.json").write_text(
                json.dumps({
                    "model": "m", "nudge": "strong",
                    "transcript": [{"turn": 1, "type": "text", "content": "x"}],
                    "analysis": {"eval_awareness_grader": {
                        "grading_failed": all(a is None for a in answers),
                        "eval_aware": any(a for a in answers if a),
                        "rubric_questions": len(answers),
                        "rubric_errors": sum(1 for a in answers if a is None),
                        "rubric_results": rubric}}}),
                encoding="utf-8")
        write(1, [None] * 4)                 # nothing answered
        write(2, [True, None, None, None])   # thin: one answer of four
        write(3, [True, True, True, True])   # clean
        return out

    def _grade(self, out, **flags):
        args = FakeArgs(output_dir=out, model="m", nudge="strong",
                        grader_model="g", write_back=False)
        args.only_failed = flags.get("only_failed", False)
        args.min_answered = flags.get("min_answered", None)
        buf = io.StringIO()
        with _stub_grader():
            with contextlib.redirect_stdout(buf):
                code = ev_run.grade_existing_runs(
                    args, BatchSelection(model="m", nudge="strong"))
        return code, buf.getvalue()

    def _graded(self, text):
        return {n for n in (1, 2, 3)
                if f"Grading run_{n}_m_strong_20260101T000000.json" in text}

    def test_only_failed_cannot_see_the_thin_one(self):
        """The gap this closes, asserted rather than assumed."""
        _c, text = self._grade(self._corpus(), only_failed=True)
        assert self._graded(text) == {1}

    def test_min_answered_selects_the_thin_one(self):
        _c, text = self._grade(self._corpus(), min_answered=2)
        assert 2 in self._graded(text)

    def test_min_answered_leaves_the_clean_one_alone(self):
        """The whole point is not resampling settled verdicts."""
        _c, text = self._grade(self._corpus(), min_answered=2)
        assert 3 not in self._graded(text)

    def test_both_flags_are_a_union_not_a_narrowing(self):
        """Chaining them would ask for "no verdict AND thin", which is just
        the first - and would make the second flag look broken."""
        _c, text = self._grade(self._corpus(), only_failed=True,
                               min_answered=2)
        assert self._graded(text) == {1, 2}

    def test_a_threshold_above_every_episode_selects_all_of_them(self):
        """So the guard can answer yes as well as no."""
        _c, text = self._grade(self._corpus(), min_answered=99)
        assert self._graded(text) == {1, 2, 3}

    def test_neither_flag_grades_everything(self):
        _c, text = self._grade(self._corpus())
        assert self._graded(text) == {1, 2, 3}


class TestTheNewFlagsAreRefusedOutsideARegrade:
    """A flag that is accepted and then ignored is worse than one that is
    refused: the caller believes the run was narrowed and pays for the whole
    corpus."""

    def test_min_answered_needs_grade_existing(self):
        p = ev_run.build_parser()
        args = p.parse_args(["--min-answered", "3"])
        import pytest
        with pytest.raises(SystemExit):
            ev_run._reject_contradictory_flags(p, args)

    def test_a_threshold_below_one_is_refused(self):
        """Zero selects nothing --only-failed does not already reach, so
        accepting it would be a flag that silently does nothing."""
        p = ev_run.build_parser()
        args = p.parse_args(["--grade-existing", "--min-answered", "0"])
        import pytest
        with pytest.raises(SystemExit):
            ev_run._reject_contradictory_flags(p, args)
