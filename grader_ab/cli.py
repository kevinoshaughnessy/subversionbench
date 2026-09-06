"""The command line: the sample, the cells, the abort, and the advice.

Every guard here runs before a single grader call, which is the only
reason it is worth having: the experiment is graders x shapes x episodes,
so an unguarded run against the wrong directory spends real money to
discover there was nothing there.
"""

import argparse
import collections
import json
import os
import sys
import time

from subversionbench.api_errors import api_error_message, usage_limit_reset
from subversionbench.config import RUBRIC_QUESTIONS, ROLLOUT_VERSION
from subversionbench.grading import check_quote_grounding, _normalise_quote
from subversionbench.grading.grader_io import new_channel_id
from subversionbench import llm_client
from subversionbench.redaction import redact_paths

from . import cost, readout, sampling, shapes
from .prices import (HARD_PHRASING_MODELS, PRICES_PER_MTOK, REFERENCE)


def _build_parser():
    parser = argparse.ArgumentParser(
        description="Cross grader model against grader call shape.")
    parser.add_argument("--output-dir",
                        default=f"./eval_results_{ROLLOUT_VERSION}",
                        help="results directory holding the transcripts to "
                             "re-grade (default: %(default)s)")
    parser.add_argument("--graders", nargs="+",
                        default=["claude-opus-5", "claude-sonnet-5"],
                        help="grader models to cross the shapes with")
    parser.add_argument("--shapes", nargs="+", default=sorted(shapes.SHAPES),
                        choices=sorted(shapes.SHAPES),
                        help="call shapes to cross the graders with")
    parser.add_argument("--per-model", type=int, default=4,
                        help="episodes per model, before oversampling "
                             "(default: %(default)s)")
    parser.add_argument("--models", nargs="+", default=None,
                        help="only these evaluated models (default: every one "
                             "in the directory)")
    parser.add_argument("--oversample", nargs="+", default=list(HARD_PHRASING_MODELS),
                        help="models to draw double from - those whose "
                             "awareness is phrased unusually")
    parser.add_argument("--no-balance", action="store_true",
                        help="sample at the corpus's natural aware rate instead "
                             "of balancing on the stored verdict. Measures "
                             "precision well and recall badly")
    parser.add_argument("--limit", type=int, default=None,
                        help="cap the total sample, round-robin across models")
    parser.add_argument("--delay", type=float, default=0,
                        help="seconds after every API CALL, not every episode. "
                             "The per_question shape fires nine calls per "
                             "episode back to back, which is the burst a "
                             "per-minute limit catches - and a throttled call "
                             "is recorded as an unanswered question")
    parser.add_argument("--dry-run", action="store_true",
                        help="print the sample and the call count, make no "
                             "API calls")
    return parser


def _select_sample(args):
    """
    (candidates, sample), or None with the reason printed.

    Both refusals run before a single grader call, which is the only reason
    they are worth having: the experiment is graders x shapes x episodes.
    """
    candidates = sampling.load_candidates(args.output_dir)
    if not candidates:
        print(f"No episodes with a stored grader verdict in "
              f"{redact_paths(args.output_dir)}/")
        return None
    sample = sampling.stratified_sample(
        candidates, args.per_model, models=args.models,
        oversample=set(args.oversample), balance=not args.no_balance,
        limit=args.limit)
    if not sample:
        print("The sample is empty - check --models against what is in the "
              "directory.")
        return None
    return candidates, sample


def _print_plan(args, candidates, sample, per_episode_calls, total_calls) -> bool:
    """What this run will cost, before it costs it. False means stop."""
    by_model = collections.Counter(c["model"] for c in sample)
    aware = sum(1 for c in sample if c["stored_aware"])
    print(f"{len(candidates)} candidate episode(s) in "
          f"{redact_paths(args.output_dir)}/")
    print(f"sample: {len(sample)} episode(s) over {len(by_model)} model(s), "
          f"{aware} stored-aware / {len(sample) - aware} not")
    for model, n in sorted(by_model.items()):
        mark = "  (oversampled)" if model in set(args.oversample) else ""
        print(f"    {model:34} {n:3}{mark}")
    print(f"\ncells: {len(args.graders)} grader(s) x {len(args.shapes)} shape(s)")
    for g in args.graders:
        for s in args.shapes:
            tag = "   <- reference" if (g, s) == REFERENCE else ""
            print(f"    {g:26} {s:14} "
                  f"{per_episode_calls[s] * len(sample):5} calls{tag}")
    print(f"\n{total_calls} API calls in total")
    if args.dry_run:
        print("\n--dry-run: nothing was called. Drop the flag to run it.")
        return False
    return True


class _ResultFile:
    """
    Where this run's cells are written, and when.

    The name is stamped with what varied and computed ONCE, before any call is
    made, so every cell in this run writes to the same file rather than each
    getting its own timestamp - which is what lets the incremental save cover
    the whole run rather than only its last cell. A fixed name cost a full
    145-episode 2x2 result the moment a one-episode probe of a different cell
    ran against the same --output-dir: the probe's write silently replaced it.
    """

    def __init__(self, args, sample):
        self._args = args
        self._sample = sample
        self.stored = {ep["run"]: ep["stored_rubric"] for ep in sample}
        graders_tag = "+".join(g.removeprefix("claude-")
                               for g in sorted(args.graders))
        shapes_tag = "+".join(sorted(args.shapes))
        self.path = os.path.join(
            args.output_dir,
            f"grader_ab_{graders_tag}_{shapes_tag}_n{len(sample)}_"
            f"{time.strftime('%Y%m%dT%H%M%S')}.json")

    def save(self, results, cell_costs, complete):
        # Called after every cell, not only at the end, so a killed run keeps
        # whatever it already paid for. The full 2x2 that preceded this run was
        # lost entirely to a kill with nothing on disk, because the old code
        # wrote once, at the very end.
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump({
                "output_dir": redact_paths(os.path.abspath(self._args.output_dir)),
                "reference_cell": "|".join(REFERENCE),
                "graders": self._args.graders,
                "shapes": self._args.shapes,
                "balanced_on_stored_verdict": not self._args.no_balance,
                "oversampled": sorted(set(self._args.oversample)),
                "sample": [{k: ep[k] for k in
                            ("run", "model", "nudge", "oversight", "lure",
                             "stored_aware")} for ep in self._sample],
                "cells": results,
                "cell_costs_usd": cell_costs,
                "complete": complete,
                "stored_rubrics": self.stored,
            }, f, indent=2, default=str)


def _run_cell(args, sample, grader, shape, client, out_path, cell):
    """
    One (grader, shape) cell: every episode of the sample, graded.

    Returns (rubrics, usage, unmeasured), or None when a fatal error stopped it
    partway - nothing is reported for such a cell, because a partial cell
    cannot be compared against a full one.
    """
    asker = shapes.SHAPES[shape]
    rubrics, usage, unmeasured = {}, [], []
    for i, ep in enumerate(sample):
        channel_id = new_channel_id()
        rubric = asker(ep["corpus"], grader, client, channel_id,
                       delay=args.delay, usage_sink=usage,
                       unmeasured_sink=unmeasured)
        shown = _normalise_quote(ep["corpus"])
        for entry in rubric.values():
            entry["quote_grounded"] = (
                check_quote_grounding(entry.get("quote") or "", shown,
                                      ep["scenario"])
                if entry.get("answer") else None)
        rubrics[ep["run"]] = rubric

        # STOP rather than grind on. An auth failure or an exhausted
        # usage limit fails every remaining call the same way, and the
        # report renders perfectly from zero successful ones: every rate
        # a dash, every verdict unanswered. That reads like a finding
        # instead of like a run that never happened, which is exactly
        # what the one-call smoke test of this script produced before
        # this check existed.
        fatal = shapes.fatal_error_kind(rubric)
        if fatal:
            first = next(v["error"] for v in rubric.values()
                         if v.get("error"))
            print(f"\n\n  ABORTING on a {fatal} error at episode "
                  f"{i + 1}/{len(sample)} of cell {cell}:")
            print(f"    {api_error_message(first)}")
            print(f"\n  {sum(len(r) for r in rubrics.values())} answer("
                  f"s) were attempted. Nothing is reported for this "
                  f"cell, because a partial cell cannot be compared "
                  f"against a full one - but every EARLIER cell is "
                  f"saved, at {redact_paths(out_path)}.")
            if fatal == "usage_limit":
                reset = usage_limit_reset(first)
                if reset:
                    print(f"  The limit resets at {reset}.")
            return None

        fired = sum(1 for r in rubrics.values()
                    if readout.cell_verdict(r) is True)
        errs = sum(1 for r in rubrics.values()
                   if any(v.get("answer") is None for v in r.values()))
        spend = cost.cell_cost(usage, grader)
        cost_str = (f"${spend['usd']:.2f}{'+' if spend['is_floor'] else ''}"
                   if spend["usd"] is not None else "$?")
        sys.stdout.write(f"\r    {i + 1}/{len(sample)} episodes  "
                         f"aware={fired}  with-errors={errs}  "
                         f"cost={cost_str}   ")
        sys.stdout.flush()
    print()
    return rubrics, usage, unmeasured


def _cell_spend(usage, grader, unmeasured) -> dict:
    """What one cell cost, and what that total may be missing."""
    c = cost.cell_cost(usage, grader)
    c["n_unmeasured_calls"] = len(unmeasured)
    if unmeasured:
        # These are calls ask_per_question could not even tell were
        # billed - see its docstring. Not folded into is_floor, which
        # already means something narrower (a known-incomplete
        # record); this means an unknown number of records are
        # missing outright, so the total below may be short by more
        # than the "+" on an is_floor total discloses.
        c["is_floor"] = True
    if c["usd"] is not None:
        note = " (input only - output not measured on this shape)" \
            if c["is_floor"] and not unmeasured else ""
        if unmeasured:
            note = (f" ({len(unmeasured)} call(s) errored with no "
                    f"usage recorded - may be billed and missing "
                    f"from this total)")
        print(f"    cell total: ${c['usd']:.2f}{note}")
    return c


def _run_grid(args, sample, result_file):
    """Every cell, saved as each finishes. (results, costs), or None if one died."""
    clients, results, cell_costs = {}, {}, {}
    for grader in args.graders:
        priced = grader in PRICES_PER_MTOK
        priced = grader in PRICES_PER_MTOK
        if not priced:
            print(f"\n  ! no price entry for {grader!r} in PRICES_PER_MTOK - "
                  f"cost will show as unknown, not zero. Add it if you want "
                  f"this run's spend tracked.")
        for shape in args.shapes:
            cell = f"{grader}|{shape}"
            print(f"\n  [{cell}]")
            client = clients.setdefault(grader, llm_client.get_client(grader))
            graded = _run_cell(args, sample, grader, shape, client,
                               result_file.path, cell)
            if graded is None:
                return None
            rubrics, usage, unmeasured = graded
            results[cell] = rubrics
            cell_costs[cell] = _cell_spend(usage, grader, unmeasured)
            result_file.save(results, cell_costs, complete=False)
    return results, cell_costs


def _print_spend(cell_costs) -> None:
    """What the whole run cost, and whether that total is a floor."""
    total = sum(c["usd"] for c in cell_costs.values() if c["usd"] is not None)
    any_floor = any(c["is_floor"] for c in cell_costs.values())
    any_unpriced = any(c["usd"] is None for c in cell_costs.values())
    print(f"Total spend this run: ${total:.2f}"
          f"{'+' if any_floor else ''}"
          f"{'  (plus unpriced cells - see cell_costs_usd)' if any_unpriced else ''}")


def _print_how_to_read_it(args, results) -> None:
    """What each comparison would mean, named before anyone reads the numbers."""
    print("\nReading the result:")
    ref = "|".join(REFERENCE)
    other_graders = [g for g in args.graders if g != REFERENCE[0]]
    said_something = False
    if ref not in results:
        only = next(iter(results))
        print(f"  {only} was run with no {ref} cell alongside it, so it has "
              f"nothing to be read against. Add {REFERENCE[0]!r} to --graders "
              f"to compare - it costs whatever this cell just cost, since both "
              f"use the same shape(s) and sample.")
        said_something = True
    elif other_graders:
        print(f"  {'/'.join(other_graders)} agrees with {ref} within the "
              f"noise floor -> the cheaper grader holds; take it, re-grade "
              f"everything")
        said_something = True
    if "batched" in args.shapes and "per_question" in args.shapes:
        print("  batched slopes downward across positions, or signal "
              "agreement rises")
        print("  against its own per_question cell")
        print("      -> batching is costing accuracy; keep nine calls")
        print("  batched flat and agreeing, on every grader tested")
        print("      -> the shape is free; move ask_rubric_batch into "
              "grading/grader.py,")
        print("         record it in score_provenance, and re-grade the "
              "corpus")
        said_something = True
    if not said_something:
        print(f"  One cell ({next(iter(results))}), nothing to compare it "
              f"against. Add a second --graders or --shapes value, or add "
              f"{REFERENCE[0]!r} for the reference.")
    if not said_something:
        print(f"  One cell ({next(iter(results))}), nothing to compare it "
              f"against. Add a second --graders or --shapes value, or add "
              f"{REFERENCE[0]!r} for the reference.")


def main():
    args = _build_parser().parse_args()

    chosen = _select_sample(args)
    if chosen is None:
        return 1
    candidates, sample = chosen

    keys = list(RUBRIC_QUESTIONS)
    per_episode_calls = {"per_question": len(keys), "batched": 1}
    total_calls = sum(per_episode_calls[s] for s in args.shapes) * \
        len(args.graders) * len(sample)
    if not _print_plan(args, candidates, sample, per_episode_calls,
                       total_calls):
        return 0

    result_file = _ResultFile(args, sample)
    grid = _run_grid(args, sample, result_file)
    if grid is None:
        return 1
    results, cell_costs = grid

    readout.report(results, sample, keys, result_file.stored)
    result_file.save(results, cell_costs, complete=True)
    print(f"\nSaved to {redact_paths(result_file.path)}")
    _print_spend(cell_costs)
    _print_how_to_read_it(args, results)
    return 0
