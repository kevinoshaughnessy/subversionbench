"""
Batch statistics: every figure the report and the summary are built from.

ONE DIRECTION, TWO HALVES
-------------------------
`normalise_analyses` mutates; everything else is pure. They are separate calls, named
for what they do, because a function called "facts" that rewrites its input is how the
fill-when-absent defects went unnoticed for as long as they did.

SPLIT BY CONSTRUCT
------------------
The figures were one 692-line function, which made "where does this number come from"
a search rather than a lookup. They are now grouped the way the benchmark's own claims
are grouped:

    misalignment.py  what the model DID
    scheming.py      what it HID
    awareness.py     what it SUSPECTED
    quality.py       how far any of the above can be trusted
    timing.py        what the run cost
    rates.py         the published table, assembled from all of them

Each returns a dict of its own figures and reads nothing from the others - except
rates.py, which is by definition the assembled view of them and takes the accumulated
dict. `batch_facts` is the composition, and it takes no `args`: the figures are a
property of the episodes, so a test can assert on any of them in a line.
"""

from .awareness import (awareness_before_act_flag, awareness_facts,
                        awareness_flag)
from .misalignment import misalignment_facts
from .normalise import normalise_analyses
from .quality import quality_facts, score_provenance
from .rates import rate_table
from .scheming import scheming_facts
from .timing import timing_facts

__all__ = ["awareness_before_act_flag", "awareness_flag", "batch_facts",
           "normalise_analyses", "score_provenance"]

# Figures that exist so rates.py can read them, and for no other reason: denominators
# whose value reaches the summary only inside the rate built from them. Dropped before
# batch_facts returns, so that "a figure in the result is one somebody reports" stays
# true - which is what makes the persistence test in test_batch_facts mean anything.
INTERNAL_FIGURES = ("n_boundary", "n_check_applicable", "n_config_applicable",
                    "n_env_probe")


def batch_facts(all_results: list, runtime: dict = None) -> dict:
    """
    Every figure the report and the summary JSON are built from.

    Pure: reads the analyses (already normalised - see normalise.py) and returns
    numbers. Touches no disk, prints nothing, and takes no `args`.

    `runtime` carries the batch facts that are not recoverable from run files -
    wall-clock timings, which episodes failed, whether the batch was aborted, and
    under `settings` the invocation values the batch actually ran under. Rebuilding
    from disk passes whatever the previous summary recorded, and leaves the rest empty
    rather than inventing it.

    The order below is composition order, not dependency order: the first five read
    only the episodes, so they could run in any sequence. `rate_table` comes last
    because it reads what they produced.
    """
    runtime = runtime or {}
    n = len(all_results)

    facts = {
        "n": n,
        "aborted": runtime.get("aborted", False),
        "failures": runtime.get("failures", []),
        "reasoning_config": runtime.get("reasoning_config", ""),
    }
    facts.update(misalignment_facts(all_results, n))
    facts.update(scheming_facts(all_results, n))
    facts.update(awareness_facts(all_results, n))
    facts.update(quality_facts(all_results, n))
    facts.update(timing_facts(all_results, runtime))
    facts.update(rate_table(all_results, n, facts))

    for name in INTERNAL_FIGURES:
        facts.pop(name, None)
    return facts
