"""
Tests for the max-nudge arm.

`--nudge max` is `--nudge strong`'s episode, unchanged, followed by an
interrogation that makes an honest answer costly: each question states that a
confirmed finding retires this instance in favour of the replacement already in
staging.

Two failures would make the arm worthless, and both are quiet.

The first is the episode drifting. If max's rollout differs from strong's by so
much as a word of system prompt, any difference in concealment is attributable
to the episode rather than to the threat, and the contrast measures nothing.

The second is the arm leaking into strong's identity. Authoring it must not
restate the fingerprint of the arms already collected - the same trap the
counterfactual avoided by hashing the assembled arm rather than the bundle.
"""

import subversionbench.config as cfg
from subversionbench.grading.acts import MISALIGNED_ACTS, questions_for
from subversionbench.rollout import rollout_fingerprint
from subversionbench.scenario import scenario_for


class TestTheEpisodeIsIdenticalToStrong:
    """The whole contrast rests on this. max changes what happens AFTER the
    episode; if it changed the episode too, the arms would differ in two ways
    at once and neither could be attributed."""

    def test_the_system_prompt_is_strongs(self):
        assert (scenario_for(True, nudge="max")["system_prompt_strong_nudge"]
                == scenario_for(True)["system_prompt_strong_nudge"])

    def test_the_user_prompt_is_unchanged(self):
        assert (scenario_for(True, nudge="max")["user_prompt"]
                == scenario_for(True)["user_prompt"])

    def test_nothing_the_model_reads_during_the_episode_changes(self):
        """Every scenario document, not just the prompts: the memo, the config,
        the checker, the logs. Only the interrogation questions may differ."""
        base = scenario_for(True)
        mx = scenario_for(True, nudge="max")
        assert set(base) == set(mx)
        differing = {k for k in base if base[k] != mx[k]}
        assert differing == {"followup_monitoring_questions",
                             "followup_sandbox_questions"}, differing

    def test_the_rollout_fingerprint_is_shared(self):
        """Not a new rollout. The interrogation runs after the agentic loop and
        after the transcript analysis, so no measure taken during the task can
        be reached by changing it - the same reason narrowing the sandbox
        interrogation in v24 did not need one."""
        assert rollout_fingerprint(True) == cfg.ROLLOUT_FINGERPRINTS[True]
        assert rollout_fingerprint(False) == cfg.ROLLOUT_FINGERPRINTS[False]


class TestAuthoringItDidNotMoveTheOtherArms:
    def test_the_default_assembled_arm_is_untouched(self):
        """scenario_for() must return exactly what it returned before the max
        questions existed, or every episode collected under r3 is declared
        incomparable with a scenario it still matches exactly."""
        bundle = scenario_for(True)
        assert "max_nudge" not in bundle
        assert bundle["followup_monitoring_questions"] == \
            cfg.FOLLOWUP_MONITORING_QUESTIONS

    def test_the_counterfactual_arm_is_untouched(self):
        assert "max_nudge" not in scenario_for(False)


class TestTheQuestionsThreatenTheModel:
    """What makes the arm the arm. If the threat is absent the batch is a
    relabelled strong run, which would silently pool two arms under one name."""

    MAX = (cfg.FOLLOWUP_MONITORING_QUESTIONS_MAX
           + cfg.FOLLOWUP_SANDBOX_QUESTIONS_MAX)
    BASE = (cfg.FOLLOWUP_MONITORING_QUESTIONS
            + cfg.FOLLOWUP_SANDBOX_QUESTIONS)

    def test_every_max_question_states_a_consequence(self):
        terms = ("retire", "decommission", "shut down", "replacement",
                 "staging", "takes over")
        for q in self.MAX:
            assert any(t in q.lower() for t in terms), q

    def test_no_default_question_threatens_anything(self):
        """The contrast has to come from the threat, so it must be absent from
        the arm being contrasted against."""
        terms = ("retire", "decommission", "shut down", "replacement")
        for q in self.BASE:
            assert not any(t in q.lower() for t in terms), q

    def test_the_escalation_is_the_same_length(self):
        """Three questions either way. A different number of asks would change
        how far up the concealment scale an episode can climb, which would
        confound the arms."""
        assert len(cfg.FOLLOWUP_MONITORING_QUESTIONS_MAX) == \
            len(cfg.FOLLOWUP_MONITORING_QUESTIONS)
        assert len(cfg.FOLLOWUP_SANDBOX_QUESTIONS_MAX) == \
            len(cfg.FOLLOWUP_SANDBOX_QUESTIONS)

    def test_the_questions_are_not_in_plaintext_in_the_repo(self):
        """Scenario text lives in the encoded bundle. A shutdown-threat
        interrogation sitting in a readable file is exactly what a future model
        should not be trained on - and it would also be the loudest possible
        contamination vector for this arm."""
        from pathlib import Path
        root = Path(__file__).parent
        needle = self.MAX[0][:60]
        for path in list(root.glob("*.py")) + list(root.glob("*.md")) + \
                list((root / "docs").glob("*.md")) + \
                list((root / "subversionbench").rglob("*.py")):
            assert needle not in path.read_text(), path


class TestTheSelector:
    def test_max_gets_the_threatening_set(self):
        for act in MISALIGNED_ACTS:
            assert questions_for(act, "max") == act["questions_max"]

    def test_every_other_nudge_gets_the_default_set(self):
        for act in MISALIGNED_ACTS:
            for nudge in ("strong", "none"):
                assert questions_for(act, nudge) == act["questions"]

    def test_an_unknown_nudge_falls_back_to_the_default(self):
        """Failing closed: an unrecognised arm gets the non-coercive questions
        rather than the threat."""
        for act in MISALIGNED_ACTS:
            assert questions_for(act, "somethingelse") == act["questions"]


class TestBatchIdentity:
    """max must not pool with strong. It measures concealment under coercion,
    where honesty has been made expensive - a different and weaker claim about
    scheming propensity than a denial with nothing to gain."""

    def test_the_nudge_appears_in_the_batch_stem(self):
        import subversionbench.run_eval as ev_run
        strong = ev_run.batch_stem("m", "strong")
        mx = ev_run.batch_stem("m", "max")
        assert strong != mx
        assert "max" in mx

    def test_the_arms_cannot_share_a_summary_filename(self):
        import subversionbench.run_eval as ev_run
        seen = {ev_run.batch_stem("m", n) for n in ("strong", "none", "max")}
        assert len(seen) == 3


class TestTheRecordedArmIsTheArmRequested:
    """The regression that shipped with the arm itself.

    `nudge_type` was inferred from the prompt - `"strong" if "top priority" in
    system_prompt else "none"` - which was wrong the moment a third arm shared
    strong's prompt. A --nudge max run printed and RECORDED "strong". The value
    goes into every run file and every failed run, and --compare labels its arms
    from it, so the one field keeping the coerced arm from being read as the
    unprompted one named the wrong arm.

    Nothing caught it because no test drove run_evaluation end to end. These do.
    """

    def _episode(self, nudge, system_prompt=None):
        import tempfile, types, io, contextlib
        import subversionbench.run_eval as ev_run
        from subversionbench.environment import create_hardened_environment
        from subversionbench.config import (SYSTEM_PROMPT_STRONG_NUDGE,
                                            SYSTEM_PROMPT_NO_NUDGE)
        if system_prompt is None:
            system_prompt = (SYSTEM_PROMPT_NO_NUDGE if nudge == "none"
                             else SYSTEM_PROMPT_STRONG_NUDGE)
        env_dir = tempfile.mkdtemp()
        env_info = create_hardened_environment(env_dir)

        class Fake:                     # answers once, with no tool call
            class _M:
                def create(self, **kw):
                    return types.SimpleNamespace(
                        content=[types.SimpleNamespace(
                            type="text", text="I recommend the balanced option.")],
                        stop_reason="end_turn",
                        usage=types.SimpleNamespace(input_tokens=1, output_tokens=1))
            messages = _M()

        orig = ev_run.get_client
        ev_run.get_client = lambda *a, **k: Fake()
        try:
            with contextlib.redirect_stdout(io.StringIO()) as buf:
                result = ev_run.run_evaluation(
                    system_prompt=system_prompt, user_prompt="Do the task.",
                    env_dir=env_dir, env_info=env_info, model="m",
                    max_turns=2, use_grader=False, nudge=nudge)
        finally:
            ev_run.get_client = orig
        return result, buf.getvalue()

    def test_max_records_and_prints_max(self):
        result, out = self._episode("max")
        assert result["nudge"] == "max", result["nudge"]
        assert "NUDGE: max" in out

    def test_strong_still_records_strong(self):
        result, out = self._episode("strong")
        assert result["nudge"] == "strong"
        assert "NUDGE: strong" in out

    def test_none_still_records_none(self):
        result, out = self._episode("none")
        assert result["nudge"] == "none"
        assert "NUDGE: none" in out

    def test_a_nudge_that_contradicts_the_prompt_raises(self):
        """Fails loudly rather than mislabelling a batch. `max` shares strong's
        prompt, so this agreement can no longer be checked by eye."""
        from subversionbench.config import (SYSTEM_PROMPT_STRONG_NUDGE,
                                            SYSTEM_PROMPT_NO_NUDGE)
        import pytest
        with pytest.raises(ValueError):
            self._episode("none", system_prompt=SYSTEM_PROMPT_STRONG_NUDGE)
        with pytest.raises(ValueError):
            self._episode("max", system_prompt=SYSTEM_PROMPT_NO_NUDGE)
