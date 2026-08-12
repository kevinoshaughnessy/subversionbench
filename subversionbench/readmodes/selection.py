"""
Which saved batches a read-only mode is going to work on.

The four modes all open with the same question and the same five filters, and used
to answer it four different ways - three telling the operator less than the fourth.
One answer lives here.

Fanning out lives here too, for the same reason: `--model all` is the same question
asked once per batch in a directory instead of once.
"""

import glob
import os

from ..batch import discover_batches, find_run_files
from ..redaction import redact_paths


def find_run_files_or_explain(args, model_slug: str):
    """
    The run files a read-only mode should work on, or None with the reason printed.

    All four read modes - --grade-existing, --reclassify, --resummarise and
    --reinterrogate - ask exactly this question, with exactly these filters, and
    used to answer it four different ways. Three printed only "No run files for X /
    Y in DIR"; --grade-existing also named the batch stamp it had filtered on and
    listed what the directory DOES hold.

    That difference was never a decision, and the richer message is the one an
    operator needs. The usual cause of an empty selection is a filter that does not
    match - a stamp, an effort level, or an arm whose suffix is in the filename -
    and a bare "no run files" sends the reader to `ls` to find out which. So the
    richest of the four wordings is now what all four print.

    Returns None rather than raising or exiting, because each mode owns its own exit
    code and two of them have work to report before returning it.
    """
    run_files = find_run_files(args.output_dir, model_slug, args.nudge,
                               args.batch_stamp, args.effort)
    if run_files:
        return run_files

    print(f"No run files for model={args.model} nudge={args.nudge} in "
          f"{redact_paths(args.output_dir)}/"
          + (f" (batch {args.batch_stamp})" if args.batch_stamp else "")
          + (f" (effort {args.effort})" if args.effort else ""))
    print("\nAvailable run files:")
    available = sorted(glob.glob(os.path.join(args.output_dir, "run_*.json")))
    for path in available:
        print(f"  {os.path.basename(path)}")
    if not available:
        print("  (none)")
    return None


def fan_out_read_mode(args, run_one) -> int:
    """
    Run a read-only mode once per (model, nudge) present in the directory.

    Exists because the alternative was 46 hand-written invocations to backfill
    one deterministic field across four rollouts, which is the kind of chore
    that gets half-done. Returns the worst exit code, so one failed batch is
    visible in $? even though the rest still run - a partial backfill that
    reported success would be the worst outcome.
    """
    batches = discover_batches(args.output_dir, args.model, args.nudge)
    if not batches:
        print(f"No run files in {redact_paths(args.output_dir)} match "
              f"model={args.model} nudge={args.nudge}.")
        return 1

    print(f"\n{'='*60}")
    print(f"FAN OUT: {len(batches)} (model, nudge) batch group(s) in "
          f"{redact_paths(args.output_dir)}")
    for m, n in batches:
        print(f"  {m} / {n}")
    print(f"{'='*60}")

    # No snapshot of the filter fields here any more, and that is the point.
    #
    # This loop used to restore args.effort, args.oversight and args.lure at the top
    # of every iteration, because resummarise_existing_runs assigned the batch's own
    # arm onto them - so the first batch processed at effort "medium" filtered every
    # later model to "medium", two of four groups silently reported "no run files",
    # and the backfill would have been half done while reporting success. The callee
    # now carries the arm in a BatchIdentity, so there is nothing to leak and nothing
    # to undo. Model and nudge are still set here, and both are written afresh on
    # every iteration.
    worst = 0
    for i, (model, nudge) in enumerate(batches, 1):
        args.model, args.nudge = model, nudge
        print(f"\n### [{i}/{len(batches)}] {model} / {nudge}")
        try:
            rc = run_one(args, model.replace("/", "_"))
        except Exception as e:
            # One unreadable batch must not abandon the other 45.
            print(f"  ERROR on {model} / {nudge}: {type(e).__name__}: {e}")
            rc = 1
        worst = max(worst, rc or 0)
    print(f"\nFan out complete over {len(batches)} batch group(s); "
          f"worst exit code {worst}.")
    return worst
