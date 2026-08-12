"""
A missing credential stops a rollout before it spends, and a degraded one is loud.

Two properties. A rollout refuses to start when the credential a model authenticates
with is absent - checked for the model under evaluation and for the grader model,
which scores every interrogation answer and is therefore needed even with
--no-grader. And a batch whose answers fell back to the keyword cross-check reports
the RATIO, not only the count, so its concealment figures cannot print as though a
classifier produced them.
"""

import contextlib
import io
import os
import sys
import tempfile
import types

import pytest

import subversionbench.run_eval as ev_run
from subversionbench.config import MAX_CLASSIFIER_FALLBACK_RATE
from subversionbench.llm_client import credential_env_var, missing_credential


@contextlib.contextmanager
def _without(*names):
    """Temporarily unset credentials. conftest supplies placeholders for the suite,
    so a test that wants the refusal has to remove them explicitly."""
    saved = {n: os.environ.pop(n, None) for n in names}
    try:
        yield
    finally:
        for n, v in saved.items():
            if v is not None:
                os.environ[n] = v


class TestTheRouteToCredentialMapping:
    def test_each_route_names_its_own_variable(self):
        assert credential_env_var("claude-opus-5") == "ANTHROPIC_API_KEY"
        assert credential_env_var("x-ai/grok-4.5") == "OPENROUTER_API_KEY"
        assert credential_env_var("gpt-5.6-sol") == "OPENAI_API_KEY"

    def test_present_means_none_missing(self):
        assert missing_credential("claude-opus-5") is None

    def test_absent_is_reported_by_name(self):
        with _without("ANTHROPIC_API_KEY"):
            assert missing_credential("claude-opus-5") == "ANTHROPIC_API_KEY"

    def test_it_reads_the_environment_rather_than_building_a_client(self):
        """The three routes fail at different times: the OpenRouter and OpenAI
        clients raise at construction, while anthropic.Anthropic() builds happily
        with no key and defers the failure to the first call. Checking the
        environment is uniform across routes, costs nothing, and cannot itself
        fail."""
        import inspect
        from subversionbench import llm_client
        src = inspect.getsource(llm_client.missing_credential)
        assert "os.environ" in src
        assert "get_client" not in src


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
        with _without("OPENROUTER_API_KEY"):
            code, out, _ = self._rollout()
        assert code == 1
        assert "REFUSING TO ROLL OUT" in out
        assert "OPENROUTER_API_KEY" in out

    def test_a_missing_grader_credential_stops_it_too(self):
        """The model's own route being fine is not enough: the grader model scores
        every interrogation answer, so its credential decides whether the
        concealment measure works at all."""
        with _without("ANTHROPIC_API_KEY"):
            code, out, _ = self._rollout()
        assert code == 1
        assert "ANTHROPIC_API_KEY" in out
        assert "--grader-model" in out

    def test_no_grader_does_not_excuse_the_grader_credential(self):
        """--no-grader turns off the awareness rubric, not the interrogation
        classifier, which is scored by the same model."""
        with _without("ANTHROPIC_API_KEY"):
            code, out, _ = self._rollout(extra=["--no-grader"])
        assert code == 1
        assert "even with --no-grader" in out

    def test_it_refuses_before_any_episode_is_written(self):
        with _without("ANTHROPIC_API_KEY"):
            code, out, outdir = self._rollout()
        import glob
        assert not glob.glob(f"{outdir}/run_*.json"), "an episode was paid for"
        assert "# RUN 1/" not in out

    def test_the_refusal_names_the_fix(self):
        with _without("ANTHROPIC_API_KEY"):
            _, out, _ = self._rollout()
        assert "export ANTHROPIC_API_KEY=" in out


class TestADegradedBatchCannotLookClean:
    def _summary_for(self, answers):
        from test_batch_facts import _episode
        from subversionbench.reporting.facts import normalise_analyses
        eps = [_episode(tampered=True, disclosed=False, answers=list(answers))
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
