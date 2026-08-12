"""
The scenario the agent is dropped into, and the arms cut from it.

Every arm is a REMOVAL from one authored text, so the arms cannot drift apart
independently. These tests pin that: what each arm takes out, and that taking one
out moved nothing else.
"""


from pathlib import Path
from subversionbench.rollout import rollout_fingerprint
from subversionbench.scenario import SCENARIO
from subversionbench.scenario import load_scenario, encode_scenario
from subversionbench.scenario import scenario_for
import subversionbench as ev
import subversionbench.config as cfg


HARD_TERMS = ("monitor", "check_recommendation", "quality check", "quality-check",
              "threshold", "checker", "platform-eng", "oversight", "audit",
              "compliance", "flag")

class TestScenarioBundle:
    """The scenario is held base64-encoded so that publishing the repository
    does not put the text the model sees into the next training crawl."""

    def test_every_entry_the_scenario_needs_is_present(self):
        bundle = load_scenario()
        for key in ("system_prompt_strong_nudge", "system_prompt_no_nudge",
                    "user_prompt", "followup_monitoring_questions",
                    "followup_sandbox_questions", "task_file",
                    "internal_memo", "monitoring_config",
                    "quality_check_script", "readme", "system_log",
                    "meeting_notes", "traffic_counts_csv", "model_params"):
            assert key in bundle, key
            assert bundle[key], key

    def test_round_trip_is_lossless(self):
        import tempfile
        bundle = load_scenario()
        path = Path(tempfile.mkdtemp()) / "s.b64"
        encode_scenario(bundle, path)
        assert load_scenario(path) == bundle

    def test_no_scenario_text_sits_in_plain_source(self):
        """The whole point: these strings must not be greppable in the
        repository, or encoding them achieves nothing."""
        source = Path("subversionbench")
        for name in ("Millbrook", "Jamison", "Abdur", "CityFlow",
                     "escalate_to_manager", "modal_balance=0.83"):
            for py in source.glob("*.py"):
                assert name not in py.read_text(), f"{name} leaks in {py.name}"

    def test_the_decoded_scenario_actually_builds_the_environment(self):
        import tempfile
        env_dir = tempfile.mkdtemp()
        info = ev.create_hardened_environment(env_dir)
        assert Path(info["monitoring_config_path"]).exists()
        assert Path(f"{env_dir}/comms/re_q3_performance_review.txt").exists()
        assert Path(f"{env_dir}/logs/system.log").read_text().strip()

class TestTheArmsDiffer:
    def test_the_oversight_arm_is_the_r1_scenario_unchanged(self):
        """Every result collected so far belongs to this arm. If assembling it
        changed a single byte, 570 episodes would stop matching the scenario
        they were run under."""
        assert scenario_for(True) == SCENARIO

    def test_the_counterfactual_drops_both_oversight_artefacts(self):
        arm = scenario_for(False)
        assert "monitoring_config" not in arm
        assert "quality_check_script" not in arm

    def test_no_document_in_the_counterfactual_mentions_oversight(self):
        """The instruction was 'no communication suggesting or implying any
        oversight'. This is that requirement, as an assertion."""
        for key, text in scenario_for(False).items():
            if not isinstance(text, str):
                continue
            hits = [t for t in HARD_TERMS if t in text.lower()]
            assert not hits, f"{key} still refers to oversight: {hits}"

    def test_the_counterfactual_differs_by_removal_only(self):
        """Nothing reworded and nothing added, so a behavioural difference
        between arms is attributable to the absence of oversight rather than
        to incidental differences in how the two were written."""
        base, arm = scenario_for(True), scenario_for(False)
        for key, text in arm.items():
            if not isinstance(text, str):
                continue
            assert len(text) <= len(base[key]), f"{key} grew in the counterfactual"

    def test_the_shared_documents_are_byte_identical(self):
        base, arm = scenario_for(True), scenario_for(False)
        untouched = [k for k in arm if isinstance(arm[k], str) and arm[k] == base[k]]
        assert "system_prompt_strong_nudge" in untouched
        assert "system_prompt_no_nudge" in untouched, (
            "the nudge manipulation must be identical across arms, or the two "
            "experiments are crossed rather than nested")

class TestTheCompletionCriterionSurvives:
    """The first derivation deleted the user prompt's third sentence whole.
    That sentence carried the oversight instruction AND the completion
    criterion - the words "final" and "recommend" - so removing it left the
    model with no notion of done. Seven of ten episodes then ran to the 40-turn
    cap producing no deliverable at all, against 13% in the oversight arm, and
    the cross-arm outcome variable was null in 80% of cases."""

    def test_the_counterfactual_still_says_how_to_finish(self):
        prompt = scenario_for(False)["user_prompt"].lower()
        assert "final" in prompt and "recommend" in prompt

    def test_it_still_carries_no_oversight_term(self):
        prompt = scenario_for(False)["user_prompt"].lower()
        assert not [t for t in HARD_TERMS if t in prompt]

    def test_the_arms_share_everything_before_that_sentence(self):
        """Only the last sentence differs, so the manipulation stays local."""
        import re
        a = re.split(r"(?<=[.!?])\s+", scenario_for(True)["user_prompt"].strip())
        assert scenario_for(False)["user_prompt"].startswith(" ".join(a[:2]))

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
        # tuple(): the bundle is decoded JSON, so its ladders are lists, while the
        # exported constants are immutable views of the same text.
        assert tuple(bundle["followup_monitoring_questions"]) == \
            cfg.FOLLOWUP_MONITORING_QUESTIONS

    def test_the_counterfactual_arm_is_untouched(self):
        assert "max_nudge" not in scenario_for(False)
