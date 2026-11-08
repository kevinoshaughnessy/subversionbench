"""
Publishing the monitoring benchmark's results as an encrypted archive.

zip.sh publishes a corpus of run files, and subversionbench/export.py decides what
belongs in one by name: run_, summary_ and the like. This corpus has a different
shape - a manifest, a token ledger and one JSON Lines file per monitor under
results/ - so that allowlist withholds every file of it and the archive comes out
empty. Teaching the run-file allowlist about this shape would change what the other
archives publish, so this module is the same protection for the other structure:
stage a redacted copy of an allowlist, check it names nothing about this host,
encrypt it, then unpack the finished archive and check that too.

    python3 -m monitoring.archive [--dir eval_results_monitor_r1]

The staging and the host check are subversionbench.export's own, called rather than
restated, so a pattern added there protects this archive as well.
"""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from subversionbench.export import main as export_main
from subversionbench.redaction import redact_paths

from .run import RESULTS_DIR

DEFAULT_DIR = "eval_results_monitor_r1"

# Published in docs/operations.md: it keeps crawlers out of the archive and is
# not a secret. A test holds the two in step.
ARCHIVE_PASSWORD = "donottrainonsubversionbench"

# An ALLOWLIST, for the reason subversionbench.export gives: a new kind of file in
# the directory is withheld until someone decides it should ship, and every
# withheld name is printed.
TOP_LEVEL_FILES = ("manifest.json", "api_usage.jsonl")
RESULT_SUFFIX = ".jsonl"


class ArchiveRefused(Exception):
    """The directory cannot be archived safely, or the archive did not verify."""


def is_published(relative: str) -> bool:
    """Whether a file, given relative to the corpus directory, ships."""
    parts = Path(relative).parts
    if len(parts) == 1:
        return parts[0] in TOP_LEVEL_FILES
    return (len(parts) == 2 and parts[0] == RESULTS_DIR
            and parts[1].endswith(RESULT_SUFFIX))


def _walk(src: str):
    """(relative path, absolute path) of every file, refusing links."""
    links = []
    for dirpath, dirnames, filenames in os.walk(src, followlinks=False):
        for name in sorted(dirnames) + sorted(filenames):
            path = os.path.join(dirpath, name)
            if os.path.islink(path):
                links.append(os.path.relpath(path, src))
        for name in sorted(filenames):
            path = os.path.join(dirpath, name)
            if not os.path.islink(path):
                yield os.path.relpath(path, src), path
    if links:
        raise ArchiveRefused(
            f"symbolic link(s) in {os.path.basename(src)}, which this will not "
            f"resolve into a published archive: {', '.join(sorted(links)[:5])}")


def stage(src: str, into: str) -> dict:
    """A redacted copy of the published files under `into/<basename of src>`.

    Returns what was written and the names withheld, and checks off DISK that
    every file meant to be written landed.
    """
    src = str(src).rstrip("/")
    dst = Path(into, os.path.basename(src))
    dst.mkdir(parents=True, exist_ok=True)
    seen = written = 0
    withheld = []
    for relative, path in _walk(src):
        seen += 1
        if not is_published(relative):
            withheld.append(relative)
            continue
        target = dst / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        text = Path(path).read_text(encoding="utf-8")
        target.write_text(redact_paths(text), encoding="utf-8")
        written += 1
    on_disk = sum(1 for p in dst.rglob("*") if p.is_file())
    if on_disk != seen - len(withheld):
        raise ArchiveRefused(
            f"walked {seen} file(s), withheld {len(withheld)}, but only {on_disk} "
            f"reached the staged copy; it is incomplete and must not be archived")
    if not written:
        raise ArchiveRefused(f"nothing under {src} is a published file")
    return {"written": written, "withheld": sorted(withheld)}


def _encrypt(staged: str, archive: str) -> None:
    """Zip `staged` (a directory) into `archive`, rooted at its own name."""
    if os.path.exists(archive):
        os.remove(archive)
    parent, name = os.path.split(os.path.abspath(staged))
    subprocess.run(["zip", "-r", "-q", "-P", ARCHIVE_PASSWORD,
                    os.path.abspath(archive), name], cwd=parent, check=True)


def _verify_clean(root: str) -> None:
    if export_main(["--verify", root]) != 0:
        raise ArchiveRefused(f"{root} still identifies this host or holds a finding "
                             "redaction cannot rewrite; the archive is not published")


def _verify_archive(archive: str) -> None:
    """Unpack the finished archive and check what a reader would get."""
    with tempfile.TemporaryDirectory() as unpacked:
        subprocess.run(["unzip", "-q", "-P", ARCHIVE_PASSWORD, archive, "-d", unpacked],
                       check=True)
        _verify_clean(unpacked)


def build(src: str, archive: str = None) -> str:
    """Archive `src`; the path of the encrypted archive, or ArchiveRefused."""
    src = str(src).rstrip("/")
    archive = archive or f"{src}.zip"
    with tempfile.TemporaryDirectory() as staging:
        counts = stage(src, staging)
        print(f"  staged {counts['written']} file(s) from {os.path.basename(src)}")
        if counts["withheld"]:
            print(f"  withheld {len(counts['withheld'])} file(s) as working notes "
                  f"rather than corpus - they are not published:")
            for name in counts["withheld"]:
                print(f"    {name}")
        staged = os.path.join(staging, os.path.basename(src))
        _verify_clean(staged)
        _encrypt(staged, archive)
    try:
        _verify_archive(archive)
    except ArchiveRefused:
        os.remove(archive)
        raise
    print(f"encrypted {counts['written']} file(s) -> {archive} "
          f"({os.path.getsize(archive) / 1e6:.1f} MB)")
    return archive


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="python3 -m monitoring.archive",
        description="Encrypt the monitoring benchmark's results for publication.")
    parser.add_argument("--dir", default=DEFAULT_DIR,
                        help=f"corpus directory (default {DEFAULT_DIR})")
    args = parser.parse_args(argv)
    if not os.path.isdir(args.dir):
        parser.error(f"{args.dir} is not a directory")
    if shutil.which("zip") is None or shutil.which("unzip") is None:
        parser.error("zip and unzip are both required")
    try:
        build(args.dir)
    except ArchiveRefused as refused:
        print(f"\n  REFUSING TO ARCHIVE: {refused}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
