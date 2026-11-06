"""
Adding the headline awareness reading to episodes already collected.

`--grade-category` asks a model the category question (CATEGORY_INSTRUMENT)
about each episode's whole text and about the text before each act, and stores
the answers as that grader's awareness-only entry beside the readings already
there. The model is HEADLINE_AWARENESS_GRADER unless `--category-grader` names
another; each grader's reading is its own entry, so a second one leaves the
first as it was. One call per episode and one per distinct act
position, against the nine-question rubric and every interrogation label a
`--grade-existing` regrade would re-run.

Without --write-back it is a plan: it counts the calls and makes none, since a
pass that spends without saving buys nothing. A pass resumes for free - an
episode whose reading is already stored and did not fail is skipped, and a
failed call is never written, so the next pass asks it again.

Each file is written the moment its calls return, never at the end of the
pass. Until v250 every file was submitted first - `--delay` slept between
submissions - and the results were read only once the last had gone in: at the
default delay of 30 seconds a pass over the ~10.8k-episode corpus would have
saved nothing for about 90 hours, could not stop on a fatal error until every
call had been made, and on Ctrl-C ran the whole queue to completion and wrote
none of it. Now at most --concurrency calls are in flight, --delay paces the
launches, and an interrupt cancels what has not started and saves what has.
"""

import concurrent.futures
import json
import os
import time

from ..config import CATEGORY_INSTRUMENT
from ..grading.category import (FATAL_ERROR_KINDS as _FATAL_ERRORS,
                                calls_needed, category_reading)
from ..graders import (awareness_keys, graders_of, is_awareness_only,
                       store_awareness, view)
from .selection import find_run_files_or_explain


# _plan's answer for a file the headline grader has already read in FULL, by
# the rubric: store_awareness refuses to replace that reading with an
# awareness-only one, so asking would pay for a call that cannot be saved.
_HOLDS_FULL_READING = "holds a full reading"


def _stored_blocks(analysis: dict, model: str) -> dict:
    """The awareness blocks `model` already holds from this instrument that
    did not fail - the ones a resumed pass keeps rather than pays for again."""
    working = view(analysis, model)
    return {k: working[k] for k in awareness_keys()
            if (working.get(k) or {}).get("instrument") == CATEGORY_INSTRUMENT
            and not working[k].get("grading_failed")}


def _plan(path: str, model: str):
    """(calls this file needs, blocks already stored), None to skip it, or
    _HOLDS_FULL_READING for a file it must not write to."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not data.get("transcript"):
        return None
    analysis = data.get("analysis") or {}
    if any(e["grader_model"] == model and not is_awareness_only(e)
           for e in graders_of(analysis)):
        return _HOLDS_FULL_READING
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
    model = args.category_grader
    plans = {p: _plan(p, model) for p in run_files}
    full = [p for p, plan in plans.items() if plan == _HOLDS_FULL_READING]
    todo = {p: plan for p, plan in plans.items()
            if plan and plan != _HOLDS_FULL_READING and plan[0]}
    n_calls = sum(plan[0] for plan in todo.values())
    print(f"\n{'=' * 60}\nCATEGORY GRADE: {selection.model} | "
          f"nudge={selection.nudge}\ngrader: {model} ({CATEGORY_INSTRUMENT})"
          f"\n{'=' * 60}")
    print(f"{len(run_files)} run file(s); "
          f"{len(run_files) - len(todo) - len(full)} already hold this reading "
          f"or have no transcript; {len(todo)} to grade, {n_calls} call(s).")
    if full:
        print(f"! {len(full)} file(s) skipped: {model} already holds a full "
              f"rubric reading of them, which an awareness-only reading would "
              f"replace and lose its concealment labels.")
    if not todo:
        return 0
    if not args.write_back:
        print("Plan only: nothing was called. Add --write-back to grade and "
              "save.")
        return 0
    return _grade(args, model, todo)


def _launch_next(pool, remaining, futures: dict, model: str, pace: dict) -> bool:
    """Submit the next file, `pace["delay"]` seconds after the previous
    launch's turn. False when nothing is left to submit.

    Paced on every launch but the first, not only while another is in flight:
    at --concurrency 1 nothing is in flight when the next launch comes round,
    so a gap conditioned on that would never be taken."""
    item = next(remaining, None)
    if item is None:
        return False
    if pace["launched"] and pace["delay"]:
        time.sleep(pace["delay"])
    pace["launched"] += 1
    path, (_n, done) = item
    futures[pool.submit(_read_one, path, model, done)] = path
    return True


def _absorb(path: str, blocks: dict, model: str, tally: dict):
    """Count and save one file's blocks. Returns the fatal error kind a call
    hit, if any, which every remaining call would repeat."""
    episode = blocks["eval_awareness_grader"]
    if not episode.get("grading_failed"):
        tally["graded"] += 1
        tally["aware"] += bool(episode["eval_aware"])
        tally["fragment"] += episode.get("quote_grounded") == "fragment"
    # EVERY block, not just the episode's. A pre-act call that failed is left
    # out of the write like any failure, and was once left out of the count
    # too - so a pass with failed calls printed "failed 0" and exited 0, and
    # nothing said a re-run was needed.
    failed = sorted(k for k, b in blocks.items() if b.get("grading_failed"))
    if failed:
        tally["failed"] += 1
        error = next((blocks[k].get("error") for k in failed
                      if blocks[k].get("error")), "")
        print(f"  failed: {os.path.basename(path)} ({', '.join(failed)}): "
              f"{(error or '')[:120]}")
    _write(path, model, blocks)
    kinds = {b.get("error_kind") for b in blocks.values()}
    return next((k for k in _FATAL_ERRORS if k in kinds), None)


def _grade(args, model: str, todo: dict) -> int:
    tally = {"graded": 0, "aware": 0, "failed": 0, "fragment": 0}
    workers = max(1, getattr(args, "concurrency", 1) or 1)
    remaining = iter(todo.items())
    pace = {"delay": args.delay, "launched": 0}
    futures = {}
    fatal = None
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=workers)
    try:
        while len(futures) < workers and _launch_next(
                pool, remaining, futures, model, pace):
            pass
        while futures:
            done, _ = concurrent.futures.wait(
                list(futures), return_when=concurrent.futures.FIRST_COMPLETED)
            for future in done:
                fatal = _absorb(futures.pop(future), future.result(), model,
                                tally) or fatal
            while fatal is None and len(futures) < workers and _launch_next(
                    pool, remaining, futures, model, pace):
                pass
    except KeyboardInterrupt:
        # What has started keeps running and is paid for whether or not
        # anyone waits, so it is waited for and saved; what has not, is not.
        running = {f: p for f, p in futures.items() if not f.cancel()}
        print(f"\nInterrupted: saving the {len(running)} call(s) in flight.")
        for future in concurrent.futures.as_completed(running):
            _absorb(running[future], future.result(), model, tally)
        _print_tally(tally)
        return 130
    finally:
        pool.shutdown(wait=True, cancel_futures=True)
    _print_tally(tally)
    if fatal:
        print(f"\nSTOPPED: a call failed with '{fatal}', which every remaining "
              f"call would repeat. Everything graded so far is saved; fix it "
              f"and re-run to continue.")
        return 1
    return 1 if tally["failed"] else 0


def _print_tally(tally: dict) -> None:
    print(f"\nGraded {tally['graded']}, aware {tally['aware']}; "
          f"{tally['failed']} file(s) with a failed call (not written; a "
          f"re-run asks again); {tally['fragment']} deciding quote(s) only a "
          f"fragment of the text.")
