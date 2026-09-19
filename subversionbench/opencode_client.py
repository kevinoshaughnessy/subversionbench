"""
OpenCode Zen adapter: the same OpenAI-compatible chat-completions shape as
OpenRouter, reached through a different gateway.

Confirmed live rather than assumed, 2026-09-19: an unauthenticated POST to
OPENCODE_BASE_URL's /chat/completions returns
{"error":{"type":"AuthError","message":"Missing API key."}}, and the same
request with a bogus `Authorization: Bearer` token returns "Invalid API
key" instead of that - the same standard OpenAI-compatible request shape
and Bearer auth OpenRouterClient already sends, so every translation it
does (messages, tools, tool-call parsing, reasoning capture, the non-JSON
and no-choices diagnostics) applies unchanged and is inherited rather than
duplicated here.

Two things do differ, and both are handled in this file rather than by
teaching OpenRouterClient a second mode:

  - CREDENTIAL AND BASE URL. OPENCODE_API_KEY and OPENCODE_BASE_URL, not
    OpenRouter's.

  - MODEL ID SHAPE. This corpus's OpenRouter IDs are vendor-prefixed
    ("x-ai/grok-4.5"); Zen's own /v1/models listing (checked live the same
    day) carries no such prefix ("grok-4.5"), so the vendor segment is
    stripped before the id reaches the wire. Not every model this corpus
    reaches through OpenRouter is on Zen's curated list - one that strips
    to an id Zen does not serve fails at request time with Zen's own
    "model not found" error, the same as asking for any other wrong model
    id would, rather than silently answering from a different model.

Deliberately NOT sent: OpenRouter's `extra_body.provider` routing hints
(sort / pin-to-backend / require_parameters). That is an OpenRouter-specific
extension with no evidence Zen understands it, and --openrouter-sort /
--openrouter-provider are OpenRouter concepts with no OpenCode equivalent -
episode.py's _resolved_routing nulls both before a client is built here, so
this class never has to decide what to do with them.
"""

import os

from .config import OPENCODE_BASE_URL
from .openrouter_client import OpenRouterClient, _base_request_kwargs


def _opencode_model_id(model: str) -> str:
    """Zen's bare model id for an OpenRouter-shaped one.

    "x-ai/grok-4.5" -> "grok-4.5". A model id with no "/" (already bare)
    passes through unchanged, on the same terms as is_openrouter_model():
    only a vendor-prefixed id is ever routed to a client that needs this
    translation in the first place.
    """
    return model.partition("/")[2] or model


class OpenCodeClient(OpenRouterClient):
    """OpenRouterClient, pointed at OpenCode Zen's gateway instead.

    Subclassed rather than parameterised: `create()`, `_completion()` and
    the response-block parsing are gateway-agnostic and worth inheriting
    unchanged, but __init__ (credential, base URL) and _request_kwargs
    (model id shape, no `provider` routing dict) are both genuinely
    different from the OpenRouter route, and sending OpenRouter's own
    `extra_body.provider` hints to a gateway with no documented equivalent
    is a risk this class avoids by never building that dict at all.
    """

    _GATEWAY_NAME = "OpenCode"

    def __init__(self):
        import openai

        api_key = os.environ.get("OPENCODE_API_KEY")
        if not api_key:
            raise RuntimeError(
                "OPENCODE_API_KEY environment variable not set. "
                "Get a key at https://opencode.ai/auth"
            )
        # Same retry/timeout reasoning as OpenRouterClient.__init__: a long
        # agentic-loop call is more prone to a mid-response reset than a
        # short one, and the SDK's 600s default read timeout could otherwise
        # stall a batch for max_retries x 600s on one degraded call.
        self._client = openai.OpenAI(
            base_url=OPENCODE_BASE_URL, api_key=api_key, max_retries=5,
            timeout=240,
        )
        self.messages = self
        # Kept so the two clients are duck-type identical for any caller
        # (e.g. a test) that reads these attributes without checking which
        # class it has - OpenCode has no equivalent of either, so both stay
        # unconditionally None/unused rather than settable.
        self._provider_sort = None
        self._provider_name = None

    def _request_kwargs(self, model, max_tokens, system, tools, messages) -> dict:
        """The Anthropic-shaped call, translated to OpenAI-compatible JSON -
        Zen's own model id, and no `provider` routing dict."""
        return _base_request_kwargs(_opencode_model_id(model), max_tokens,
                                    system, tools, messages)
