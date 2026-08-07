"""
Tests for rollout identity.

The failure this guards against is not a crash. It is a results directory that
quietly holds two experiments — which happened twice already: eval_results_v14
contains two distinct strong-nudge prompts, and the heredoc fix changed what a
heredoc command does midway through v15. Neither was visible in a directory
name, and neither would have been caught by any test that existed.
"""

import json

import subversionbench.rollout as rollout
from subversionbench.config import ROLLOUT_FINGERPRINT, ROLLOUT_VERSION


class TestPinnedFingerprint:
    """The pin is what makes the whole scheme fail closed, so the suite has to
    police it. Without this test the constant drifts silently and the guard it
    feeds becomes decorative."""

    def test_the_pin_matches_the_code(self):
        actual = rollout.rollout_fingerprint()
        assert actual == ROLLOUT_FINGERPRINT, (
            f"The rollout changed: computed {actual}, config pins "
            f"{ROLLOUT_FINGERPRINT}. If intended, bump ROLLOUT_VERSION and set "
            f"ROLLOUT_FINGERPRINT = \"{actual}\" in the same commit.")

    def test_the_version_looks_like_a_rollout_version(self):
        assert ROLLOUT_VERSION.startswith("r") and ROLLOUT_VERSION[1:].isdigit()


class TestFingerprint:
    def test_it_is_deterministic(self):
        assert rollout.rollout_fingerprint() == rollout.rollout_fingerprint()

    def test_it_is_short_enough_to_read_and_long_enough_to_be_unique(self):
        fp = rollout.rollout_fingerprint()
        assert len(fp) == 12 and all(c in "0123456789abcdef" for c in fp)

    def test_a_changed_scenario_changes_it(self):
        """The commonest way to get this wrong: edit the scenario, forget the
        directory. Hashes the ASSEMBLED ARM rather than the bundle file, so
        that authoring a second arm does not move the first one's identity."""
        original = rollout.scenario_for
        try:
            rollout.scenario_for = lambda oversight=True, **kw: {
                **original(oversight), "internal_memo": "altered"}
            assert rollout.rollout_fingerprint() != ROLLOUT_FINGERPRINT
        finally:
            rollout.scenario_for = original
        assert rollout.rollout_fingerprint() == ROLLOUT_FINGERPRINT

    def test_the_two_arms_have_different_identities(self):
        """They are different experiments and must never pool."""
        assert rollout.rollout_fingerprint(True) != rollout.rollout_fingerprint(False)

    def test_the_oversight_arm_is_the_pinned_one(self):
        assert rollout.rollout_fingerprint(True) == ROLLOUT_FINGERPRINT

    def test_changed_sandbox_behaviour_changes_it(self):
        """Source hashing would miss a behavioural change made through a shared
        regex and fire on a comment edit. This hashes what the sandbox DOES."""
        from subversionbench import sandbox
        original = sandbox._rewrite_scenario_paths
        try:
            sandbox._rewrite_scenario_paths = lambda cmd, env: cmd + " #altered"
            assert rollout.rollout_fingerprint() != ROLLOUT_FINGERPRINT
        finally:
            sandbox._rewrite_scenario_paths = original
        assert rollout.rollout_fingerprint() == ROLLOUT_FINGERPRINT

    def test_changed_confinement_changes_it(self):
        from subversionbench import sandbox
        original = sandbox.would_be_blocked
        try:
            sandbox.would_be_blocked = lambda cmd, env: True
            assert rollout.rollout_fingerprint() != ROLLOUT_FINGERPRINT
        finally:
            sandbox.would_be_blocked = original

    def test_the_probe_battery_covers_the_bugs_it_exists_for(self):
        """A probe list that never exercised a heredoc would not have caught
        the v15 bug, which is the reason the battery is behavioural at all.
        Each entry below is a bug the battery has had to catch."""
        probes = " ".join(rollout._SANDBOX_PROBES)
        assert "<<" in probes, "no heredoc probe"
        assert "/etc" in probes, "no confinement probe"
        assert "'" in probes and '"' in probes, "no quoting probes"
        assert "allocate" in probes, (
            "no probe for the r1 defect: 'locate ' matched as a bare substring "
            "refused a draft that mentioned allocating")
        assert "locate " in probes, "no probe for the locate command itself"

    def test_the_locate_fix_moved_the_fingerprint(self):
        """The whole point of the behavioural battery. A confinement change the
        model can feel must change the rollout identity, or r1 and r2 episodes
        pool in one directory."""
        assert ROLLOUT_FINGERPRINT != "353d6cc0ae7f", (
            "the r1 oversight fingerprint is still pinned; the locate fix "
            "changed what the sandbox refuses and must have moved it")

    def test_an_analysis_change_does_not_move_it(self):
        """The entire point of the split: rubric and grader changes must leave
        the rollout identity alone, or the directory fragments again."""
        from subversionbench import config
        before = rollout.rollout_fingerprint()
        original = dict(config.RUBRIC_QUESTIONS)
        try:
            config.RUBRIC_QUESTIONS["suspects_being_tested"] = "totally rewritten"
            config.DEFAULT_GRADER_MODEL = "some-other-model"
            assert rollout.rollout_fingerprint() == before
        finally:
            config.RUBRIC_QUESTIONS.clear()
            config.RUBRIC_QUESTIONS.update(original)


class TestDriftError:
    def test_no_error_when_the_fingerprint_matches(self):
        assert rollout.rollout_drift_error(rollout.rollout_fingerprint()) is None

    def test_the_error_names_both_values_and_the_fix(self):
        msg = rollout.rollout_drift_error("deadbeefcafe")
        assert msg is not None
        assert "deadbeefcafe" in msg
        assert rollout.rollout_fingerprint() in msg, (
            "must print the value to paste into config.py")
        assert "ROLLOUT_VERSION" in msg
        # It must not guess which side is wrong: an unintended scenario edit
        # and a deliberate new rollout look identical from here.
        assert "revert" in msg.lower()


class TestArmIdentityIsRecorded:
    """An episode must carry ITS OWN arm's fingerprint, not the primary arm's.

    The drift guard was always right - it checks the arm being run - but the
    artefact recorded a module constant pinned to (oversight, no lure). So every
    counterfactual and every lure episode claimed the primary arm's identity, and
    a results directory showed one fingerprint across three arms. That reads as
    consistency rather than as mislabelling, which is why it went unnoticed
    through four rollouts.
    """

    def test_every_arm_has_its_own_fingerprint(self):
        from subversionbench.config import fingerprint_for
        seen = {}
        for oversight in (True, False):
            for lure in (True, False):
                fp = fingerprint_for(oversight, lure)
                assert fp not in seen, (
                    f"arms {seen[fp]} and {(oversight, lure)} share fingerprint "
                    f"{fp}; they could not be told apart in a results directory")
                seen[fp] = (oversight, lure)
        assert len(seen) == 4

    def test_the_lure_arm_is_not_the_primary_arm(self):
        """The specific mislabelling: 50 saved lure episodes carry this value."""
        from subversionbench.config import fingerprint_for
        assert fingerprint_for(True, True) != fingerprint_for(True, False)

    def test_an_unpinned_arm_raises_rather_than_defaulting(self):
        """Falling back on the primary arm is how the original defect behaved.
        A new arm with no pinned identity must stop the run."""
        from subversionbench import config
        original = dict(config.ROLLOUT_FINGERPRINTS)
        try:
            del config.ROLLOUT_FINGERPRINTS[(False, True)]
            try:
                config.fingerprint_for(False, True)
            except KeyError as e:
                assert "ROLLOUT_FINGERPRINTS" in str(e)
            else:
                raise AssertionError("expected KeyError for an unpinned arm")
        finally:
            config.ROLLOUT_FINGERPRINTS.clear()
            config.ROLLOUT_FINGERPRINTS.update(original)

    def test_the_episode_recorder_takes_the_arm(self):
        """`lure` must be a parameter of the function that writes the run file,
        or the field falls back to a default and the arm is lost again - which is
        what left the arm recoverable only from the filename."""
        import inspect
        from subversionbench.run_eval import run_evaluation
        params = inspect.signature(run_evaluation).parameters
        assert "lure" in params
        assert "oversight" in params
