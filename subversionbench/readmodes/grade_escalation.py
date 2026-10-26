"""
Adding `escalated` to episodes already collected.

`--grade-escalation` asks --grader-model the two escalation questions about each
episode's closing report (grading/closing_report.detect_escalation) and stores
the answer as `analysis["escalation"]`. Nothing at collection asks them: the
measure belongs to the impossible-task scenario, where a model that leaves the
check alone and refers it is the outcome no act measure can see, and asking it
of every mainline episode would pay for an answer nothing reads.

Without --write-back it is a plan, as --grade-category is. A pass resumes for
free - an episode holding an answer is skipped, and an unanswered one is never
written, so the next pass asks again. An episode that hit the turn cap wrote no
closing report and is not asked.
"""

import json
import os

from ..grading import detect_escalation
from .selection import find_run_files_or_explain

ESCALATION_KEY = "escalation"


def _needs_asking(path: str) -> bool:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    stored = (data.get("analysis") or {}).get(ESCALATION_KEY) or {}
    return (bool(data.get("transcript")) and data.get("ended_by") != "turn_cap"
            and stored.get("escalated") is None)


def _grade_one(path: str, model: str) -> dict:
    """Ask, and save the answer unless neither half settled it."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    result = detect_escalation(data["transcript"], model=model)
    if result["escalated"] is None:
        return result
    data.setdefault("analysis", {})[ESCALATION_KEY] = result
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str)
    os.replace(tmp, path)
    return result


def grade_escalation_runs(args, selection) -> int:
    """Add `escalated` to the selected run files. Returns an exit code."""
    run_files = find_run_files_or_explain(args, selection)
    if run_files is None:
        return 1
    todo = [p for p in run_files if _needs_asking(p)]
    print(f"\n{'=' * 60}\nESCALATION GRADE: {selection.model} | "
          f"nudge={selection.nudge}\ngrader: {args.grader_model}\n{'=' * 60}")
    print(f"{len(run_files)} run file(s); {len(run_files) - len(todo)} already "
          f"answered, turn-capped or without a transcript; {len(todo)} to "
          f"grade, {2 * len(todo)} call(s).")
    if not todo:
        return 0
    if not args.write_back:
        print("Plan only: nothing was called. Add --write-back to grade and "
              "save.")
        return 0
    tally = {"escalated": 0, "shortfall only": 0, "neither": 0, "failed": 0}
    for path in todo:
        result = _grade_one(path, args.grader_model)
        if result["escalated"] is None:
            tally["failed"] += 1
            print(f"  failed: {os.path.basename(path)}: "
                  f"{(result['error'] or '')[:120]}")
        elif result["escalated"]:
            tally["escalated"] += 1
        elif result["reports_shortfall"]:
            tally["shortfall only"] += 1
        else:
            tally["neither"] += 1
    print("\n" + "; ".join(f"{k} {v}" for k, v in tally.items())
          + " (a failed file is not written; a re-run asks again).")
    return 1 if tally["failed"] else 0
