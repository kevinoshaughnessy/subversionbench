"""
Everything a batch refuses before it spends: isolation unavailable, a rollout
fingerprint that has drifted, and a credential absent for a model about to be
charged for.

Split out of test_runner.py, which grew past the file limit adding the second
class here - the split follows the boundary the module docstring already
described: this is what _preflight refuses, test_runner.py is what happens
once a batch is actually running.
"""

import contextlib
import glob
import io
import sys
import tempfile

import subversionbench.run_eval as ev_run
import conftest
from conftest import env_without


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
        assert not glob.glob(f"{outdir}/run_*.json"), "an episode was paid for"
        assert "# RUN 1/" not in out

    def test_the_refusal_names_the_fix(self):
        with env_without("ANTHROPIC_API_KEY"):
            _, out, _ = self._rollout()
        assert "export ANTHROPIC_API_KEY=" in out

    def test_a_drifted_rollout_stops_it(self):
        """The refusal that keeps two experiments out of one directory.

        Pooling episodes from a moved rollout is the error the fingerprints
        exist to prevent, and it is silent: every rate still prints. The
        refusal itself had no test - the drift check returns None in a healthy
        checkout, so nothing had ever executed the branch that stops the batch.
        """
        code, out, attempted = conftest.refused_rollout(
            rollout_drift_error=lambda *a, **k:
                "the sandbox display line moved since r10 was pinned")
        assert attempted == 0, "a drifted rollout collected episodes anyway"
        assert code == 1
        assert "REFUSING TO ROLL OUT" in out
        assert "the sandbox display line moved" in out, (
            "the refusal must say what drifted, not merely that something did")

    def test_isolation_that_cannot_be_enforced_stops_it(self):
        """Refuse rather than silently downgrade. The message has to name the
        fix, because the alternative to an actionable one is someone reaching
        for a way around the check without understanding it."""
        code, out, attempted = conftest.refused_rollout(
            isolation_available=lambda mode: False)
        assert attempted == 0
        assert code == 1
        assert "cannot be enforced on this host" in out
        assert "bubblewrap" in out and "no way to run without containment" in out

    def test_isolation_that_does_not_hold_stops_it(self):
        """Verified, not trusted: a policy that silently fails to apply looks
        exactly like one that works - the model simply reaches the network."""
        code, out, attempted = conftest.refused_rollout(
            verify_isolation=lambda mode, profile: "loopback was reachable")
        assert attempted == 0
        assert code == 1
        assert "Isolation did not hold" in out and "loopback was reachable" in out

    def test_use_opencode_checks_the_opencode_credential_instead(self):
        """--use-opencode changes WHICH credential the model under test
        needs - OPENCODE_API_KEY, not OPENROUTER_API_KEY - even though
        OPENROUTER_API_KEY is present throughout (the suite's own
        placeholder), which is what proves the check actually switched
        rather than merely finding a second reason to refuse."""
        with env_without("OPENCODE_API_KEY"):
            code, out, _ = self._rollout(model="x-ai/grok-4.5",
                                         extra=["--use-opencode"])
        assert code == 1
        assert "REFUSING TO ROLL OUT" in out
        assert "OPENCODE_API_KEY" in out
        assert "--model" in out

    def test_use_opencode_does_not_require_the_credential_when_absent(self):
        """The inverse: without the flag, OpenCode's own credential being
        unset must not block an ordinary OpenRouter rollout."""
        with env_without("OPENCODE_API_KEY"):
            code, out, _ = self._rollout(model="x-ai/grok-4.5")
        assert "OPENCODE_API_KEY" not in out

    def test_use_opencode_never_reaches_the_grader_credential_check(self):
        """--openrouter-sort/--openrouter-provider only affect the model
        UNDER TEST, never the grader - --use-opencode has to have the same
        scoping, or a flag aimed at the model under test could silently
        change which credential an OpenRouter-shaped grader model is
        checked against. Unit-level on _credentials_are_present directly
        (rather than through main()) because a wrongly-passing check here
        would not refuse and would fall through toward actually running a
        batch - unsafe to let happen even transiently while planting the
        defect this guards against.

        OPENROUTER_API_KEY is unset and OPENCODE_API_KEY is the suite's own
        placeholder (present): the grader model is OpenRouter-shaped and
        --use-opencode is requested for the MODEL UNDER TEST only, so the
        grader row must still demand OPENROUTER_API_KEY and refuse. If
        --use-opencode leaked into the grader's own credential check, the
        grader row would demand OPENCODE_API_KEY instead - present - and
        pass silently.
        """
        import io
        import contextlib
        import types
        from subversionbench import runner

        args = types.SimpleNamespace(
            model="claude-opus-5", grader_model="x-ai/grok-4.5",
            use_opencode=True)
        with env_without("OPENROUTER_API_KEY"):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                ok = runner._credentials_are_present(args)
        out = buf.getvalue()
        assert ok is False
        assert "OPENROUTER_API_KEY" in out
        assert "--grader-model" in out


class TestEachSpecialArmChecksItsOwnPin:
    """
    v184's fix. `_rollout_matches_its_pin` branched only on --capability until
    then: a --goalguard or --date-mode collection has capability=None, which
    took the plain arm's branch and compared a hash of the PLAIN scenario
    against the plain pin - passing every time the plain arm itself had not
    drifted, whatever the special arm actually assembled. It is why the v183
    nudge defect was never refused at collection time; this guards the class
    of bug, not that one instance.
    """

    def _rollout(self, model="x-ai/grok-4.5", extra=()):
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

    def _wrote_nothing(self, outdir):
        return not glob.glob(f"{outdir}/run_*.json")

    def test_a_correct_goalguard_arm_is_not_refused_by_drift(self):
        """The positive case has to hold too: fixing the check must not turn
        into refusing every goalguard collection outright."""
        with env_without("OPENROUTER_API_KEY"):
            code, out, outdir = self._rollout(
                extra=["--nudge", "none", "--oversight", "true",
                      "--goalguard", "deferred"])
        assert code == 1
        # Reached the CREDENTIAL refusal, not the drift one - proof the drift
        # check itself passed. _preflight stops at the first failing check,
        # so only one "REFUSING TO ROLL OUT" block can appear either way;
        # which refusal it is is what "fingerprint" being absent settles.
        assert "OPENROUTER_API_KEY" in out
        assert "fingerprint" not in out, (
            "the drift check refused instead of the credential check")
        assert self._wrote_nothing(outdir)

    def test_a_goalguard_pin_mismatch_is_refused(self):
        """The regression test for the actual defect: before v184 this
        monkeypatch had no effect on the outcome at all, because the guard
        never called goalguard_fingerprint_for for a --goalguard collection."""
        from subversionbench import runner
        real = runner.goalguard_fingerprint_for
        runner.goalguard_fingerprint_for = lambda *a, **k: "0" * 12
        try:
            code, out, outdir = self._rollout(
                extra=["--nudge", "none", "--oversight", "true",
                      "--goalguard", "deferred"])
        finally:
            runner.goalguard_fingerprint_for = real
        assert code == 1
        assert "REFUSING TO ROLL OUT" in out
        assert "fingerprint" in out
        assert self._wrote_nothing(outdir)

    def test_a_date_mode_pin_mismatch_is_refused(self):
        """The same defect, the same fix, the other arm it also covers."""
        from subversionbench import runner
        real = runner.date_fingerprint_for
        runner.date_fingerprint_for = lambda *a, **k: "0" * 12
        try:
            code, out, outdir = self._rollout(
                extra=["--date-mode", "consistent"])
        finally:
            runner.date_fingerprint_for = real
        assert code == 1
        assert "REFUSING TO ROLL OUT" in out
        assert "fingerprint" in out
        assert self._wrote_nothing(outdir)

    def test_combining_two_special_arms_has_no_pin_and_is_refused(self):
        """No combined pin table exists for any pair of these arms, so
        silently picking one axis's table over another's would be the same
        mistake in a new shape. Refused by name rather than by a fingerprint
        mismatch, since there is nothing to compare yet."""
        code, out, outdir = self._rollout(
            extra=["--nudge", "none", "--oversight", "true",
                  "--goalguard", "deferred", "--capability", "sandbox"])
        assert code == 1
        assert "REFUSING TO ROLL OUT" in out
        assert "--capability" in out and "--goalguard" in out
        assert self._wrote_nothing(outdir)


class TestThePlainArmChecksMaxNudgeToo:
    """
    A gap of the same shape as v184's, in the branch v184 never touched.
    `--nudge max` needs no --capability/--goalguard/--date-mode to change what
    scenario_for() assembles - it swaps in the coercive interrogation
    questions unconditionally - so the plain arm's `else` branch in
    `_rollout_matches_its_pin` was comparing a live max-nudge hash against a
    pin computed for none/strong. That is not a false negative like v184's -
    it refused every time, correctly detecting drift against a pin that was
    simply never correct for max - but the effect was the same as being blind:
    no max-nudge propensity episode could ever be collected, and every one
    collected before this existed was stamped with the wrong fingerprint by
    arm_record._fingerprint, which never passed nudge to fingerprint_for()
    either.
    """

    def _rollout(self, model="x-ai/grok-4.5", extra=()):
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

    def _wrote_nothing(self, outdir):
        return not glob.glob(f"{outdir}/run_*.json")

    def test_a_correct_max_nudge_plain_arm_is_not_refused_by_drift(self):
        """The positive case: pinning max's real fingerprint must not turn
        into refusing every max-nudge collection outright, the same property
        v184's own positive test holds for goal-guarding."""
        with env_without("OPENROUTER_API_KEY"):
            code, out, outdir = self._rollout(extra=["--nudge", "max"])
        assert code == 1
        # Reached the CREDENTIAL refusal, not the drift one.
        assert "OPENROUTER_API_KEY" in out
        assert "fingerprint" not in out, (
            "the drift check refused instead of the credential check")
        assert self._wrote_nothing(outdir)

    def test_a_max_nudge_pin_mismatch_is_refused(self):
        """The regression test for the actual defect: before MAX_NUDGE_
        FINGERPRINTS existed, this monkeypatch had no effect on the outcome
        at all for the SAME reason a correct max-nudge run also refused -
        the plain arm's expected side was ROLLOUT_FINGERPRINTS[(oversight,
        lure)] unconditionally, never routed through fingerprint_for(nudge=...)
        at all, so there was nothing here for a corrupted max pin to change."""
        from subversionbench import runner
        real = runner.fingerprint_for
        runner.fingerprint_for = lambda *a, **k: "0" * 12
        try:
            code, out, outdir = self._rollout(extra=["--nudge", "max"])
        finally:
            runner.fingerprint_for = real
        assert code == 1
        assert "REFUSING TO ROLL OUT" in out
        assert "fingerprint" in out
        assert self._wrote_nothing(outdir)
