"""What a cell cost, and what it could not price.

Three kinds of not-knowing, deliberately not collapsed into one: a model
with no price entry (unknown), a shape that does not report output tokens
(a floor), and calls that errored before any usage record existed (an
unknown NUMBER of records missing). None is ever reported as zero.
"""

# READ from prices.py, not restated. This module held a second copy of the
# table, and the two were read by different callers: `__init__` and cli.py
# resolve PRICES_PER_MTOK from prices.py to decide whether a grader is priced
# at all, while the arithmetic below read this file's own copy. So the check
# and the thing checked could disagree - add a model to one and the CLI reports
# it as priced while the cost comes back None, or the reverse.
#
# Both copies also carried a comment asserting that "no pricing table exists
# elsewhere in this repository (grep confirms it)", which the second copy had
# made false. The surviving one is in prices.py, where the table is.
from subversionbench.routing import is_openai_model, is_openrouter_model

from .prices import (CACHE_READ_MULTIPLIER, PRICES_PER_MTOK,
                     STANDARD_CACHE_READ_MULTIPLIER)

# What a cache write costs on the native Anthropic route, where `uncached`
# excludes the written tokens and they are billed separately at this multiple.
_ANTHROPIC_CACHE_WRITE_MULTIPLIER = 1.25


def _effective_input_tokens(usage: dict, model: str) -> float:
    """Input tokens weighted by what each kind actually costs.

    Extracted because the exact and floor prices below both need it, and a
    second copy of this line is a second place the cache discount can go stale
    - which is the defect PRICES_PER_MTOK itself already had once, when
    cost.py and prices.py each held a table and different callers read each.

    WRITTEN TOKENS ARE ALREADY INSIDE `uncached` OFF THE NATIVE ROUTE, which
    usage.py's docstring records and deliberately leaves in place. Adding
    them again billed each one twice: a real explicit-cache call to gpt-6-sol
    came back read 0, written 2812, uncached 2841 on a 2,841-token prompt,
    and was priced at about 2.2x its input. Corrected here rather than in
    usage.py, because saved episodes carry `uncached` under that meaning.
    """
    read = CACHE_READ_MULTIPLIER.get(model, STANDARD_CACHE_READ_MULTIPLIER)
    if is_openai_model(model) or is_openrouter_model(model):
        # ponytail: an OpenAI-shaped write is priced at the plain input rate
        # it already carries inside `uncached`. OpenAI's explicit-cache write
        # premium, if any, is not known here; when it is, add the excess over
        # 1.0 as `written * (multiplier - 1)`.
        return usage["read"] * read + usage["uncached"]
    return (usage["read"] * read
            + usage["written"] * _ANTHROPIC_CACHE_WRITE_MULTIPLIER
            + usage["uncached"])


def usage_cost_usd(usage: dict, model: str) -> float | None:
    """Dollars for one call's usage record, or None when the model has no
    entry in PRICES_PER_MTOK.

    None rather than 0.0 on purpose - a missing price is an unknown cost, and
    reporting it as free would be worse than not reporting it at all.
    """
    prices = PRICES_PER_MTOK.get(model)
    if prices is None or usage is None:
        return None
    price_in, price_out = prices
    effective_in = _effective_input_tokens(usage, model)
    output = usage.get("output")
    out_cost = output * price_out / 1e6 if output is not None else None
    in_cost = effective_in * price_in / 1e6
    return in_cost + out_cost if out_cost is not None else None


def cell_cost(usage_records: list, model: str) -> dict:
    """Running dollar total for one cell's calls so far.

    {"usd": float|None, "is_floor": bool, "n_unpriced": int}. `usd` is None
    only when the model has no PRICES_PER_MTOK entry - a record with no
    measured output (the per_question shape) still contributes its known input
    cost, folded into `is_floor` instead, so a caller gets a real number with
    an honest caveat rather than nothing.
    """
    if model not in PRICES_PER_MTOK:
        return {"usd": None, "is_floor": False, "n_unpriced": len(usage_records)}
    total, is_floor = 0.0, False
    for u in usage_records:
        exact = usage_cost_usd(u, model)
        if exact is not None:
            total += exact
        else:
            total += usage_cost_floor_usd(u, model) or 0.0
            is_floor = True
    return {"usd": total, "is_floor": is_floor, "n_unpriced": 0}


def usage_cost_floor_usd(usage: dict, model: str) -> float | None:
    """Input-only cost - what is knowable when `usage["output"]` is None.

    That happens on the per_question shape: it goes through the shipped
    `ask_rubric_question`, which does not expose output_tokens, so a model
    that cannot disable thinking has an unmeasured and possibly large output
    cost on this shape specifically. Called out by name rather than silently
    substituting 0 for the missing half.
    """
    prices = PRICES_PER_MTOK.get(model)
    if prices is None or usage is None:
        return None
    price_in, _ = prices
    return _effective_input_tokens(usage, model) * price_in / 1e6
