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

import getpass
import os
import re
import tempfile
from pathlib import Path

from .config import OPERATOR_DISPLAY_NAME, SANDBOX_DISPLAY_PATH


def _username_pattern():
    """
    Match the OS username as a standalone word, or None if we shouldn't try.

    `ls -l` inside the scenario prints an owner column - the scenario files
    belong to whoever ran the eval - so the username reaches output with no
    surrounding path for the path rules below to catch.

    Case-sensitive and word-bounded on purpose. The scenario text contains
    ordinary first names, and an operator whose username collided with one
    would otherwise have their transcripts rewritten mid-sentence. Very short usernames are skipped for the same
    reason: too likely to appear inside unrelated output.
    """
    try:
        username = getpass.getuser().strip()
    except Exception:
        # No passwd entry and no USER/LOGNAME set - nothing to redact.
        return None

    if len(username) < 3:
        return None

    return re.compile(rf'(?<![\w.-]){re.escape(username)}(?![\w.-])')


_USERNAME_RE = _username_pattern()


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

    for real_path, placeholder in path_substitutions(env_dir):
        text = text.replace(real_path, placeholder)

    # After the paths, so that a username inside one has already gone with it.
    if _USERNAME_RE is not None:
        text = _USERNAME_RE.sub(OPERATOR_DISPLAY_NAME, text)

    return text
