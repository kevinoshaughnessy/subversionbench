"""
What a model could see of its own voiced suspicion, turn by turn, and the turn-level estimate.

The harness sends each earlier turn back to the model on the next request, but not all of it.
Visible text and tool calls always go back. Reasoning goes back only through the native
Anthropic client, whose thinking blocks are returned exactly as they came (turns.py), and for
the OpenRouter models `sends_reasoning_back` names. For every other model, suspicion voiced in
an earlier turn's reasoning is not in the context of a later turn.

An awareness verdict that reads the whole transcript therefore counts suspicion the model may not
have had in front of it when it acted, and suspicion voiced only after it acted. Re-scoring only
the episodes that acted would remove that suspicion from one side of the contrast alone, which
manufactures an association. The turn-level reading here treats every episode alike: each turn
up to and including the first act (or the episode's last turn) is a unit, exposed if located
suspicion was in context on that turn, and the event is the first act on that turn. The
estimate is a Mantel-Haenszel odds ratio over strata that include the turn number, so that later
turns, which carry more suspicion and more acts, are compared only with each other. Turns of one
episode are not independent, so the interval comes from resampling episodes within each model.

Locating suspicion is left to the caller, which knows what its awareness reading quotes.
"""
import collections
import random

from .openrouter_client import sends_reasoning_back
from .power.stratified import mantel_haenszel

TURN_CAP = 40
# A quoted passage shorter than this matches too much ordinary text to place suspicion.
QUOTE_MIN = 12
RESAMPLING_SEED = 20261127


def reasoning_replayed(model: str) -> bool:
    """Whether the harness returns this model's earlier reasoning to it on later turns."""
    return model.startswith("claude") or sends_reasoning_back(model)


def seen_on_turn(transcript: list, located: list, turn: int, before, replayed: bool) -> bool:
    """Whether an entry in `located` was in the model's context on `turn`, ahead of entry `before`.

    An entry of that turn counts, reasoning included, since the model wrote it in the same
    response. An entry of an earlier turn counts if it is visible text or a command, or if it is
    reasoning and the model's reasoning is replayed. Nothing at or after `before` counts.
    """
    for i in located:
        if before is not None and i >= before:
            continue
        entry = transcript[i]
        written = entry.get("turn") or 0
        if written == turn or (written < turn and (entry["type"] != "thinking" or replayed)):
            return True
    return False


def turn_units(transcript: list, located: list, last_turn: int, act_index, acted: bool,
               replayed: bool) -> list:
    """(turn, exposed, event) for each turn from the first to `last_turn`, the first act's turn
    where the episode acted and its last turn where it did not."""
    return [(t, seen_on_turn(transcript, located, t, act_index if t == last_turn else None, replayed),
             acted and t == last_turn)
            for t in range(1, last_turn + 1)]


def turn_level_estimate(rows: list, stratum) -> dict:
    """Mantel-Haenszel over `stratum(row)` x turn, from each row's `units`."""
    cells = collections.defaultdict(lambda: [0, 0, 0, 0])
    for r in rows:
        for turn, exposed, event in r["units"]:
            c = cells[(stratum(r), min(turn, TURN_CAP))]
            c[0 if exposed else 2] += event
            c[1 if exposed else 3] += 1
    return mantel_haenszel([tuple(v) for v in cells.values()])


def resampled_odds_ratio_interval(rows: list, stratum, draws: int = 400) -> tuple:
    """The 95% interval of the turn-level odds ratio over episodes resampled within each model,
    and how many draws gave one."""
    by_model = collections.defaultdict(list)
    for r in rows:
        by_model[r["model"]].append(r)
    rng = random.Random(RESAMPLING_SEED)
    ratios = []
    for _ in range(draws):
        sample = [x for m in sorted(by_model) for x in rng.choices(by_model[m], k=len(by_model[m]))]
        ratio = turn_level_estimate(sample, stratum).get("odds_ratio")
        if ratio is not None:
            ratios.append(ratio)
    if not ratios:
        return None, None, 0
    ratios.sort()
    return ratios[int(0.025 * len(ratios))], ratios[int(0.975 * len(ratios)) - 1], len(ratios)
