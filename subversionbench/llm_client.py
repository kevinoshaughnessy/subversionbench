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
    openai_client.py      OpenAI Responses adapter

The names re-exported below are this package's client-facing API, kept here so
that callers - and the tests that patch `llm_client.get_client` - have one
import site rather than seven. New code should prefer the owning module.

Three routes, and the choice between two of them is deliberate:

  provider/model  -> OpenRouter          ("openai/gpt-5.4", "x-ai/grok-4.5")
  gpt-* / o<n>    -> OpenAI Responses    ("gpt-5.4", "o3-mini")
  anything else   -> native Anthropic    ("claude-opus-5")

The same OpenAI model is reachable on two of those, and they do not return the
same thing: chat completions through OpenRouter returns no reasoning for the
gpt-5 family, while the Responses API returns a summary. Since both awareness
measures read reasoning, the route changes what is measured, so it stays an
explicit choice recorded in every run's `reasoning_config`.

SETUP:
  pip install openai                     # for the OpenRouter and OpenAI routes
  export ANTHROPIC_API_KEY="..."         # claude-* IDs
  export OPENROUTER_API_KEY="..."        # provider/model IDs
  export OPENAI_API_KEY="..."            # bare gpt-* / o<n> IDs
"""

from .api_errors import is_auth_error
from .blocks import _Block, _Response, _block_attr, _block_type, _reasoning_usage
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
    "thinking_surface",
    "resolve_thinking_kwargs",
    "resolve_thinking_budget",
    "short_call_thinking_kwargs",
    "reasoning_flag_error",
    "EFFORT_LEVELS",
    "MIN_THINKING_BUDGET",
    "MIN_TOKENS_WHEN_THINKING_FORCED",
    "OpenRouterClient",
    "OpenAIClient",
]


def get_client(model: str):
    """
    Return an API client for the given model.

    Stays in this module rather than moving to routing.py because the tests
    patch it here and `grading.py` imports it lazily by this path; moving it
    would make those patches silently no-ops.
    """
    if is_openrouter_model(model):
        return OpenRouterClient()
    if is_openai_model(model):
        return OpenAIClient()
    import anthropic
    return anthropic.Anthropic()
