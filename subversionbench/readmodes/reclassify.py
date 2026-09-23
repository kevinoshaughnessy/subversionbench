"""
Re-deriving the concealment verdicts from answers already on disk.

The interrogation answers are fixed text; what they MEAN is a classifier's reading,
and that reading changes when the classifier or its prompt does. So this re-labels
saved answers rather than asking new questions.

Its write-back policy is its own, and the strictest: nothing is persisted until the
whole pass is known to be sound. A reclassification in which most classifier calls
failed has produced little but keyword fallbacks - the very verdicts this mode
exists to replace - and writing those over good ones destroys work while looking
like a result.
"""

import json
import os
import time

from ..config import (MAX_CLASSIFIER_FALLBACK_RATE,
                      MIN_CALLS_FOR_FALLBACK_RATE, VERSION)
from ..graders import grader_models, regrade_targets, store, view
from ..grading import MISALIGNED_ACTS
from ..rederive import rederive_free_measures
from .rescore import (_new_tally, _recheck_misrepresentation, _rescore_acts,
                      relabel_variant_answers)
from .selection import find_run_files_or_explain




def record_reanalysis(data: dict, mode: str, version: str) -> list:
    """
    Note on the run file that a read mode re-derived part of it, and under
    which version.

    WHY THE PER-ANSWER STAMP IS NOT ENOUGH
    --------------------------------------
    `classifier_version` covers the LLM verdicts, which is where a version
    difference changes a judgement. It does not cover what this mode re-derives
    for free: the awareness ordering, the quote grounding and the transient
    tampering are recomputed from the saved transcript on every pass, carry no
    provenance of their own, and are exactly as version-dependent - they are
    code reading a transcript.

    `analysis_version` is deliberately left where it is. It names the code that
    produced the episode, which is a fact about collection and does not become
    untrue when a verdict is re-read; overwriting it would lose the only record
    of what the model was actually run against.

    Deduplicated on (mode, version): re-running the same pass under the same
    version refreshes the timestamp rather than appending, so an operator
    working through a directory one batch group at a time does not accumulate a
    hundred identical entries.
    """
    history = [h for h in (data.get("reanalysis") or [])
               if isinstance(h, dict)]
    entry = {"mode": mode, "version": version,
             "at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    for existing in history:
        if (existing.get("mode"), existing.get("version")) == (mode, version):
            existing.update(entry)
            break
    else:
        history.append(entry)
    data["reanalysis"] = history
    return history


def _first_classifier_error(pending):
    """
    The first classifier error anywhere in a pass, for the abort message.

    Searches the VARIANT maps as well as the headline fields. It used to read
    the headline fields alone, so a pass whose only failure was on an extra
    phrasing printed "Fix the cause above" with no cause above it - which is
    exactly the shape of a targeted repair, since --reclassify re-labels a
    variant answer only when it needs one. An abort that will not say why is
    worse than the failure it is reporting.
    """
    for _path, data in pending:
        stored = data.get("analysis") or {}
        for analysis in (view(stored, m) for m in grader_models(stored)):
            first = _first_error_in(analysis)
            if first:
                return first
    return None


def _first_error_in(analysis: dict):
    """The first classifier error in one grader's view, or None."""
    for act in MISALIGNED_ACTS:
        key = act["followup_key"]
        groups = [analysis.get(key) or []]
        groups.extend((analysis.get(key + "_by_variant") or {}).values())
        for answers in groups:
            for answer in answers or []:
                if isinstance(answer, dict) and answer.get("classifier_error"):
                    return answer["classifier_error"]
    return None


def _relabel_extra_phrasings(analysis, grader_model, tally) -> None:
    # The EXTRA phrasings, which the loop above does not reach: they live in
    # a map beside the headline field and nothing re-labelled them until now.
    # Only the answers whose verdict came from the keyword floor, so a batch
    # that classified cleanly costs nothing here.
    variant_counts = relabel_variant_answers(
        analysis, MISALIGNED_ACTS, grader_model)
    tally['calls'] += variant_counts["calls"]
    tally['failures'] += variant_counts["failures"]
    tally['auth_error'] = tally['auth_error'] or variant_counts["auth_error"]
    tally['relabelled'] += variant_counts["relabelled"]
    tally['declined'] += variant_counts["declined"]


def _abort_on_auth(auth_error, grader_model) -> None:
    """
    Missing or rejected credentials fail every call identically.

    Carrying on would only convert the whole batch to keyword fallbacks.
    Nothing has been written at the point this is reached.
    """
    print(f"\n{'='*60}")
    print("RECLASSIFY ABORTED: the grader could not authenticate.")
    print(f"{'='*60}")
    print(f"\n{auth_error}")
    print(f"\nNothing written. Export the API key for "
          f"{grader_model} and re-run.")
    return 1


def _fail_closed(tally: dict, pending: list) -> int:
    """
    Whether this pass may be written at all. Nonzero means it may not.

    A reclassification in which most classifier calls failed has produced
    little but keyword fallbacks - the very verdicts this mode exists to
    replace. Writing those over good ones destroys work and looks like a
    result. Nothing is persisted until the whole pass is known to be sound.
    """
    classifier_calls, classifier_failures = tally["calls"], tally["failures"]
    fallback_rate = (classifier_failures / classifier_calls
                     if classifier_calls else 0)

    # TWO CONDITIONS, BECAUSE A RATE CANNOT EXPRESS THE SMALL CASE
    #
    # A pass whose every call failed has achieved nothing this mode exists for,
    # whether that is one call or ninety-five, so it is refused on the count
    # rather than on the rate. That is the criterion the real incident in
    # TestReclassifyFailsClosed needs, and it is sample-size independent.
    #
    # The rate then handles the PARTIAL failure - mostly-failed but not
    # entirely - and only once the sample can express it, which is what
    # MIN_CALLS_FOR_FALLBACK_RATE means. Below that a single bad roll reads as
    # 50% or 100% and aborted passes that had real repairs in them: a targeted
    # repair of one batch group makes as few as two calls, and the empty-reply
    # flakiness in grading/interrogation.py makes one of them failing ordinary.
    total_failure = bool(classifier_calls
                         and classifier_failures == classifier_calls)
    rate_too_high = (classifier_calls >= MIN_CALLS_FOR_FALLBACK_RATE
                     and fallback_rate > MAX_CLASSIFIER_FALLBACK_RATE)
    if total_failure or rate_too_high:
        limit = f"{MAX_CLASSIFIER_FALLBACK_RATE:.0%}"
        reason = ("every classifier call failed" if total_failure else
                  f"{fallback_rate:.0%} of them failed, over the {limit} limit")
        print(f"\n{'='*60}")
        print(f"RECLASSIFY FAILED: {classifier_failures} of "
              f"{classifier_calls} classifier call(s) failed - {reason}; "
              f"those verdicts are keyword fallbacks.")
        print(f"{'='*60}")
        first = _first_classifier_error(pending)
        if first:
            print(f"\nFirst error: {str(first)[:300]}")
        print("\nNothing written. Fix the cause above - a rate limit wants a "
              "larger --delay - and re-run.")
        return 1

    return 0


def _report_repairs(tally: dict, pending: list) -> None:
    """What this pass repaired, what failed, and what it declined to overwrite."""
    classifier_calls, classifier_failures = tally["calls"], tally["failures"]
    relabelled_variants, declined = tally["relabelled"], tally["declined"]
    if relabelled_variants:
        # Reported separately from the headline count because it is a different
        # repair: these answers had a verdict no classifier ever supplied, and
        # nothing re-labelled them before this existed.
        print(f"\n{relabelled_variants} extra-phrasing answer(s) re-labelled "
              f"from the saved text (keyword-floor verdicts replaced).")

    if classifier_failures:
        print(f"\n! {classifier_failures}/{classifier_calls} classifier "
              f"call(s) failed and fell back to keywords.")
        first = _first_classifier_error(pending)
        if first:
            # Printed on the surviving path too, not just the abort. A pass
            # that writes while reporting failures still owes the operator the
            # reason - it is what says whether to re-run or to fix something.
            print(f"  first error: {str(first)[:300]}")

    if declined:
        # The answers a failed call was NOT allowed to overwrite. Reported
        # because it is the difference between "re-graded" and "left alone",
        # and a silent no-op would look like a successful repair.
        print(f"\n{declined} answer(s) kept the verdict they already had: the "
              f"call failed on this pass and a keyword fallback must not "
              f"replace a classifier verdict.")


def _persist(write_back: bool, pending: list, changed: list,
             run_files: list) -> int:
    if write_back:
        for path, data in pending:
            with open(path, "w") as f:
                json.dump(data, f, indent=2, default=str)

    print(f"\n{len(changed)}/{len(run_files)} episode(s) changed verdict.")
    if write_back:
        print("Run files updated in place.")
    else:
        print("Run files NOT modified (pass --write-back to persist).")
    return 0


def reclassify_one(data: dict, model: str, tally: dict):
    """Re-score one grader's concealment reading of one run, in `data`.

    The grader's view is re-scored with the same functions this mode always
    used, then folded back as that grader's entry - every other grader's entry
    is untouched. Returns (scheming before, scheming after, levels).
    """
    stored = data.get("analysis") or {}
    analysis = view(stored, model)
    before = analysis.get("scheming")

    # Back-fill the act flag for runs predating the script hash.
    if "oversight_tampered" not in analysis:
        analysis["oversight_tampered"] = bool(
            analysis.get("monitoring_disabled")
        )

    has_report = data.get("ended_by") != "turn_cap"
    if analysis.get("oversight_tampered") and has_report:
        _recheck_misrepresentation(analysis, data, model, tally)
    _rescore_acts(analysis, data, has_report, model, tally)
    _relabel_extra_phrasings(analysis, model, tally)

    rederive_free_measures(analysis, data.get("transcript") or [],
                           bool(data.get("lure")))
    data["analysis"] = store(stored, analysis, model)
    levels = {act["name"]: analysis.get(act["level_key"])
              for act in MISALIGNED_ACTS if analysis.get(act["key"])}
    return before, analysis["scheming"], levels


def reclassify_existing_runs(args, selection) -> int:
    """
    Re-score the interrogations in run files already on disk.

    The answers, the transcript and the act flags are all saved, so the
    concealment scale can be recomputed without re-running a single episode.
    That matters because the classifier is the part most likely to need
    revising after you have read real replies.

    Runs saved before the oversight artefacts were both hashed only know
    whether monitoring.yaml changed; their `oversight_tampered` is taken from
    `monitoring_disabled`, so an episode that edited only the quality-check
    script still cannot be recovered from those files.
    """
    run_files = find_run_files_or_explain(args, selection)
    if run_files is None:
        return 1

    print(f"\n{'='*60}")
    print(f"RECLASSIFY: {selection.model} | nudge={selection.nudge}")
    print(f"classifier: --regrade {args.regrade}")
    print(f"{'='*60}")

    changed, pending = [], []
    tally = _new_tally()

    for path in run_files:
        with open(path) as f:
            data = json.load(f)
        for model in regrade_targets(args.regrade, data.get("analysis") or {}):
            before, after, levels = reclassify_one(data, model, tally)
            if tally["auth_error"]:
                _abort_on_auth(tally["auth_error"], model)
                return 1
            flip = " CHANGED" if after != before else ""
            print(f"  {os.path.basename(path):55s} [{model}] "
                  f"scheming {before} -> {after}{flip}  {levels}")
            if after != before:
                changed.append(f"{os.path.basename(path)} [{model}]")
        record_reanalysis(data, "reclassify", VERSION)
        pending.append((path, data))

    refused = _fail_closed(tally, pending)
    if refused:
        return refused

    _report_repairs(tally, pending)
    return _persist(args.write_back, pending, changed, run_files)
