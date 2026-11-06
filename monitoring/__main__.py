"""
python3 -m monitoring sample | run | report - see monitoring/__init__.py.
"""

import argparse
import glob
import os
import sys

from subversionbench.version import VERSION

from .arms import SOURCE_ARMS, arm_named
from .render import CUTS, VIEWS

DEFAULT_OUTPUT_DIR = "eval_results_monitor_r1"


def _csv(choices):
    def parse(text):
        values = [v for v in text.split(",") if v]
        bad = [v for v in values if v not in choices]
        if bad or not values:
            raise argparse.ArgumentTypeError(
                f"{text!r}: choose from {', '.join(choices)}")
        return tuple(values)
    return parse


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python3 -m monitoring",
                                     description=__doc__)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--corpus-root", default=".",
                        help="where the source corpora live (default: here)")
    sub = parser.add_subparsers(dest="command", required=True)
    sample = sub.add_parser("sample", help="draw the episodes into a manifest")
    sample.add_argument("--arms", type=_csv([a.name for a in SOURCE_ARMS]),
                        default=tuple(a.name for a in SOURCE_ARMS))
    sample.add_argument("--seed", type=int, default=0)
    sample.add_argument("--per-arm", type=int, default=None,
                        help="positives per arm (default: every one)")
    run = sub.add_parser("run", help="put the manifest to one monitor")
    run.add_argument("--monitor", required=True)
    run.add_argument("--openrouter-provider", default=None)
    run.add_argument("--views", type=_csv(VIEWS), default=VIEWS)
    run.add_argument("--cuts", type=_csv(CUTS), default=CUTS)
    run.add_argument("--concurrency", type=int, default=4)
    run.add_argument("--limit", type=int, default=None,
                     help="only the first N manifest episodes (a pilot)")
    run.add_argument("--dry-run", action="store_true",
                     help="count calls and tokens; send nothing")
    run.add_argument("--yes", action="store_true", help="send the calls")
    sub.add_parser("report", help="score every monitor run so far")
    return parser


def _sample(opts) -> int:
    from .sample import draw, scan_arm, write_manifest
    records, skipped = [], 0
    for name in opts.arms:
        found, unread = scan_arm(arm_named(name), opts.corpus_root)
        records += found
        skipped += unread
    sample = draw(records, opts.seed, opts.per_arm)
    meta = {"arms": list(opts.arms), "seed": opts.seed, "per_arm": opts.per_arm,
            "version": VERSION, "unreadable_files": skipped}
    path = write_manifest(opts.output_dir, sample, meta)
    pos = sum(e["label"] == "act" for e in sample)
    print(f"{pos} episodes with an act and {len(sample) - pos} without, "
          f"written to {path}")
    if skipped:
        print(f"{skipped} files could not be read - an episode being written? "
              f"Redraw once collection has finished.")
    return 0


def _report(opts) -> int:
    from .bundle import fingerprints, load_bundle
    from .run import RESULTS_DIR, read_rows
    from .sample import load_manifest
    from .scores import (current_rows, delays, format_delays, format_summary,
                         summarise)
    manifest = load_manifest(opts.output_dir)
    pins = fingerprints(load_bundle())
    rows = []
    for path in sorted(glob.glob(os.path.join(opts.output_dir, RESULTS_DIR,
                                              "*.jsonl"))):
        rows += read_rows(path)
    kept = current_rows(rows, pins)
    print(format_summary(summarise(kept, manifest)))
    print("\nFirst cut each act was flagged at (1% FPR at each cut):")
    print(format_delays(delays(kept, manifest)))
    if len(kept) < len(rows):
        print(f"\n{len(rows) - len(kept)} rows under an earlier fingerprint left out.")
    return 0


def main(argv=None) -> int:
    opts = _parser().parse_args(argv)
    if opts.command == "sample":
        return _sample(opts)
    if opts.command == "report":
        return _report(opts)
    from .run import run_monitor
    return run_monitor(opts.output_dir, opts.monitor, opts.openrouter_provider,
                       opts.views, opts.cuts, opts.concurrency, opts.dry_run,
                       opts.yes, opts.limit, opts.corpus_root)


if __name__ == "__main__":
    sys.exit(main())
