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


class TestResponsesUsageFieldNames:
    """Chat completions and the Responses API name the same quantities
    differently. Reading one set only lost input/output counts on the first
    native batch, which recorded total_tokens alone."""

    def test_responses_api_names_are_read(self):
        import types
        from subversionbench.blocks import _reasoning_usage
        usage = _reasoning_usage(types.SimpleNamespace(usage=types.SimpleNamespace(
            input_tokens=1200, output_tokens=340, total_tokens=1540,
            output_tokens_details=types.SimpleNamespace(reasoning_tokens=256))))
        assert usage == {"total_tokens": 1540, "input_tokens": 1200,
                         "output_tokens": 340, "reasoning_tokens": 256}

    def test_chat_completions_names_still_work(self):
        import types
        from subversionbench.blocks import _reasoning_usage
        usage = _reasoning_usage(types.SimpleNamespace(usage=types.SimpleNamespace(
            prompt_tokens=10, completion_tokens=5, total_tokens=15,
            completion_tokens_details=types.SimpleNamespace(reasoning_tokens=3))))
        assert usage["prompt_tokens"] == 10 and usage["reasoning_tokens"] == 3

    def test_zero_reasoning_tokens_is_recorded_not_dropped(self):
        """Zero is the finding: the model did not reason. Dropping it would
        make it indistinguishable from a provider that reports nothing."""
        import types
        from subversionbench.blocks import _reasoning_usage
        usage = _reasoning_usage(types.SimpleNamespace(usage=types.SimpleNamespace(
            total_tokens=15151,
            output_tokens_details=types.SimpleNamespace(reasoning_tokens=0))))
        assert usage["reasoning_tokens"] == 0
