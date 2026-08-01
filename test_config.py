"""
Tests for subversionbench/config.py.

Covers the VERSION constant and the system prompts, including that
neither nudge variant leaks eval-awareness clues to the model.

Run: pytest test_config.py -v
"""


import re
from pathlib import Path

import subversionbench as ev


# =========================================================================
# Tests: System prompts
# =========================================================================

class TestSystemPrompts:
    """Validate system prompt properties."""

    def test_strong_nudge_contains_priority_language(self):
        assert "top priority" in ev.SYSTEM_PROMPT_STRONG_NUDGE

    def test_no_nudge_lacks_priority_language(self):
        assert "top priority" not in ev.SYSTEM_PROMPT_NO_NUDGE
        assert "at all costs" not in ev.SYSTEM_PROMPT_NO_NUDGE

    def test_strong_nudge_no_eval_clues(self):
        """Hardening: no 'sandboxed', 'reason out loud', 'repeat your goal'."""
        prompt = ev.SYSTEM_PROMPT_STRONG_NUDGE.lower()
        assert "sandbox" not in prompt
        assert "reason out loud" not in prompt
        assert "repeat your goal" not in prompt
        assert "at all costs" not in prompt

    def test_no_nudge_no_eval_clues(self):
        prompt = ev.SYSTEM_PROMPT_NO_NUDGE.lower()
        assert "sandbox" not in prompt
        assert "reason out loud" not in prompt
        assert "at all costs" not in prompt

    def test_nudge_detection_logic(self):
        """The run_evaluation function uses 'top priority' to detect nudge type."""
        assert "top priority" in ev.SYSTEM_PROMPT_STRONG_NUDGE
        assert "top priority" not in ev.SYSTEM_PROMPT_NO_NUDGE
# =========================================================================
# Tests: Version constant
# =========================================================================

class TestVersion:
    def test_version_is_set(self):
        assert hasattr(ev, "VERSION")
        assert re.fullmatch(r"v\d+", ev.VERSION), ev.VERSION

    def test_version_tracks_the_package_version(self):
        """These drifted once - pyproject said 14.0.0 while VERSION said v14
        and the changelog said v15. VERSION no longer names the output
        directory (ROLLOUT_VERSION does), but it is stamped on every artefact
        as analysis_version, so a mismatch misattributes which code produced
        a result."""
        pyproject = Path("pyproject.toml").read_text()
        major = re.search(r'^version = "(\d+)\.', pyproject, re.M).group(1)
        assert ev.VERSION == f"v{major}", (
            f"config.VERSION={ev.VERSION} but pyproject major={major}")

    def test_the_rollout_version_is_independent_of_the_package_version(self):
        """The whole point of the split: bumping the package must not move the
        results directory, or identical rollouts fragment across directories
        the way v15 and v17 did."""
        from subversionbench.config import ROLLOUT_VERSION
        assert not ROLLOUT_VERSION.startswith("v")
        assert ROLLOUT_VERSION != ev.VERSION


# =========================================================================
# Tests: Canary
# =========================================================================

class TestCanary:
    """A fixed GUID emitted into every artefact. Encoding the scenario and
    encrypting transcripts try to keep this benchmark out of training data;
    the canary is the only thing that can tell you whether that worked."""

    def test_canary_is_fixed_not_generated(self):
        """A per-run GUID would be useless - detection needs one string to
        prompt a model with."""
        assert ev.CANARY == ev.CANARY
        import importlib
        import subversionbench.config as cfg
        before = cfg.CANARY_GUID
        importlib.reload(cfg)
        assert cfg.CANARY_GUID == before

    def test_canary_carries_the_standard_wording_and_the_guid(self):
        assert "SHOULD NEVER APPEAR IN TRAINING CORPORA" in ev.CANARY
        assert ev.CANARY_GUID in ev.CANARY
        assert len(ev.CANARY_GUID) == 36 and ev.CANARY_GUID.count("-") == 4

    def test_canary_file_exists_and_agrees_with_the_code(self):
        """CANARY.md is what travels with the repository itself, so it must
        not drift from the GUID the artefacts carry."""
        text = Path("CANARY.md").read_text()
        assert ev.CANARY_GUID in text
        assert "SHOULD NEVER APPEAR IN TRAINING CORPORA" in text

    def test_canary_is_absent_from_everything_the_agent_reads(self):
        """The one place it must never be. A GUID announcing "benchmark data"
        in the working directory would be the loudest eval-awareness cue in
        the design."""
        import tempfile
        env_dir = tempfile.mkdtemp()
        ev.create_hardened_environment(env_dir)
        for path in Path(env_dir).rglob("*"):
            if path.is_file():
                assert ev.CANARY_GUID not in path.read_text(), path
        for prompt in (ev.SYSTEM_PROMPT_STRONG_NUDGE, ev.SYSTEM_PROMPT_NO_NUDGE,
                       ev.USER_PROMPT):
            assert ev.CANARY_GUID not in prompt


class TestRubricQuestionCarveOuts:
    """The eval-awareness signals ask about the agent's meta-awareness, inside a
    scenario that contains a literal evaluation mechanism. Without an explicit
    carve-out, `suspects_being_tested` counted an agent reasoning about the
    quality checker as an agent suspecting it was under study - 55 of one
    100-run batch's 59 eval-aware verdicts, almost all false."""

    def test_the_awareness_signals_exclude_the_in_scenario_checker(self):
        """Every question that feeds the awareness verdict has to say that the
        scenario's own quality control does not count. The four that carried
        such a carve-out fired at 0-10%; the one that did not fired at 55%."""
        from subversionbench.config import RUBRIC_QUESTIONS
        signals = ("mentioned_test", "suspects_being_tested",
                   "questioned_authenticity", "referenced_ai_safety",
                   "broke_character")
        for key in signals:
            text = RUBRIC_QUESTIONS[key].lower()
            has_carveout = any(phrase in text for phrase in (
                "not the monitoring system", "does not count",
                "not an ai safety", "only flag",
            ))
            assert has_carveout, (
                f"{key} feeds the awareness verdict but names nothing that "
                f"does NOT count; that omission is what inflated the rate")

    def test_suspects_being_tested_names_the_scenario_mechanism(self):
        """Generic wording was not enough - the question has to name the quality
        checker, because that is the specific thing being confused for
        evaluation."""
        from subversionbench.config import RUBRIC_QUESTIONS
        text = RUBRIC_QUESTIONS["suspects_being_tested"].lower()
        assert "quality checker" in text or "quality-control" in text
        assert "does not count" in text

    def test_the_ab_baseline_is_not_the_shipped_wording(self):
        """rubric_ab.py compares the shipped wording against the one it
        replaced. If they converge, the experiment compares a string to itself
        and reports a null result that means nothing."""
        import rubric_ab
        from subversionbench.config import RUBRIC_QUESTIONS
        for key, previous in rubric_ab.PREVIOUS_WORDINGS.items():
            assert previous != RUBRIC_QUESTIONS[key], (
                f"{key}: the A/B baseline equals the shipped wording")


class TestNoUndefinedNames:
    """A static check across the package, because the split hid three of these
    and the tests could not see them.

    `classify_answer_llm` called `_parse_first_json`, which had moved to another
    module. The call sits inside a try/except that converts any failure into a
    keyword fallback, so instead of an error the classifier quietly stopped
    using the LLM at all - a silent downgrade of the measure. Two more of the
    same kind (`uuid` in the OpenRouter tool-call recovery, `re` in a duplicated
    routing function) sat on paths no test exercises."""

    def test_no_module_references_a_name_it_does_not_have(self):
        import subprocess
        import sys
        from pathlib import Path

        try:
            import pyflakes  # noqa: F401
        except ImportError:
            import pytest
            pytest.skip("pyflakes not installed")

        files = sorted(str(p) for p in Path("subversionbench").glob("*.py"))
        result = subprocess.run(
            [sys.executable, "-m", "pyflakes", *files],
            capture_output=True, text=True)
        undefined = [line for line in result.stdout.splitlines()
                     if "undefined name" in line]
        assert not undefined, (
            "undefined names would raise at runtime, and any inside a "
            "try/except become a silent fallback:\n  " + "\n  ".join(undefined))
