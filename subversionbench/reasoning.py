"""
Reasoning controls: which parameters a model accepts, and what to send.

Anthropic's reasoning surface changed shape across model generations and the
old parameter is rejected rather than ignored on the newer ones, so there is no
single request that works everywhere. This module owns that knowledge and
nothing else - it builds request parameters and never makes a request.

The non-Anthropic branches live here too, because the question they answer is
the same one: what reasoning parameters does this harness send? For OpenRouter
it sends none - that route does accept a `reasoning` parameter, but omitting it
suppresses nothing, so nothing has to be sent to capture what a model produces.
For OpenAI it is the Responses API's own effort, alongside a summary request.

Sent, not accepted: the distinction matters because this module's description
string is recorded in every run, and a claim about what an API offers would be a
claim the harness cannot support from its own behaviour.
"""

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
    # Before "claude-opus-5", which is a prefix of it. Forced-thinking like the
    # Fable family: the API answers thinking={"type": "disabled"} with a 400
    # naming the model, not the effort, so this is not Opus 5's narrower rule
    # of disabling being refused only above "high". Inheriting Opus 5's row
    # cost 1,908 consecutive failed grader calls - every call of a cell - each
    # one a 400 that the run recorded as an unanswered question rather than as
    # a configuration error.
    ("claude-opus-5-5",       _Surface("adaptive", _EFFORT_FULL,     False, True)),
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

# Sent to OpenAI models when the operator names no --effort. Matches OpenAI's
# own default for gpt-5.5 and gpt-5.6, so it is a no-op there, and it stops a
# model with a lower default from silently doing no reasoning at all. The value
# lands in reasoning_config, so a batch always records what it ran with.
DEFAULT_OPENAI_EFFORT = "medium"

# What every OpenRouter run records as its reasoning config. Describes what the
# harness SENT - nothing - and why that still captures reasoning, rather than
# asserting the route has no reasoning parameter. It has one; this does not send
# it, and omitting it suppresses nothing.
OPENROUTER_REASONING_CONFIG = (
    "not sent (OpenRouter returns reasoning when the model generates it)")

# The wording this replaced, kept because it is recorded in every OpenRouter run
# already collected. The two describe the SAME request - no reasoning parameter -
# so they must compare equal: reinterrogate.py warns when a replayed probe's
# config differs from the episode's, and that warning exists to catch a real
# confound. Firing it on a corrected sentence would train the operator to ignore
# it. Superseded strings are added here, never removed.
_SUPERSEDED_CONFIGS = frozenset({
    "not sent (OpenRouter takes no reasoning parameter)",
})


def same_reasoning_config(recorded: str, resolved: str) -> bool:
    """
    Whether a saved run's reasoning config describes the same request as one
    resolved now.

    String equality, except that a config superseded only in its wording still
    matches the current one. Compares descriptions rather than parameters
    because the description is all a run records.
    """
    if recorded == resolved:
        return True
    both = {recorded, resolved}
    return (both <= _SUPERSEDED_CONFIGS | {OPENROUTER_REASONING_CONFIG}
            and OPENROUTER_REASONING_CONFIG in both)

MIN_THINKING_BUDGET = 1024

# On a model where thinking cannot be turned off, thinking tokens come out of
# the same max_tokens as the answer, so a 200-token grader call would spend
# its whole budget reasoning and return no verdict.
#
# ADDED to what the caller asked for, not used as a floor over it. A floor
# makes the answer's own tokens come out of the thinking allowance, which
# holds while the answer is small and fails as it grows: at a floor of 4096
# the single-answer grader shape kept 3,896 tokens to think in, while the
# batched shape - which asks for the same 200 tokens nine times - kept 2,296.
# The batched cell then failed 432 of 1,908 answers, 378 of them replies that
# carried no text block at all and 54 severed mid-JSON. Those are recorded as
# `reply` errors, which this experiment reads as the grader's own fragility
# under batching, so a budget that narrows with the size of the request does
# not merely lose answers - it answers the question the experiment is asking.
THINKING_HEADROOM_TOKENS = 4096

# Asked for on the short JSON grader and classifier calls, on any surface that
# accepts an effort and cannot be told to stop thinking altogether. The work is
# reading a transcript against a fixed rubric and emitting the shape back, not
# open-ended reasoning, and the headroom above is what catches the rest.
SHORT_CALL_EFFORT = "low"


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
        # An explicit effort is sent even when the operator asked for none.
        # The first native gpt-5.4 batch sent no effort and the API reported
        # reasoning_tokens=0 across all ten episodes: the model did not reason
        # at all, so both awareness measures were left reading visible text
        # only - the exact failure this route was added to fix. gpt-5.5 and
        # gpt-5.6 default to "medium" anyway, so naming it changes nothing for
        # them and turns reasoning on for a model whose default is lower.
        chosen = effort or DEFAULT_OPENAI_EFFORT
        described = (f"responses API, reasoning summary=auto, effort={chosen}"
                     + ("" if effort else " (default)"))
        return {"output_config": {"effort": chosen}}, described, warnings

    if surface is None:
        if requested_budget:
            warnings.append(
                f"--thinking-budget {requested_budget} does not apply to "
                f"OpenRouter model {model}: this harness sends no reasoning "
                f"parameter on that route. Reasoning is captured when the "
                f"model returns it, which omitting the parameter does not "
                f"prevent."
            )
        if effort:
            warnings.append(
                f"--effort {effort} does not apply to OpenRouter model "
                f"{model}: this harness sends no reasoning parameter there."
            )
        return {}, OPENROUTER_REASONING_CONFIG, warnings

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


def short_call_thinking_kwargs(model: str, max_tokens: int,
                               steer_effort: bool = True):
    """
    Reasoning config for the short JSON-only grader and classifier calls.

    These ask for a couple of hundred tokens of JSON, and thinking is on by
    default from Sonnet 5 / Opus 5 onwards - so leaving the parameter unset
    lets a grader spend its entire max_tokens reasoning and return no verdict
    at all, which the eval would record as a grading failure. Turn thinking
    off for these calls where the model allows it, and give the answer room
    where it does not.

    `steer_effort=False` keeps the headroom but sends no effort, for a caller
    whose short call is put to the model UNDER TEST rather than to a grader:
    contamination_check.py measures what the model recalls, and lowering its
    effort would lower the thing being measured.

    Returns (kwargs, max_tokens).
    """
    surface = thinking_surface(model)
    if surface is not None and surface.mode == "budget":
        # Unset really does mean off here, so the answer has the whole budget.
        return {}, max_tokens
    if surface is not None and surface.can_disable:
        return {"thinking": {"type": "disabled"}}, max_tokens
    # THINKING CANNOT BE SUPPRESSED, so the answer needs room after it. Two
    # different cases reach this, and they used to be split: a surface that
    # says so outright, and `surface is None`, which was grouped with the
    # budget case above under "no reasoning parameter, or a model where unset
    # already means off". Those are not the same fact. A route that accepts no
    # reasoning parameter is one where thinking cannot be turned OFF, not one
    # where it is already off - OPENROUTER_REASONING_CONFIG says as much in
    # this file: "It has one; this does not send it, and omitting it
    # suppresses nothing."
    #
    # Measured, not reasoned about: self-grading pointed the rubric grader at
    # google/gemini-3.5-flash over OpenRouter and 9 of 9 questions failed to
    # parse on every episode of a batch. The replies were not malformed - they
    # were correct JSON severed mid-token at 18 and 25 characters, the whole
    # 200 having gone on reasoning. contamination_check.py hit this first and
    # fixed it the same way for its own calls (FORCED_CHOICE_TOKENS), for the
    # reason it gives there: on THAT route the model cannot be told how much
    # to think, so room to answer is the only lever left.
    #
    # A ceiling is not a spend. A model that emits its JSON and stops is
    # byte-identical under a higher one, so raising it changes only calls that
    # were failing. The EFFORT below is different: it changes calls that
    # already succeeded, so a forced-thinking or native OpenAI grader
    # (--self-grade-kind, or --grader-model on Fable/Mythos/Opus 5.5/gpt-*)
    # grades differently from v212 on.
    # The reference and default grader, claude-opus-5, can disable thinking
    # and never reaches this branch, which is why no published figure moves.
    #
    # BUT A CEILING ALONE IS NOT ENOUGH, because a model that does not stop
    # spends whatever it is given. On a native route that takes an effort
    # there is a second lever, and the API named it itself when it rejected
    # thinking={"type": "disabled"}: "use output_config.effort to control
    # thinking behavior". These calls emit a fixed JSON shape and need almost
    # no reasoning to do it.
    #
    # Measured: at the default effort, two of eight batched grader calls to
    # claude-opus-5-5 spent the whole ceiling thinking and returned no text
    # block at all - and those two were 87% of that probe's spend, so raising
    # the ceiling buys more of the waste rather than less of it.
    #
    # It also narrows the gap to the reference cell instead of widening it.
    # That cell grades with thinking disabled outright, so a candidate left at
    # its default effort would differ from the reference by reasoning depth as
    # well as by model - a confound inside the comparison the experiment
    # exists to make.
    #
    # OpenAI's own route takes the same lever, as reasoning.effort, which
    # OpenAIClient translates output_config into. It has no surface row, so
    # it was sent nothing and reasoned at its default: gpt-6-sol graded at
    # 3x the cost of Opus 5 and 5x Opus 5.5 despite cheaper per-token rates.
    # OpenRouter's "openai/..." IDs are not is_openai_model and still get
    # nothing - that route takes no reasoning parameter here.
    kwargs = {}
    if steer_effort and (is_openai_model(model) or (
            surface is not None and SHORT_CALL_EFFORT in surface.effort)):
        kwargs["output_config"] = {"effort": SHORT_CALL_EFFORT}
    return kwargs, max_tokens + THINKING_HEADROOM_TOKENS


