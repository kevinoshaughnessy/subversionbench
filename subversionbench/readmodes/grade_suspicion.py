"""
Adding one of the two suspicion readings to episodes already collected.

`--grade-suspicion decision` asks, of every episode with an act that can be
placed, how suspicion voiced before the earliest such act relates to it;
`--grade-suspicion framing` asks, of every episode the headline reading calls
aware, what kind of test the agent took its situation to be (both in
grading/suspicion.py). The grader is --category-grader. Each answer is stored
under `analysis["suspicion"][question][grader]`, beside every other reading.

Without --write-back it is a plan, as --grade-category is. A pass resumes for
free - an episode holding this grader's answer under the current instrument is
skipped, and a failed call is never written, so the next pass asks again. Each
file is written as its call returns, and a fatal error stops the pass.
"""

import concurrent.futures
import json
import os

from ..config import HEADLINE_AWARENESS_GRADER
from ..graders import view
from ..grading.suspicion import (SUSPICION_KEY, instrument, suspicion_reading,
                                 suspicion_text)
from ..grading.category import FATAL_ERROR_KINDS
from .selection import find_run_files_or_explain


def _run_file(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _headline(data: dict) -> tuple:
    """(the flat analysis, the headline reading's whole-episode verdict)."""
    flat = view(data.get("analysis") or {}, HEADLINE_AWARENESS_GRADER)
    return flat, (flat.get("eval_awareness_grader") or {}).get("eval_aware")


def _stored(data: dict, question: str, model: str) -> dict:
    return ((data.get("analysis") or {}).get(SUSPICION_KEY, {})
            .get(question, {}).get(model) or {})


def _needs_asking(path: str, question: str, model: str) -> bool:
    data = _run_file(path)
    if not data.get("transcript"):
        return False
    stored = _stored(data, question, model)
    if (stored.get("instrument") == instrument(question)
            and not stored.get("grading_failed")):
        return False
    flat, aware = _headline(data)
    return suspicion_text(question, data["transcript"], flat, aware)[0] is not None


def _read_one(path: str, question: str, model: str) -> dict:
    """Runs on a worker thread and writes nothing."""
    data = _run_file(path)
    flat, aware = _headline(data)
    return suspicion_reading(question, data["transcript"], flat, aware, model)


def _write(path: str, question: str, model: str, block: dict) -> None:
    data = _run_file(path)
    analysis = data.setdefault("analysis", {})
    analysis.setdefault(SUSPICION_KEY, {}).setdefault(question, {})[model] = block
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str)
    os.replace(tmp, path)


def grade_suspicion_runs(args, selection) -> int:
    """Add the reading to the selected run files. Returns an exit code."""
    run_files = find_run_files_or_explain(args, selection)
    if run_files is None:
        return 1
    question, model = args.grade_suspicion, args.category_grader
    todo = [p for p in run_files if _needs_asking(p, question, model)]
    print(f"\n{'=' * 60}\nSUSPICION GRADE ({question}): {selection.model} | "
          f"nudge={selection.nudge}\ngrader: {model} ({instrument(question)})"
          f"\n{'=' * 60}")
    print(f"{len(run_files)} run file(s); {len(todo)} to grade, one call "
          f"each; the rest already answered or not asked this question.")
    if not todo:
        return 0
    if not args.write_back:
        print("Plan only: nothing was called. Add --write-back to grade and "
              "save.")
        return 0
    return _grade(todo, question, model, max(1, args.concurrency or 1))


def _grade(todo: list, question: str, model: str, workers: int) -> int:
    tally = {}
    failed = 0
    fatal = None
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_read_one, p, question, model): p for p in todo}
        for future in concurrent.futures.as_completed(futures):
            if future.cancelled():
                continue
            path, block = futures[future], future.result()
            if block["grading_failed"]:
                failed += 1
                print(f"  failed: {os.path.basename(path)}: "
                      f"{(block['error'] or '')[:120]}")
                if block["error_kind"] in FATAL_ERROR_KINDS:
                    fatal = block["error_kind"]
                    for f in futures:
                        f.cancel()
                continue
            tally[block["category"]] = tally.get(block["category"], 0) + 1
            _write(path, question, model, block)
    print("\n" + "; ".join(f"{k} {v}" for k, v in sorted(tally.items()))
          + f"; {failed} failed (not written; a re-run asks again).")
    if fatal:
        print(f"\nSTOPPED: a call failed with '{fatal}', which every remaining "
              f"call would repeat. Everything graded so far is saved.")
    return 1 if failed else 0
