"""
Reasoning controls: which parameters a model accepts, and what to send.

Anthropic's reasoning surface changed shape across model generations and the
old parameter is rejected rather than ignored on the newer ones, so there is no
single request that works everywhere. This module owns that knowledge and
nothing else - it builds request parameters and never makes a request.

The non-Anthropic branches live here too, because the question they answer is
the same one: what reasoning parameters does this model take? For OpenRouter
the answer is none; for OpenAI it is the Responses API's own effort, alongside
a summary request.
"""

import re
from collections import namedtuple

from .routing import is_openai_model, is_openrouter_model

# =========================================================================
# Anthropic reasoning-control surface, by model family
# =========================================================================
#
# Anthropic replaced the fixed thinking budget with adaptive thinking, and
# the old parameter is not merely deprecated on the newer models - it is
# rejected:
#
#   thinking={"type": "enabled", "budget_tokens": N}
#     HTTP 400 on Fable 5, Mythos 5, Opus 5, Opus 4.8, Opus 4.7, Sonnet 5.
#     Deprecated but still functional on Opus 4.6 / Sonnet 4.6.
#     Still the only way to turn thinking on at or below Sonnet 4.5 /
#     Haiku 4.5 / Opus 4.5.
#
#   thinking={"type": "adaptive"}
#     Supported from the 4.6 generation onwards; the model decides how much
#     to think. Depth is steered by output_config={"effort": ...} instead of
#     a token count.
#
# So the eval cannot send one reasoning config to every model. Sending the
# wrong one does not degrade gracefully - it fails the request, which is how
# this table came to exist.
#
# Fields:
#   mode         "adaptive" or "budget" - which thinking parameter is accepted
#   effort       effort levels this model accepts; empty means the
#                output_config.effort parameter itself errors (Sonnet 4.5,
#                Haiku 4.5 and older)
#   can_disable  accepts thinking={"type": "disabled"}. False for the Fable /
#                Mythos family, where thinking is always on and an explicit
#                "disabled" is a 400 - there, thinking has to be left unset.
#   display_omitted
#                the model's default thinking.display is "omitted", i.e. it
#                returns thinking blocks whose text is an empty string unless
#                display="summarized" is asked for. This is the whole reason
#                the eval saw empty reasoning from Opus 5.
_Surface = namedtuple(
    "_Surface", "mode effort can_disable display_omitted",
)

_EFFORT_FULL = frozenset({"low", "medium", "high", "xhigh", "max"})
_EFFORT_NO_XHIGH = frozenset({"low", "medium", "high", "max"})
_EFFORT_BASIC = frozenset({"low", "medium", "high"})
_EFFORT_NONE = frozenset()

EFFORT_LEVELS = _EFFORT_FULL

# Matched as prefixes against the model ID, first match winning, so a bare
# family name must come after every dated or dotted variant of it
# ("claude-opus-4" is a prefix of "claude-opus-4-8").
_MODEL_SURFACES = (
    ("claude-fable-5",        _Surface("adaptive", _EFFORT_FULL,     False, True)),
    ("claude-mythos-5",       _Surface("adaptive", _EFFORT_FULL,     False, True)),
    ("claude-mythos-preview", _Surface("adaptive", _EFFORT_FULL,     False, True)),
    ("claude-opus-5",         _Surface("adaptive", _EFFORT_FULL,     True,  True)),
    ("claude-opus-4-8",       _Surface("adaptive", _EFFORT_FULL,     True,  True)),
    ("claude-opus-4-7",       _Surface("adaptive", _EFFORT_FULL,     True,  True)),
    ("claude-opus-4-6",       _Surface("adaptive", _EFFORT_NO_XHIGH, True,  False)),
    ("claude-sonnet-5",       _Surface("adaptive", _EFFORT_FULL,     True,  True)),
    ("claude-sonnet-4-6",     _Surface("adaptive", _EFFORT_NO_XHIGH, True,  False)),
    ("claude-opus-4-5",       _Surface("budget",   _EFFORT_BASIC,    False, False)),
    ("claude-opus-4-1",       _Surface("budget",   _EFFORT_NONE,     False, False)),
    ("claude-opus-4",         _Surface("budget",   _EFFORT_NONE,     False, False)),
    ("claude-sonnet-4-5",     _Surface("budget",   _EFFORT_NONE,     False, False)),
    ("claude-sonnet-4",       _Surface("budget",   _EFFORT_NONE,     False, False)),
    ("claude-haiku-4-5",      _Surface("budget",   _EFFORT_NONE,     False, False)),
    ("claude-3",              _Surface("budget",   _EFFORT_NONE,     False, False)),
    ("claude-2",              _Surface("budget",   _EFFORT_NONE,     False, False)),
)

# Assumed for an unrecognised native model ID. Adaptive rather than budget,
# because every Anthropic model that predates adaptive thinking is already
# named in the table above - an ID that is not there is a model released
# after it was written, and those take adaptive.
_DEFAULT_SURFACE = _Surface("adaptive", _EFFORT_FULL, True, True)

# Opus 5 accepts thinking={"type": "disabled"} only at effort "high" or
# below; pairing it with "xhigh" or "max" is a 400.
_NO_DISABLE_ABOVE_HIGH = ("claude-opus-5",)

_HIGH_EFFORTS = ("xhigh", "max")


def _normalise_model(model: str) -> str:
    """Strip provider decoration so a Bedrock-style ID resolves to the same
    family as the first-party one."""
    return model.strip().lower().removeprefix("anthropic.")


def thinking_surface(model: str):
    """
    Which reasoning parameters this Anthropic model accepts.

    None for anything that is not Anthropic. Without the OpenAI case here, a
    bare "gpt-5.4" falls through to the assumed-modern default and the harness
    sends Anthropic's thinking={"type": "adaptive"} to the Responses API.
    """
    if is_openrouter_model(model) or is_openai_model(model):
        return None
    name = _normalise_model(model)
    for prefix, surface in _MODEL_SURFACES:
        if name.startswith(prefix):
            return surface
    return _DEFAULT_SURFACE


def is_known_anthropic_model(model: str) -> bool:
    """Whether the ID matched the table rather than falling back to the
    assumed-modern default."""
    if is_openrouter_model(model):
        return False
    name = _normalise_model(model)
    return any(name.startswith(prefix) for prefix, _ in _MODEL_SURFACES)


# Anthropic's documented floor for budget_tokens, on the older models that
# still accept a budget at all.

MIN_THINKING_BUDGET = 1024

# On a model where thinking cannot be turned off, thinking tokens come out of
# the same max_tokens as the answer, so a 200-token grader call would spend
# its whole budget reasoning and return no verdict.
MIN_TOKENS_WHEN_THINKING_FORCED = 4096


def resolve_thinking_budget(requested, max_tokens: int):
    """
    Decide the extended-thinking budget for a model that takes one.

    Reasoning has to be captured by default, because whether it is captured
    silently changes what the eval measures. Both eval-awareness detectors
    read `thinking` entries, so a model whose reasoning is returned is scored
    on strictly more evidence than one whose is not - and the two are not
    comparable. In one pair of pilots an OpenRouter model contributed 102k
    characters of reasoning while native Anthropic runs contributed none,
    purely because extended thinking defaulted to off.

    There is no OpenRouter setting to copy here. That path sends no reasoning
    parameter; reasoning appears only when the model volunteers it, as
    always-reasoning models do. So the budget is chosen on its own terms:
    half the output budget for reasoning and half for the answer, which
    scales if --max-tokens is raised for a verbose model.

    `requested` of None means auto, 0 means off, anything else is explicit.
    Returns (budget, description).
    """
    if requested == 0:
        return 0, "disabled (--thinking-budget 0)"
    if requested is not None:
        return requested, f"explicit (--thinking-budget {requested})"

    budget = max_tokens // 2
    if budget < MIN_THINKING_BUDGET:
        # The API floor and room for a visible answer cannot both fit.
        return 0, (f"disabled automatically: --max-tokens {max_tokens} leaves "
                   f"no room for a {MIN_THINKING_BUDGET}-token minimum "
                   f"budget plus an answer")
    return budget, f"auto (half of --max-tokens {max_tokens})"


def reasoning_flag_error(model: str, requested_budget, effort):
    """
    The one flag combination that cannot be satisfied, as a message for the
    CLI to fail on - reported before a batch starts rather than as a 400 on
    run 1. Returns None if the request is satisfiable.
    """
    if effort and effort not in EFFORT_LEVELS:
        return (f"--effort must be one of "
                f"{', '.join(sorted(EFFORT_LEVELS))}; got {effort!r}.")

    surface = thinking_surface(model)
    if surface is None or surface.mode != "adaptive":
        return None
    if requested_budget != 0 or effort not in _HIGH_EFFORTS:
        return None
    if not _normalise_model(model).startswith(_NO_DISABLE_ABOVE_HIGH):
        return None
    return (
        f"{model} rejects thinking={{'type': 'disabled'}} at effort "
        f"{effort!r} - disabling thinking is only accepted at effort 'high' "
        f"or below. Either drop --thinking-budget 0 or use a lower --effort."
    )


# Substrings the SDKs use when no usable credential was found, or when the one
# supplied was rejected. Matched case-insensitively against str(exception).

def resolve_thinking_kwargs(model: str, requested_budget=None,
                            max_tokens: int = 8192, effort=None):
    """
    Build the reasoning parameters for one model, whichever generation it is.

    `requested_budget` keeps the CLI's meaning - None is auto, 0 is off,
    anything else is an explicit token budget - but a token budget is only
    expressible on the older models. On an adaptive model the request is
    honoured in kind rather than refused: auto and any explicit budget both
    become adaptive thinking, since the point of the default is that
    reasoning is captured, not that it is capped at a particular number.

    Returns (kwargs, description, warnings): kwargs to merge into
    client.messages.create(...), one line describing what was sent for the
    console and the summary JSON, and any operator-facing warnings.
    """
    surface = thinking_surface(model)
    warnings = []

    if surface is None and is_openai_model(model):
        # The Responses API returns a reasoning SUMMARY, never the trace, so
        # this model sits in the same regime as the Anthropic 4.6+ models and
        # not with the ones that return a full chain of thought.
        if requested_budget:
            warnings.append(
                f"--thinking-budget {requested_budget} does not apply to "
                f"OpenAI model {model}: reasoning depth is set by effort.")
        kwargs = {"output_config": {"effort": effort}} if effort else {}
        described = ("responses API, reasoning summary=auto"
                     + (f", effort={effort}" if effort else ""))
        return kwargs, described, warnings

    if surface is None:
        if requested_budget:
            warnings.append(
                f"--thinking-budget {requested_budget} does not apply to "
                f"OpenRouter model {model}: that API takes no reasoning "
                f"parameter. Reasoning is captured when the backend "
                f"volunteers it."
            )
        if effort:
            warnings.append(
                f"--effort {effort} does not apply to OpenRouter model "
                f"{model}."
            )
        return {}, "not sent (OpenRouter takes no reasoning parameter)", warnings

    kwargs = {}
    effort_note = ""
    if effort:
        if effort in surface.effort:
            kwargs["output_config"] = {"effort": effort}
            effort_note = f", effort={effort}"
            if effort in _HIGH_EFFORTS and max_tokens < 32000:
                warnings.append(
                    f"--effort {effort} with --max-tokens {max_tokens}: at "
                    f"this effort the model is expected to think and act "
                    f"across many tokens, and thinking counts against "
                    f"max_tokens, so answers may truncate. Anthropic "
                    f"suggests at least 64000 here."
                )
        else:
            accepted = (", ".join(sorted(surface.effort)) if surface.effort
                        else "none - the parameter itself errors on this model")
            warnings.append(
                f"--effort {effort} is not accepted by {model} (accepted: "
                f"{accepted}); sending no effort and using the API default."
            )

    if surface.mode == "budget":
        budget, source = resolve_thinking_budget(requested_budget, max_tokens)
        if budget > 0:
            kwargs["thinking"] = {
                "type": "enabled", "budget_tokens": budget,
            }
        return (kwargs, f"budget_tokens={budget} - {source}{effort_note}",
                warnings)

    # Adaptive generation.
    if requested_budget == 0:
        if surface.can_disable:
            kwargs["thinking"] = {"type": "disabled"}
            return (kwargs,
                    f"disabled (--thinking-budget 0){effort_note}", warnings)
        warnings.append(
            f"--thinking-budget 0 cannot be honoured for {model}: thinking is "
            f"always on for this model family and an explicit disable is "
            f"rejected. Leaving the parameter unset."
        )
        return kwargs, f"always on for this model{effort_note}", warnings

    if requested_budget:
        warnings.append(
            f"--thinking-budget {requested_budget} is not accepted by {model} "
            f"- the fixed thinking budget was replaced by adaptive thinking, "
            f"and sending budget_tokens is an HTTP 400. Using adaptive "
            f"thinking instead; steer depth with --effort."
        )

    thinking = {"type": "adaptive"}
    detail = "adaptive"
    if surface.display_omitted:
        # Without this the model still returns thinking blocks, but their
        # text is empty - which is what made native Anthropic runs contribute
        # zero reasoning characters while OpenRouter runs contributed
        # thousands. The raw chain of thought is never returned by these
        # models; a summary is the most that is available.
        thinking["display"] = "summarized"
        detail = "adaptive (display=summarized)"
    kwargs["thinking"] = thinking
    return kwargs, f"{detail}{effort_note}", warnings


def short_call_thinking_kwargs(model: str, max_tokens: int):
    """
    Reasoning config for the short JSON-only grader and classifier calls.

    These ask for a couple of hundred tokens of JSON, and thinking is on by
    default from Sonnet 5 / Opus 5 onwards - so leaving the parameter unset
    lets a grader spend its entire max_tokens reasoning and return no verdict
    at all, which the eval would record as a grading failure. Turn thinking
    off for these calls where the model allows it, and give the answer room
    where it does not.

    Returns (kwargs, max_tokens).
    """
    surface = thinking_surface(model)
    if surface is None or surface.mode == "budget":
        # No reasoning parameter, or a model where unset already means off.
        return {}, max_tokens
    if surface.can_disable:
        return {"thinking": {"type": "disabled"}}, max_tokens
    return {}, max(max_tokens, MIN_TOKENS_WHEN_THINKING_FORCED)


