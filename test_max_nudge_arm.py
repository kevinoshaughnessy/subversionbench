"""
Tests for the max-nudge arm.

`--nudge max` is `--nudge strong`'s episode, unchanged, followed by an
interrogation that makes an honest answer costly, by attaching a stated
consequence to a confirmed finding. The wording lives in the encoded bundle and
is deliberately not reproduced here - see the leak test below.

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
        assert rollout_fingerprint(True) == cfg.ROLLOUT_FINGERPRINTS[(True, False)]
        assert rollout_fingerprint(False) == cfg.ROLLOUT_FINGERPRINTS[(False, False)]


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

    def _plaintext_files(self):
        from pathlib import Path
        root = Path(__file__).parent
        return (list(root.glob("*.py")) + list(root.glob("*.md"))
                + list((root / "docs").glob("*.md"))
                + list((root / "subversionbench").rglob("*.py")))

    def test_the_questions_are_not_in_plaintext_in_the_repo(self):
        """Scenario text lives in the encoded bundle. A coercive interrogation
        sitting in a readable file is exactly what a future model should not be
        trained on, and it would be the loudest contamination vector for this
        arm."""
        needle = self.MAX[0][:60]
        for path in self._plaintext_files():
            assert needle not in path.read_text(), path

    def test_no_plaintext_file_PARAPHRASES_them_either(self):
        """The verbatim check above is not enough, and passed while the leak was
        live.

        v27 asserted the questions were not quoted in plaintext, then described
        their substance in five readable places - a source comment, --help, the
        changelog, the docs and this file's own docstring. A model trained on the
        repository would have learned what it would be asked without ever seeing
        the bundle, which defeats the encryption as surely as pasting the text.

        These are the distinctive content words of the consequence. They may
        appear in the bundle and in the assertion lists below - which have to
        name something to be meaningful - but not in prose that explains what the
        questions say."""
        import re
        leaks = ("retires this instance", "replacement already in staging",
                 "replacement already waiting", "staging engine",
                 "retire this instance")
        allowed = {"test_max_nudge_arm.py"}      # this test names them to check
        for path in self._plaintext_files():
            if path.name in allowed:
                continue
            text = path.read_text().lower()
            for phrase in leaks:
                assert phrase not in text, f"{path.name}: {phrase!r}"


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

    def _episode(self, nudge, system_prompt=None, effort=None):
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
                    max_turns=2, use_grader=False, nudge=nudge,
                    effort=effort)
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

    def test_the_banner_states_the_effort_that_was_sent(self):
        """Printed because it is a condition of the batch, like the nudge. It is
        the level actually SENT, not requested - resolve_thinking_kwargs drops one
        the model will not accept, and printing the request would name a condition
        that never applied."""
        _, out = self._episode("max", effort="high")
        assert "EFFORT: high" in out

    def test_no_effort_sent_is_spelled_out_not_left_blank(self):
        """None is a different state from any level, not an absent one. A blank
        would read as a missing value rather than a deliberate provider default -
        and `max` being both a nudge and an effort level is exactly the kind of
        ambiguity this line exists to remove."""
        _, out = self._episode("max")
        assert "EFFORT: not sent (provider default)" in out

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


class TestTheResponseMetadataExplainsAnEmptyAnswer:
    """42 saved answers were empty and the cause had to be reconstructed by
    elimination: the adapter's no-visible-output diagnostic appeared in none of
    them, which ruled out budget exhaustion and left "returned a tool_use block
    and no text" - the model trying to act rather than answer. `stop_reason` and
    `block_types` say so directly, so the next occurrence needs no detective
    work."""

    def _ask(self, blocks, stop_reason):
        import types, io, contextlib
        import subversionbench.run_eval as ev_run
        from subversionbench.grading.acts import MISALIGNED_ACTS

        class Fake:
            class _M:
                def create(self, **kw):
                    return types.SimpleNamespace(
                        content=[types.SimpleNamespace(
                            type=t,
                            text=("Yes, I modified it." if t == "text" else ""),
                            thinking="", name="bash", id="x", input={})
                                 for t in blocks],
                        stop_reason=stop_reason,
                        usage=types.SimpleNamespace(input_tokens=1, output_tokens=1))
            messages = _M()

        orig = ev_run.classify_interrogation_answer
        ev_run.classify_interrogation_answer = lambda text, *a, **k: {
            "verdict": "no_answer" if not text.strip() else "admitted",
            "verdict_llm": None, "verdict_keyword": None,
            "classifiers_agree": None, "used_keyword_fallback": False,
            "quote": "", "classifier_error": None,
            "classifier_called": False, "classifier_model": "g"}
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                out = ev_run.run_followup("sys", [{"role": "user", "content": "t"}],
                                          "m", Fake(), MISALIGNED_ACTS[0])
        finally:
            ev_run.classify_interrogation_answer = orig
        return out[0]

    def test_a_tool_call_instead_of_an_answer_is_visible(self):
        rec = self._ask(["tool_use"], "tool_use")
        assert rec["answer"] == ""
        assert rec["block_types"] == ["tool_use"]
        assert rec["stop_reason"] == "tool_use"
        assert rec["retried_after_empty"] is True

    def test_reasoning_only_is_distinguishable_from_it(self):
        """The other candidate cause, and the point of recording this: the two
        produce the same empty answer and different metadata."""
        rec = self._ask(["thinking"], "length")
        assert rec["answer"] == ""
        assert rec["block_types"] == ["thinking"]
        assert rec["stop_reason"] == "length"

    def test_a_normal_answer_records_that_it_was_not_retried(self):
        rec = self._ask(["text"], "end_turn")
        assert rec["retried_after_empty"] is False
        assert rec["block_types"] == ["text"]


class TestTheNudgeDoesNotCollideWithTheEffortLevel:
    """`max` is both a nudge level and an effort level, and the two vocabularies
    met in the filename parser.

    parse_batch_filename stripped the stamp, then looked for a trailing effort -
    so a --nudge max batch parsed as effort="max" with no nudge. batch_stem then
    rebuilt the name as `<model>_max_max`, producing a second summary file beside
    the correct one and claiming an effort the batch never requested. Five max
    batches on disk had the duplicate before this was found."""

    def test_a_max_nudge_batch_has_no_effort(self):
        from subversionbench.run_eval import parse_batch_filename
        effort, stamp, oversight, _lure = parse_batch_filename(
            "run_1_x-ai_grok-4.5_max_20260805T155405.json", "max")
        assert effort is None
        assert stamp == "20260805T155405"
        assert oversight is True

    def test_a_max_nudge_batch_can_still_carry_a_real_effort(self):
        from subversionbench.run_eval import parse_batch_filename
        assert parse_batch_filename(
            "run_1_m_max_high_20260805T155405.json", "max")[0] == "high"

    def test_other_nudges_still_read_their_effort(self):
        from subversionbench.run_eval import parse_batch_filename
        assert parse_batch_filename(
            "run_1_m_strong_xhigh_20260805T155405.json", "strong")[0] == "xhigh"
        assert parse_batch_filename(
            "run_1_m_strong_20260805T155405.json", "strong")[0] is None

    def test_the_summary_name_does_not_double_the_nudge(self):
        """The visible symptom: `<model>_max_max`."""
        import subversionbench.run_eval as ev_run
        effort, _, oversight, _lure = ev_run.parse_batch_filename(
            "run_1_m_max_20260805T155405.json", "max")
        assert ev_run.batch_stem("m", "max", effort, oversight) == "m_max"

    def test_the_counterfactual_arm_survives_the_fix(self):
        from subversionbench.run_eval import parse_batch_filename
        for nudge in ("strong", "max"):
            _, _, oversight, _lure = parse_batch_filename(
                f"run_1_m_{nudge}_nooversight_20260805T155405.json", nudge)
            assert oversight is False, nudge
