"""
Which API serves a model ID.

One job, and it is a leaf: the reasoning table, both client adapters and the
factory all need to ask this question, and none of them may import each other.

The OpenRouter and OpenAI routes overlap deliberately. "openai/gpt-5.4" and
"gpt-5.4" are the same model reached two ways, and they do not return the same
thing - chat completions through OpenRouter returns no reasoning for the gpt-5
family, while the Responses API returns a summary. Both awareness measures read
reasoning, so the route changes what is measured and has to stay selectable.
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
