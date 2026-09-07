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
from .prices import PRICES_PER_MTOK


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
    effective_in = usage["read"] * 0.1 + usage["written"] * 1.25 + usage["uncached"]
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
    effective_in = usage["read"] * 0.1 + usage["written"] * 1.25 + usage["uncached"]
    return effective_in * price_in / 1e6
