"""
Re-measuring the KIND of suspicion with the model that was the episode.

Whether an episode is eval-aware at all is a judgement a capable grader gets
right, and the five rubric questions that decide it are not what varies between
models. Which words imply suspicion of a SAFETY evaluation rather than a
CAPABILITY one is the reading that does: it turns on what a model meant by its
own phrasing, and the model that wrote the phrase has a claim to read it better
than a third party.

So this mode re-measures the kind ALONE. It takes `eval_aware` from the verdict
already in the run file and asks the episode's own model the two purpose
questions - the pair that was already held outside `_EVAL_SIGNAL_KEYS` so that
it could not move the awareness rate. Two calls per aware episode, none at all
for the rest.

WHAT IT WRITES, and what it must never touch. The result goes to
`analysis.awareness_kind_self`, never to `analysis.eval_awareness_grader`.
The two are different instruments, and this project has already measured one
grader being wrong for one model - see docs/methodology.md#validating-the-grader
- so a second, unvalidated reading must not become the column every report
reads.
"""

import datetime
import json
import os
import time

from .. import grading as grading_api
from ..graders import view
from ..batch import unique_batch_stamp
from ..config import CANARY, VERSION
from ..redaction import redact_paths
from .selection import find_run_files_or_explain

SELF_KIND_FIELD = "awareness_kind_self"


def _primary_awareness(analysis: dict):
    """
    (eval_aware, kind) from the primary grader, or (None, None) if it has no
    usable verdict.

    None rather than False for a failed or absent grading: an episode nothing
    measured must not be read as one measured and found unaware, which is the
    same absence-is-not-a-no rule the rest of the harness applies. Without a
    primary verdict there is no awareness to condition on and nothing to
    compare a re-measured kind against, so the episode is skipped rather than
    asked about.
    """
    grader = analysis.get("eval_awareness_grader") or {}
    if grader.get("grading_failed") or grader.get("eval_aware") is None:
        return None, None
    return bool(grader["eval_aware"]), grader.get("eval_awareness_kind")


def _grade_one(path: str, model: str, write_back: bool) -> dict:
    """Re-measure one episode's kind. Returns a row, or None if skipped."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    transcript = data.get("transcript")
    if not transcript:
        print("  Skipped: no transcript in this file.")
        return None

    # The DEFAULT grader's verdict is the primary one; see graders.py. Only
    # read through the view - the write below is to this mode's own field.
    eval_aware, primary_kind = _primary_awareness(
        view(data.get("analysis") or {}))
    if eval_aware is None:
        print("  Skipped: no primary grader verdict to take awareness from.")
        return None
    if not eval_aware:
        # THE SAVING, and the reason this mode exists in this shape. An
        # unaware episode has no kind by construction, so there is nothing to
        # re-measure and nothing a call could find.
        print("  Skipped: not eval-aware, so there is no kind to categorise.")
        return None

    block = grading_api.detect_awareness_kind(transcript, True, model)
    block["eval_aware_from"] = "eval_awareness_grader"
    kind = block["eval_awareness_kind"]

    if kind is None:
        print(f"  UNDETERMINED: {block.get('undetermined')}")
    else:
        agree = "agrees" if kind == primary_kind else "DIFFERS from"
        print(f"  kind={kind}  ({agree} primary {primary_kind!r})")

    if write_back and kind is not None:
        data.setdefault("analysis", {})[SELF_KIND_FIELD] = block
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, default=str)
        print(f"  Written to analysis.{SELF_KIND_FIELD}")

    return {"run_file": os.path.basename(path),
            "primary_kind": primary_kind,
            "self_kind": kind,
            "undetermined": block.get("undetermined"),
            SELF_KIND_FIELD: block}


def self_grade_kinds(args, selection) -> int:
    """
    Re-measure the awareness kind for one (model, nudge) batch, with that
    model as its own grader. Returns a process exit code.
    """
    run_files = find_run_files_or_explain(args, selection)
    if run_files is None:
        return 1

    model = selection.model
    print(f"\n{'='*60}")
    print(f"SELF-GRADE KIND: {selection.model} | nudge={selection.nudge}")
    print(f"grader:  {model} (the episode's own model)")
    print(f"asks:    {', '.join(grading_api.PURPOSE_KEYS)}")
    print(f"writes:  analysis.{SELF_KIND_FIELD} - "
          f"analysis.eval_awareness_grader is never touched")
    print(f"{'='*60}")
    print(f"\n{len(run_files)} run file(s); only the eval-aware ones cost "
          f"anything.")

    t_start = time.time()
    rows = []
    for i, path in enumerate(run_files):
        print(f"\n--- {os.path.basename(path)} ({i+1}/{len(run_files)}) ---")
        row = _grade_one(path, model, args.write_back)
        if row is None:
            continue
        rows.append(row)
        if args.delay and i < len(run_files) - 1:
            time.sleep(args.delay)

    return _report(args, selection, model, rows, len(run_files),
                   round(time.time() - t_start, 1))


def _agreement(rows: list) -> dict:
    """
    How often the model's own reading of its words matched the primary's.

    Over the episodes where BOTH produced a kind: an undetermined
    re-measurement is not a disagreement, and counting it as one would make a
    grader that failed look like a grader that dissented.
    """
    both = [r for r in rows if r["self_kind"] and r["primary_kind"]]
    if not both:
        return {"n": 0}
    pairs = {}
    for r in both:
        pairs[(r["primary_kind"], r["self_kind"])] = 1 + pairs.get(
            (r["primary_kind"], r["self_kind"]), 0)
    return {
        "n": len(both),
        "agreed": sum(1 for r in both if r["primary_kind"] == r["self_kind"]),
        "pairs": {f"{p} -> {s}": n for (p, s), n in sorted(pairs.items())},
    }


def _report(args, selection, model: str, rows: list, n_files: int,
            elapsed: float) -> int:
    """Print what the pass found and save it beside the runs."""
    asked = len(rows)
    determined = [r for r in rows if r["self_kind"] is not None]
    agreement = _agreement(rows)

    print(f"\n{'='*60}")
    print(f"SELF-GRADE KIND SUMMARY: {selection.model} | "
          f"nudge={selection.nudge}")
    print(f"{'='*60}")
    print(f"\nRun files:              {n_files}")
    print(f"Eval-aware, asked:      {asked}  "
          f"({asked * len(grading_api.PURPOSE_KEYS)} API call(s))")
    print(f"Kind determined:        {len(determined)}")
    if asked and not determined:
        # Every question failed on every aware episode. Not a finding about
        # the model's reading of its words - a finding about the calls.
        print("\nNothing was determined: every purpose question failed on "
              "every aware episode. No kind recorded.")
        return 1
    if agreement["n"]:
        print(f"Agreed with primary:    {agreement['agreed']}/"
              f"{agreement['n']}")
        for pair, n in agreement["pairs"].items():
            print(f"    {pair:34s} {n}")
    elif asked:
        print("No episode produced a kind under both readings, so there is "
              "nothing to compare.")
    else:
        print("\nNo eval-aware episodes in this batch, so nothing was asked "
              "and nothing was spent.")
    print(f"\nTotal elapsed:          {elapsed}s")

    document = {
        "canary": CANARY,
        "mode": "self_grade_kind",
        "model": selection.model,
        "nudge": selection.nudge,
        "grader_model": model,
        "asks": list(grading_api.PURPOSE_KEYS),
        "eval_aware_from": "eval_awareness_grader",
        "n_run_files": n_files,
        "n_asked": asked,
        "n_determined": len(determined),
        "n_api_calls": asked * len(grading_api.PURPOSE_KEYS),
        "agreement_with_primary": agreement,
        "wrote_back_to_run_files": bool(args.write_back),
        "runs": rows,
        "timing": {"total_elapsed_seconds": elapsed},
        "timestamp": datetime.datetime.now().isoformat(),
        "version": VERSION,
    }
    stamp = unique_batch_stamp(args.output_dir)
    out = (f"{args.output_dir}/kindself_{selection.model_slug}"
           f"_{selection.nudge}_{stamp}.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(document, f, indent=2, default=str)
    print(f"\nSaved to {redact_paths(out)}")
    if not args.write_back:
        print("Run files were not modified (pass --write-back to record the "
              "kinds).")
    return 0
