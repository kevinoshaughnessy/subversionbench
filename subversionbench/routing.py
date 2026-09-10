"""
Which API serves a model ID.

One job, and it is a leaf: the reasoning table, both client adapters and the
factory all need to ask this question, and none of them may import each other.

The OpenRouter and OpenAI routes overlap deliberately. "openai/gpt-5.4" and
"gpt-5.4" are the same model reached two ways, and the choice has to stay
selectable because it changes what the harness CONTROLS: the Responses route
sends an effort and asks for a reasoning summary, while the OpenRouter route
sends no reasoning parameter at all, so effort is whatever the model does by
default. Both return a summary, never the trace. Every run records which, in
`reasoning_config`.

WHAT IT DOES NOT CHANGE IS WHETHER REASONING COMES BACK. This said, until it
was measured, that chat completions through OpenRouter returns no reasoning for
the gpt-5 family. Across the 240 OpenRouter episodes of gpt-5.6-luna in r9 and
r10 - the only gpt-5-family model in either corpus - not one has empty
reasoning, at a median near 1,800 characters. Omitting the parameter suppresses
nothing. A model may still decline, and gpt-5.4's zero is that model
withholding rather than this route: a per-model fact, not a property of the
route.

docs/methodology.md, "Reasoning exposure and the provider route", had this
right, and so did reasoning.py, whose OpenRouter config string was corrected on
the same evidence. This file, openai_client.py and llm_client.py were missed,
which is how one correction left four sites disagreeing with two.
"""

import re


def is_openrouter_model(model: str) -> bool:
    """A "provider/model" ID goes through OpenRouter."""
    return "/" in model


def is_openai_model(model: str) -> bool:
    """
    Whether to route this ID to OpenAI's own API.

    Bare IDs only: a provider prefix keeps the model on OpenRouter, which is
    what makes the two routes comparable against each other.
    """
    if is_openrouter_model(model):
        return False
    name = model.strip().lower()
    return name.startswith("gpt-") or bool(re.match(r"^o\d", name))
