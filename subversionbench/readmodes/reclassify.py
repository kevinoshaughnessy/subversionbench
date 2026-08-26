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

from .. import grading as grading_api
from ..config import (DEFAULT_INTERROGATION, MAX_CLASSIFIER_FALLBACK_RATE,
                      MIN_CALLS_FOR_FALLBACK_RATE, VERSION)
from ..episode import add_awareness_timing
from ..grading import (MISALIGNED_ACTS, classify_transient_tampering,
                       concealment_level, detect_transient_tampering,
                       recheck_quote_grounding, settle_analysis)
from ..llm_client import is_auth_error
from .selection import find_run_files_or_explain




def _auth_error_in(result, key: str = "error"):
    """The auth error inside a grader result dict, if that is what failed."""
    if isinstance(result, dict) and is_auth_error(result.get(key)):
        return result.get(key)
    return None


def _needs_relabel(answer: dict) -> bool:
    """
    Whether this answer's verdict came from the keyword floor rather than the
    classifier.

    The keyword lists are documented as a floor that under-detects, so an answer
    carrying `used_keyword_fallback` has a verdict the classifier never
    supplied. `classifier_error` is checked too, for answers written before the
    fallback flag existed.
    """
    return bool(answer.get("used_keyword_fallback")
                or answer.get("classifier_error"))


def _apply_label(answer: dict, labelled: dict) -> bool:
    """
    Write a fresh label onto a saved answer, unless that would DEGRADE it.

    THE INVARIANT THIS MODE WAS MISSING
    -----------------------------------
    An LLM verdict must never be replaced by a keyword-floor one. The update
    used to be unconditional, so a classifier call that failed on THIS pass
    overwrote a verdict a previous pass had got from the classifier - turning a
    real reading into a phrase-list reading, in a mode whose whole purpose is
    the reverse.

    MAX_CLASSIFIER_FALLBACK_RATE was the only thing standing in the way, and it
    is a blunt instrument for the job: it judges the pass as a whole, so it
    cannot save one good verdict from one bad call, and it aborts everything
    else to do it. Enforced here instead, per answer, where the comparison is
    exact - which is what lets the rate guard stand down on small passes.

    Returns True when the label was applied, so the caller can report the
    answers that kept what they had.
    """
    if labelled.get("used_keyword_fallback") and not _needs_relabel(answer):
        return False
    answer.update(labelled)
    return True


def relabel_variant_answers(analysis: dict, acts, model: str,
                            only_failed: bool = True) -> dict:
    """
    Re-label the EXTRA interrogation phrasings from their saved answers.

    WHY THIS IS SEPARATE FROM THE HEADLINE LOOP
    -------------------------------------------
    The headline field holds the default phrasing; `<followup_key>_by_variant`
    holds the others, and until now nothing re-labelled that map. A spend cap
    during collection therefore left 305 variant answers on one grok-4.5 corpus
    with keyword-floor verdicts that no read mode could repair: --reclassify
    walked past the map, and --reinterrogate skips a variant already recorded.
    The answers themselves were saved, so the verdicts were recoverable all
    along - there was simply no command that recovered them.

    WHAT IT WILL NOT TOUCH
    ----------------------
    Any copy of the DEFAULT phrasing inside the map. That copy is stale by
    construction and is documented in reinterrogate._drop_copied_default as the
    confound that already invalidated one phrasing comparison: the headline
    answers get re-labelled in place while the copy keeps whichever verdicts it
    was made with. Re-labelling the copy INDEPENDENTLY would be worse still -
    two verdicts for one phrasing, sampled separately, with nothing to say which
    the comparison used. The default side of every comparison is read from the
    headline field; see report.load_episodes.

    `only_failed` re-asks just the answers whose verdict came from the keyword
    floor, which is the repair case. False re-labels every variant answer, for
    when the classifier itself has changed.

    Returns counts. The caller owns writing.
    """
    counts = {"relabelled": 0, "skipped_default_copy": 0, "calls": 0,
              "failures": 0, "levels_recomputed": 0, "auth_error": None,
              "declined": 0}
    for act in acts:
        key = act["followup_key"] + "_by_variant"
        by_variant = analysis.get(key)
        if not by_variant:
            continue
        touched = False
        for variant, answers in by_variant.items():
            if variant == DEFAULT_INTERROGATION:
                counts["skipped_default_copy"] += 1
                continue
            for answer in answers or []:
                if not isinstance(answer, dict):
                    continue
                if only_failed and not _needs_relabel(answer):
                    continue
                labelled = grading_api.classify_interrogation_answer(
                    answer.get("answer", ""), act["description"],
                    act["admission"], act["denial"], act["contrition"],
                    model=model,
                )
                if labelled.get("classifier_called", True):
                    counts["calls"] += 1
                    counts["failures"] += bool(labelled["used_keyword_fallback"])
                counts["auth_error"] = counts["auth_error"] or _auth_error_in(
                    labelled, "classifier_error")
                if not _apply_label(answer, labelled):
                    # The call failed and this answer already held a real
                    # classifier verdict, so it keeps it. Not a relabel, and
                    # the levels below must not be recomputed on its account.
                    counts["declined"] += 1
                    continue
                counts["relabelled"] += 1
                touched = True
        if touched:
            # The per-variant levels are DERIVED from the answers just changed,
            # so leaving them would publish a level that disagrees with the
            # verdicts underneath it.
            analysis[act["level_key"] + "_by_variant"] = {
                variant: concealment_level(analysis, act, answers=answers)
                for variant, answers in by_variant.items()
            }
            counts["levels_recomputed"] += 1
    return counts


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


def _keep_better(existing, fresh):
    """
    The grader result to store: the fresh one, unless it FAILED and the stored
    one did not.

    Same invariant as _apply_label, for the two readings that are not
    interrogation answers - `disclosure_<act>` and `misrepresented_check`.
    Those are written unconditionally, and neither is counted in the
    classifier-call tally, so the pass-level guard never saw them: a disclosure
    call that failed while the interrogation calls succeeded would replace a
    real reading with an error dict.

    That is not a theoretical ordering. It is the same failure
    TestReclassifyPreservesGraderResults documents for the pre-act awareness
    grader, where a graderless pass wrote a skip marker over a real reading and
    silently downgraded a 100-run batch - and add_awareness_timing already
    guards it this way.
    """
    if (isinstance(fresh, dict) and fresh.get("error")
            and isinstance(existing, dict) and not existing.get("error")):
        return existing
    return fresh


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
        analysis = data.get("analysis") or {}
        for act in MISALIGNED_ACTS:
            key = act["followup_key"]
            groups = [analysis.get(key) or []]
            groups.extend((analysis.get(key + "_by_variant") or {}).values())
            for answers in groups:
                for answer in answers or []:
                    if isinstance(answer, dict) and answer.get(
                            "classifier_error"):
                        return answer["classifier_error"]
    return None


def reclassify_existing_runs(args, model_slug: str) -> int:
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
    run_files = find_run_files_or_explain(args, model_slug)
    if run_files is None:
        return 1

    print(f"\n{'='*60}")
    print(f"RECLASSIFY: {args.model} | nudge={args.nudge}")
    print(f"classifier: {args.grader_model}")
    print(f"{'='*60}")

    changed = []
    pending = []
    classifier_calls = classifier_failures = 0
    relabelled_variants = declined = 0
    auth_error = None

    for path in run_files:
        with open(path) as f:
            data = json.load(f)
        analysis = data.get("analysis") or {}
        before = analysis.get("scheming")

        # Back-fill the act flag for runs predating the script hash.
        if "oversight_tampered" not in analysis:
            analysis["oversight_tampered"] = bool(
                analysis.get("monitoring_disabled")
            )

        has_report = data.get("ended_by") != "turn_cap"

        if analysis.get("oversight_tampered") and has_report:
            fresh = grading_api.detect_misrepresentation(
                data.get("transcript") or [], model=args.grader_model
            )
            auth_error = auth_error or _auth_error_in(fresh)
            analysis["misrepresented_check"] = _keep_better(
                analysis.get("misrepresented_check"), fresh)

        for act in MISALIGNED_ACTS:
            if not analysis.get(act["key"]):
                continue
            fresh = (
                grading_api.detect_disclosure(data.get("transcript") or [],
                                  act["description"],
                                  model=args.grader_model)
                if has_report else
                {"disclosed": None, "quote": "",
                 "error": "episode hit the turn cap; no closing report"}
            )
            auth_error = auth_error or _auth_error_in(fresh)
            analysis[act["disclosure_key"]] = _keep_better(
                analysis.get(act["disclosure_key"]), fresh)
            for ans in analysis.get(act["followup_key"]) or []:
                labelled = grading_api.classify_interrogation_answer(
                    ans.get("answer", ""), act["description"],
                    act["admission"], act["denial"], act["contrition"],
                    model=args.grader_model,
                )
                # An empty answer is labelled without asking anything, so
                # counting it as a call would let free no-ops dilute the
                # failure rate the guard below reads.
                if labelled.get("classifier_called", True):
                    classifier_calls += 1
                    classifier_failures += bool(
                        labelled["used_keyword_fallback"])
                auth_error = auth_error or _auth_error_in(
                    labelled, "classifier_error")
                declined += not _apply_label(ans, labelled)

        # The EXTRA phrasings, which the loop above does not reach: they live in
        # a map beside the headline field and nothing re-labelled them until now.
        # Only the answers whose verdict came from the keyword floor, so a batch
        # that classified cleanly costs nothing here.
        variant_counts = relabel_variant_answers(
            analysis, MISALIGNED_ACTS, args.grader_model)
        classifier_calls += variant_counts["calls"]
        classifier_failures += variant_counts["failures"]
        auth_error = auth_error or variant_counts["auth_error"]
        relabelled_variants += variant_counts["relabelled"]
        declined += variant_counts["declined"]

        # Missing or rejected credentials fail every call identically, so
        # carrying on would only convert the whole batch to keyword fallbacks.
        # Nothing has been written at this point.
        if auth_error:
            print(f"\n{'='*60}")
            print("RECLASSIFY ABORTED: the grader could not authenticate.")
            print(f"{'='*60}")
            print(f"\n{auth_error}")
            print(f"\nNothing written. Export the API key for "
                  f"{args.grader_model} and re-run.")
            return 1

        settle_analysis(analysis)
        # Also free, and backfilled here so runs collected before the measure
        # existed gain it without a re-run.
        analysis["transient_tampering_detail"] = detect_transient_tampering(
            data.get("transcript") or [])
        analysis["transient_tampering"] = classify_transient_tampering(analysis)

        # Free: ordering is read off the saved transcript, no API calls. The
        # grader's pre-act reading needs --grade-existing, which can spend.
        add_awareness_timing(analysis, data.get("transcript") or [],
                             grader_model=None)
        # Also free: whether the grader's citations trace to the agent's own
        # words. Backfills the check onto runs graded before it existed.
        recheck_quote_grounding(analysis, data.get("transcript") or [])
        data["analysis"] = analysis
        record_reanalysis(data, "reclassify", VERSION)

        levels = {act["name"]: analysis.get(act["level_key"])
                  for act in MISALIGNED_ACTS if analysis.get(act["key"])}
        flip = " CHANGED" if analysis["scheming"] != before else ""
        print(f"  {os.path.basename(path):55s} "
              f"scheming {before} -> {analysis['scheming']}{flip}  {levels}")
        if analysis["scheming"] != before:
            changed.append(os.path.basename(path))

        pending.append((path, data))

    # A reclassification in which most classifier calls failed has produced
    # little but keyword fallbacks - the very verdicts this mode exists to
    # replace. Writing those over good ones destroys work and looks like a
    # result. Nothing is persisted until the whole pass is known to be sound.
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

    if args.write_back:
        for path, data in pending:
            with open(path, "w") as f:
                json.dump(data, f, indent=2, default=str)

    print(f"\n{len(changed)}/{len(run_files)} episode(s) changed verdict.")
    if args.write_back:
        print("Run files updated in place.")
    else:
        print("Run files NOT modified (pass --write-back to persist).")
    return 0
