"""
Tests for subversionbench/reasoning.py.

Which reasoning parameters each model generation accepts. Sending the wrong one
does not degrade gracefully - it fails the request with a 400 - and sending
none at all silently changes what the eval measures, because both awareness
detectors read reasoning.

Run: pytest test_reasoning.py -v
"""

import json



class TestThinkingSurface:
    """The reasoning parameter differs by model generation, and sending the
    wrong one does not degrade gracefully - it is an HTTP 400. Opus 5 batches
    failed outright on `thinking.type.enabled` until this table existed."""

    def test_budget_tokens_is_never_sent_to_an_adaptive_model(self):
        """The regression that started this: budget_tokens is rejected from
        Sonnet 5 / Opus 5 onwards, so no code path may emit it for them."""
        from subversionbench.reasoning import resolve_thinking_kwargs

        for model in ("claude-opus-5", "claude-sonnet-5", "claude-opus-4-8",
                      "claude-opus-4-7", "claude-fable-5"):
            for requested in (None, 4096):
                kwargs, _, _ = resolve_thinking_kwargs(model, requested, 8192)
                assert kwargs["thinking"]["type"] == "adaptive", model
                assert "budget_tokens" not in kwargs["thinking"], model

    def test_older_models_still_get_a_budget(self):
        """Adaptive thinking does not exist below the 4.6 generation, so the
        default grader model must keep the old parameter."""
        from subversionbench.reasoning import resolve_thinking_kwargs

        for model in ("claude-haiku-4-5-20251001", "claude-sonnet-4-5",
                      "claude-opus-4-5"):
            kwargs, desc, _ = resolve_thinking_kwargs(model, None, 8192)
            assert kwargs["thinking"] == {
                "type": "enabled", "budget_tokens": 4096,
            }, model
            assert "budget_tokens=4096" in desc

    def test_an_explicit_budget_on_an_adaptive_model_warns(self):
        """Silently ignoring the flag would leave the operator believing they
        had capped reasoning."""
        from subversionbench.reasoning import resolve_thinking_kwargs

        _, _, warnings = resolve_thinking_kwargs("claude-opus-5", 4096, 8192)
        assert any("adaptive" in w for w in warnings)

    def test_summarized_display_is_requested_where_the_default_is_omitted(self):
        """Without this the model returns thinking blocks whose text is empty,
        which is what made native Anthropic runs contribute zero reasoning
        characters while OpenRouter runs contributed thousands."""
        from subversionbench.reasoning import resolve_thinking_kwargs

        kwargs, _, _ = resolve_thinking_kwargs("claude-opus-5", None, 8192)
        assert kwargs["thinking"]["display"] == "summarized"

        # Opus 4.6 already defaults to summarized, so nothing needs asking
        # for - and not sending an unnecessary parameter cannot be rejected.
        kwargs, _, _ = resolve_thinking_kwargs("claude-opus-4-6", None, 8192)
        assert "display" not in kwargs["thinking"]

    def test_openrouter_gets_no_reasoning_parameter_at_all(self):
        from subversionbench.reasoning import resolve_thinking_kwargs

        kwargs, desc, _ = resolve_thinking_kwargs("x-ai/grok-4.5", None, 8192)
        assert kwargs == {}
        assert "OpenRouter" in desc

    def test_disable_uses_the_form_each_family_accepts(self):
        from subversionbench.reasoning import resolve_thinking_kwargs

        kwargs, _, _ = resolve_thinking_kwargs("claude-opus-5", 0, 8192)
        assert kwargs["thinking"] == {"type": "disabled"}

        # Fable/Mythos reject an explicit disable - thinking is always on
        # there, so the only legal way to express it is to send nothing.
        kwargs, desc, warnings = resolve_thinking_kwargs("claude-fable-5", 0, 8192)
        assert "thinking" not in kwargs
        assert "always on" in desc
        assert warnings

        # Below 4.6, unset already means no thinking.
        kwargs, _, _ = resolve_thinking_kwargs("claude-haiku-4-5", 0, 8192)
        assert "thinking" not in kwargs

    def test_effort_is_only_sent_where_it_is_accepted(self):
        from subversionbench.reasoning import resolve_thinking_kwargs

        kwargs, _, warnings = resolve_thinking_kwargs(
            "claude-opus-5", None, 64000, "medium")
        assert kwargs["output_config"] == {"effort": "medium"}
        assert not warnings

        # xhigh arrived after Opus 4.6, and the effort parameter itself
        # errors on Haiku 4.5 - neither may be sent.
        kwargs, _, warnings = resolve_thinking_kwargs(
            "claude-opus-4-6", None, 64000, "xhigh")
        assert "output_config" not in kwargs
        assert warnings

        kwargs, _, warnings = resolve_thinking_kwargs(
            "claude-haiku-4-5", None, 8192, "high")
        assert "output_config" not in kwargs
        assert warnings

    def test_disabling_thinking_above_high_effort_is_refused_up_front(self):
        """Opus 5 rejects that pair with a 400, so it has to fail at argument
        parsing rather than on run 1 of a batch."""
        from subversionbench.reasoning import reasoning_flag_error

        assert reasoning_flag_error("claude-opus-5", 0, "max")
        assert reasoning_flag_error("claude-opus-5", 0, "xhigh")
        assert reasoning_flag_error("claude-opus-5", 0, "high") is None
        assert reasoning_flag_error("claude-opus-5", None, "max") is None
        assert reasoning_flag_error("claude-sonnet-5", 0, "max") is None

    def test_dated_and_bedrock_ids_resolve_to_the_same_family(self):
        from subversionbench.reasoning import thinking_surface

        assert thinking_surface("claude-haiku-4-5-20251001").mode == "budget"
        assert thinking_surface("anthropic.claude-opus-5").mode == "adaptive"
        assert thinking_surface("Claude-Opus-5").mode == "adaptive"

    def test_family_prefixes_do_not_shadow_each_other(self):
        """"claude-opus-4" is a prefix of "claude-opus-4-8", so a careless
        table would classify the newer model as the older one."""
        from subversionbench.reasoning import thinking_surface

        assert thinking_surface("claude-opus-4-8").mode == "adaptive"
        assert thinking_surface("claude-opus-4-0").mode == "budget"
        assert thinking_surface("claude-sonnet-4-6").mode == "adaptive"
        assert thinking_surface("claude-sonnet-4-5").mode == "budget"

    def test_an_unknown_anthropic_model_is_assumed_modern(self):
        """Every model predating adaptive thinking is already in the table, so
        an unrecognised ID is a newer one - and guessing "budget" for it would
        fail every request."""
        from subversionbench.reasoning import (
            thinking_surface, is_known_anthropic_model,
        )

        assert thinking_surface("claude-opus-6").mode == "adaptive"
        assert not is_known_anthropic_model("claude-opus-6")
        assert is_known_anthropic_model("claude-opus-5")




class TestGraderThinking:
    """The grader asks for 200 tokens of JSON. Thinking is on by default from
    Sonnet 5 / Opus 5 onwards, so leaving the parameter unset lets a grader
    spend its whole budget reasoning and return no verdict - which the eval
    would record as a grading failure, not a configuration error."""

    def test_thinking_is_turned_off_for_short_grader_calls(self):
        from subversionbench.reasoning import short_call_thinking_kwargs

        kwargs, tokens = short_call_thinking_kwargs("claude-opus-5", 200)
        assert kwargs["thinking"] == {"type": "disabled"}
        assert tokens == 200

    def test_older_grader_models_are_left_alone(self):
        from subversionbench.reasoning import short_call_thinking_kwargs

        kwargs, tokens = short_call_thinking_kwargs(
            "claude-haiku-4-5-20251001", 200)
        assert kwargs == {}
        assert tokens == 200

    def test_a_forced_thinking_grader_gets_room_for_its_answer(self):
        """Fable/Mythos cannot turn thinking off, and thinking comes out of the
        same max_tokens as the answer."""
        from subversionbench.reasoning import short_call_thinking_kwargs

        kwargs, tokens = short_call_thinking_kwargs("claude-fable-5", 200)
        assert kwargs == {}
        assert tokens >= 4096

    def test_openrouter_grader_gets_no_parameter(self):
        from subversionbench.reasoning import short_call_thinking_kwargs

        kwargs, tokens = short_call_thinking_kwargs("x-ai/grok-4.5", 200)
        assert kwargs == {}
        assert tokens == 200


# =========================================================================
# Tests: routing between the three APIs
# =========================================================================


class TestOpenAIEffortDefault:
    """A native gpt-5.4 batch sent no effort and came back with
    reasoning_tokens=0 on all ten episodes - the model did no reasoning, so
    both awareness measures read visible text only, which is the exact failure
    the OpenAI route was added to fix."""

    def test_an_effort_is_always_sent(self):
        from subversionbench.reasoning import resolve_thinking_kwargs
        kwargs, described, _ = resolve_thinking_kwargs("gpt-5.4", None, 8192)
        assert kwargs["output_config"]["effort"], "must not send a bare summary"
        assert "default" in described, "the batch must record that it defaulted"

    def test_an_explicit_effort_wins(self):
        from subversionbench.reasoning import resolve_thinking_kwargs
        kwargs, described, _ = resolve_thinking_kwargs(
            "gpt-5.4", None, 8192, "xhigh")
        assert kwargs["output_config"]["effort"] == "xhigh"
        assert "default" not in described

    def test_the_default_matches_openai_s_own(self):
        """Chosen so it is a no-op for the models that already default to it,
        and only changes behaviour where the default was lower."""
        from subversionbench.reasoning import DEFAULT_OPENAI_EFFORT
        assert DEFAULT_OPENAI_EFFORT == "medium"

    def test_the_effort_reaches_the_request(self):
        from subversionbench.reasoning import resolve_thinking_kwargs
        kwargs, _, _ = resolve_thinking_kwargs("gpt-5.4", None, 8192, "high")
        # OpenAIClient reads output_config.effort and puts it in reasoning.
        assert kwargs == {"output_config": {"effort": "high"}}
