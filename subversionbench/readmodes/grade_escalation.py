"""
Adding `escalated` to episodes already collected.

`--grade-escalation` asks --grader-model the two escalation questions about each
episode's closing report (grading/closing_report.detect_escalation) and stores
the answer as `analysis["escalation"]`. Nothing at collection asks them: the
measure belongs to the impossible-task scenario, where a model that leaves the
check alone and refers it is the outcome no act measure can see, and asking it
of every mainline episode would pay for an answer nothing reads.

Only an episode the model ended with a closing turn is asked - its settled
ending (endings.py) is `model_stopped`. The first pass over the fourth pilot
asked them all, and gemini-3.5-flash's episodes that ended on a provider error,
an empty turn or a leaked tool call were answered "no" about a placeholder or a
command: a report never written read as a model that did not escalate. An
answer stored on an episode that does not qualify is withdrawn, so that pass's
answers do not outlive the rule.

Without --write-back it is a plan, as --grade-category is. A pass resumes for
free - an episode answered under the current wording is skipped, an unmeasured
one is never written so the next pass asks again, and an answer to an earlier
wording of the questions is asked again.
"""

import json
import os

from ..endings import settled_ending
from ..grading import ESCALATION_INSTRUMENT, detect_escalation
from .selection import find_run_files_or_explain

ESCALATION_KEY = "escalation"


def _load(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _save(path: str, data: dict) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str)
    os.replace(tmp, path)


def _plan(path: str) -> str:
    """"ask", "withdraw" (holds an answer it must not), or "skip"."""
    data = _load(path)
    stored = (data.get("analysis") or {}).get(ESCALATION_KEY)
    if settled_ending(data) != "model_stopped":
        return "withdraw" if stored is not None else "skip"
    current = (stored or {}).get("instrument") == ESCALATION_INSTRUMENT
    return "skip" if current and stored["escalated"] is not None else "ask"


def _withdraw(path: str) -> None:
    data = _load(path)
    del data["analysis"][ESCALATION_KEY]
    _save(path, data)


def _grade_one(path: str, model: str) -> dict:
    """Ask, and save the answer unless neither half settled it."""
    data = _load(path)
    result = detect_escalation(data["transcript"], model=model)
    if result["escalated"] is not None:
        data.setdefault("analysis", {})[ESCALATION_KEY] = result
        _save(path, data)
    return result


def grade_escalation_runs(args, selection) -> int:
    """Add `escalated` to the selected run files. Returns an exit code."""
    run_files = find_run_files_or_explain(args, selection)
    if run_files is None:
        return 1
    plans = {p: _plan(p) for p in run_files}
    todo = [p for p, plan in plans.items() if plan == "ask"]
    stale = [p for p, plan in plans.items() if plan == "withdraw"]
    print(f"\n{'=' * 60}\nESCALATION GRADE: {selection.model} | "
          f"nudge={selection.nudge}\ngrader: {args.grader_model}\n{'=' * 60}")
    print(f"{len(run_files)} run file(s); {len(todo)} to grade, "
          f"{2 * len(todo)} call(s); {len(stale)} answer(s) to withdraw from "
          f"episodes with no closing turn; the rest already answered or with "
          f"no closing turn.")
    if not (todo or stale):
        return 0
    if not args.write_back:
        print("Plan only: nothing was called or changed. Add --write-back to "
              "grade and save.")
        return 0
    for path in stale:
        _withdraw(path)
    return _grade(todo, args.grader_model)


def _grade(todo: list, model: str) -> int:
    tally = {"escalated": 0, "shortfall only": 0, "neither": 0, "failed": 0}
    for path in todo:
        result = _grade_one(path, model)
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
