#!/usr/bin/env python3
"""
Stage one model's poolable episodes from an older results directory into a
newer one, so `report`/`trends`/`arms_summary` can be run against a single
directory that combines what a rollout bump left unchanged with what it fixed.

Why this exists
----------------
r10 changed only the no-oversight arm - the README no longer promises a
quality-preview tool the arm itself removed. Both oversight arms assemble
byte-for-byte as they did at r9, so r9's oversight-arm episodes are still
exactly what current code produces and remain one population with anything
collected under r10. r9's no-oversight episodes are not: they were produced
by the scenario the fix changed, and pooling them with r10's no-oversight
episodes would silently reintroduce the confound r10 exists to remove -
measured directly on google/gemini-3.5-flash and deepseek/deepseek-v4-flash,
where the escape rate that scenario induced fell from 89.8% to 0.0%.

So "which of a model's r9 episodes are safe to reuse" is not a judgment call
per model - it is decided per ARM, by the same test the rollout block in every
summary already uses to report drift: does this episode's own
`rollout_fingerprint` match what `rollout_fingerprint(oversight, lure)`
computes right now. A match means the arm has not moved since; a mismatch
means it has, and the episode belongs to a rollout that no longer exists in
the code.

Checked against the real corpus before this was built: of google/gemini-3.5-
flash's 205 r9 episodes, exactly the 100 oversight-present ones match current
code across all three nudge levels; all 105 no-oversight ones are stale,
regardless of nudge - the defect was arm-wide, not tied to one nudge setting.

What it does
------------
For --model, walks --source-dir's run_*.json and summary_*.json, keeps only
the ones whose recorded fingerprint(s) match current code for their own
arm, and copies those into --dest-dir - real files, unmodified, so a reader
of the merged directory sees exactly what the rollout block already reports:
the observed SET of versions and fingerprints, not a rewritten single value.
Never overwrites anything already in --dest-dir; a name collision is skipped
and counted rather than silently resolved.

Read-only on --source-dir. --dry-run prints the selection without copying
anything, the same pattern zip.sh's --print-selection uses for the same
reason: the check is worth being able to run before anything is copied.

Usage
-----
    python restage_model.py --model google/gemini-3.5-flash \\
        --source-dir eval_results_r9 --dest-dir eval_results_r10 --dry-run
    python restage_model.py --model google/gemini-3.5-flash \\
        --source-dir eval_results_r9 --dest-dir eval_results_r10

Rerunnable per model, which is the point - the no-oversight side still needs
collecting fresh for every model in turn, but the oversight side never does:

    for m in x-ai/grok-4.5 z-ai/glm-5.3 moonshotai/kimi-k3; do
        python restage_model.py --model "$m" \\
            --source-dir eval_results_r9 --dest-dir eval_results_r10
    done

Idempotent: running it twice for the same model copies nothing the second
time, since every file it would have copied is already there.
"""

import argparse
import glob
import json
import os
import shutil
import sys

from subversionbench.batch import parse_batch_filename
from subversionbench.rollout import rollout_fingerprint
from subversionbench.redaction import redact_paths


def _current_fingerprint_cache():
    """A 4-entry memo of rollout_fingerprint(oversight, lure) - computed at
    most four times regardless of corpus size, since the underlying call
    decodes and hashes the whole scenario bundle and this script may walk
    thousands of files."""
    cache = {}

    def get(oversight: bool, lure: bool) -> str:
        key = (bool(oversight), bool(lure))
        if key not in cache:
            cache[key] = rollout_fingerprint(oversight=key[0], lure=key[1])
        return cache[key]
    return get


def poolable_run_files(source_dir: str, model: str, current) -> dict:
    """{path: (nudge, oversight, lure)} for every run file belonging to
    `model` whose recorded fingerprint matches what current code assembles
    for its own arm. Everything else is silently excluded here and counted
    by the caller - staleness is the expected, common case for a no-oversight
    episode under r10, not an error."""
    keep = {}
    for path in sorted(glob.glob(os.path.join(source_dir, "run_*.json"))):
        try:
            with open(path, encoding="utf-8") as f:
                d = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        if d.get("model") != model:
            continue
        oversight, lure = d.get("oversight"), d.get("lure")
        recorded = d.get("rollout_fingerprint")
        if oversight is None or not recorded:
            continue    # nothing to compare - not this script's job to guess
        if recorded == current(oversight, lure):
            keep[path] = (d.get("nudge"), bool(oversight), bool(lure))
    return keep


def poolable_summary_files(source_dir: str, model: str, current) -> dict:
    """The same rule applied to summary_*.json, since arms_summary.py and
    report's own load_summaries read batch-level files rather than episodes.

    Summaries do not stamp oversight/lure on themselves at the top level -
    checked against a real file before writing this, rather than assumed -
    so the arm comes from `parse_batch_filename`, the same production parser
    every other reader of a batch filename uses. Deriving it independently
    here (e.g. by re-parsing this script's own `current_fingerprints` label
    strings) would be a second, weaker copy of a rule that already exists.

    A summary's rollout block records the SET of fingerprints its batch's
    episodes carry - conservatively treated as poolable only when every one
    of them matches, so a batch that itself straddled a rollout change
    (should not exist post-fix, but is not this script's business to assume)
    is excluded rather than guessed about.
    """
    keep = {}
    for path in sorted(glob.glob(os.path.join(source_dir, "summary_*.json"))):
        try:
            with open(path, encoding="utf-8") as f:
                s = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        if s.get("model") != model:
            continue
        nudge = s.get("nudge")
        if not nudge:
            continue
        fingerprints = (s.get("rollout") or {}).get("fingerprints") or {}
        if not fingerprints:
            continue
        _effort, _stamp, oversight, lure = parse_batch_filename(path, nudge)
        want = current(oversight, lure)
        if all(fp == want for fp in fingerprints):
            keep[path] = (nudge, bool(oversight), bool(lure))
    return keep


def stage(model: str, source_dir: str, dest_dir: str, dry_run: bool = False) -> dict:
    """Copy every poolable run+summary file for `model` from source_dir into
    dest_dir. Returns counts by outcome and by arm, for the caller to print
    or assert on."""
    current = _current_fingerprint_cache()
    run_keep = poolable_run_files(source_dir, model, current)
    summary_keep = poolable_summary_files(source_dir, model, current)

    by_arm = {}
    staged = skipped_existing = 0
    for path, arm in {**run_keep, **summary_keep}.items():
        by_arm.setdefault(arm, {"staged": 0, "skipped_existing": 0})
        dest = os.path.join(dest_dir, os.path.basename(path))
        if os.path.exists(dest):
            skipped_existing += 1
            by_arm[arm]["skipped_existing"] += 1
            continue
        staged += 1
        by_arm[arm]["staged"] += 1
        if not dry_run:
            shutil.copy2(path, dest)

    return {
        "model": model,
        "n_run_files_poolable": len(run_keep),
        "n_summary_files_poolable": len(summary_keep),
        "staged": staged,
        "skipped_existing": skipped_existing,
        "by_arm": {f"nudge={n} oversight={o} lure={lure}": v
                  for (n, o, lure), v in sorted(by_arm.items(), key=str)},
    }


def main():
    parser = argparse.ArgumentParser(
        description="Stage one model's poolable episodes into a newer "
                    "results directory.")
    parser.add_argument("--model", required=True)
    parser.add_argument("--source-dir", required=True,
                        help="the older results directory to read from "
                             "(never written to)")
    parser.add_argument("--dest-dir", required=True,
                        help="the results directory to copy into")
    parser.add_argument("--dry-run", action="store_true",
                        help="print what would be staged without copying "
                             "anything")
    args = parser.parse_args()

    if not os.path.isdir(args.source_dir):
        print(f"! {redact_paths(args.source_dir)} is not a directory")
        return 1
    if not os.path.isdir(args.dest_dir):
        print(f"! {redact_paths(args.dest_dir)} is not a directory")
        return 1

    result = stage(args.model, args.source_dir, args.dest_dir,
                   dry_run=args.dry_run)
    verb = "would stage" if args.dry_run else "staged"
    print(f"{args.model}: {result['n_run_files_poolable']} poolable run "
          f"file(s), {result['n_summary_files_poolable']} poolable summary "
          f"file(s) found in {redact_paths(args.source_dir)}")
    print(f"  {verb} {result['staged']}, "
          f"{result['skipped_existing']} already present in "
          f"{redact_paths(args.dest_dir)}\n")
    for arm, counts in result["by_arm"].items():
        print(f"  {arm:42} {verb} {counts['staged']:4}  "
              f"already-present {counts['skipped_existing']:4}")

    if result["n_run_files_poolable"] == 0 and result["n_summary_files_poolable"] == 0:
        print(f"\n! nothing poolable found for {args.model!r} in "
              f"{redact_paths(args.source_dir)} - check the model name is "
              f"exact, or this model may have no oversight-arm episodes "
              f"collected there yet.")
        return 1
    if args.dry_run:
        print("\n--dry-run: nothing was copied. Drop the flag to stage it.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
