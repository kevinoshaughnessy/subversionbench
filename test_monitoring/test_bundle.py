"""
The monitor's instructions are not greppable in the repository, which is the
whole point of encoding them. Phrases are read from the bundle rather than
listed here, so the guard does not publish what it protects.
"""

import os
import subprocess
import tempfile
from pathlib import Path

from monitoring.bundle import REQUIRED, encode_bundle, load_bundle


def _phrases(bundle: dict) -> list:
    """Every sentence-sized run of the instructions long enough to be
    distinctive, split on line breaks and full stops."""
    out = []
    for name in REQUIRED:
        for line in bundle[name].replace(". ", ".\n").splitlines():
            line = line.strip()
            if len(line) >= 40:
                out.append(line[:60].lower())
    return out


def _tracked_and_new_files() -> list:
    names = subprocess.run(
        ["git", "ls-files", "-co", "--exclude-standard", "-z"],
        capture_output=True, text=True, check=True).stdout.split("\0")
    return [Path(n) for n in names
            if n and not n.endswith((".b64", ".zip", ".lock"))]


def _leaks(paths, phrases) -> list:
    found = []
    for path in paths:
        try:
            body = path.read_text(encoding="utf-8", errors="ignore").lower()
        except OSError:
            continue
        found += [f"{p!r} in {path}" for p in phrases if p in body]
    return found


class TestTheInstructionsStayEncoded:
    def test_no_tracked_file_holds_a_phrase_of_them(self):
        phrases = _phrases(load_bundle())
        assert phrases, "no phrase long enough to check - the guard is vacuous"
        leaks = _leaks(_tracked_and_new_files(), phrases)
        assert not leaks, "the monitor's instructions appear in plain text:\n" + \
            "\n".join(leaks)

    def test_the_scan_finds_a_planted_phrase(self):
        phrase = _phrases(load_bundle())[0]
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False,
                                         encoding="utf-8") as f:
            f.write("prose\n" + phrase.upper() + "\n")
        try:
            assert _leaks([Path(f.name)], [phrase])
        finally:
            os.unlink(f.name)


class TestTheBundle:
    def test_an_incomplete_bundle_is_refused(self):
        path = Path(tempfile.mkdtemp()) / "m.b64"
        try:
            encode_bundle({"system_prompt": "x"}, path)
        except ValueError:
            return
        raise AssertionError("a bundle with no question was encoded")

    def test_round_trip(self):
        path = Path(tempfile.mkdtemp()) / "m.b64"
        encode_bundle(load_bundle(), path)
        assert load_bundle(path) == load_bundle()
