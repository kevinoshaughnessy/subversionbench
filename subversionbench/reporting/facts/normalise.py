"""
Bringing saved analyses up to the current definitions, in place.

The one MUTATING step in the reporting layer, and separate from everything that reads
its output for exactly that reason: a function named for its figures that rewrites its
input is the shape the fill-when-absent defects hid in.

Call this first. Every figure in this package reads a field it derives - the escape
nesting above all, since MISALIGNED_ACTS points the sandbox act at
`sandbox_boundary_excl_scratch`, and a batch collected before that field existed would
otherwise read as having taken no sandbox act at all.

The derivations themselves are NOT here. They live in `subversionbench/rederive.py`,
because two of their three callers are read modes rather than the report, and holding
them in the reporting package is what let --reclassify and --resummarise each grow
their own partial copy. This module is the report path's loop over that owner, and
nothing else.
"""

from ...rederive import rederive_free_measures


def normalise_analyses(all_results: list) -> list:
    """
    Bring every saved analysis up to the current definitions, in place.

    Re-derives every deterministic field from the saved transcript, then re-derives
    the verdicts via settle_analysis. The sampled judgements - the interrogation
    answers, the disclosure reading, the awareness rubric - are read and never
    written, which is the split --resummarise is built on.

    One episode at a time through `rederive_free_measures`, which is where the
    ordering, the guards and the evidence for each derivation live. That contract
    is the whole reason this function is three lines: a second implementation of
    it is what the read modes had, and what this is no longer able to drift from.

    Returns the same list it was given, for callers that want to chain.
    """
    for r in all_results:
        rederive_free_measures(r["analysis"], r.get("transcript") or [],
                               bool(r.get("lure")))
    return all_results
