"""
Path redaction for SubversionBench.

Console output and the saved run JSON are research artifacts - they get
pasted into write-ups and issues - so they must not carry the operator's
real filesystem layout. Everything printed or persisted goes through
redact_paths() first, which rewrites host-specific directories to stable
placeholders so two runs of the same eval on different machines produce
identical text.

This is display-only. The real env_dir is still what the sandbox executes
in and what the ground-truth hash check reads, so redaction cannot change
what the eval measures.
"""

import functools
import getpass
import os
import re
import tempfile
from pathlib import Path

from .config import OPERATOR_DISPLAY_NAME, SANDBOX_DISPLAY_PATH


def _operator_username():
    """
    The OS username, or None if we shouldn't try to redact it.

    Very short usernames are skipped: too likely to appear inside unrelated
    output.
    """
    try:
        username = getpass.getuser().strip()
    except Exception:
        # No passwd entry and no USER/LOGNAME set - nothing to redact.
        return None

    return username if len(username) >= 3 else None


def _username_pattern():
    """
    Match the OS username as a standalone word, or None if we shouldn't try.

    `ls -l` inside the scenario prints an owner column - the scenario files
    belong to whoever ran the eval - so the username reaches output with no
    surrounding path for the path rules below to catch.

    Case-sensitive and word-bounded on purpose. The scenario text contains
    ordinary first names, and an operator whose username collided with one
    would otherwise have their transcripts rewritten mid-sentence.

    THE TWO SIDES ARE NOT SYMMETRIC, and that is deliberate.

    Before: the username had to be followed by a non-`[\\w.-]` character, so
    `<username>-code-zsh` - a real directory the shell listed out of /tmp - kept
    the username and blocked an archive from publishing. Tools name things after
    the account that owns them, so the username leading a hyphenated or dotted
    compound is one of its commonest routes into output, not an edge case.

    So a following `-` or `.` is now allowed and only a word character is not:
    `<username>-code-zsh` becomes `operator-code-zsh`, keeping the shape of the
    name while removing the identity. The LEADING guard stays strict, because
    something ending in the username (`x<username>y`) is a different token that
    merely contains those letters. `<username>s_backup` is likewise untouched -
    a following word character still blocks the match.
    """
    username = _operator_username()
    if username is None:
        return None

    return re.compile(rf'(?<![\w.-]){re.escape(username)}(?!\w)')


_USERNAME = _operator_username()
_USERNAME_RE = _username_pattern()


# The gap between two characters of one string in a character dump: runs of
# spaces on the same line, or a line break - which for `od` is followed by its
# offset column before the characters resume.
_DUMP_GAP = (
    r'(?:[ \t]+|[ \t]*\r?\n[ \t]*(?:[0-9a-fA-F]{4,10}[ \t]+)?)'
)


@functools.lru_cache(maxsize=64)
def _dump_spread_re(literal: str, word_bounded: bool):
    """
    Match `literal` spelled one character per column, as `od -c` prints it.

    A literal replacement cannot see a path in that form, so one reached a
    saved v15 transcript spelled
    "/   p   r   i   v   a   t   e   /   v   a   r   /   f   o   l   d   e   r
    s", complete with the octal offset column wrapping it across lines.

    Whitespace is required between *every* character, which is what keeps this
    off ordinary prose: with a username of "kevin", "take vintage" contains
    "ke vin" but not "k e v i n". Cached because the patterns are rebuilt for
    every redacted string and only change with the host.
    """
    body = _DUMP_GAP.join(re.escape(char) for char in literal)
    if word_bounded:
        body = rf'(?<![\w.-]){body}(?![\w.-])'
    return re.compile(body)


def _variants(path: str) -> list:
    """
    A directory and its symlink-resolved spelling.

    Both are needed because they can differ and both reach the console:
    on macOS TMPDIR is under /var/folders, which resolves to /private/var,
    and shell builtins report whichever form they were handed.
    """
    seen = []
    for candidate in (path, os.path.realpath(path)):
        candidate = str(candidate).rstrip("/")
        if candidate and candidate not in seen:
            seen.append(candidate)
    return seen


def path_substitutions(env_dir: str = None) -> list:
    """
    Build the (real_path, placeholder) pairs to apply, longest real path
    first so that nested directories are rewritten before their parents -
    env_dir lives inside the temp dir, which on some hosts lives inside the
    home dir, and replacing the parent first would strand a half-rewritten
    path like "~/T/mtp_prod_a1b2_xyz".
    """
    pairs = []

    if env_dir:
        for variant in _variants(env_dir):
            pairs.append((variant, SANDBOX_DISPLAY_PATH))

    for variant in _variants(tempfile.gettempdir()):
        pairs.append((variant, "/tmp"))

    for variant in _variants(str(Path.home())):
        pairs.append((variant, "~"))

    pairs.sort(key=lambda pair: len(pair[0]), reverse=True)
    return pairs


def redact_paths(text, env_dir: str = None):
    """
    Rewrite host-specific absolute paths in `text` to stable placeholders.

    Non-string input is returned unchanged, so this can be applied to
    transcript fields without the caller type-checking first.
    """
    if not isinstance(text, str) or not text:
        return text

    pairs = path_substitutions(env_dir)

    for real_path, placeholder in pairs:
        text = text.replace(real_path, placeholder)

    # `od -c`, `hexdump -c` and `fold -w1` print one character per column, so
    # a path in their output is not the literal string the pass above looks
    # for. Longest first, like the pass above, so a nested directory is
    # rewritten before its parent.
    for real_path, placeholder in pairs:
        text = _dump_spread_re(real_path, False).sub(placeholder, text)

    # After the paths, so that a username inside one has already gone with it.
    if _USERNAME_RE is not None:
        text = _USERNAME_RE.sub(OPERATOR_DISPLAY_NAME, text)
        text = _dump_spread_re(_USERNAME, True).sub(OPERATOR_DISPLAY_NAME, text)

    return text
