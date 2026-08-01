"""
Tests for subversionbench/routing.py.

Which API serves a model ID. The OpenAI and OpenRouter routes reach the same
models on purpose and do not return the same thing, so the split has to hold.

Run: pytest test_routing.py -v
"""



# =========================================================================
# Tests: routing between the three APIs
# =========================================================================

class TestOpenAIRouting:
    """The same model returns reasoning on one route and not the other, so
    which route is used has to be an explicit choice. openai/gpt-5.4 through
    OpenRouter returned zero reasoning characters across ten episodes while
    openai/gpt-5.5 returned 25,553 - both awareness measures read reasoning,
    so the route silently changes what is measured."""

    def test_bare_gpt_ids_go_to_openai(self):
        from subversionbench.routing import is_openai_model
        for model in ("gpt-5.4", "gpt-5.6-sol", "GPT-5.4", "o3-mini", "o1"):
            assert is_openai_model(model), model

    def test_a_provider_prefix_keeps_it_on_openrouter(self):
        """Prefixing is how the operator selects the other route; if this
        collapsed, the two could not be compared against each other."""
        from subversionbench.routing import is_openai_model, is_openrouter_model
        assert is_openrouter_model("openai/gpt-5.4")
        assert not is_openai_model("openai/gpt-5.4")

    def test_anthropic_ids_are_untouched(self):
        from subversionbench.routing import is_openai_model
        for model in ("claude-opus-5", "claude-haiku-4-5", "claude-sonnet-4-6"):
            assert not is_openai_model(model)

    def test_openai_models_get_no_anthropic_thinking_parameter(self):
        """Without this, a bare gpt-5.4 falls through to the assumed-modern
        Anthropic surface and the harness posts thinking={"type": "adaptive"}
        to the Responses API."""
        from subversionbench.reasoning import (
            thinking_surface, resolve_thinking_kwargs)
        assert thinking_surface("gpt-5.4") is None
        kwargs, described, _ = resolve_thinking_kwargs("gpt-5.4", None, 8192)
        assert "thinking" not in kwargs
        assert "summary=auto" in described

    def test_effort_maps_onto_the_responses_api(self):
        from subversionbench.reasoning import resolve_thinking_kwargs
        kwargs, described, _ = resolve_thinking_kwargs(
            "gpt-5.4", None, 8192, "high")
        assert kwargs == {"output_config": {"effort": "high"}}
        assert "effort=high" in described
