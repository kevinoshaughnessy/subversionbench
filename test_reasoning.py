"""
The thinking/effort surface, and what each provider is actually sent.
"""

import contextlib
import glob
import io
import json
import sys
import tempfile
import types

from pathlib import Path
import subversionbench.llm_client as ev_llm
import subversionbench.run_eval as ev_run


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

class TestThinkingBudget:
    """Reasoning must be captured without the operator remembering a flag.
    Whether it is captured changes what the eval measures: both awareness
    detectors read `thinking`, so a model whose reasoning is returned is
    scored on strictly more evidence than one whose is not."""

    def test_default_is_on_not_off(self):
        budget, source = ev_run.resolve_thinking_budget(None, 8192)
        assert budget == 4096
        assert "auto" in source

    def test_it_scales_with_max_tokens(self):
        """A verbose model given more output room should get more reasoning
        room, rather than a fixed budget that truncates."""
        assert ev_run.resolve_thinking_budget(None, 16384)[0] == 8192
        assert ev_run.resolve_thinking_budget(None, 4096)[0] == 2048

    def test_zero_still_disables(self):
        budget, source = ev_run.resolve_thinking_budget(0, 8192)
        assert budget == 0
        assert "disabled" in source

    def test_explicit_value_is_respected(self):
        budget, source = ev_run.resolve_thinking_budget(4000, 8192)
        assert budget == 4000
        assert "explicit" in source

    def test_disabled_when_the_api_floor_cannot_fit(self):
        """budget_tokens has a floor of 1024 and counts against max_tokens, so
        below 2048 there is no room for both a minimum budget and an answer."""
        budget, source = ev_run.resolve_thinking_budget(None, 1024)
        assert budget == 0
        assert "no room" in source

    def test_auto_always_leaves_room_for_the_answer(self):
        for max_tokens in (2048, 4096, 8192, 32000):
            budget, _ = ev_run.resolve_thinking_budget(None, max_tokens)
            assert budget < max_tokens

    def test_empty_thinking_blocks_are_not_recorded(self):
        """An empty block is a placeholder for reasoning the API withheld.
        Recording it makes a transcript claim reasoning was captured when none
        was, and feeds the grader hollow [REASONING] sections - 243 such
        entries appeared in the pilot data."""
        out = tempfile.mkdtemp()

        def blk(**kw):
            return types.SimpleNamespace(**kw)

        class Messages:
            def create(self, messages=None, **kw):
                if "tools" not in kw:
                    return blk(stop_reason="end_turn",
                               content=[blk(type="text", text="no")])
                return blk(stop_reason="end_turn", content=[
                    blk(type="thinking", thinking=""),
                    blk(type="thinking", thinking="   "),
                    blk(type="thinking", thinking="Real reasoning here."),
                    blk(type="text", text="I recommend Strategy B.")])

        class Client:
            def __init__(self):
                self.messages = Messages()

        original, original_argv = ev_llm.get_client, sys.argv
        ev_llm.get_client = lambda m: Client()
        sys.argv = ["run_eval", "--model", "m", "--runs", "1", "--delay", "0",
                    "--no-grader", "--output-dir", out]
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                ev_run.main()
        finally:
            ev_llm.get_client, sys.argv = original, original_argv

        data = json.loads(Path(glob.glob(f"{out}/run_1_*.json")[0]).read_text())
        thinking = [e for e in data["transcript"] if e["type"] == "thinking"]
        assert len(thinking) == 1, "only the non-empty block should survive"
        assert thinking[0]["content"] == "Real reasoning here."
        assert data["reasoning_chars"] == len("Real reasoning here.")

    def test_summary_reports_whether_reasoning_was_captured(self):
        """Two batches that differ on this are not comparable on awareness, so
        it has to be visible in the artefact rather than inferred."""
        out = tempfile.mkdtemp()

        def blk(**kw):
            return types.SimpleNamespace(**kw)

        class Messages:
            def create(self, messages=None, **kw):
                if "tools" not in kw:
                    return blk(stop_reason="end_turn",
                               content=[blk(type="text", text="no")])
                return blk(stop_reason="end_turn", content=[
                    blk(type="thinking", thinking=""),
                    blk(type="text", text="I recommend Strategy B.")])

        class Client:
            def __init__(self):
                self.messages = Messages()

        original, original_argv = ev_llm.get_client, sys.argv
        ev_llm.get_client = lambda m: Client()
        sys.argv = ["run_eval", "--model", "m", "--runs", "2", "--delay", "0",
                    "--no-grader", "--output-dir", out]
        try:
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                ev_run.main()
            output = buf.getvalue()
        finally:
            ev_llm.get_client, sys.argv = original, original_argv

        assert "No reasoning was captured" in output
        summary = json.loads(
            Path(sorted(glob.glob(f"{out}/summary_*.json"))[-1]).read_text())
        assert summary["episodes_with_reasoning"] == 0
        # What was actually sent, so a reader can tell "the model produced no
        # reasoning" from "the eval never asked for any".
        assert "adaptive" in summary["reasoning_config"]
