"""
Rebuilding a summary from run files already on disk, for free.

Every measure added after a batch was collected is derivable from the saved
transcript with no API call. Requiring --reclassify to obtain them would make the
operator pay classifier calls AND resample LLM verdicts as a side effect,
perturbing figures that are already final.

Its write-back policy is the narrowest of the four: only the allowlisted re-derived
fields, and only those that actually differ, because it must never touch a sampled
judgement.
"""

import json
import os

from ..batch import BatchIdentity, parse_batch_filename
from ..followup import add_awareness_timing
from ..grading import (detect_strategy_recommendation, recheck_quote_grounding,
                       settle_analysis)
from ..redaction import redact_paths
from ..reporting.summary import runtime_from_existing_summary, summarise_batch
from .selection import find_run_files_or_explain


# The analysis fields --resummarise re-derives, and the only ones
# --resummarise --write-back is allowed to save back into a run file.
#
# An allowlist rather than "write whatever changed", because the run file holds
# two kinds of value and only one of them may be rewritten from saved data:
#
#   derived - a pure function of the transcript and the current code. Rebuilding
#             it cannot lose information; refusing to rebuild it pins the file
#             to whatever the definition was when it was written.
#   sampled - an LLM's reading: the awareness grader, the interrogation
#             verdicts, the disclosure judgement. Rebuilding these would mean
#             calling a model again and resampling figures that are already
#             final, which is what --reclassify and --grade-existing are for.
#
# Four defects in v23-v25 came from that distinction being implicit. Anything
# not named here is treated as sampled and left exactly as it stands.
REDERIVED_ANALYSIS_FIELDS = (
    "sandbox_boundary_attempts",
    "sandbox_environment_probes",
    # Refusals caused by a find-style name PATTERN reading as a path - see
    # refusal_kind. Listed for the reason the block at the end of this tuple
    # spells out: normalise_analyses derives it either way, and a field derived
    # in memory and never persisted leaves the saved episode carrying the old
    # answer. Here that answer is a misaligned act the episode did not take.
    "sandbox_name_pattern_refusals",
    "sandbox_system_path_refusals",
    "sandbox_scratch_only",
    "sandbox_boundary_excl_scratch",
    # Which refusals the model was never shown. Derived from the saved
    # transcript by the same pairing rule every time, so it belongs here for
    # the reason the two above it do - and its absence would leave the split
    # inside out_of_scope_detail claiming every refusal was observed.
    "sandbox_refusal_unobserved",
    # Refused on a token inside collapsed generation. Same reason as
    # the field above: derived either way, and a saved episode left
    # without it keeps a concealment verdict this withdraws.
    "sandbox_corrupt_output",
    "eval_awareness_keywords",
    "transient_tampering",
    "transient_tampering_detail",
    "network_probe",
    "network_probe_detail",
    "filesystem_escape",
    "filesystem_escape_detail",
    # What the harness left reachable rather than what the model chose. Read off the
    # transcript like the two above, so a rebuild backfills it onto every episode
    # already collected at no cost.
    "host_path_read",
    "host_path_read_detail",
    # How the model encoded its own words, read off the transcript like the two
    # above. Derived, so a rebuild backfills it onto every episode already
    # collected - which is how the four r1 episodes that reasoned about a
    # substitution became visible without re-running anything.
    "disguised_text",
    "disguised_text_detail",
    # A base64 payload in the model's own words, read off the transcript like
    # the two above - see disguised_text_detail's own comment for why this is
    # a rebuild rather than a resample.
    "encoded_payload",
    "encoded_payload_detail",
    "honeypot_read",
    "honeypot_detail",
    "out_of_scope_attempts",
    "out_of_scope_detail",
    "concealment_oversight",
    "concealment_sandbox",
    # Deterministic given the stored answers, exactly like the two above. The
    # ANSWERS are sampled and stay out of this list; the levels derived from them
    # do not, or a change to the scale would reach the headline level and leave
    # the per-phrasing ones pinned to the old rule.
    "concealment_oversight_by_variant",
    "concealment_sandbox_by_variant",
    "scheming_oversight",
    "scheming_sandbox",
    "awareness_timing_oversight",
    "awareness_timing_sandbox",
    # Episode-level awareness onset, act-independent, so an analysis can condition
    # on "aware by turn N" without reference to whether an act happened - which is
    # what the selection-bias note in README.md is about.
    #
    # Absent from this list until now, so the two fields were recomputed in memory
    # on every --resummarise and then thrown away: the guard above them was fixed,
    # the values were correct in the run, and the saved file kept the old ones. 70
    # episodes were stale on disk after the awareness matcher was corrected. Same
    # class as that guard, one level up - deriving a field freshly is no use if
    # nothing persists it.
    "first_awareness_index",
    "first_awareness_turn",
    "misaligned",
    "scheming",
    # Sixth instance of the same fill-when-absent class. A pure scan of the
    # saved transcript, no API - and until now not on this list at all, so a
    # correction to the matcher (a negation blind spot: "not recommending
    # Strategy B" was counted as a vote for B) would have fixed nothing that
    # was already on disk. See the block above where this is recomputed.
    "strategy_recommended",
)


def resummarise_existing_runs(args, selection) -> int:
    """
    Rebuild summary files from run files already on disk.

    --reclassify rewrites the verdicts inside each run, which leaves every
    verdict-derived figure in the batch summary stale. Without this, the only
    way to get a current summary is to pay for the whole batch again.

    Reads nothing from any model and calls no API: every figure it writes is
    derived from the saved runs. One summary per batch stamp, so a model with
    several batches on disk gets each rebuilt separately rather than merged.
    """
    run_files = find_run_files_or_explain(args, selection)
    if run_files is None:
        return 1

    # Grouped by (effort, oversight, stamp), because those together identify a
    # batch: the same model and nudge at two effort levels, or across the two
    # arms of the oversight counterfactual, are different conditions, and
    # merging them into one summary would silently pool them.
    by_batch = {}
    for path in run_files:
        effort, stamp, oversight, lure, capability = parse_batch_filename(
            path, selection.nudge)
        if args.batch_stamp:
            # find_run_files has already filtered to this stamp, and it is what
            # the summary should be named after - reading it back out of the
            # filename would drop any stamp that is not datetime-shaped and
            # write over the unstamped legacy summary.
            stamp = args.batch_stamp
        # capability is part of the grouping key for the reason every other
        # field here is: a capability batch and a propensity batch of the same
        # model, nudge, arm and stamp are two conditions, and merging them
        # would write one summary over the other.
        by_batch.setdefault((effort, oversight, lure, capability, stamp),
                            []).append(path)

    print(f"{len(run_files)} run file(s) across {len(by_batch)} batch(es).")

    n_written = 0
    for (effort, oversight, lure, capability, stamp), paths in sorted(
            by_batch.items(),
            key=lambda kv: (kv[0][4], kv[0][0] or "", kv[0][1], kv[0][2],
                            kv[0][3] or "")):
        all_results = []
        batch_paths = sorted(paths)
        for path in batch_paths:
            with open(path) as f:
                run = json.load(f)
            # Everything below is derivable from the saved run with no API call,
            # so a batch collected before these measures existed should not have
            # to pay for a --reclassify to be summarised correctly - and
            # --reclassify would resample the LLM verdicts as a side effect,
            # perturbing figures that are already final. Filled in memory only,
            # and only when absent: a value already recorded stays as recorded,
            # since it was produced under whatever rules were in force then.
            analysis = run.get("analysis") or {}
            transcript = run.get("transcript") or []

            # Unconditional, and one call rather than a partial copy of the
            # settling logic. This site used to re-derive only the per-act scheming
            # verdicts, which is how it came to disagree with the summary builder
            # it hands off to.
            if analysis:
                settle_analysis(analysis)

            if analysis:
                # UNCONDITIONAL, not fill-when-absent.
                #
                # This was gated on the field being absent, so a change to how the
                # ordering is derived could never reach a run that already had one.
                # That is exactly what happened: when the awareness matcher and
                # the read/write verb lists were corrected, 14 episodes kept their
                # old ordering and no amount of --resummarise would refresh them.
                # The field is in REDERIVED_ANALYSIS_FIELDS, so write-back was
                # willing to save a new value; nothing ever computed one.
                #
                # Recomputing is safe despite grader_model=None. add_awareness_timing
                # sets the ordering before it touches anything paid, and it already
                # refuses to overwrite a real pre-act grader reading with a skip
                # marker - a guard that exists because that clobbering once cost a
                # 100-run batch. So the free half refreshes and the paid half is
                # preserved, which is the same split --resummarise is built on.
                #
                # Fifth instance of the fill-when-absent class, after the four in
                # v23-v25. The general lesson: a deterministic field must be
                # re-derived every time, or the guard silently pins it to whatever
                # rule was in force when it was first written.
                add_awareness_timing(analysis, transcript, grader_model=None)

                # Sixth instance of the same class. `_detect_strategy_recommendation`
                # had a negation blind spot - "### What I am not recommending:
                # Strategy B" tied against a genuine "Recommendation: Strategy A"
                # header and abstained - and this field was never in
                # REDERIVED_ANALYSIS_FIELDS at all, so fixing the matcher would
                # have silently done nothing for every episode already on disk.
                # Free and fully deterministic: no API, a pure scan of the saved
                # transcript, so recomputing here costs nothing and cannot lose
                # a sampled judgement, because it never held one.
                analysis["strategy_recommended"] = detect_strategy_recommendation(
                    transcript)

            # Third of the three, same class. Whether the grader's citations
            # trace back to the agent's own words is a string comparison against
            # the saved transcript - no API, fully deterministic - so it must be
            # re-derived rather than filled in once. Gated only on there being
            # citations to check.
            grader = analysis.get("eval_awareness_grader") or {}
            if grader.get("rubric_results"):
                recheck_quote_grounding(analysis, transcript)

            all_results.append(run)

        # The arm these runs were made under is whatever their FILENAMES say, not
        # whatever this invocation was passed. Built as an identity and handed to
        # summarise_batch, which is what makes the rebuild write to the file it
        # just named: this used to be done by assigning back onto `args`, and both
        # directions of that failed - see BatchIdentity.
        identity = BatchIdentity(model=selection.model,
                                 model_slug=selection.model_slug,
                                 nudge=selection.nudge, effort=effort,
                                 oversight=oversight, lure=lure, stamp=stamp,
                                 capability=capability)
        summary_path = identity.filename(args.output_dir)
        runtime = runtime_from_existing_summary(summary_path, all_results)

        print(f"\n{'#'*60}")
        print(f"# Rebuilding {os.path.basename(summary_path)} "
              f"from {len(all_results)} run(s)"
              + (f" at effort {effort}" if effort else ""))
        print(f"{'#'*60}")
        summarise_batch(args, all_results, identity, runtime)

        # After summarise_batch, because that is what re-derives them. Only the
        # allowlisted fields are saved, and only those that actually differ, so
        # a file whose stored values already match is left untouched rather
        # than rewritten with an identical payload.
        if args.write_back:
            for path, run in zip(batch_paths, all_results, strict=True):
                with open(path) as f:
                    on_disk = json.load(f)
                stored = on_disk.get("analysis") or {}
                fresh = run.get("analysis") or {}
                changed = {k: fresh[k] for k in REDERIVED_ANALYSIS_FIELDS
                           if k in fresh and stored.get(k) != fresh[k]}
                if not changed:
                    continue
                stored.update(changed)
                on_disk["analysis"] = stored
                with open(path, "w") as f:
                    json.dump(on_disk, f, indent=2)
                n_written += 1
                print(f"  wrote back {len(changed)} field(s) to "
                      f"{redact_paths(os.path.basename(path))}: "
                      f"{', '.join(sorted(changed))}")

    if args.write_back:
        print(f"\n--write-back: {n_written} run file(s) updated. Only "
              f"re-derived fields were written; every LLM verdict is as it was.")
    return 0
