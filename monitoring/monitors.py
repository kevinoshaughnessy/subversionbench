"""
The monitors under evaluation, and the provider each OpenRouter one is pinned to.

The latest model in each developer's cheapest fast tier. Pinned by the rule
docs/models.md gives for agents (Provider routing), for the same reason: one
model on several hosts is several deployments, and a monitor's scores should be
one deployment's. Every result row records the provider that served it
(`served_by`), so a pin can be checked rather than trusted.

Chosen 2026-11-06 from OpenRouter's endpoint data. Every endpoint below had
100% uptime over the previous day.
"""

MONITORS = {
    # Native routes: no OpenRouter provider to pin.
    "claude-haiku-5-5": None,
    # There is no gpt-6.1-luna: OpenAI announced none and OpenRouter lists none.
    "gpt-6-luna": None,
    # Step 2, the developer's own endpoint; the pin its goal-guarding agent
    # arms were collected on.
    "z-ai/glm-5.3-flash": "Z.AI",
    # Step 2; the pin its agent episodes were collected on.
    "google/gemini-3.8-flash": "google-ai-studio",
    # DeepSeek lists no endpoint of its own, so step 3: the fastest priced at
    # no more than twice the cheapest per call (7,800 input and 170 output
    # tokens, the first pilot's mean). Throughput is not in the public endpoint
    # data, so among the three within that price Morph is chosen as the one
    # not quantised to 4 bits. Together, which served the model's own agent
    # episodes, is 19 times the cheapest and outside the rule.
    "deepseek/deepseek-v4.1-flash": "morph",
}


def pinned_provider(monitor: str, override: str = None):
    """The provider a monitor's calls go to: `override` if given, else its pin."""
    if override:
        return override
    if monitor not in MONITORS:
        raise ValueError(f"{monitor!r} is not a listed monitor; pass "
                         f"--openrouter-provider to run it unpinned on purpose, "
                         f"or add it to monitoring/monitors.py")
    return MONITORS[monitor]
