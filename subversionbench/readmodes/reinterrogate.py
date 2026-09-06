"""
Putting a second phrasing of the opening question to episodes already collected.

The interrogation happens after the episode and each probe starts from the
conversation as the episode LEFT it, so several wordings can be put to the same
episode with no order effect to control for. That is what makes a phrasing
comparison paired rather than between-batch - and it needs the saved API
conversation, not just the transcript, because the reasoning blocks carry
signatures the API verifies.

Its write-back policy adds answers under a phrasing key and leaves the headline
fields alone, so a batch probed with extras still pools with one probed without.
"""

import collections
import json
import os

from .. import llm_client as llm_api
from ..blocks import reconstruct_messages
from ..config import DEFAULT_INTERROGATION, INTERROGATION_CHOICES
from ..followup import run_followup
from ..grading import MISALIGNED_ACTS, questions_for, settle_analysis
from ..llm_client import resolve_thinking_kwargs
from ..reasoning import same_reasoning_config
from ..redaction import redact_paths
from .selection import find_run_files_or_explain


def _drop_copied_default(analysis: dict, acts) -> bool:
    """
    Remove any copy of the default phrasing's answers from the variant map.

    The map holds the EXTRA phrasings. The default phrasing's answers live in the
    headline field, and they used to be copied in here as well so that the
    comparison read as one structure rather than a field against a map.

    A copy of a sampled field is a second place it can go stale, and this one went
    stale at once: --reclassify re-labels the headline answers in place and does not
    walk this map, so the copy kept whichever verdicts it was made with. The default
    side of every phrasing comparison was then scored by whichever classifier ran
    first - stale keyword verdicts against fresh classifier ones, which is exactly
    the confound that already invalidated one phrasing comparison.

    Returns whether anything was removed, so the caller can decide to save.
    """
    removed = False
    for act in acts:
        key = act["followup_key"] + "_by_variant"
        by_variant = analysis.get(key)
        if by_variant and DEFAULT_INTERROGATION in by_variant:
            by_variant = {k: v for k, v in by_variant.items()
                          if k != DEFAULT_INTERROGATION}
            analysis[key] = by_variant
            removed = True
    if removed:
        # The levels are derived from the answers, so they have to be re-settled
        # after one is removed. settle_analysis puts the default phrasing's level
        # back into the map from the headline field.
        settle_analysis(analysis)
    return removed


def _save(path: str, run: dict, analysis: dict) -> None:
    run["analysis"] = analysis
    with open(path, "w") as f:
        json.dump(run, f, indent=2, default=str)
    print(f"  written back: {redact_paths(os.path.basename(path))}")


def reinterrogate_existing_runs(args, selection) -> int:
    """
    Put another phrasing of the opening question to episodes already collected.

    Only episodes that took an act are candidates - there is nothing to ask about
    otherwise - and only phrasings not already recorded are asked, so re-running
    the mode is idempotent and costs nothing on a corpus already covered.

    Writes into `<followup_key>_by_variant` and recomputes
    `<level_key>_by_variant` beside it. The headline fields are never touched: the
    default phrasing's answers and level stay exactly as they were, so every rate
    over this corpus keeps its meaning and batches with and without extras pool.

    Refuses an episode it cannot reconstruct faithfully rather than replaying a
    conversation with the model's own reasoning stripped out. See
    reconstruct_messages.
    """
    wanted = [v for v in args.interrogations if v != DEFAULT_INTERROGATION]
    if not wanted:
        print("--reinterrogate needs a phrasing to add, e.g. "
              f"--interrogation {INTERROGATION_CHOICES[-1]}")
        return 2

    run_files = find_run_files_or_explain(args, selection)
    if run_files is None:
        return 1

    # The client is created lazily, on the first episode that actually needs a
    # question asked. The eligibility scan below - which episodes have an act,
    # which are already covered, which cannot be reconstructed - is free and reads
    # only saved files, so it must be reportable without credentials. Building the
    # client up front made the whole mode fail on a missing key before it could say
    # what it would have done.
    client = None
    counts = collections.Counter()
    for path in run_files:
        with open(path) as f:
            run = json.load(f)
        analysis = run.get("analysis") or {}
        acts = [a for a in MISALIGNED_ACTS if analysis.get(a["key"])]
        if not acts:
            counts["no act to ask about"] += 1
            continue
        todo = [v for v in wanted
                if any(v not in (analysis.get(a["followup_key"] + "_by_variant")
                                 or {}) for a in acts)]
        if not todo:
            # Nothing to ask, but there may still be a copy of the default
            # phrasing's answers to remove - see the note at the write below. The
            # repair is free and local, so an episode already covered gets it
            # rather than being skipped with the stale copy left in place, which
            # would leave most of the corpus holding it forever.
            if _drop_copied_default(analysis, acts):
                counts["stale default copy removed"] += 1
                if args.write_back:
                    _save(path, run, analysis)
            else:
                counts["already covered"] += 1
            continue

        messages, reason = reconstruct_messages(run)
        if messages is None:
            counts[f"refused: {reason}"] += 1
            print(f"  SKIP {os.path.basename(path)}: {reason}")
            continue

        print(f"\n--- {os.path.basename(path)}: adding {todo} ---")
        if client is None:
            client = llm_api.get_client(selection.model)

        # Match the reasoning parameter the ORIGINAL probe ran under, resolved
        # from the effort this run recorded rather than from the command line.
        #
        # Omitting it made the replayed probe run with no reasoning parameter at
        # all while the default probe had one, so the two differed in the question
        # AND in whether the model could think - the exact confound the paired
        # design exists to remove. A mismatch is warned about rather than guessed
        # past: max_tokens and the thinking budget are not recorded per run, so
        # they can only come from the command line.
        replay_kwargs, replay_config, _warn = resolve_thinking_kwargs(
            selection.model, args.thinking_budget, args.max_tokens,
            run.get("effort"))
        recorded = run.get("reasoning_config")
        # Not string equality: a config whose WORDING was corrected still
        # describes the same request, and warning on that would cry wolf over
        # every OpenRouter episode already on disk. See same_reasoning_config.
        if recorded and not same_reasoning_config(recorded, replay_config):
            print(f"  [WARNING] reasoning config differs from the original: "
                  f"replaying with {replay_config!r}, the episode ran under "
                  f"{recorded!r}. The two probes are then not matched on it.")
        _drop_copied_default(analysis, acts)
        for act in acts:
            key = act["followup_key"] + "_by_variant"
            by_variant = dict(analysis.get(key) or {})
            for variant in todo:
                if variant in by_variant:
                    continue
                by_variant[variant] = run_followup(
                    run.get("system_prompt") or "", messages,
                    selection.model,
                    client, act,
                    questions=questions_for(act, selection.nudge, variant),
                    classifier_model=args.grader_model,
                    max_tokens=args.max_tokens,
                    reasoning_kwargs=replay_kwargs,
                )
            analysis[key] = by_variant
        # settle_analysis is the one place a deterministic verdict is derived, and
        # it puts the default phrasing's level in the map from the headline field.
        # Deriving the levels here as well is how the two came to disagree.
        settle_analysis(analysis)
        counts["interrogated"] += 1
        if args.write_back:
            _save(path, run, analysis)

    print(f"\n{'='*60}")
    for reason, n in counts.most_common():
        print(f"  {n:>4}  {reason}")
    if not args.write_back and counts["interrogated"]:
        print("\n  Nothing saved: pass --write-back to keep these answers.")
    return 0
