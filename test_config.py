"""
Tests for subversionbench/config.py.

Covers the VERSION constant and the system prompts, including that
neither nudge variant leaks eval-awareness clues to the model.

Run: pytest test_config.py -v
"""


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
        assert ev.VERSION == "v14"
