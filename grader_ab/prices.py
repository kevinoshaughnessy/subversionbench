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
PRICES_PER_MTOK = {
    "claude-opus-5": (5.0, 25.0),
    "claude-sonnet-5": (3.0, 15.0),
    "claude-fable-5": (10.0, 50.0),
    "claude-haiku-4-5": (1.0, 5.0),
    "claude-haiku-4-5-20251001": (1.0, 5.0),
}
