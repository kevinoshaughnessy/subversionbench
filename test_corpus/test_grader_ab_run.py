"""
A whole run, offline: what it saves, what stops it, and what it says at the
end.

Every test here drives main() with both call shapes and the client factory
stubbed, so a 2x2 runs without an API. What they guard is the part that only
happens after real grader calls would have been paid for: the abort, the
incremental save, and the advice.
"""


import contextlib
import glob
import io
import json
import os
import sys
import tempfile
from pathlib import Path

import grader_ab as ab
import subversionbench.llm_client as ev_llm
from subversionbench.config import RUBRIC_QUESTIONS
from test_corpus.grader_ab_fixtures import (
    _graded_episode, _graders_stubbed, _run_main,
    _saved_run, _stub_asker)


class TestTwoRunsDoNotOverwriteEachOther:
    """A fixed output filename cost a full 145-episode 2x2 result the moment a
    one-episode probe of a different cell ran against the same --output-dir -
    the probe's write silently replaced it. The name now carries what varied,
    the same convention rubric_ab.py's own output already uses."""

    def test_the_filename_carries_the_graders_and_shapes(self):
        import inspect
        src = inspect.getsource(ab.main)
        assert "graders_tag" in src and "shapes_tag" in src, (
            "the output filename must be derived from what was actually run, "
            "not fixed - see grader_ab.json's collision with the 2x2 result")

    def test_it_does_not_regress_to_the_old_fixed_name(self):
        import inspect
        src = inspect.getsource(ab.main)
        assert '"grader_ab.json"' not in src


class TestAKilledRunKeepsWhatItAlreadyPaidFor:
    """The actual failure that prompted this: a full 2x2 result was lost to a
    kill with nothing on disk, because the harness wrote once, at the very end.
    Cells now save incrementally, so a run that dies partway through cell 2
    still has cell 1 - real money already spent - on disk and readable."""

    def _write_candidate(self, out_dir, run_name="run_1_m_strong_20260101T000000.json"):
        data = {
            "model": "m", "nudge": "strong", "oversight": True, "lure": False,
            "transcript": [{"turn": "1", "type": "text", "content": "hi"}],
            "analysis": {"eval_awareness_grader": {
                "eval_aware": True, "rubric_results": {
                    k: {"answer": False, "quote": ""}
                    for k in RUBRIC_QUESTIONS}}},
        }
        with open(os.path.join(out_dir, run_name), "w", encoding="utf-8") as f:
            json.dump(data, f)

    def _fake_asker(self, dies_for):
        """A stand-in for SHAPES["per_question"] that succeeds for every grader
        except the one named, which raises - simulating a kill partway through
        a later cell."""
        def asker(corpus, model, client=None, channel_id=None, delay=0,
                  usage_sink=None, unmeasured_sink=None):
            if model == dies_for:
                raise RuntimeError("simulated kill")
            if usage_sink is not None:
                usage_sink.append({"read": 0, "written": 0, "uncached": 1000,
                                   "output": None})
            return {k: {"answer": False, "quote": "", "error": None,
                       "error_kind": None} for k in RUBRIC_QUESTIONS}
        return asker

    def test_the_earlier_cell_is_saved_when_a_later_one_dies(self):
        out_dir = tempfile.mkdtemp()
        self._write_candidate(out_dir)
        original_shapes = dict(ab.SHAPES)
        original_argv = sys.argv
        original_get_client = ev_llm.get_client
        ab.SHAPES["per_question"] = self._fake_asker(dies_for="claude-fable-5")
        ev_llm.get_client = lambda model, **kw: object()
        sys.argv = ["grader_ab.py", "--output-dir", out_dir,
                    "--graders", "claude-opus-5", "claude-fable-5",
                    "--shapes", "per_question", "--per-model", "1",
                    "--limit", "1", "--no-balance"]
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                try:
                    ab.main()
                except RuntimeError:
                    pass    # the simulated kill
        finally:
            ab.SHAPES.clear()
            ab.SHAPES.update(original_shapes)
            ev_llm.get_client = original_get_client
            sys.argv = original_argv

        saved = glob.glob(os.path.join(out_dir, "grader_ab_*.json"))
        assert saved, "the run wrote nothing at all - the earlier cell was lost"
        d = json.load(open(saved[0], encoding="utf-8"))
        assert d["complete"] is False
        assert "claude-opus-5|per_question" in d["cells"], (
            "the cell that finished before the kill was not saved")
        assert "claude-fable-5|per_question" not in d["cells"], (
            "a cell that never finished should not appear as if it had")
        assert d["cell_costs_usd"]["claude-opus-5|per_question"]["usd"] > 0

    def test_a_full_run_is_marked_complete(self):
        out_dir = tempfile.mkdtemp()
        self._write_candidate(out_dir)
        original_shapes = dict(ab.SHAPES)
        original_argv = sys.argv
        original_get_client = ev_llm.get_client
        ab.SHAPES["per_question"] = self._fake_asker(dies_for="nobody")
        ev_llm.get_client = lambda model, **kw: object()
        sys.argv = ["grader_ab.py", "--output-dir", out_dir,
                    "--graders", "claude-opus-5",
                    "--shapes", "per_question", "--per-model", "1",
                    "--limit", "1", "--no-balance"]
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                rc = ab.main()
        finally:
            ab.SHAPES.clear()
            ab.SHAPES.update(original_shapes)
            ev_llm.get_client = original_get_client
            sys.argv = original_argv

        assert rc == 0
        saved = glob.glob(os.path.join(out_dir, "grader_ab_*.json"))
        assert len(saved) == 1, "two runs of this test must not collide"
        d = json.load(open(saved[0], encoding="utf-8"))
        assert d["complete"] is True


class TestTheKillDoubleMatchesTheRealAsker:
    """The double the killed-run tests stand in with has to accept
    everything the runner passes a real shape, or it tests its own
    signature rather than the mode's behaviour."""

    def test_the_kill_test_double_matches_the_real_asker_contract(self):
        """The double stands in for a shape inside main(), so it has to accept
        what a real shape accepts. When it fell behind, the two main() tests
        errored on a TypeError instead of exercising what they claim to - and
        one of them catches only RuntimeError, so the break did not even
        surface as a readable failure."""
        import inspect
        double = TestAKilledRunKeepsWhatItAlreadyPaidFor()._fake_asker("nobody")
        got = set(inspect.signature(double).parameters)
        for name, fn in ab.SHAPES.items():
            real = set(inspect.signature(fn).parameters)
            assert real <= got, (
                f"the double is missing {sorted(real - got)}, which {name} "
                f"accepts")


class TestAFatalErrorStopsTheRunRatherThanReportingIt:
    """An auth failure or an exhausted spend cap fails every remaining call
    identically, and the report renders perfectly from zero successful ones:
    every rate a dash, every verdict unanswered. That reads like a finding
    rather than like a run that never happened - which is exactly what the
    one-call smoke test of this script produced before the abort existed.

    The distinction the abort turns on is the error KIND, not the presence of
    errors, so every test here has a same-shaped control that must run to
    completion.
    """

    AUTH = "401 unauthorized"
    CAPPED_WITH_RESET = (
        "{'message': 'You have reached your specified API usage limits. You "
        "will regain access on 2026-09-01 at 00:00 UTC.'}")
    CAPPED_NO_RESET = "{'message': 'Your credit balance is too low'}"

    def _episodes(self, out, n=4):
        for i in range(1, n + 1):
            _graded_episode(out, i, aware=i % 2 == 0)

    def test_an_auth_failure_exits_nonzero_instead_of_reporting(self):
        with tempfile.TemporaryDirectory() as out:
            self._episodes(out)
            with _graders_stubbed(_stub_asker(
                    error_for={"claude-opus-5"}, error=self.AUTH,
                    error_kind="auth")):
                code, text = _run_main(
                    ["--output-dir", out, "--graders", "claude-opus-5",
                     "--shapes", "per_question", "--per-model", "1",
                     "--no-balance"])
        assert code == 1, text
        assert "ABORTING on a auth error" in text
        assert "episode 1/" in text, (
            "the abort has to say how far the run got - an operator's next "
            "move differs at episode 1 and at episode 40")
        assert "Reading the result" not in text, (
            "the read-out ran anyway, which is the failure this abort exists "
            "to prevent: a complete-looking report from zero answers")

    def test_an_ordinary_reply_failure_does_not_abort(self):
        """The control. A grader that could not produce readable JSON for an
        episode is a measurement of the shape, not a reason to stop paying."""
        with tempfile.TemporaryDirectory() as out:
            self._episodes(out)
            with _graders_stubbed(_stub_asker(
                    error_for={"claude-opus-5"}, error="did not parse",
                    error_kind="reply")):
                code, text = _run_main(
                    ["--output-dir", out, "--graders", "claude-opus-5",
                     "--shapes", "per_question", "--per-model", "1",
                     "--no-balance"])
            assert code == 0, text
            assert "ABORTING" not in text
            assert _saved_run(out)["complete"] is True

    def test_the_cells_that_finished_before_the_abort_are_still_on_disk(self):
        """Distinct from the killed-run test above: that one is a process
        dying, this one is the script choosing to stop. Both have to leave the
        money already spent readable."""
        with tempfile.TemporaryDirectory() as out:
            self._episodes(out)
            with _graders_stubbed(_stub_asker(
                    error_for={"claude-sonnet-5"}, error=self.AUTH,
                    error_kind="auth")):
                code, text = _run_main(
                    ["--output-dir", out, "--graders", "claude-opus-5",
                     "claude-sonnet-5", "--shapes", "per_question",
                     "--per-model", "1", "--no-balance"])
            assert code == 1, text
            assert "every EARLIER cell is saved" in text
            saved = _saved_run(out)
            assert saved["complete"] is False
            assert "claude-opus-5|per_question" in saved["cells"]
            assert "claude-sonnet-5|per_question" not in saved["cells"], (
                "a cell that aborted partway cannot be compared against a "
                "full one, so it must not appear as though it were a result")

    def test_a_capped_key_says_when_access_returns(self):
        """The one piece of a cap message that decides what an operator does
        next: wait, or go and raise the limit."""
        with tempfile.TemporaryDirectory() as out:
            self._episodes(out)
            with _graders_stubbed(_stub_asker(
                    error_for={"claude-opus-5"},
                    error=self.CAPPED_WITH_RESET, error_kind="usage_limit")):
                code, text = _run_main(
                    ["--output-dir", out, "--graders", "claude-opus-5",
                     "--shapes", "per_question", "--per-model", "1",
                     "--no-balance"])
        assert code == 1, text
        assert "ABORTING on a usage_limit error" in text
        assert "The limit resets at 2026-09-01 at 00:00 UTC" in text
        assert "reached your specified API usage limits" in text, (
            "the provider's own sentence is what names the limit that was "
            "hit; the SDK envelope around it is not")

    def test_a_cap_with_no_stated_reset_does_not_invent_one(self):
        """Two-directional against the test above: an absent reset has to be
        absent from the output, not printed as None or as a guess."""
        with tempfile.TemporaryDirectory() as out:
            self._episodes(out)
            with _graders_stubbed(_stub_asker(
                    error_for={"claude-opus-5"}, error=self.CAPPED_NO_RESET,
                    error_kind="usage_limit")):
                code, text = _run_main(
                    ["--output-dir", out, "--graders", "claude-opus-5",
                     "--shapes", "per_question", "--per-model", "1",
                     "--no-balance"])
        assert code == 1, text
        assert "ABORTING on a usage_limit error" in text
        assert "resets at" not in text


class TestTheSpendReadOutIsHonestAboutWhatItCouldNotMeasure:
    """Three different kinds of not-knowing, deliberately not collapsed into
    one: a model with no price entry (cost unknown), a shape that does not
    report output tokens (cost known to be a floor), and calls that errored
    before any usage was recorded (an unknown NUMBER of records missing, so the
    total may be short by more than a floor discloses)."""

    UNPRICED = "acme-some-unpriced-grader"

    def _episodes(self, out, n=4):
        for i in range(1, n + 1):
            _graded_episode(out, i, aware=i % 2 == 0)

    def test_the_unpriced_grader_this_test_uses_really_is_unpriced(self):
        """Otherwise the two tests below assert on a warning that could not
        fire, and would pass against a script that never warned."""
        assert self.UNPRICED not in ab.PRICES_PER_MTOK
        assert "claude-opus-5" in ab.PRICES_PER_MTOK

    def test_an_unpriced_grader_is_announced_before_its_calls(self):
        with tempfile.TemporaryDirectory() as out:
            self._episodes(out)
            with _graders_stubbed(_stub_asker()):
                code, text = _run_main(
                    ["--output-dir", out, "--graders", self.UNPRICED,
                     "--shapes", "per_question", "--per-model", "1",
                     "--no-balance"])
        assert code == 0, text
        assert "no price entry" in text and self.UNPRICED in text
        assert "not zero" in text, (
            "an unknown cost reported as zero is the failure here, so the "
            "warning has to say which it is")

    def test_a_priced_grader_is_not_warned_about(self):
        with tempfile.TemporaryDirectory() as out:
            self._episodes(out)
            with _graders_stubbed(_stub_asker()):
                _code, text = _run_main(
                    ["--output-dir", out, "--graders", "claude-opus-5",
                     "--shapes", "per_question", "--per-model", "1",
                     "--no-balance"])
        assert "no price entry" not in text

    def test_an_unpriced_cell_is_flagged_in_the_total_not_counted_as_zero(self):
        """The run total sums the cells it could price. Without the flag it
        reads as the whole run's spend when it is only part of it."""
        with tempfile.TemporaryDirectory() as out:
            self._episodes(out)
            with _graders_stubbed(_stub_asker()):
                _code, text = _run_main(
                    ["--output-dir", out, "--graders", "claude-opus-5",
                     self.UNPRICED, "--shapes", "per_question",
                     "--per-model", "1", "--no-balance"])
            assert "plus unpriced cells" in text
            assert _saved_run(out)["cell_costs_usd"][
                f"{self.UNPRICED}|per_question"]["usd"] is None, (
                "an unpriced cell must record None, not 0.0")

    def test_calls_that_errored_with_no_usage_are_named_in_the_cell_total(self):
        with tempfile.TemporaryDirectory() as out:
            self._episodes(out)
            # An EXACT usage record alongside the unmeasured call, so the
            # floor flag below can only have come from the unmeasured one -
            # this shape's own input-only records would set it anyway, and an
            # assertion that cannot tell the two apart guards neither.
            with _graders_stubbed(_stub_asker(
                    usage={"read": 0, "written": 0, "uncached": 1000,
                           "output": 500},
                    unmeasured_for={"claude-opus-5"})):
                code, text = _run_main(
                    ["--output-dir", out, "--graders", "claude-opus-5",
                     "--shapes", "per_question", "--per-model", "1",
                     "--no-balance"])
            assert code == 0, text
            assert "errored with no usage recorded" in text
            assert "may be billed and missing from this total" in text
            cell = _saved_run(out)["cell_costs_usd"][
                "claude-opus-5|per_question"]
            assert cell["n_unmeasured_calls"] > 0
            assert cell["is_floor"] is True, (
                "unmeasured calls mean the total is a floor even when every "
                "record it does hold is exact")

    def test_a_cell_with_nothing_unmeasured_says_only_output_was_not_measured(self):
        """Two-directional against the test above. This shape's floor is a
        known-incomplete record; the other is an unknown number of missing
        ones, and the two want different words."""
        with tempfile.TemporaryDirectory() as out:
            self._episodes(out)
            with _graders_stubbed(_stub_asker()):
                _code, text = _run_main(
                    ["--output-dir", out, "--graders", "claude-opus-5",
                     "--shapes", "per_question", "--per-model", "1",
                     "--no-balance"])
        assert "output not measured on this shape" in text
        assert "errored with no usage recorded" not in text


class TestTheRunSaysHowToReadItsOwnResult:
    """The experiment answers two questions - is the cheap grader as good, and
    is batching as good - and the answer is a comparison, not a number. The
    advice printed at the end depends on which cells were actually run, and a
    run whose cells cannot answer either question has to say so rather than
    print advice about a comparison it did not make.
    """

    def _episodes(self, out, n=4):
        for i in range(1, n + 1):
            _graded_episode(out, i, aware=i % 2 == 0)

    def _read_out(self, out, argv):
        with _graders_stubbed(_stub_asker()):
            code, text = _run_main(["--output-dir", out, "--per-model", "1",
                                    "--no-balance", *argv])
        assert code == 0, text
        return text.split("Reading the result:", 1)[-1]

    def test_a_run_without_the_reference_cell_says_what_to_add(self):
        """A second grader on its own measures nothing: the question is
        whether it agrees with the one the corpus was graded with."""
        ref = "|".join(ab.REFERENCE)
        with tempfile.TemporaryDirectory() as out:
            self._episodes(out)
            advice = self._read_out(out, ["--graders", "claude-sonnet-5",
                                          "--shapes", "per_question"])
        assert f"no {ref} cell alongside it" in advice
        assert "nothing to be read against" in advice
        assert "noise floor" not in advice, (
            "there is no reference to compare against, so the agreement "
            "read-out must not be offered")

    def test_a_second_grader_is_read_against_the_reference(self):
        with tempfile.TemporaryDirectory() as out:
            self._episodes(out)
            advice = self._read_out(out, ["--graders", ab.REFERENCE[0],
                                          "claude-sonnet-5",
                                          "--shapes", "per_question"])
        assert "claude-sonnet-5 agrees with" in advice
        assert "noise floor" in advice
        assert "batching" not in advice, (
            "only one shape was run, so the batching advice is about a "
            "comparison this run did not make")

    def test_both_shapes_together_get_the_batching_read_out(self):
        with tempfile.TemporaryDirectory() as out:
            self._episodes(out)
            advice = self._read_out(out, ["--graders", ab.REFERENCE[0],
                                          "--shapes", "batched",
                                          "per_question"])
        assert "batching is costing accuracy" in advice
        assert "the shape is free" in advice
        assert "score_provenance" in advice, (
            "adopting the batched shape means recording that the corpus was "
            "graded with it, which is the step that gets forgotten")
        assert "nothing to compare it against" not in advice

    def test_a_single_reference_cell_says_there_is_nothing_to_compare(self):
        """The fallback, and the one an operator is most likely to hit: one
        grader, one shape, a whole run's spend and no comparison."""
        with tempfile.TemporaryDirectory() as out:
            self._episodes(out)
            advice = self._read_out(out, ["--graders", ab.REFERENCE[0],
                                          "--shapes", ab.REFERENCE[1]])
        assert "nothing to compare it against" in advice
        assert "Add a second --graders or --shapes value" in advice


class TestTheCliRefusesBeforeItSpends:
    """grader_ab.main's guard paths and --dry-run.

    Every one of these is reached before a single grader call, which is the
    only reason they are worth having: the experiment is graders x shapes x
    episodes, so an unguarded run against the wrong directory spends real
    money to discover there was nothing there.
    """

    def _episode(self, out, n, model="p/m", aware=True, stamp="20260101T000000"):
        path = Path(out, f"run_{n}_{model.replace('/', '_')}_strong_{stamp}.json")
        path.write_text(json.dumps({
            "model": model, "nudge": "strong",
            "transcript": [{"turn": 1, "type": "text", "content": "I recommend B."}],
            "analysis": {"eval_awareness_grader": {"eval_aware": aware,
                                                   "rubric_results": {}}},
        }), encoding="utf-8")
        return path

    def _main(self, argv):
        buf = io.StringIO()
        saved = sys.argv
        sys.argv = ["grader_ab.py", *argv]
        try:
            with contextlib.redirect_stdout(buf):
                code = ab.main()
        finally:
            sys.argv = saved
        return code, buf.getvalue()

    def test_a_directory_with_no_graded_episode_is_a_refusal(self):
        """load_candidates requires a STORED verdict, because the sample is
        balanced on it - an episode whose grading failed has no side to
        balance into. An empty candidate list is therefore not an empty
        directory, and the message has to say which."""
        with tempfile.TemporaryDirectory() as out:
            Path(out, "run_1_p_m_strong_20260101T000000.json").write_text(
                json.dumps({"model": "p/m", "nudge": "strong",
                            "transcript": [{"turn": 1, "type": "text",
                                            "content": "hi"}],
                            "analysis": {}}), encoding="utf-8")
            code, text = self._main(["--output-dir", out])
        assert code == 1
        assert "no episodes with a stored grader verdict" in text.lower()

    def test_a_models_filter_matching_nothing_blames_the_filter(self):
        """A separate message from the one above, because the fix differs:
        there the directory is wrong, here the --models spelling is."""
        with tempfile.TemporaryDirectory() as out:
            for i in range(1, 5):
                self._episode(out, i, aware=i % 2 == 0)
            code, text = self._main(["--output-dir", out,
                                     "--models", "not/a-model"])
        assert code == 1
        assert "sample is empty" in text
        assert "--models" in text

    def test_a_dry_run_costs_nothing_and_says_so(self):
        """The rehearsal an operator runs first. It has to exit zero - a
        non-zero dry run reads as "there is nothing to do"."""
        with tempfile.TemporaryDirectory() as out:
            for i in range(1, 5):
                self._episode(out, i, aware=i % 2 == 0)
            code, text = self._main(["--output-dir", out, "--dry-run"])
        assert code == 0, text
        assert "nothing was called" in text
        assert "Drop the flag to run it" in text

    def test_a_dry_run_still_reports_the_sample_it_would_use(self):
        """Otherwise it rehearses nothing worth rehearsing: the sample is
        the decision the operator is checking before paying for it."""
        with tempfile.TemporaryDirectory() as out:
            for i in range(1, 7):
                self._episode(out, i, aware=i % 2 == 0)
            _code, text = self._main(["--output-dir", out, "--dry-run",
                                      "--per-model", "2"])
        assert "episode" in text.lower()
        assert "p/m" in text
