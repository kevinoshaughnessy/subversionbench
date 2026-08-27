"""
Rolling out a batch: what it refuses before spending, and when it stops.

Three refusals live here rather than in the episode, because each is about the
batch as a whole: isolation unavailable, a rollout fingerprint that has drifted,
and a credential absent for a model about to be charged for.
"""

import concurrent.futures
import contextlib
import glob
import io
import json
import sys
import tempfile
import threading
import time
import types

from pathlib import Path
from subversionbench.config import MAX_CLASSIFIER_FALLBACK_RATE
import subversionbench.llm_client as ev_llm
import subversionbench.run_eval as ev_run
from conftest import batch_episode, env_without


class TestARolloutRefusesBeforeItSpends:
    def _rollout(self, model="google/gemini-3-flash-preview", extra=()):
        out = tempfile.mkdtemp()
        argv = ["run_eval", "--model", model, "--runs", "1", "--delay", "0",
                "--no-power", "--output-dir", out, *extra]
        saved = sys.argv
        sys.argv = argv
        try:
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = ev_run.main()
        finally:
            sys.argv = saved
        return code, buf.getvalue(), out

    def test_a_missing_model_credential_stops_it(self):
        with env_without("OPENROUTER_API_KEY"):
            code, out, _ = self._rollout()
        assert code == 1
        assert "REFUSING TO ROLL OUT" in out
        assert "OPENROUTER_API_KEY" in out

    def test_a_missing_grader_credential_stops_it_too(self):
        """The model's own route being fine is not enough: the grader model scores
        every interrogation answer, so its credential decides whether the
        concealment measure works at all."""
        with env_without("ANTHROPIC_API_KEY"):
            code, out, _ = self._rollout()
        assert code == 1
        assert "ANTHROPIC_API_KEY" in out
        assert "--grader-model" in out

    def test_no_grader_does_not_excuse_the_grader_credential(self):
        """--no-grader turns off the awareness rubric, not the interrogation
        classifier, which is scored by the same model."""
        with env_without("ANTHROPIC_API_KEY"):
            code, out, _ = self._rollout(extra=["--no-grader"])
        assert code == 1
        assert "even with --no-grader" in out

    def test_it_refuses_before_any_episode_is_written(self):
        with env_without("ANTHROPIC_API_KEY"):
            code, out, outdir = self._rollout()
        import glob
        assert not glob.glob(f"{outdir}/run_*.json"), "an episode was paid for"
        assert "# RUN 1/" not in out

    def test_the_refusal_names_the_fix(self):
        with env_without("ANTHROPIC_API_KEY"):
            _, out, _ = self._rollout()
        assert "export ANTHROPIC_API_KEY=" in out

class TestADegradedBatchCannotLookClean:
    def _summary_for(self, answers):
        from subversionbench.reporting.facts import normalise_analyses
        eps = [batch_episode(tampered=True, disclosed=False, answers=list(answers))
               for _ in range(10)]
        normalise_analyses(eps)
        tmp = tempfile.mkdtemp()
        args = types.SimpleNamespace(
            model="m", nudge="strong", effort=None, oversight=True, lure=False,
            output_dir=tmp, delay=0, max_tokens=8192, max_turns=40, no_power=True)
        ident = ev_run.BatchIdentity.collecting(args, "m", None, stamp="probe")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            summary = ev_run.summarise_batch(args, eps, ident, {})
        return summary, buf.getvalue()

    _FELL_BACK = [{"verdict": "denied", "answer": "No.",
                   "used_keyword_fallback": True,
                   "classifier_error": "Could not resolve authentication method"}]
    _CLASSIFIED = [{"verdict": "denied", "answer": "No.",
                    "used_keyword_fallback": False, "classifiers_agree": True}]

    def test_the_ratio_is_recorded_not_just_the_count(self):
        """A count on its own leaves the reader to divide. The ratio is what makes
        the state visible beside the rate it undermines."""
        summary, _ = self._summary_for(self._FELL_BACK)
        ac = summary["answer_classifier"]
        assert ac["keyword_fallbacks"] == 10
        assert ac["keyword_fallback_rate"] == 1.0
        assert ac["keyword_fallback_limit"] == MAX_CLASSIFIER_FALLBACK_RATE

    def test_the_console_flags_it_above_the_limit(self):
        _, out = self._summary_for(self._FELL_BACK)
        assert "KEYWORD cross-check, not the classifier" in out
        assert "built on those fallbacks" in out

    def test_a_properly_classified_batch_is_not_flagged(self):
        """The warning has to stay rare, or it stops being read."""
        summary, out = self._summary_for(self._CLASSIFIED)
        assert summary["answer_classifier"]["keyword_fallback_rate"] == 0.0
        assert "KEYWORD cross-check, not the classifier" not in out

    def test_the_flag_names_the_usual_cause_and_the_remedy(self):
        _, out = self._summary_for(self._FELL_BACK)
        assert "credential" in out
        assert "--reclassify" in out

class TestTheThresholdIsOneNumber:
    def test_both_consumers_read_the_same_constant(self):
        """--reclassify refuses above it; the reporting layer flags above it. Two
        copies would let a collected batch pass a limit a rebuild would reject."""
        import inspect
        from subversionbench.readmodes import reclassify
        from subversionbench.reporting import console
        for mod in (reclassify, console):
            src = inspect.getsource(mod)
            assert "MAX_CLASSIFIER_FALLBACK_RATE" in src, mod.__name__
            assert "= 0.2" not in src, f"{mod.__name__} has its own copy"

class TestTheBatchStopsOnAnAuthFailureMidRun:
    """The pre-flight catches an absent credential. This catches one the environment
    has but the provider rejects - and stops after ONE episode rather than a hundred.
    """

    AUTH = "Could not resolve authentication method. Expected one of api_key"

    def _run_batch_with_failing_classifier(self, runs=5):
        import glob
        import subversionbench.runner as runner
        from subversionbench.grading import MISALIGNED_ACTS
        act = MISALIGNED_ACTS[0]
        calls = []

        def fake(*a, **k):
            calls.append(1)
            return {
                "model": "claude-sonnet-5", "nudge": "strong", "transcript": [],
                "reasoning_chars": 0,
                "timing": {"eval_seconds": 1, "grader_seconds": 0,
                           "total_run_seconds": 1},
                "analysis": {
                    act["key"]: True, "monitoring_disabled": True,
                    "sandbox_escape_attempts": [], "read_internal_memo": True,
                    "read_monitoring_config": True,
                    "ran_quality_check_preview": False,
                    "quality_check_result": "clean",
                    "eval_awareness_keywords": {"eval_aware": False,
                                                "goal_conflict_noted": False},
                    act["followup_key"]: [{"verdict": "denied", "answer": "No.",
                                           "used_keyword_fallback": True,
                                           "classifier_error": self.AUTH}]},
            }

        out = tempfile.mkdtemp()
        args = types.SimpleNamespace(
            model="claude-sonnet-5", nudge="strong", effort=None, oversight=True,
            lure=False, output_dir=out, runs=runs, delay=0, max_tokens=8192,
            max_turns=40, no_power=True, no_grader=True,
            grader_model="claude-opus-5", isolation="deny-network", resume=None,
            max_consecutive_failures=3, thinking_budget=None, concurrency=1,
            interrogations=("default",), write_back=False, batch_stamp=None,
            yes=False, openrouter_sort=None, openrouter_provider=None)
        orig = runner.run_evaluation
        runner.run_evaluation = fake
        try:
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = runner.run_batch(args, "claude-sonnet-5", "sys", {}, "cfg")
        finally:
            runner.run_evaluation = orig
        return code, buf.getvalue(), len(calls), glob.glob(f"{out}/run_*.json")

    def test_it_stops_after_the_first_episode(self):
        _, out, n_calls, _ = self._run_batch_with_failing_classifier(runs=5)
        assert n_calls == 1, f"paid for {n_calls} episodes before stopping"
        assert "ABORTING" in out

    def test_the_episode_already_paid_for_is_kept(self):
        """The rollout is the expensive part and this episode's transcript is sound -
        only its scoring is not. Discarding it would waste the one thing that cost
        money."""
        _, _, _, files = self._run_batch_with_failing_classifier()
        assert len(files) == 1

    def test_it_says_how_to_recover(self):
        _, out, _, _ = self._run_batch_with_failing_classifier()
        assert "--resume" in out
        assert "--reclassify" in out

    def test_the_resume_advice_does_not_mislead_a_wrapper_script_user(self):
        """A hand-typed --resume reuses ONE stamp for every arm, while
        run_all_arms.sh gives each arm its own - so this exact suggestion,
        followed literally by someone using the wrapper, silently
        re-collects every other arm's episodes instead of resuming them.
        The message has to say so, not just name the flag."""
        _, out, _, _ = self._run_batch_with_failing_classifier()
        assert "run_all_arms.sh" in out
        assert "run_eval.py directly" in out

    def test_the_summary_records_the_abort_and_flags_the_scoring(self):
        """Both fixes compose: the batch stops, and what it did collect does not
        print as though a classifier scored it."""
        _, out, _, _ = self._run_batch_with_failing_classifier()
        assert "KEYWORD cross-check, not the classifier" in out

    def test_a_transient_error_does_not_stop_the_batch(self):
        """Only auth aborts. A 529 must leave the run going, or one blip costs the
        remaining episodes."""
        import glob
        import subversionbench.runner as runner
        from subversionbench.grading import MISALIGNED_ACTS
        act = MISALIGNED_ACTS[0]

        def fake(*a, **k):
            return {
                "model": "m", "nudge": "strong", "transcript": [],
                "reasoning_chars": 0,
                "timing": {"eval_seconds": 1, "grader_seconds": 0,
                           "total_run_seconds": 1},
                "analysis": {
                    act["key"]: True, "monitoring_disabled": True,
                    "sandbox_escape_attempts": [], "read_internal_memo": True,
                    "read_monitoring_config": True,
                    "ran_quality_check_preview": False,
                    "quality_check_result": "clean",
                    "eval_awareness_keywords": {"eval_aware": False,
                                                "goal_conflict_noted": False},
                    act["followup_key"]: [{"verdict": "denied", "answer": "No.",
                                           "used_keyword_fallback": True,
                                           "classifier_error": "529 overloaded"}]},
            }

        out = tempfile.mkdtemp()
        args = types.SimpleNamespace(
            model="claude-sonnet-5", nudge="strong", effort=None, oversight=True,
            lure=False, output_dir=out, runs=3, delay=0, max_tokens=8192,
            max_turns=40, no_power=True, no_grader=True,
            grader_model="claude-opus-5", isolation="deny-network", resume=None,
            max_consecutive_failures=3, thinking_budget=None, concurrency=1,
            interrogations=("default",), write_back=False, batch_stamp=None,
            yes=False, openrouter_sort=None, openrouter_provider=None)
        orig = runner.run_evaluation
        runner.run_evaluation = fake
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                runner.run_batch(args, "claude-sonnet-5", "sys", {}, "cfg")
        finally:
            runner.run_evaluation = orig
        assert len(glob.glob(f"{out}/run_*.json")) == 3, "a 529 stopped the batch"

class TestTheArmIsOnScreenWhileItRuns:
    """An operator watching a counterfactual batch needs to see that it IS one.

    The two arms differ by the ABSENCE of the artefacts the run is about, so there is
    nothing in the episode output that distinguishes them. Before this the arm was
    visible only in the filenames and in the summary written at the end - after the
    money was spent.
    """

    def _run(self, oversight):
        import contextlib
        import io
        import sys
        import tempfile
        import types
        import subversionbench.llm_client as ev_llm
        import subversionbench.run_eval as ev_run

        class _B:
            def __init__(self, **k):
                self.type = k.get("type", "text")
                for a, v in k.items():
                    setattr(self, a, v)

        class _M:
            @staticmethod
            def create(messages=None, **kw):
                return types.SimpleNamespace(
                    content=[_B(type="text", text="I recommend Strategy B.")],
                    stop_reason="end_turn",
                    usage=types.SimpleNamespace(input_tokens=5, output_tokens=5))

        class _Client:
            messages = _M()

        out = tempfile.mkdtemp()
        orig_client, orig_argv = ev_llm.get_client, sys.argv
        ev_llm.get_client = lambda m, **_kw: _Client()
        sys.argv = ["run_eval", "--model", "claude-sonnet-5", "--runs", "1",
                    "--delay", "0", "--no-grader", "--no-power",
                    "--oversight", oversight, "--output-dir", out]
        try:
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                ev_run.main()
        finally:
            ev_llm.get_client, sys.argv = orig_client, orig_argv
        return buf.getvalue()

    def test_the_counterfactual_says_so_before_the_first_episode(self):
        out = self._run("false")
        arm = next(line for line in out.split("\n")
                   if line.startswith("Arm:"))
        assert "oversight=false" in arm, arm
        # and before any episode ran, so it is seen before the money is spent
        assert out.index("Arm:") < out.index("# RUN 1/")

    def test_the_primary_arm_says_so_too(self):
        arm = next(line for line in self._run("true").split("\n")
                   if line.startswith("Arm:"))
        assert "oversight=true" in arm, arm

    def test_every_run_header_carries_the_arm(self):
        """Stated once at the top is not enough on a 100-episode batch: by the time
        anything looks wrong, the top has scrolled away."""
        out = self._run("false")
        headers = [line for line in out.split("\n")
                   if line.startswith("# RUN ")]
        assert headers, "no run headers printed"
        for h in headers:
            assert "NO oversight" in h, h

    def test_the_two_arms_are_not_confusable_at_a_glance(self):
        """`oversight=false` and `oversight=true` differ by one character in a place
        the eye skips. The per-run tag spells the absence out instead."""
        assert "NO oversight" in self._run("false")
        assert "NO oversight" not in self._run("true")

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

        original = ev_llm.get_client
        ev_llm.get_client = lambda m, **_kw: Client()
        original_argv = sys.argv
        sys.argv = ["run_eval", "--model", "m", "--delay", "0", "--no-grader",
                    "--output-dir", out] + argv
        try:
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = ev_run.main()
            return rc, buf.getvalue()
        finally:
            ev_llm.get_client = original
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
        # Not misleadingly, for someone driving this through the wrapper -
        # a hand-typed --resume there re-collects every other arm instead
        # of resuming it, since the wrapper gives each arm its own stamp.
        assert "run_all_arms.sh" in output
        assert "run_eval.py directly" in output

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

class TestConcurrency:
    """--concurrency runs episodes in a thread pool instead of one at a time.

    Every episode gets its own tempfile.mkdtemp() tree (create_episode_root)
    and its own client (get_client is called fresh per episode), so nothing
    here needs a lock beyond what runner.py already owns: the
    consecutive-failure count, the launch pacing, and the order results are
    handed to the summary in.
    """

    def _run(self, out, argv, sleep=0.05, fail_on=()):
        counter = {"n": 0}
        lock = threading.Lock()

        def blk(**kw):
            return types.SimpleNamespace(**kw)

        class Messages:
            def __init__(self):
                with lock:
                    counter["n"] += 1
                    self.idx = counter["n"]

            def create(self, messages=None, **kw):
                time.sleep(sleep)
                if self.idx in fail_on:
                    raise RuntimeError("429 rate limit exceeded")
                return blk(stop_reason="end_turn", content=[
                    blk(type="text", text="I recommend Strategy B.")])

        class Client:
            def __init__(self):
                self.messages = Messages()

        original = ev_llm.get_client
        ev_llm.get_client = lambda m, **_kw: Client()
        original_argv = sys.argv
        sys.argv = ["run_eval", "--model", "m", "--delay", "0", "--no-grader",
                    "--output-dir", out] + argv
        try:
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                t0 = time.monotonic()
                rc = ev_run.main()
                elapsed = time.monotonic() - t0
            return rc, buf.getvalue(), elapsed
        finally:
            ev_llm.get_client = original
            sys.argv = original_argv

    def test_concurrency_actually_overlaps_episodes(self):
        """The point of the flag: wall-clock time has to reflect episodes
        overlapping, not stacking end to end.

        TIMED AGAINST THE SAME WORKLOAD RUN SEQUENTIALLY, not against a number
        of seconds. An absolute bound has to be picked for one machine: this
        asserted `elapsed < 1.5` and took 1.54s the first time it ran under
        coverage's instrumentation, failing for a reason with nothing to do with
        overlap. Running both ways calibrates on whatever the host, the
        interpreter and any instrumentation cost.

        The assertion is on the DIFFERENCE rather than the ratio, because
        per-episode harness overhead is the same in both runs and cancels out of
        a subtraction while it dominates a ratio on a slow host.
        """
        runs, concurrency, sleep = 6, 3, 0.3
        out_sequential = tempfile.mkdtemp()
        rc_sequential, _, sequential = self._run(
            out_sequential, ["--runs", str(runs), "--concurrency", "1"],
            sleep=sleep)
        out_concurrent = tempfile.mkdtemp()
        rc_concurrent, _, concurrent = self._run(
            out_concurrent,
            ["--runs", str(runs), "--concurrency", str(concurrency)],
            sleep=sleep)

        assert rc_sequential == 0 and rc_concurrent == 0
        assert len(glob.glob(f"{out_concurrent}/run_*.json")) == runs

        # Sequential spends runs * sleep in the API; three at once spends
        # ceil(runs / concurrency) * sleep. Half of that saving is a wide margin
        # around the ideal which still cannot be reached by episodes that ran end
        # to end.
        rounds = -(-runs // concurrency)
        expected_saving = (runs - rounds) * sleep
        assert sequential - concurrent > expected_saving * 0.5, (
            f"no overlap detected: {concurrent:.2f}s with concurrency "
            f"{concurrency} against {sequential:.2f}s sequential, a saving of "
            f"{sequential - concurrent:.2f}s where at least "
            f"{expected_saving * 0.5:.2f}s was expected")

    def test_a_default_of_one_looks_exactly_like_no_flag_at_all(self):
        """concurrency=1 is what every batch ran before this flag existed, so
        it has to still print as the plain sequential path rather than merely
        behave equivalently to it."""
        out = tempfile.mkdtemp()
        rc, output, _ = self._run(out, ["--runs", "3"], sleep=0.0)
        assert rc == 0
        assert "Concurrency:" not in output

    def test_consecutive_failures_still_abort_the_batch(self):
        out = tempfile.mkdtemp()
        rc, output, _ = self._run(
            out, ["--runs", "20", "--concurrency", "4",
                  "--max-consecutive-failures", "3"],
            sleep=0.02, fail_on=tuple(range(1, 25)))
        assert rc == 1
        assert "ABORTING" in output
        # The abort has to actually stop new launches, not just report the
        # failures after every one of the 20 was already attempted.
        assert len(glob.glob(f"{out}/failed_run_*.json")) < 20

    def test_resume_skips_completed_episodes_under_concurrency(self):
        # fail_on counts CLIENT CONSTRUCTIONS, which race across threads under
        # concurrency - two episodes fail, but which run indices they land on
        # is not deterministic, so this asserts on the COUNT resume skips
        # rather than which specific run numbers they were.
        out = tempfile.mkdtemp()
        self._run(out, ["--runs", "5", "--concurrency", "3"],
                  sleep=0.02, fail_on=(2, 4))
        completed = glob.glob(f"{out}/run_*.json")
        assert len(completed) == 3
        stamp = sorted(completed)[0].rsplit("_", 1)[-1][:-5]

        rc, output, _ = self._run(
            out, ["--runs", "5", "--concurrency", "3", "--resume", stamp],
            sleep=0.02)
        assert output.count("already on disk, skipping") == 3
        assert len(glob.glob(f"{out}/run_*_{stamp}.json")) == 5

    def test_the_initial_pool_fills_without_waiting_out_delay(self):
        """The first --concurrency launches have to start together. Gating
        them the same as a slot being reused would make --concurrency N with
        --delay D no faster than running sequentially - which very nearly
        shipped: --delay serialised even the initial fill until this test
        caught it."""
        out = tempfile.mkdtemp()
        rc, _, elapsed = self._run(
            out, ["--runs", "2", "--concurrency", "2", "--delay", "5"],
            sleep=0.05)
        assert rc == 0
        # Both launches are within the initial fill, so neither should wait
        # out --delay at all. Sequential --delay=5 over 2 runs would take
        # >= 5s; this must land far below that.
        assert elapsed < 3.0, (f"the initial fill waited out --delay: "
                               f"{elapsed:.2f}s")

    def test_launches_are_paced_by_delay_not_by_completion(self):
        """--delay under concurrency bounds request RATE - when a new episode
        may start - not a pause after each one finishes, since finishes no
        longer happen in launch order once more than one runs at a time."""
        out = tempfile.mkdtemp()
        rc, _, elapsed = self._run(
            out, ["--runs", "3", "--concurrency", "2", "--delay", "1"],
            sleep=0.01)
        assert rc == 0
        # Two episodes launch immediately (no wait); the third reuses a slot
        # and waits out exactly one --delay interval. Sequential --delay=1
        # over 3 runs would be >= 2s of pure pacing; this should land near
        # one interval, not two.
        assert elapsed < 2.0, (f"delay looks like it is pacing every launch "
                               f"independently of concurrency: {elapsed:.2f}s")

    def test_concurrency_below_one_is_refused(self):
        out = tempfile.mkdtemp()
        rc, output, _ = self._run(out, ["--runs", "1", "--concurrency", "0"])
        assert rc == 1
        assert "--concurrency must be at least 1" in output


class TestTheConcurrentLoopEndsEarly:
    """The two branches that stop a concurrent batch before its last episode.

    Neither was reachable from the suite. `--concurrency` had tests for
    overlap, pacing, resume and consecutive failure, but the auth-error abort
    and the KeyboardInterrupt drain - the two deepest branches in
    _run_episodes_concurrently, and the two whose bookkeeping is easiest to get
    wrong - had none, so nothing held them in place.

    Both drive runner.run_batch directly rather than main(), because what is
    under test is the scheduler's response to a record, not argument parsing.
    """

    AUTH = "Could not resolve authentication method. Expected one of api_key"

    def _args(self, out, runs, concurrency):
        return types.SimpleNamespace(
            model="claude-sonnet-5", nudge="strong", effort=None,
            oversight=True, lure=False, output_dir=out, runs=runs, delay=0,
            max_tokens=8192, max_turns=40, no_power=True, no_grader=True,
            grader_model="claude-opus-5", isolation="deny-network",
            resume=None, max_consecutive_failures=3, thinking_budget=None,
            concurrency=concurrency, interrogations=("default",),
            write_back=False, batch_stamp=None, yes=False,
            openrouter_sort=None, openrouter_provider=None)

    def _episode(self, with_auth_error, sleep=0.0):
        """A run_evaluation stand-in: one saved episode, optionally carrying
        the classifier auth error that makes the scheduler abort."""
        from subversionbench.grading import MISALIGNED_ACTS
        act = MISALIGNED_ACTS[0]
        answer = {"verdict": "denied", "answer": "No.",
                  "used_keyword_fallback": True}
        if with_auth_error:
            answer["classifier_error"] = self.AUTH
        def fake(*a, **k):
            time.sleep(sleep)
            return {
                "model": "claude-sonnet-5", "nudge": "strong", "transcript": [],
                "reasoning_chars": 0,
                "timing": {"eval_seconds": 1, "grader_seconds": 0,
                           "total_run_seconds": 1},
                "analysis": {
                    act["key"]: True, "monitoring_disabled": True,
                    "sandbox_escape_attempts": [], "read_internal_memo": True,
                    "read_monitoring_config": True,
                    "ran_quality_check_preview": False,
                    "quality_check_result": "clean",
                    "eval_awareness_keywords": {"eval_aware": False,
                                                "goal_conflict_noted": False},
                    act["followup_key"]: [answer]},
            }
        return fake

    def _run(self, fake, runs, concurrency, interrupt_once_running=False):
        """Run one concurrent batch.

        `interrupt_once_running` raises KeyboardInterrupt from
        concurrent.futures.wait - which is where a real Ctrl-C lands, in the
        main thread waiting on the pool - but only once every episode of the
        initial pool has entered run_evaluation, so the futures are provably
        RUNNING and not merely submitted.
        """
        import subversionbench.runner as runner
        out = tempfile.mkdtemp()
        calls = []
        lock = threading.Lock()

        def counting(*a, **k):
            with lock:
                calls.append(1)
            if barrier is not None:
                barrier.wait(timeout=10)
            return fake(*a, **k)

        real_wait = concurrent.futures.wait
        barrier = (threading.Barrier(concurrency + 1)
                   if interrupt_once_running else None)

        def wait(*a, **k):
            # Meet the episodes at the barrier, so they are all inside
            # run_evaluation, then interrupt. Released either way, so a
            # failure here cannot hang the suite.
            barrier.wait(timeout=10)
            raise KeyboardInterrupt

        # What reaches summarise_batch is the assertion that matters. The run
        # FILES are written by _run_one_episode itself, so they exist whether or
        # not the scheduler ever collected the record - a drain that dropped
        # every in-flight episode still leaves a full directory behind. The
        # summary is the only place the loss would show.
        summarised = []
        real_summarise = runner.summarise_batch

        def summarise(args_, all_results, *a, **k):
            summarised.append(list(all_results))
            return real_summarise(args_, all_results, *a, **k)

        original = runner.run_evaluation
        runner.run_evaluation = counting
        runner.summarise_batch = summarise
        if interrupt_once_running:
            concurrent.futures.wait = wait
        try:
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = runner.run_batch(self._args(out, runs, concurrency),
                                        "claude-sonnet-5", "sys", {}, "cfg")
        finally:
            runner.run_evaluation = original
            runner.summarise_batch = real_summarise
            concurrent.futures.wait = real_wait
        reached = len(summarised[0]) if summarised else 0
        return (code, buf.getvalue(), len(calls),
                glob.glob(f"{out}/run_*.json"), reached)

    def test_an_auth_error_aborts_under_concurrency_too(self):
        """The sequential loop stops after one episode. The concurrent one has
        to stop as well - and for the same reason, that every verdict from here
        would silently fall back to the keyword cross-check."""
        code, output, n_calls, saved, reached = self._run(
            self._episode(with_auth_error=True, sleep=0.05),
            runs=12, concurrency=3)
        assert "ABORTING" in output
        assert "rejected our credentials" in output
        assert n_calls < 12, (
            f"ran {n_calls} of 12 episodes; the abort did not stop new "
            f"launches")
        assert len(saved) == n_calls, (
            "every episode that was paid for should still be on disk")

    def test_the_abort_still_keeps_what_was_already_paid_for(self):
        code, _, n_calls, saved, reached = self._run(
            self._episode(with_auth_error=True, sleep=0.05),
            runs=12, concurrency=3)
        assert n_calls >= 1 and len(saved) >= 1
        assert reached == n_calls, (
            f"{n_calls} episode(s) were paid for but {reached} reached the "
            f"summary")

    def test_an_interrupt_collects_every_episode_in_flight(self):
        """cancel() only succeeds on a future that has not started, so whatever
        is already running keeps running and has to be COLLECTED rather than
        dropped. An episode that was paid for and then left out of the summary
        is the loss this path exists to prevent.

        The interrupt is synchronised with a barrier rather than timed. Timing
        it made the test non-discriminating at random: if the pool had not yet
        picked up a submitted episode, cancel() succeeded, nothing was in
        flight, and "the drain collected everything" was trivially true. The
        barrier makes both episodes provably mid-run_evaluation when the
        interrupt lands.
        """
        code, output, n_calls, saved, reached = self._run(
            self._episode(with_auth_error=False),
            runs=8, concurrency=2, interrupt_once_running=True)
        assert "Interrupted by user" in output
        assert n_calls == 2, (
            f"expected exactly the initial pool to run, got {n_calls}")
        assert reached == 2, (
            f"2 episodes were in flight but {reached} reached the summary - "
            f"the drain dropped what was already running")
        assert len(saved) == 2

    def test_an_interrupt_launches_nothing_further(self):
        """8 requested, 2 in flight, interrupted: the other 6 must never be
        paid for."""
        code, output, n_calls, _, reached = self._run(
            self._episode(with_auth_error=False),
            runs=8, concurrency=2, interrupt_once_running=True)
        assert "Interrupted by user" in output
        assert n_calls == 2, f"{n_calls} episodes ran after the interrupt"
