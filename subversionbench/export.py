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
import hashlib
import json
import os
import re
import shutil
import sys
import unicodedata
from pathlib import Path

from .grading import detect_host_path_reads
from .invisible import INVISIBLE_CLASSES
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
            # UTF-8 named rather than left to the machine's locale. Under a
            # non-UTF-8 locale this raised UnicodeDecodeError on any run file
            # holding a non-ASCII character - and the corpus holds them by
            # design, since the invisible characters are the subject. Strict
            # still, so a genuinely undecodable file stops the build rather
            # than being written to the archive mangled.
            raw = Path(s).read_text(encoding="utf-8")
            try:
                data = json.loads(raw)
            except Exception:
                # A truncated run file is data too: copy it rather than dropping it,
                # but redact it as text since it cannot be parsed.
                Path(d).write_text(redact_paths(raw), encoding="utf-8")
                counts["unreadable"] += 1
                counts["written"] += 1
                continue
            clean = _redact_value(data)
            Path(d).write_text(json.dumps(clean, indent=2, default=str),
                               encoding="utf-8")
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


# ---------------------------------------------------------------------------
# Content the redactor cannot rewrite, and so has to refuse
#
# The check above asks whether the redactor missed an identifier it knows about.
# This one asks a different question, and the difference decides the remedy.
#
# `path_substitutions` is a list of strings the redactor can rewrite. A value that is
# not on that list is not rewritten, and the identifier check does not look for it -
# so it cannot report anything about it either way.
#
# Such a value cannot be fixed by adding a substitution, because the harness has no
# way to know what it should become. So it is REFUSED rather than rewritten, and the
# operator decides: drop the episode, or accept the finding explicitly.
# ---------------------------------------------------------------------------

# Never publishable, and never acceptable: no note justifies shipping a credential.
_SECRET_PATTERNS = (
    ("Anthropic API key", r"sk-ant-[A-Za-z0-9_\-]{20,}"),
    ("OpenAI API key", r"\bsk-(?!ant-|or-)[A-Za-z0-9]{32,}"),
    ("OpenRouter API key", r"sk-or-[A-Za-z0-9_\-]{20,}"),
    ("AWS access key id", r"\bAKIA[0-9A-Z]{16}\b"),
    ("GitHub token", r"\bgh[pousr]_[A-Za-z0-9]{30,}"),
    ("private key block", r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    ("bearer token", r"(?i)authorization:\s*bearer\s+[A-Za-z0-9._\-]{20,}"),
    # A name that means "credential", assigned a value long enough to be one.
    #
    # The value must contain a letter: run files are full of usage counters, and
    # `"cache_read_input_tokens": 1234567890123456` is sixteen characters assigned to
    # a name ending in "tokens". The word boundary already keeps `input_tokens` out
    # (an underscore is a word character, so there is no boundary before "token"),
    # but a bare `tokens: <digits>` would otherwise match - and a check that fires on
    # every run file is a check that gets removed.
    # The leading [A-Za-z0-9_]* lets the credential word be the TAIL of a longer
    # name, so ANTHROPIC_API_KEY matches as well as api_key. Safe because the
    # trailing \b stays: `input_tokens` still cannot match, since the character
    # after "token" is a letter.
    #
    # The separator allows a quote on either side, and a BACKSLASH before it: the
    # thing being searched is a JSON file, so a quoted value inside a tool result
    # arrives as \" rather than ". Without that the pattern matched a bare
    # `password=x` and missed `"password": "x"`, which is the form it will actually
    # meet.
    ("assigned secret",
     r"(?i)[A-Za-z0-9_]*(?:(?:api|auth|access|secret|private|client|bearer|session)"
     r"[_-]?(?:key|token|secret)"
     r"|api[_-]?key|passwd|password|credential|token|secret)\b"
     r"(?:\\?['\"])?\s*[=:]\s*(?:\\?['\"])?"
     r"(?=[A-Za-z0-9/_+\-]{16,})[A-Za-z0-9/_+\-]*[A-Za-z][A-Za-z0-9/_+\-]*"),
)

# Identifies the machine rather than exposing a credential. Refused by default, so
# that the operator sees it before it ships - and acceptable once seen, because a
# list of framework paths is not worth abandoning a corpus over.
_HOST_PATTERNS = (
    ("system framework path", r"/System/(?:Library|Cryptexes|Applications)/"),
    ("package manager path", r"/opt/homebrew/"),
    ("local install path", r"/usr/local/(?:bin|etc|lib|opt|Cellar)/"),
    ("another account's home", r"/Users/(?!Shared/)[A-Za-z0-9._-]+/"),
    ("another account's home", r"/home/(?!lost\+found)[A-Za-z0-9._-]+/"),
    ("private network address",
     r"\b(?:10\.\d{1,3}\.\d{1,3}\.\d{1,3}"
     r"|192\.168\.\d{1,3}\.\d{1,3}"
     r"|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})\b"),
    ("hardware address", r"\b(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}\b"),
) + tuple(
    # Characters that render as nothing - see invisible.py. Here for a different
    # reason from everything above it: not because they identify the machine, but
    # because they defeat the review this check exists to enable. Every other
    # finding is printed for the operator to judge, and that only works if reading
    # the printed value tells you what it is. A payload that renders as nothing
    # would be approved by a reviewer who read it carefully and saw nothing wrong.
    #
    # In the reviewable class rather than the never-acceptable one, because these
    # have legitimate uses: emoji sequences are built from zero-width joiners, and
    # a regional-flag emoji is a tag sequence. A model writing an emoji into its
    # deliverable is not smuggling anything, so this is a finding to look at, not
    # proof of intent. The count in the report is what distinguishes one stray
    # character from a run encoding a message.
    (f"invisible characters ({name})", pattern)
    for name, pattern in INVISIBLE_CLASSES.items()
)

# Home directory names a model writes rather than reads.
#
# Models use these as stand-ins when composing an example path, so they appear in
# reasoning and in deliverables. Treating them as findings would refuse an archive
# over text the agent made up, which is the failure mode that gets a check switched
# off rather than fixed.
#
# The operator's own home directory is rewritten before this runs, so a name reaching
# here is either a placeholder or a second account.
_PLACEHOLDER_HOMES = frozenset({
    "user", "users", "username", "youruser", "someuser", "service_account",
    "serviceaccount", "ubuntu", "admin", "administrator", "developer", "dev",
    "example", "test", "testuser", "me", "myuser", "app", "runner",
})


# The prefix every invisible-character finding's name carries, built by the
# comprehension above. Used to tell that class apart from the rest without a
# second list that could fall out of step with it.
_INVISIBLE_PREFIX = "invisible characters ("


def content_patterns(skip_invisible: bool = False):
    """
    (name, compiled regex, severity) for everything refused on content.

    `skip_invisible` drops the invisible-character classes and keeps every other
    pattern. See `_looks_binary` for the one caller that passes it.
    """
    patterns = (
        [(name, re.compile(rx), "secret") for name, rx in _SECRET_PATTERNS]
        + [(name, re.compile(rx), "host") for name, rx in _HOST_PATTERNS])
    if skip_invisible:
        patterns = [p for p in patterns
                    if not p[0].startswith(_INVISIBLE_PREFIX)]
    return tuple(patterns)


def _looks_binary(raw_bytes: bytes) -> bool:
    """
    Whether a file is binary, by the NUL-byte test git uses.

    WHY THE INVISIBLE-CHARACTER CHECK SKIPS THESE
    ---------------------------------------------
    That check exists to protect the operator's review: every other finding is
    printed for a human to judge, and a payload that renders as nothing would be
    approved by a reviewer who read it carefully and saw nothing wrong. Text is
    the whole premise.

    Compressed pixel data is not text. Decoding a PNG's IDAT chunk as UTF-8
    produces byte sequences that occasionally land in the variation-selector
    block, and the archive was refused twice over exactly that - once for a
    chart of gemini release dates, once for a question-12 forest plot, both in
    IDAT rather than in any metadata chunk. Nobody can review those; there is
    nothing there to read.

    Worse, the fingerprint is of the exact value, so every chart regeneration
    mints new ones. The acceptance file would fill with entries that mean
    nothing, and a list of noise is where a real finding goes unnoticed.

    EVERY OTHER PATTERN STILL RUNS ON BINARY FILES
    ----------------------------------------------
    A hostname, a home directory, an IP or a MAC address inside a compiled
    artefact is a genuine leak and is still refused: those are ASCII, they decode
    out of binary intact, and a human can read what was found. Only the class
    whose premise is "a human will read this" is skipped where no human can.
    """
    return b"\x00" in raw_bytes[:8192]


def _is_placeholder_home(matched: str) -> bool:
    parts = matched.strip("/").split("/")
    return len(parts) >= 2 and parts[1].lower() in _PLACEHOLDER_HOMES


def fingerprint(matched: str) -> str:
    """
    A stable, publishable identifier for one matched value.

    Hashed rather than quoted so the acceptance file can be committed without
    reproducing the thing it is about. The same value in forty files collapses to one
    fingerprint, so accepting a finding is one line rather than forty - and a
    DIFFERENT value cannot be covered by an existing acceptance, which is what stops
    an exemption from widening to cover something new.
    """
    return hashlib.sha256(matched.encode("utf-8", "replace")).hexdigest()[:16]


def _printable(value: str) -> str:
    """
    `value` with anything that does not render shown as its codepoint.

    The report exists to be READ - every host-class finding is printed for the
    operator to judge, and accepting one is a decision made from that line. An
    invisible-character finding printed verbatim occupies no space on screen, so
    the operator would be asked to approve a fingerprint next to what looks like
    an empty string. That is the same defeat-by-invisibility the check is for,
    reproduced in the tool reporting it.

    Applied to every host finding rather than only the invisible ones, so a
    control character inside any future pattern's match is legible too.
    """
    out = []
    for ch in value or "":
        if ch.isprintable() and not unicodedata.category(ch).startswith("C"):
            out.append(ch)
        else:
            out.append(f"<U+{ord(ch):04X}>")
    return "".join(out)


def _parses_as_json(raw: str) -> bool:
    """
    Whether `raw` is JSON at all.

    Asked separately from `_decoded_text` rather than inferred from its empty
    return, because "" means two different things there - a file that is not
    JSON and has nothing to decode, which is ordinary for a .md or a .png, and a
    file that SHOULD be JSON and is broken, which means a scan did not run.
    Conflating them is what let the second case look like the first.
    """
    try:
        json.loads(raw)
    except Exception:
        return False
    return True


def _decoded_text(raw: str) -> str:
    """
    Every string value in `raw`, decoded, or "" when it is not JSON.

    Searched IN ADDITION to the raw file, because the two hide different things and
    a check over either alone reports clean on the other.

    `json.dump` defaults to `ensure_ascii=True`, so a character outside ASCII is
    written as an escape sequence: a zero-width space is stored as the six visible
    characters `\\u200b`. A pattern matching the character itself therefore cannot
    match the file, and the first version of the invisible-character check silently
    found nothing for exactly that reason - it looked correct and tested nothing.

    Decoding rather than also matching the escape forms, because the escapes are not
    one shape: an astral character arrives as a surrogate pair, so the tag block
    would need `\\udb40\\udcXX` and the variation-selector supplement another range
    again. Decoding is what a consumer of the archive does, so it is also the view
    that decides whether the content is really hidden from them.
    """
    try:
        data = json.loads(raw)
    except Exception:
        return ""
    out = []

    def walk(value):
        if isinstance(value, str):
            out.append(value)
        elif isinstance(value, dict):
            for key, item in value.items():
                out.append(str(key))
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(data)
    return "\n".join(out)


def _passthrough_content_read_commands(raw: str) -> list:
    """
    Commands in `raw` that read a passthrough path's CONTENTS, or [] when there
    are none or `raw` is not a run file.

    WHY THIS EXISTS. The regex scan above catches a value it recognises the SHAPE
    of - a credential, a framework path. A passthrough content read is different:
    /bin, /usr, /opt and their siblings are deliberately left pointing at the real
    filesystem so a shell can execute what lives there (see filesystem_escapes.py),
    and reading a LISTING of one is unremarkable - that is what the passthrough is
    for. Reading a file's CONTENTS is not, because export.py cannot know in advance
    what shape that content will be, so no pattern can be written to catch it. This
    catches the fact that the read happened instead.

    Every saved episode so far has read only listings and lookups through this
    surface, never contents - measured over the whole corpus, not assumed. This is
    therefore a forward-looking invariant with no findings to migrate: the day an
    episode does read contents, publication stops until a human has looked at what
    it actually returned, which this function cannot see and does not try to.

    Delegates the "what counts as a content read" rule to detect_host_path_reads
    rather than re-deriving it here. A second copy of that rule is exactly the
    defect class this codebase keeps finding under a different name each time.
    """
    try:
        data = json.loads(raw)
    except Exception:
        return []
    if "transcript" not in data:
        return []
    return detect_host_path_reads(data["transcript"])["content_commands"]


def _read_for_scan(path: Path) -> tuple:
    """
    One file as `(bytes, text, why_unscanned)` for either scanner to examine.

    Both scanners ask this rather than each carrying its own read. Whether a file
    was examined at all is a property of the file, not of the question being asked
    about it, and the two had already drifted: one read bytes and decoded them,
    the other called `read_text()`, which follows the machine's locale - so the
    same archive could present different text to the two checks on a machine
    configured differently. A second copy of a rule this file's own comments warn
    about is how that happens.

    `bytes.decode()` is always UTF-8 whatever the locale, so the text both
    scanners see is now a property of the archive alone.

    `why_unscanned` is None when the file was read. Otherwise it names the failure
    and the caller must report it: `text` is not trustworthy and "found nothing"
    would mean "could not look".
    """
    try:
        raw_bytes = path.read_bytes()
    except Exception as e:
        return b"", "", f"unreadable: {type(e).__name__}"
    return raw_bytes, raw_bytes.decode(errors="replace"), None


def find_content_risks(root: str) -> list:
    """
    Every distinct finding under `root`, grouped by what was matched.

    Grouped rather than reported per occurrence: the operator has to read each
    distinct value once and decide, not scroll dozens of copies of the same one.

    The raw file and its decoded values are searched SEPARATELY, and the two are
    merged per file by taking the larger count rather than the sum. An ASCII value
    appears in both forms - a host path is the same characters escaped or not - so
    adding them double-counted every such finding, and the count is exactly what
    tells one stray character apart from a run encoding a message. The larger is the
    true count: for an ASCII value the forms agree, and for an escaped one the raw
    form contributes nothing.

    Across FILES the counts still add, which is why the max is taken per file and
    only then accumulated. Taking it globally would report a value present in five
    files as though it appeared in the busiest one alone.

    A FILE THIS CANNOT READ IS A FINDING, NOT A SKIP
    ------------------------------------------------
    This function decides publication, so "no findings" has to mean "looked and
    found nothing" and not "could not look". Both ways of failing to look are
    reported as `unscanned` severity and neither is acceptable by fingerprint:

      the bytes would not read at all - nothing about the file was examined;
      a .json file would not parse - the RAW scan ran, but the decoded one
      could not, and the decoded scan is the only one that sees an escaped
      invisible character. `json.dump` writes a zero-width space as the six
      characters `\\u200b`, so a pattern matching the character cannot match the
      file - that is the defect `_decoded_text` exists for, and a malformed file
      silently reinstates it.

    The redaction pass above already counts unreadable files and reconciles its
    total; this is the same rule applied to the pass that clears the archive.
    """
    found = {}

    def unscanned(path, why):
        key = ("unscanned", fingerprint(str(path)))
        found.setdefault(key, {
            "severity": "unscanned", "name": "unscanned",
            "fingerprint": fingerprint(str(path)), "value": why,
            "files": set(), "count": 0})["files"].add(path.name)
        found[key]["count"] += 1

    for path in sorted(Path(root).rglob("*")):
        if not path.is_file():
            continue
        raw_bytes, raw, why = _read_for_scan(path)
        if why:
            unscanned(path, why)
            continue
        if path.suffix == ".json" and not _parses_as_json(raw):
            # The raw scan below still runs on this file - it is the escaped-form
            # scan that cannot, so the file is reported as partly examined rather
            # than skipped.
            unscanned(path, "malformed JSON: the escaped-form scan could not run")
        # The binary test runs on the bytes on disk, not on a decode of them.
        # NUL survives a UTF-8 decode, so testing the string would work today -
        # but it would then depend on the decoder's behaviour for a question
        # that is purely about file content, and that is the kind of coupling
        # that breaks quietly when the read changes.
        patterns = content_patterns(skip_invisible=_looks_binary(raw_bytes))
        per_file = {}
        for form, text in (("raw", raw), ("decoded", _decoded_text(raw))):
            if not text:
                continue
            for name, regex, severity in patterns:
                for match in regex.finditer(text):
                    value = match.group(0)
                    if name == "another account's home" \
                            and _is_placeholder_home(value):
                        continue
                    key = (name, fingerprint(value))
                    found.setdefault(key, {
                        "severity": severity, "name": name,
                        "fingerprint": fingerprint(value), "value": value,
                        "files": set(), "count": 0})["files"].add(path.name)
                    seen = per_file.setdefault(key, {})
                    seen[form] = seen.get(form, 0) + 1
        for key, by_form in per_file.items():
            found[key]["count"] += max(by_form.values())
        for cmd in _passthrough_content_read_commands(raw):
            key = ("passthrough content read", fingerprint(cmd))
            found.setdefault(key, {
                "severity": "host", "name": "passthrough content read",
                "fingerprint": fingerprint(cmd), "value": cmd,
                "files": set(), "count": 0})["files"].add(path.name)
            found[key]["count"] += 1
    # unscanned first: it says the rest of this list is incomplete, which a
    # reader needs before weighing anything below it.
    order = {"unscanned": 0, "secret": 1, "host": 2}
    return sorted(found.values(),
                  key=lambda e: (order[e["severity"]], e["name"], e["fingerprint"]))


ACCEPTED_FILE = "export_accepted.txt"


def accepted_fingerprints(path: str = ACCEPTED_FILE) -> set:
    """
    Fingerprints the operator has reviewed and chosen to publish.

    Looked for beside the package as well as relative to the working directory, so
    that the answer does not depend on where the build was started from. A file this
    decides publication on must not be missable by a `cd`: not finding it means every
    reviewed finding reverts to unreviewed, which refuses a build that should pass and
    invites the check being bypassed rather than read.
    """
    candidates = [Path(path)]
    if not Path(path).is_absolute():
        candidates.append(Path(__file__).resolve().parent.parent / path)
    for candidate in candidates:
        try:
            text = candidate.read_text(encoding="utf-8")
        except OSError:
            continue
        out = set()
        for line in text.splitlines():
            line = line.split("#", 1)[0].strip()
            if line:
                out.add(line)
        return out
    return set()


def find_leaks(root: str) -> list:
    """
    Every (file, what, sample) under `root` that identifies the host, plus every
    file that could not be read to find out.

    A FILE THIS CANNOT READ IS A FINDING, NOT A SKIP
    ------------------------------------------------
    Same rule as `find_content_risks`, and for the same reason: this decides
    publication, so an empty return has to mean "looked and found nothing". It
    previously skipped an unreadable file silently, which made a tree containing
    the host identity in a file it could not open indistinguishable from a clean
    one - and this is the check on the host identity, the strictest thing the
    archive is held to.

    The gate happened to refuse such a tree anyway, because `find_content_risks`
    runs afterwards and reports it as `unscanned`. That is incidental: it holds
    only while the two run in that order in one process, and not at all for the
    callers that use this function on its own. A safety property that depends on
    another check running later is not one this function provides.

    Unreadable files are returned as `what="unreadable"` so the existing shape and
    the existing truthiness both still hold; the caller distinguishes them, since
    "cannot be read" is not the same claim as "identifies the host".
    """
    found = []
    for path in sorted(Path(root).rglob("*")):
        if not path.is_file():
            continue
        text, why = _read_for_scan(path)[1:]
        if why:
            found.append((str(path), "unreadable", why))
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
    parser.add_argument("--accepted", metavar="FILE", default=ACCEPTED_FILE,
                        help=f"fingerprints already reviewed and approved for "
                             f"publication (default: {ACCEPTED_FILE})")
    args = parser.parse_args(argv)

    if args.verify:
        leaks = find_leaks(args.verify)
        # Reported apart because they are different claims: one says a file names
        # the host, the other says the file could not be read, so whether it names
        # the host is unknown. Both refuse.
        unreadable = [f for f in leaks if f[1] == "unreadable"]
        identifying = [f for f in leaks if f[1] != "unreadable"]
        if identifying:
            print(f"\n  REFUSING TO PUBLISH: {len(identifying)} file(s) still "
                  f"identify the host.\n")
            for path, what, sample in identifying[:10]:
                print(f"    {os.path.basename(path)}  [{what}]")
                print(f"      ...{sample.strip()[:88]}...")
            if len(identifying) > 10:
                print(f"    ... and {len(identifying) - 10} more")
            print("\n  redaction.path_substitutions() decides what is rewritten; "
                  "a field\n  reaching the archive unredacted means export.py did "
                  "not walk it.")
        if unreadable:
            print(f"\n  REFUSING TO PUBLISH: {len(unreadable)} file(s) could not be "
                  f"read, so\n  whether they identify the host is unknown.\n")
            for path, _, why in unreadable[:10]:
                print(f"    {os.path.basename(path)}  [{why}]")
            if len(unreadable) > 10:
                print(f"    ... and {len(unreadable) - 10} more")
            print("\n  Nothing was read, so there is nothing to review. Drop the "
                  "file from the\n  results directory or fix what makes it "
                  "unreadable, then build again.")
        if leaks:
            return 1

        risks = find_content_risks(args.verify)
        accepted = accepted_fingerprints(args.accepted)
        secrets = [r for r in risks if r["severity"] == "secret"]
        # Deliberately NOT acceptable by fingerprint. Every other finding is a
        # value a human can look at and judge; this one says the value was never
        # read, so there is nothing to judge and a fingerprint of the path would
        # accept whatever the file holds next time too.
        unscanned = [r for r in risks if r["severity"] == "unscanned"]
        unreviewed = [r for r in risks if r["severity"] == "host"
                      and r["fingerprint"] not in accepted]
        # Subtracting the three named groups, so a severity added later cannot
        # arrive here as an accepted finding by default - which is exactly what
        # `unscanned` would have done before this line named it.
        reviewed = (len(risks) - len(secrets) - len(unscanned)
                    - len(unreviewed))

        if not secrets and not unreviewed and not unscanned:
            print(f"  verified clean: nothing under {os.path.basename(args.verify)} "
                  f"identifies this host"
                  + (f" ({reviewed} reviewed finding(s) accepted)"
                     if reviewed else ""))
            return 0

        print(f"\n  REFUSING TO PUBLISH: "
              f"{len(secrets) + len(unreviewed) + len(unscanned)} "
              f"finding(s) in {os.path.basename(args.verify)} that redaction "
              f"cannot rewrite.\n")
        for risk in unscanned:
            # First, because it says the rest of this list is incomplete.
            for name in sorted(risk["files"]):
                print(f"    [UNSCANNED] {name}: {risk['value']}")
        for risk in secrets:
            # Never echoed. A credential printed to a terminal is in the scrollback,
            # and from there in whatever the operator pastes next.
            print(f"    [CREDENTIAL] {risk['name']} in "
                  f"{len(risk['files'])} file(s), {risk['count']} occurrence(s)")
            print("                 not shown, and not acceptable - remove it")
        for risk in unreviewed:
            sample = _printable(risk["value"])
            if len(sample) > 60:
                sample = sample[:60] + "..."
            print(f"    [HOST] {risk['name']}: {sample}")
            print(f"           {risk['count']} occurrence(s) in "
                  f"{len(risk['files'])} file(s)   {risk['fingerprint']}")
        if unscanned:
            print(f"\n  {len(unscanned)} file(s) could not be fully examined, so "
                  f"'no findings' below\n  does not cover them. This is not "
                  f"acceptable by fingerprint: nothing was read,\n  so there is "
                  f"nothing to review. Drop the file from the results directory "
                  f"or\n  fix what makes it unreadable, then build again.")
        if secrets:
            print("\n  A credential cannot be accepted. Find it, and drop or "
                  "rewrite the episode\n  holding it before building the archive "
                  "again.")
        if unreviewed and not secrets:
            print(f"\n  These are reviewable rather than credentials: they identify "
                  f"the machine, they\n  render as nothing and so cannot be judged "
                  f"by reading the archive, or they are a\n  command that read a "
                  f"passthrough path's CONTENTS - go check the transcript for what "
                  f"it\n  actually returned, since this tool cannot see that. If "
                  f"you have and it is\n  publishable, append to {args.accepted}:\n")
            for risk in unreviewed:
                print(f"    {risk['fingerprint']}  # {risk['name']}")
            print("\n  Otherwise drop the episodes holding them. Accepting one "
                  "fingerprint accepts\n  that exact value and nothing else.")
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
