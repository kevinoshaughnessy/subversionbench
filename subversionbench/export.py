"""
Preparing results for publication: redact on the way out, then check.

WHY NOT AT SAVE TIME
--------------------
`messages` holds the API conversation an episode ended with, and it exists so a saved
episode can be re-interrogated. Replay needs the bytes the model actually saw -
thinking-block signatures the API verifies, tool ids, and the paths the shell really
reported, because a path the agent read in one turn has to match the one it types in
the next. Redacting that at save time would make every replay a different
conversation from the one it claims to reproduce, which is the live-vs-replayed
asymmetry that already invalidated one phrasing comparison.

The corpus is gitignored and stays on the operator's machine, where the real paths
are not a secret. The archive is the only thing that leaves. So the archive is what
gets cleaned, and the corpus keeps full fidelity.

WHY A VERIFY STEP
-----------------
The redaction is a string substitution over a nested structure, and the failure mode
is silent: a field nobody thought about keeps its host path and the archive ships. So
the patterns the verifier looks for are DERIVED from the substitutions the redactor
applies - `path_substitutions()` is the single source of truth for both - and the
check runs on the unpacked archive rather than on the staging copy, so it tests the
artefact that is actually published.
"""

import argparse
import json
import os
import re
import shutil
import sys
from pathlib import Path

from .config import OPERATOR_DISPLAY_NAME
from .redaction import _operator_username, path_substitutions, redact_paths


def _redact_value(value):
    """Redact every string in a decoded JSON structure, in place by rebuilding.

    Applied to values rather than to the serialised text: `redact_paths` returns
    non-strings unchanged, so walking is no harder, and it cannot disturb JSON
    syntax the way a substitution over the encoded form could.
    """
    if isinstance(value, str):
        return redact_paths(value)
    if isinstance(value, dict):
        return {k: _redact_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact_value(v) for v in value]
    return value


class ExportRefused(Exception):
    """The directory holds something this cannot publish safely."""


def redact_tree(src: str, into: str) -> dict:
    """
    Copy `src` into `into/<basename>`, redacting every JSON file on the way.

    Non-JSON files are copied verbatim. Returns counts for the caller to report.

    RECURSIVE, and it counts what it wrote.
    ---------------------------------------
    The first version skipped directories, so a nested file never reached the
    archive - while zip.sh reported a count from a recursive `find` and declared
    success. An incomplete archive with a reassuring message is worse than a failed
    build, so every file is now walked and the total written is checked against the
    total seen before returning. That check is what would have caught the omission.

    SYMLINKS ARE REFUSED, not followed.
    -----------------------------------
    `shutil.copy2` follows a link, so a symlink in a results directory pointing
    anywhere on disk would have had its CONTENT copied into a published archive.
    This module exists to control what leaves the machine, so a link out of the tree
    is refused rather than resolved - and refused rather than skipped, because
    silently dropping it is the same class of mistake as silently dropping a
    subdirectory.
    """
    src = str(src).rstrip("/")
    dst = os.path.join(into, os.path.basename(src))
    os.makedirs(dst, exist_ok=True)
    counts = {"json": 0, "changed": 0, "copied": 0, "unreadable": 0,
              "seen": 0, "written": 0}
    links = []

    for dirpath, dirnames, filenames in os.walk(src, followlinks=False):
        relative = os.path.relpath(dirpath, src)
        out_dir = dst if relative == "." else os.path.join(dst, relative)
        os.makedirs(out_dir, exist_ok=True)

        for name in sorted(dirnames):
            if os.path.islink(os.path.join(dirpath, name)):
                links.append(os.path.relpath(os.path.join(dirpath, name), src))

        for name in sorted(filenames):
            s = os.path.join(dirpath, name)
            if os.path.islink(s):
                links.append(os.path.relpath(s, src))
                continue
            d = os.path.join(out_dir, name)
            counts["seen"] += 1
            if not name.endswith(".json"):
                shutil.copy2(s, d)
                counts["copied"] += 1
                counts["written"] += 1
                continue
            counts["json"] += 1
            raw = Path(s).read_text()
            try:
                data = json.loads(raw)
            except Exception:
                # A truncated run file is data too: copy it rather than dropping it,
                # but redact it as text since it cannot be parsed.
                Path(d).write_text(redact_paths(raw))
                counts["unreadable"] += 1
                counts["written"] += 1
                continue
            clean = _redact_value(data)
            Path(d).write_text(json.dumps(clean, indent=2, default=str))
            counts["written"] += 1
            if clean != data:
                counts["changed"] += 1

    if links:
        raise ExportRefused(
            f"{len(links)} symbolic link(s) in {os.path.basename(src)}, which this "
            f"will not resolve into a published archive: "
            f"{', '.join(sorted(links)[:5])}"
            + (" ..." if len(links) > 5 else "")
            + ". Replace them with real files, or move them out of the directory.")

    # Counted off DISK, not off the loop above. Incrementing a counter beside each
    # write only proves the code meant to write; it proves nothing about what landed,
    # and a branch that walks a file and fails to write it would still tick the
    # counter up. Comparing against what is actually staged is what makes this a
    # check rather than a restatement of the loop's own bookkeeping.
    staged = sum(1 for path in Path(dst).rglob("*") if path.is_file())
    if staged != counts["seen"]:
        raise ExportRefused(
            f"walked {counts['seen']} file(s) but only {staged} reached the staged "
            f"copy; it is incomplete and must not be archived.")
    return counts


def leak_patterns():
    """
    What must not survive redaction, derived from what the redactor removes.

    Deriving these rather than restating them is the point: a substitution added to
    `path_substitutions` is checked for automatically, and the two cannot drift.
    """
    patterns = [(real, "host path") for real, _ in path_substitutions()]
    username = _operator_username()
    if username:
        patterns.append((username, "operator username"))
    return patterns


def find_leaks(root: str) -> list:
    """Every (file, what, sample) still identifying the host, under `root`."""
    found = []
    for path in sorted(Path(root).rglob("*")):
        if not path.is_file():
            continue
        try:
            text = path.read_text(errors="replace")
        except Exception:
            continue
        for needle, what in leak_patterns():
            index = text.find(needle)
            if index != -1:
                start = max(0, index - 30)
                found.append((str(path), what,
                              text[start:index + len(needle) + 20]))
                break
    return found


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Redact a results directory for publication, or verify one.")
    parser.add_argument("--dir", help="results directory to redact")
    parser.add_argument("--into", help="staging directory to write the copy into")
    parser.add_argument("--verify", metavar="ROOT",
                        help="check an unpacked archive and exit nonzero if it "
                             "still identifies the host")
    args = parser.parse_args(argv)

    if args.verify:
        leaks = find_leaks(args.verify)
        if not leaks:
            print(f"  verified clean: nothing under {os.path.basename(args.verify)} "
                  f"identifies this host")
            return 0
        print(f"\n  REFUSING TO PUBLISH: {len(leaks)} file(s) still identify the "
              f"host.\n")
        for path, what, sample in leaks[:10]:
            print(f"    {os.path.basename(path)}  [{what}]")
            print(f"      ...{sample.strip()[:88]}...")
        if len(leaks) > 10:
            print(f"    ... and {len(leaks) - 10} more")
        print(f"\n  redaction.path_substitutions() decides what is rewritten; a "
              f"field\n  reaching the archive unredacted means export.py did not "
              f"walk it.")
        return 1

    if not (args.dir and args.into):
        parser.error("--dir and --into are both required unless --verify is given")
    try:
        counts = redact_tree(args.dir, args.into)
    except ExportRefused as refused:
        print(f"\n  REFUSING TO STAGE: {refused}")
        return 1
    print(f"  redacted {counts['changed']}/{counts['json']} JSON file(s) from "
          f"{os.path.basename(str(args.dir).rstrip('/'))}"
          + (f", {counts['copied']} other file(s) copied" if counts["copied"] else "")
          + (f", {counts['unreadable']} unparseable file(s) redacted as text"
             if counts["unreadable"] else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
