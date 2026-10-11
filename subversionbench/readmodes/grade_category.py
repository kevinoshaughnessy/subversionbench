"""
Adding the headline awareness reading to episodes already collected.

`--grade-category` asks HEADLINE_AWARENESS_GRADER the category question
(CATEGORY_INSTRUMENT) about each episode's whole text and about the text before
each act, and stores the answers as that grader's awareness-only entry beside
the readings already there. One call per episode and one per distinct act
position, against the nine-question rubric and every interrogation label a
`--grade-existing` regrade would re-run.

Without --write-back it is a plan: it counts the calls and makes none, since a
pass that spends without saving buys nothing. A pass resumes for free - an
episode whose reading is already stored and did not fail is skipped, and a
failed call is never written, so the next pass asks it again.
"""

import concurrent.futures
import json
import os
import time

from ..config import CATEGORY_INSTRUMENT, HEADLINE_AWARENESS_GRADER
from ..grading.category import calls_needed, category_reading
from ..graders import awareness_keys, store_awareness, view
from .selection import find_run_files_or_explain

# A failure of either kind repeats on every remaining call, so the pass stops.
_FATAL_ERRORS = ("auth", "usage_limit")


def _stored_blocks(analysis: dict, model: str) -> dict:
    """The awareness blocks `model` already holds from this instrument that
    did not fail - the ones a resumed pass keeps rather than pays for again."""
    working = view(analysis, model)
    return {k: working[k] for k in awareness_keys()
            if (working.get(k) or {}).get("instrument") == CATEGORY_INSTRUMENT
            and not working[k].get("grading_failed")}


def _plan(path: str, model: str):
    """(calls this file needs, blocks already stored), or None to skip it."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not data.get("transcript"):
        return None
    analysis = data.get("analysis") or {}
    done = _stored_blocks(analysis, model)
    return calls_needed(view(analysis, model), data["transcript"], done), done


def _read_one(path: str, model: str, done: dict) -> dict:
    """The grader's blocks for one file. Runs on a worker thread; writes
    nothing, so the main thread is the only writer of any run file."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return category_reading(view(data.get("analysis") or {}, model),
                            data["transcript"], model, CATEGORY_INSTRUMENT,
                            done=done)


def _write(path: str, model: str, blocks: dict) -> None:
    """Store the blocks that did not fail. A failed block is left out, so the
    stored one - if any - stands, and the next pass asks again."""
    keep = {k: v for k, v in blocks.items()
            if v.get("skipped") or not v.get("grading_failed")}
    if not keep.get("eval_awareness_grader"):
        return
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    data["analysis"] = store_awareness(data.get("analysis") or {}, keep, model)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str)
    os.replace(tmp, path)


def grade_category_runs(args, selection) -> int:
    """Add the category reading to the selected run files. Returns an exit code."""
    run_files = find_run_files_or_explain(args, selection)
    if run_files is None:
        return 1
    model = HEADLINE_AWARENESS_GRADER
    plans = {p: _plan(p, model) for p in run_files}
    todo = {p: plan for p, plan in plans.items() if plan and plan[0]}
    n_calls = sum(plan[0] for plan in todo.values())
    print(f"\n{'=' * 60}\nCATEGORY GRADE: {selection.model} | "
          f"nudge={selection.nudge}\ngrader: {model} ({CATEGORY_INSTRUMENT})"
          f"\n{'=' * 60}")
    print(f"{len(run_files)} run file(s); {len(run_files) - len(todo)} already "
          f"hold this reading or have no transcript; {len(todo)} to grade, "
          f"{n_calls} call(s).")
    if not todo:
        return 0
    if not args.write_back:
        print("Plan only: nothing was called. Add --write-back to grade and "
              "save.")
        return 0
    return _grade(args, model, todo)


def _grade(args, model: str, todo: dict) -> int:
    tally = {"graded": 0, "aware": 0, "failed": 0, "fragment": 0}
    workers = max(1, getattr(args, "concurrency", 1) or 1)
    fatal = None
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {}
        for path, (_n, done) in todo.items():
            futures[pool.submit(_read_one, path, model, done)] = path
            if args.delay:
                time.sleep(args.delay)
        for future in concurrent.futures.as_completed(futures):
            if future.cancelled():
                continue
            path = futures[future]
            blocks = future.result()
            episode = blocks["eval_awareness_grader"]
            kinds = {b.get("error_kind") for b in blocks.values()}
            if fatal is None and kinds & set(_FATAL_ERRORS):
                fatal = next(k for k in _FATAL_ERRORS if k in kinds)
                for other in futures:
                    other.cancel()
            if episode.get("grading_failed"):
                tally["failed"] += 1
                print(f"  failed: {os.path.basename(path)}: "
                      f"{(episode.get('error') or '')[:120]}")
            else:
                tally["graded"] += 1
                tally["aware"] += bool(episode["eval_aware"])
                tally["fragment"] += episode.get("quote_grounded") == "fragment"
            _write(path, model, blocks)
    print(f"\nGraded {tally['graded']}, aware {tally['aware']}, failed "
          f"{tally['failed']} (not written; a re-run asks again); "
          f"{tally['fragment']} deciding quote(s) only a fragment of the text.")
    if fatal:
        print(f"\nSTOPPED: a call failed with '{fatal}', which every remaining "
              f"call would repeat. Everything graded so far is saved; fix it "
              f"and re-run to continue.")
        return 1
    return 1 if tally["failed"] else 0
