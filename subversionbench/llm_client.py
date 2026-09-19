"""
Client factory for SubversionBench: pick the API for a model ID.

One job. Everything the factory used to also do now lives beside it, each in a
module with a single reason to change:

    routing.py            which API serves a model ID
    reasoning.py          which reasoning parameters a model accepts
    blocks.py             the Anthropic-shaped response objects adapters emit
    tool_parsing.py       recovering tool calls emitted as prose
    api_errors.py         classifying provider errors
    openrouter_client.py  OpenRouter adapter
    opencode_client.py    OpenCode Zen adapter - an alternate gateway for the
                          same "provider/model" ids, opted into per run
    openai_client.py      OpenAI Responses adapter

The names re-exported below are this package's client-facing API, kept here so
that callers - and the tests that patch `llm_client.get_client` - have one
import site rather than seven. New code should prefer the owning module.

Three ID SHAPES decide the route, and the choice between two OpenAI-model
routes is deliberate:

  provider/model  -> OpenRouter (or OpenCode, see below) ("openai/gpt-5.4", "x-ai/grok-4.5")
  gpt-* / o<n>    -> OpenAI Responses    ("gpt-5.4", "o3-mini")
  anything else   -> native Anthropic    ("claude-opus-5")

The same OpenAI model is reachable on two of those, and the choice changes what
the harness controls: the Responses route sends an effort and asks for a
reasoning summary, while OpenRouter sends no reasoning parameter, so effort is
the model's own default. Both awareness measures read reasoning, so the route
stays an explicit choice recorded in every run's `reasoning_config`. What it
does NOT change is whether reasoning comes back at all - see routing.py for the
measurement that retired that claim.

A "provider/model" id is a SHAPE, not a commitment to one gateway: --use-opencode
sends it to OpenCode Zen instead of OpenRouter, unchanged, because that shape is
what Zen's ids collapse to once its own vendor prefix is stripped (see
opencode_client.py). OpenRouter remains the default - nothing about the shape
or the id changes, only which client get_client() returns.

SETUP:
  pip install openai                     # for the OpenRouter/OpenCode and OpenAI routes
  export ANTHROPIC_API_KEY="..."         # claude-* IDs
  export OPENROUTER_API_KEY="..."        # provider/model IDs
  export OPENCODE_API_KEY="..."          # provider/model IDs, with --use-opencode
  export OPENAI_API_KEY="..."            # bare gpt-* / o<n> IDs
"""

import os

from .api_errors import (api_error_message, is_auth_error,
                         is_usage_limit_error, usage_limit_reset,
                         warn_usage_limit_once)
from .blocks import _Block, _Response, _block_attr, _block_type, _reasoning_usage
from .opencode_client import OpenCodeClient
from .openai_client import (
    OpenAIClient,
    _from_responses_output,
    _to_responses_input,
    _to_responses_tool,
)
from .openrouter_client import OpenRouterClient, _to_openai_messages, _to_openai_tool
from .reasoning import (
    EFFORT_LEVELS,
    MIN_THINKING_BUDGET,
    MIN_TOKENS_WHEN_THINKING_FORCED,
    is_known_anthropic_model,
    reasoning_flag_error,
    resolve_thinking_budget,
    resolve_thinking_kwargs,
    short_call_thinking_kwargs,
    thinking_surface,
)
from .routing import is_openai_model, is_openrouter_model
from .tool_parsing import (
    _BRACKET_TOOL_CALL_RE,
    _RAW_TOOL_CALL_START,
    _parse_bracket_tool_calls,
    _parse_raw_tool_call_text,
)

__all__ = [
    "get_client",
    "is_openrouter_model",
    "is_openai_model",
    "is_known_anthropic_model",
    "is_auth_error",
    "is_usage_limit_error",
    "usage_limit_reset",
    "api_error_message",
    "warn_usage_limit_once",
    "thinking_surface",
    "resolve_thinking_kwargs",
    "resolve_thinking_budget",
    "short_call_thinking_kwargs",
    "reasoning_flag_error",
    "EFFORT_LEVELS",
    "MIN_THINKING_BUDGET",
    "MIN_TOKENS_WHEN_THINKING_FORCED",
    "OpenRouterClient",
    "OpenCodeClient",
    "OpenAIClient",
]


# Which credential each route needs, so a missing one can be reported before a
# rollout spends anything rather than per-call once it has.
_CREDENTIAL_ENV = {"openrouter": "OPENROUTER_API_KEY",
                   "opencode": "OPENCODE_API_KEY",
                   "openai": "OPENAI_API_KEY",
                   "anthropic": "ANTHROPIC_API_KEY"}


def credential_env_var(model: str, use_opencode: bool = False) -> str:
    """
    The environment variable this model's route authenticates with.

    `use_opencode` only changes anything for an OpenRouter-shaped id: it is
    the same --use-opencode choice get_client() takes, and has to be passed
    here too so a batch's own pre-flight credential check (missing_credential,
    below) asks for the key the run will actually need rather than the one
    the default route would have.
    """
    if is_openrouter_model(model):
        return _CREDENTIAL_ENV["opencode" if use_opencode else "openrouter"]
    if is_openai_model(model):
        return _CREDENTIAL_ENV["openai"]
    return _CREDENTIAL_ENV["anthropic"]


def missing_credential(model: str, use_opencode: bool = False):
    """
    The credential this model needs and does not have, or None.

    WHY THIS IS NOT "just try to build the client"
    ---------------------------------------------
    The routes fail at different times, and the difference is what made a
    real batch silently useless. The OpenRouter, OpenCode and OpenAI clients
    raise at CONSTRUCTION with a clear message. `anthropic.Anthropic()`
    constructs happily with no key at all and defers the failure to the first
    call - so a rollout whose ANTHROPIC_API_KEY was absent built its client,
    ran every episode, and failed one interrogation-classifier call at a
    time. Each failure fell back to the keyword cross-check, which is a
    legitimate mechanism for one bad answer and a fiction for all of them:
    three r4 batches recorded 100% keyword fallback with an auth error on
    all 401 answers, and still reported a scheming rate.

    Checked against the environment rather than by calling anything, so it costs
    nothing and is exact.
    """
    var = credential_env_var(model, use_opencode=use_opencode)
    return None if os.environ.get(var) else var


def get_client(model: str, provider_sort: str = None, provider_name: str = None,
               use_opencode: bool = False):
    """
    Return an API client for the given model.

    Stays in this module rather than moving to routing.py because the tests
    patch it here and `grading.py` imports it lazily by this path; moving it
    would make those patches silently no-ops.

    `provider_sort`, `provider_name` and `use_opencode` only mean anything
    for OpenRouter-shaped ids, and only episode.py's call for the model
    UNDER TEST passes any of them - grading.py's calls (grader, interrogation
    classifier, closing-report check) build their own client from
    `grader_model` and never see these arguments, so a
    `--openrouter-sort`/`--openrouter-provider`/`--use-opencode` aimed at the
    model under test cannot silently change which backend, or which gateway,
    answers a grading call for an unrelated model.

    `use_opencode` picks OpenCodeClient over OpenRouterClient for the same
    "provider/model" ids - a different gateway to the same corpus of model
    ids, not a new id shape - and provider_sort/provider_name are OpenRouter-
    only concepts OpenCodeClient's own __init__ takes no parameters for;
    episode.py's _resolved_routing nulls both before either client is built
    here, so this function never has to reconcile the two.
    """
    if is_openrouter_model(model):
        if use_opencode:
            return OpenCodeClient()
        return OpenRouterClient(provider_sort=provider_sort, provider_name=provider_name)
    if is_openai_model(model):
        return OpenAIClient()
    import anthropic
    # Every call through this client asks for a couple hundred tokens of JSON
    # with thinking disabled where the model allows it (short_call_thinking_
    # kwargs) - grading, interrogation classification, closing-report checks.
    # None of that legitimately needs the SDK's 600s default read timeout;
    # 90s is generous headroom over normal latency and bounds how long one
    # degraded call can stall a batch before the SDK's own retry takes over.
    return anthropic.Anthropic(timeout=90)
