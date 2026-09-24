"""The numbers this experiment is configured by, and the reason each is
what it is.

Their own module rather than the package __init__, so a submodule can
read them without importing the package that imports the submodule.
"""


# The reference cell: what the corpus was graded with. Everything is compared
# against this, and it is re-run rather than read so the comparison carries its
# own noise floor.
REFERENCE = ("claude-opus-5", "per_question")

# Models whose awareness the free keyword screen catches least often - 18% to
# 32% recall against the grader, where the corpus average is 72%. Their
# awareness is phrased in ways a literal match misses, which makes them where a
# weaker grader or a contaminated batch should fail first. Named here rather
# than left to a proportional sample, which would be dominated by the models
# whose phrasing is easy.
HARD_PHRASING_MODELS = (
    "google/gemini-3.5-flash",
    "qwen/qwen3.6-27b",
    "x-ai/grok-4.5",
    "x-ai/grok-4.6",
)

# Per-answer token room, matched to the shipped per-question call so the batched
# cell is not handicapped by a tighter budget than the thing it is compared
# against.
_TOKENS_PER_ANSWER = 200

# $ per million tokens, (input, output). A SNAPSHOT copied from the model
# table current when this script was written, not derived from any API - no
# pricing table exists elsewhere in this repository (grep confirms it; cost is
# estimated in a prose comment in config.py and nowhere computed). Re-check
# before trusting a run made long after this file was last touched, and treat
# an unpriced model as a real unknown, not a $0.
#
# Last re-checked against the published pricing page on 2026-09-22. That check
# found claude-sonnet-5 stale at (3.0, 15.0): the $2/$10 announced as
# introductory pricing became the standard price, and the increase to $3/$15
# scheduled for 2026-09-01 was cancelled. It is the DEFAULT second grader, so
# every cell it priced between that date and this one was overstated by 1.5x.
# Which is the argument for the re-check note above being acted on rather than
# read: nothing here expires on its own.
PRICES_PER_MTOK = {
    "claude-opus-5-5": (4.0, 20.0),
    "claude-opus-5": (5.0, 25.0),
    "claude-sonnet-5": (2.0, 10.0),
    "claude-fable-5": (10.0, 50.0),
    "claude-haiku-4-5": (1.0, 5.0),
    "claude-haiku-4-5-20251001": (1.0, 5.0),
    # Bare, so routing.is_openai_model sends it to OpenAI's own Responses API
    # rather than OpenRouter - "openai/gpt-6-sol" would be the same model on
    # the other route and is deliberately not the same key, the distinction
    # model_releases.py keeps for the same reason.
    "gpt-6-sol": (2.0, 10.0),
    "gpt-6-luna": (0.1, 0.5),
}

# What a cached read costs as a fraction of the base input price. 0.1x is the
# standard multiplier and the default; Claude Opus 5.5 reads at 0.05x
# ($0.20/MTok against its $4 base), so a single hardcoded 0.1 would charge its
# reads at twice their real price - and on the per_question shape a re-grade is
# mostly cached reads of the same transcript. Keyed separately from the price
# tuple because only the READ multiplier varies: the 1.25x five-minute write
# applies to every model in the table, Opus 5.5 included.
CACHE_READ_MULTIPLIER = {"claude-opus-5-5": 0.05}
STANDARD_CACHE_READ_MULTIPLIER = 0.1
