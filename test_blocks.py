"""
Tests for subversionbench/blocks.py.

The Anthropic-shaped objects every adapter normalises to, and the token
accounting carried alongside them.

Run: pytest test_blocks.py -v
"""

import json



class TestReasoningUsage:
    """A reasoning-token count is the only thing that separates a model which
    did not reason from one whose reasoning was withheld. Both look like an
    empty transcript."""

    def test_reasoning_tokens_are_extracted(self):
        import types
        from subversionbench.blocks import _reasoning_usage
        completion = types.SimpleNamespace(usage=types.SimpleNamespace(
            prompt_tokens=100, completion_tokens=50, total_tokens=150,
            completion_tokens_details=types.SimpleNamespace(reasoning_tokens=40)))
        usage = _reasoning_usage(completion)
        assert usage["reasoning_tokens"] == 40
        assert usage["prompt_tokens"] == 100

    def test_the_responses_api_field_name_also_works(self):
        import types
        from subversionbench.blocks import _reasoning_usage
        completion = types.SimpleNamespace(usage=types.SimpleNamespace(
            output_tokens_details=types.SimpleNamespace(reasoning_tokens=7)))
        assert _reasoning_usage(completion)["reasoning_tokens"] == 7

    def test_an_absent_count_is_absent_not_zero(self):
        """A provider that reports nothing and one that reports zero are
        making different claims, and the classification turns on which."""
        import types
        from subversionbench.blocks import _reasoning_usage
        assert _reasoning_usage(types.SimpleNamespace(usage=None)) == {}
        completion = types.SimpleNamespace(usage=types.SimpleNamespace(
            prompt_tokens=10, completion_tokens_details=None))
        assert "reasoning_tokens" not in _reasoning_usage(completion)
