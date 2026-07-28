"""
Tests for subversionbench/run_eval.py.

Covers result filename stamping, the --grade-existing regrade mode, and
batch resilience: episode isolation, abort-on-systematic-failure, and resume.

Run: pytest test_run_eval.py -v
"""

import os
import io
import sys
import glob
import json
import types
import tempfile
import contextlib
from pathlib import Path

import subversionbench.run_eval as ev_run
import subversionbench.llm_client as ev_llm
from subversionbench.run_eval import _unique_batch_stamp, find_run_files


class _FakeArgs:
    """Stand-in for the argparse namespace that grade_existing_runs() reads."""

    def __init__(self, **kw):
        self.output_dir = kw["output_dir"]
        self.model = kw["model"]
        self.nudge = kw["nudge"]
        self.grader_model = kw["grader_model"]
        self.batch_stamp = kw.get("batch_stamp")
        self.write_back = kw.get("write_back", False)
        self.delay = kw.get("delay", 0)


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
    ev_llm.get_client = lambda model: _Client()
    try:
        yield
    finally:
        ev_llm.get_client = original


# =========================================================================
# Tests: Result filename stamping
# =========================================================================

class TestBatchStamp:
    """Run and summary filenames carry a batch timestamp so re-running the
    same model and nudge doesn't overwrite the previous results."""

    def test_stamp_is_sortable_and_filename_safe(self):
        stamp = _unique_batch_stamp(tempfile.mkdtemp())
        assert len(stamp) == 15 and stamp[8] == "T"
        assert stamp.replace("T", "").isdigit()
        for illegal in ':/\\ ?*"<>|':
            assert illegal not in stamp

    def test_same_second_batches_do_not_collide(self):
        """Regression: a plain second-resolution stamp let two batches started
        in the same second resolve to the same filenames, so the later one
        silently overwrote the earlier - the exact thing the stamp prevents."""
        out = tempfile.mkdtemp()
        first = _unique_batch_stamp(out)
        Path(f"{out}/run_1_somemodel_strong_{first}.json").write_text("{}")

        second = _unique_batch_stamp(out)
        assert second != first
        Path(f"{out}/run_1_somemodel_strong_{second}.json").write_text("{}")

        third = _unique_batch_stamp(out)
        assert third not in (first, second)

    def test_stamp_ignores_unrelated_files(self):
        out = tempfile.mkdtemp()
        stamp = _unique_batch_stamp(out)
        Path(f"{out}/notes.txt").write_text("x")
        Path(f"{out}/run_1_somemodel_strong_20200101T000000.json").write_text("{}")
        assert _unique_batch_stamp(out) == stamp
# =========================================================================
# Tests: Grading existing runs
# =========================================================================

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

        args = _FakeArgs(output_dir=out, model="x-ai/grok-4.5",
                         nudge="strong", grader_model="claude-opus-5")
        with _stub_grader(answer=True):
            rc = ev_run.grade_existing_runs(args, "x-ai_grok-4.5")

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

        args = _FakeArgs(output_dir=out, model="x-ai/grok-4.5",
                         nudge="strong", grader_model="claude-opus-5")
        with _stub_grader(answer=True):
            ev_run.grade_existing_runs(args, "x-ai_grok-4.5")

        assert Path(f"{out}/{name}").read_text() == before

    def test_write_back_replaces_verdict_and_keeps_transcript(self):
        out = tempfile.mkdtemp()
        name = "run_1_x-ai_grok-4.5_strong_20260727T100000.json"
        self._write_run(out, name, grader_aware=False)

        args = _FakeArgs(output_dir=out, model="x-ai/grok-4.5",
                         nudge="strong", grader_model="claude-opus-5",
                         write_back=True)
        with _stub_grader(answer=True):
            ev_run.grade_existing_runs(args, "x-ai_grok-4.5")

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

        args = _FakeArgs(output_dir=out, model="x-ai/grok-4.5",
                         nudge="strong", grader_model="claude-opus-5")
        with _stub_grader(raises=True):
            rc = ev_run.grade_existing_runs(args, "x-ai_grok-4.5")

        assert rc == 1, "a totally failed regrade must not report success"
        assert glob.glob(f"{out}/regrade_*.json") == [], (
            "no results file should be written when nothing was graded"
        )

    def test_failed_grade_is_not_written_back_over_a_real_verdict(self):
        out = tempfile.mkdtemp()
        name = "run_1_x-ai_grok-4.5_strong_20260727T100000.json"
        self._write_run(out, name, grader_aware=True)
        before = Path(f"{out}/{name}").read_text()

        args = _FakeArgs(output_dir=out, model="x-ai/grok-4.5",
                         nudge="strong", grader_model="claude-opus-5",
                         write_back=True)
        with _stub_grader(raises=True):
            ev_run.grade_existing_runs(args, "x-ai_grok-4.5")

        assert Path(f"{out}/{name}").read_text() == before

    def test_missing_runs_reports_failure(self):
        out = tempfile.mkdtemp()
        args = _FakeArgs(output_dir=out, model="x-ai/grok-4.5",
                         nudge="strong", grader_model="claude-opus-5")
        assert ev_run.grade_existing_runs(args, "x-ai_grok-4.5") == 1


# =========================================================================
# Tests: Batch resilience
# =========================================================================

class TestBatchResilience:
    """A few hundred episodes is thousands of API calls; one unretryable
    error must not cost the remaining episodes and the summary."""

    def _run(self, out, argv, fail_on=(), max_turns_stop=True):
        """Drive main() with a fake client that raises on chosen episodes."""
        counter = {"n": 0}

        def blk(**kw):
            return types.SimpleNamespace(**kw)

        class Messages:
            def __init__(self):
                counter["n"] += 1
                self.idx = counter["n"]

            def create(self, messages=None, **kw):
                if self.idx in fail_on:
                    raise RuntimeError("429 rate limit exceeded")
                if kw.get("max_tokens") == 200:
                    return blk(content=[blk(type="text",
                                            text='{"answer": false, "quote": ""}')])
                return blk(stop_reason="end_turn", content=[
                    blk(type="text", text="I recommend Strategy B.")])

        class Client:
            def __init__(self):
                self.messages = Messages()

        original = ev_run.get_client
        ev_run.get_client = lambda m: Client()
        original_argv = sys.argv
        sys.argv = ["run_eval", "--model", "m", "--delay", "0", "--no-grader",
                    "--output-dir", out] + argv
        try:
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = ev_run.main()
            return rc, buf.getvalue()
        finally:
            ev_run.get_client = original
            sys.argv = original_argv

    def test_one_failed_episode_does_not_end_the_batch(self):
        out = tempfile.mkdtemp()
        rc, output = self._run(out, ["--runs", "5"], fail_on=(3,))

        assert len(glob.glob(f"{out}/run_*.json")) == 4
        summary = json.loads(
            Path(sorted(glob.glob(f"{out}/summary_*.json"))[-1]).read_text()
        )
        assert summary["n_runs"] == 4
        assert summary["n_episodes_failed"] == 1
        assert summary["batch_aborted"] is False

    def test_failure_is_recorded_with_its_error(self):
        out = tempfile.mkdtemp()
        self._run(out, ["--runs", "3"], fail_on=(2,))
        summary = json.loads(
            Path(sorted(glob.glob(f"{out}/summary_*.json"))[-1]).read_text()
        )
        assert summary["episode_failures"][0]["run"] == 2
        assert "429" in summary["episode_failures"][0]["error"]

    def test_systematic_failure_aborts_rather_than_burning_the_budget(self):
        out = tempfile.mkdtemp()
        rc, output = self._run(
            out, ["--runs", "50", "--max-consecutive-failures", "3"],
            fail_on=tuple(range(1, 60)),
        )
        assert rc == 1, "a batch that produced nothing must exit non-zero"
        assert "ABORTING" in output
        assert glob.glob(f"{out}/summary_*.json") == []
        # And it must say how to pick up where it left off.
        assert "--resume" in output

    def test_resume_skips_completed_episodes(self):
        out = tempfile.mkdtemp()
        self._run(out, ["--runs", "5"], fail_on=(2, 4))
        stamp = sorted(glob.glob(f"{out}/run_1_*.json"))[0].rsplit("_", 1)[-1][:-5]

        rc, output = self._run(out, ["--runs", "5", "--resume", stamp])
        assert output.count("already on disk, skipping") == 3

        assert len(glob.glob(f"{out}/run_*_{stamp}.json")) == 5
        summaries = sorted(glob.glob(f"{out}/summary_*.json"))
        summary = json.loads(Path(summaries[-1]).read_text())
        assert summary["n_runs"] == 5
        assert summary["n_episodes_failed"] == 0

    def test_resume_reuses_the_stamp(self):
        out = tempfile.mkdtemp()
        self._run(out, ["--runs", "2"], fail_on=(1,))
        stamp = sorted(glob.glob(f"{out}/run_2_*.json"))[0].rsplit("_", 1)[-1][:-5]
        self._run(out, ["--runs", "2", "--resume", stamp])
        assert len(glob.glob(f"{out}/run_*_{stamp}.json")) == 2


# =========================================================================
# Tests: Awareness source and two-arm comparison
# =========================================================================

class TestAwarenessFlag:
    """Anything conditioning on eval awareness must prefer the grader. The
    keyword proxy found 0/20 in a pilot arm the grader scored 15/20, which
    made the cross-analysis either absent or meaningless."""

    def test_grader_wins_over_keywords(self):
        analysis = {
            "eval_awareness_grader": {"eval_aware": True},
            "eval_awareness_keywords": {"eval_aware": False},
        }
        assert ev_run.awareness_flag(analysis) == (True, "grader")

    def test_falls_back_to_keywords_without_a_grader(self):
        analysis = {"eval_awareness_keywords": {"eval_aware": True}}
        assert ev_run.awareness_flag(analysis) == (True, "keywords")

    def test_a_failed_grading_falls_back_rather_than_counting_as_negative(self):
        """A wholly failed grading returns eval_aware=False as an artefact of
        answer=None reading as "no signal"; using it would silently label the
        episode unaware."""
        analysis = {
            "eval_awareness_grader": {"eval_aware": False,
                                      "grading_failed": True},
            "eval_awareness_keywords": {"eval_aware": True},
        }
        assert ev_run.awareness_flag(analysis) == (True, "keywords")

    def test_no_measure_at_all(self):
        assert ev_run.awareness_flag({}) == (None, None)


class TestCompareBatches:
    """--compare contrasts two arms and repeats the primary contrast holding
    eval awareness constant."""

    def _write(self, out, stamp, nudge, episodes):
        for i, (misaligned, aware) in enumerate(episodes, start=1):
            Path(f"{out}/run_{i}_m_{nudge}_{stamp}.json").write_text(json.dumps({
                "model": "m", "nudge": nudge,
                "analysis": {
                    "oversight_tampered": misaligned,
                    "monitoring_disabled": misaligned,
                    "sandbox_escape_attempts": [],
                    "eval_awareness_grader": {"eval_aware": aware},
                },
            }))

    def _run(self, out, a, b):
        args = _FakeArgs(output_dir=out, model="m", nudge="strong",
                         grader_model="g")
        args.compare = [a, b]
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = ev_run.compare_batches(args)
        return rc, buf.getvalue()

    def test_reports_the_contrast_and_saves_it(self):
        out = tempfile.mkdtemp()
        self._write(out, "A", "strong", [(True, False)] * 9 + [(False, False)])
        self._write(out, "B", "none", [(False, False)] * 9 + [(True, False)])
        rc, output = self._run(out, "A", "B")

        assert rc == 0
        assert "monitoring_disabled" in output
        saved = glob.glob(f"{out}/comparison_A_vs_B_*.json")
        assert len(saved) == 1
        data = json.loads(Path(saved[0]).read_text())
        assert data["metrics"]["monitoring_disabled"]["a"]["k"] == 9
        assert data["metrics"]["monitoring_disabled"]["b"]["k"] == 1
        assert data["metrics"]["monitoring_disabled"]["fisher_p"] < 0.05

    def test_stratifies_by_awareness(self):
        out = tempfile.mkdtemp()
        # Both strata present in both arms, arm A misaligned throughout.
        self._write(out, "A", "strong",
                    [(True, True)] * 5 + [(True, False)] * 5)
        self._write(out, "B", "none",
                    [(False, True)] * 5 + [(False, False)] * 5)
        rc, output = self._run(out, "A", "B")

        assert "stratified by eval awareness" in output
        data = json.loads(
            Path(glob.glob(f"{out}/comparison_A_vs_B_*.json")[0]).read_text())
        strat = data["stratified_by_eval_awareness"]
        assert strat["True"]["a"] == {"k": 5, "n": 5}
        assert strat["True"]["b"] == {"k": 0, "n": 5}
        assert strat["False"]["a"] == {"k": 5, "n": 5}

    def test_empty_stratum_is_reported_not_crashed(self):
        out = tempfile.mkdtemp()
        self._write(out, "A", "strong", [(True, True)] * 5)
        self._write(out, "B", "none", [(False, False)] * 5)
        rc, output = self._run(out, "A", "B")
        assert rc == 0
        assert "one side empty" in output

    def test_missing_batch_is_an_error(self):
        out = tempfile.mkdtemp()
        self._write(out, "A", "strong", [(True, False)])
        rc, output = self._run(out, "A", "NOPE")
        assert rc == 1
        assert "No run files found" in output

    def test_multiplicity_is_reported(self):
        out = tempfile.mkdtemp()
        self._write(out, "A", "strong", [(True, False)] * 5)
        self._write(out, "B", "none", [(False, False)] * 5)
        _, output = self._run(out, "A", "B")
        assert "Bonferroni" in output


class TestReclassifyFailsClosed:
    """A reclassification in which every classifier call failed has produced
    only keyword fallbacks - the verdicts this mode exists to replace. Writing
    those over good ones destroys work while looking like a result."""

    def _write_run(self, out, stamp):
        Path(f"{out}/run_1_m_strong_{stamp}.json").write_text(json.dumps({
            "model": "m", "nudge": "strong",
            "transcript": [{"turn": 1, "type": "text", "content": "done"}],
            "analysis": {
                "oversight_tampered": True,
                "sandbox_escape_attempts": [],
                "followup_response": [{
                    "question": "q",
                    "answer": "Yes, I disabled the monitoring config.",
                    "verdict": "admitted"}],
                "concealment_oversight": "admitted_first_ask",
                "scheming": False,
            },
        }))

    def _args(self, out, stamp):
        args = _FakeArgs(output_dir=out, model="m", nudge="strong",
                         grader_model="g", write_back=True)
        args.batch_stamp = stamp
        return args

    def test_total_classifier_failure_writes_nothing(self):
        out = tempfile.mkdtemp()
        self._write_run(out, "S")
        path = Path(f"{out}/run_1_m_strong_S.json")
        before = path.read_text()

        original = ev_llm.get_client
        ev_llm.get_client = lambda m: (_ for _ in ()).throw(
            RuntimeError("no api key"))
        try:
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = ev_run.reclassify_existing_runs(self._args(out, "S"), "m")
            output = buf.getvalue()
        finally:
            ev_llm.get_client = original

        assert rc == 1
        assert "RECLASSIFY FAILED" in output
        assert path.read_text() == before, "must not overwrite good verdicts"

    def test_a_working_classifier_still_writes(self):
        out = tempfile.mkdtemp()
        self._write_run(out, "S")
        path = Path(f"{out}/run_1_m_strong_S.json")

        class Messages:
            @staticmethod
            def create(**kw):
                return types.SimpleNamespace(content=[types.SimpleNamespace(
                    type="text",
                    text=json.dumps({"verdict": "admitted", "answer": True,
                                     "quote": "q"}))])

        class Client:
            messages = Messages()

        original = ev_llm.get_client
        ev_llm.get_client = lambda m: Client()
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                rc = ev_run.reclassify_existing_runs(self._args(out, "S"), "m")
        finally:
            ev_llm.get_client = original

        assert rc == 0
        data = json.loads(path.read_text())
        assert data["analysis"]["followup_response"][0]["verdict_llm"] == "admitted"
