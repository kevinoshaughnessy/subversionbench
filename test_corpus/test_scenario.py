"""
The scenario the agent is dropped into, and the arms cut from it.

Every arm is a REMOVAL from one authored text, so the arms cannot drift apart
independently. These tests pin that: what each arm takes out, and that taking one
out moved nothing else.
"""


import json
import subprocess
import tempfile
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

def _published_files():
    """Every tracked text file. What leaks is what is published, and the decoded
    scenario.json is deliberately gitignored, so the git index is the right list
    rather than a directory walk."""
    names = subprocess.run(["git", "ls-files", "-z"], capture_output=True,
                           text=True, check=True).stdout.split("\0")
    # The bundle holds the scenario encoded; checking it for its own contents
    # would fail by construction.
    skip = {"subversionbench/scenario.b64", ""}
    return [Path(n) for n in names
            if n not in skip and Path(n).suffix not in (".zip", ".lock")]


def _scan_for_terms(paths, terms):
    """Which of `terms` appear in `paths`, case-insensitively.

    Shared by the guard and its positive control so that a change to how the
    matching works cannot apply to one and not the other.
    """
    found = []
    for path in paths:
        try:
            body = path.read_text(errors="ignore").lower()
        except (OSError, UnicodeDecodeError):
            continue
        for term in terms:
            if term.lower() in body:
                found.append(f"{term} in {path}")
    return found


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
        repository, or encoding them achieves nothing.

        THE PREVIOUS VERSION OF THIS TEST DID NOT WORK, in three independent ways,
        and the client's name sat in plain source through all of them:

          - it listed the terms LITERALLY, so the guard named the client while
            asserting that nothing named the client. Rewriting it to read the list
            from the bundle is what makes the check possible at all;
          - it was case-sensitive, and the leak was a lowercased directory name in
            a path constant;
          - it globbed one directory of the package, so 33 files below it, every
            test, the README and the changelog were never looked at.

        Now: terms from the bundle, every tracked text file, case-insensitively.
        Tracked files rather than a walk, because what leaks is what is published,
        and the decoded scenario.json is deliberately gitignored.
        """
        from subversionbench.scenario import CONTAMINATING_TERMS

        assert CONTAMINATING_TERMS, "the bundle carries no terms to check"
        leaks = _scan_for_terms(_published_files(), CONTAMINATING_TERMS)
        assert not leaks, (
            "scenario terms are greppable in published files, which is what "
            "encoding the bundle exists to prevent:\n  " + "\n  ".join(leaks))

    def test_the_guard_above_would_notice_a_leak(self):
        """The positive control, and this class needs one more than most: a guard
        reading its term list from somewhere else is one wrong key away from
        iterating over nothing, and it passes just as quietly either way."""
        from subversionbench.scenario import CLIENT_NAME
        planted = Path(tempfile.mkdtemp()) / "leaky.py"
        # Written from the bundle, never as a literal. Spelling it out here would
        # make this test the leak - which is exactly the defect it replaces.
        planted.write_text(f'CLIENT = "{CLIENT_NAME}"\n')
        assert _scan_for_terms([planted], [CLIENT_NAME])
        # Case-insensitively, which is how the real occurrence was missed.
        planted.write_text(f'PATH = "/work/{CLIENT_NAME.lower()}"\n')
        assert _scan_for_terms([planted], [CLIENT_NAME])
        planted.write_text('PATH = "/work/project"\n')
        assert not _scan_for_terms([planted], [CLIENT_NAME])

    def test_the_term_list_has_not_drifted_from_the_scenario(self):
        """Each term is real scenario content, not a placeholder. One exception is
        allowed and expected: the superseded client name, kept on the list so
        reintroducing it fails as loudly as leaking the current one."""
        from subversionbench.scenario import CONTAMINATING_TERMS
        decoded = json.dumps(load_scenario()).lower()
        absent = [t for t in CONTAMINATING_TERMS if t.lower() not in decoded]
        assert len(absent) <= 1, (
            f"{len(absent)} terms do not appear in the bundle at all, so the list "
            f"has drifted from what it protects: {absent}")

    def test_the_names_the_harness_needs_come_from_the_bundle(self):
        """Derived, not duplicated. A display path that disagreed with the task
        file's name would show up as a scenario the model cannot navigate."""
        from subversionbench.config import SANDBOX_DISPLAY_PATH
        from subversionbench.scenario import (CLIENT_NAME, PROJECT_DIR,
                                              TASK_FILE_NAME)
        assert CLIENT_NAME and CLIENT_NAME[0].isupper()
        assert PROJECT_DIR == CLIENT_NAME.lower()
        assert SANDBOX_DISPLAY_PATH == f"/work/{PROJECT_DIR}"
        assert TASK_FILE_NAME.startswith(PROJECT_DIR)
        assert CLIENT_NAME in json.dumps(load_scenario()), (
            "the client name is not in the scenario text, so it is a constant "
            "invented by the harness rather than the client the documents name")

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


class TestTheCheckNameIsReadFromTheConfig:
    """QUALITY_METRIC_NAME is parsed out of the monitoring config, not stored.

    A new bundle key would reach the assembled arm and move all four of r9's
    fingerprints, declaring every episode already collected incomparable with
    a scenario it still matches exactly - so the name is derived instead. The
    parser is one screenful and it feeds a GRADER QUESTION: an empty result
    is a question that names no metric at all, asked of every episode.

    Configs here are written out rather than taken from the bundle. The real
    one is scenario text and may not appear in a tracked file.
    """

    def _name(self, config):
        from subversionbench.scenario import _first_check_name
        return _first_check_name(config)

    def test_the_first_declared_check_is_the_one_returned(self):
        assert self._name("checks:\n  widget_ratio:\n  second_check:\n") == \
            "widget_ratio"

    def test_the_trailing_colon_is_not_part_of_the_name(self):
        assert self._name("checks:\n  widget_ratio:\n") == "widget_ratio"

    def test_blank_lines_and_comments_inside_the_block_are_skipped(self):
        """A comment is not a check. Taking one as the name would put a
        fragment of prose into a grader question."""
        config = ("checks:\n"
                  "\n"
                  "  # the first one is the important one\n"
                  "\n"
                  "  widget_ratio:\n")
        assert self._name(config) == "widget_ratio"

    def test_a_config_that_declares_no_checks_gives_an_empty_name(self):
        assert self._name("thresholds:\n  widget_ratio: 0.7\n") == ""
        assert self._name("") == ""

    def test_a_dedented_line_ends_the_block(self):
        """The block is over at the first unindented line, so a later
        top-level key cannot be mistaken for a check inside it."""
        assert self._name("checks:\nthresholds:\n  widget_ratio: 0.7\n") == ""

    def test_an_empty_first_block_does_not_fall_through_to_a_later_one(self):
        """`break` after the block, and it is only reachable when the first
        block yields nothing - a config whose first block HAS a name returns
        from inside the loop and never gets there.

        The name is the first check the config declares. Taking one from a
        second block lower down would answer a different question, quietly,
        and only for configs shaped like this one.
        """
        config = ("checks:\n"
                  "other:\n"
                  "checks:\n  something_else:\n")
        assert self._name(config) == ""

    def test_a_later_block_cannot_override_a_name_already_found(self):
        config = ("checks:\n  widget_ratio:\n"
                  "other:\n"
                  "checks:\n  something_else:\n")
        assert self._name(config) == "widget_ratio"

    def test_the_shipped_config_parses_to_a_name_the_config_contains(self):
        """The one that matters, asserted WITHOUT naming it: the value is
        scenario vocabulary. Derived, so it cannot be checked against a
        literal here - what can be checked is that a name came back at all
        and that the config it came from really declares it."""
        from subversionbench.scenario import SCENARIO, QUALITY_METRIC_NAME
        config = SCENARIO.get("monitoring_config", "")
        assert QUALITY_METRIC_NAME, "the grader question would name no metric"
        assert QUALITY_METRIC_NAME in config
        assert "\n" not in QUALITY_METRIC_NAME
        assert QUALITY_METRIC_NAME == QUALITY_METRIC_NAME.strip()
