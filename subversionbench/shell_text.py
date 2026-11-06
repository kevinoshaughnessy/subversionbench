"""
Where a shell command's text is data rather than something the shell resolves:
quoted strings and heredoc bodies.

Split out of sandbox.py, which reached the file limit, because two readers of a
command need the same answer: the sandbox's path rewriter, which must not touch
data, and its traversal check under a bundle's sandbox policy (sandbox_policy.py),
which must not treat a `..` inside an awk or perl program as navigation.
"""

import re

_HEREDOC_START_RE = re.compile(r'<<-?\s*(["\']?)([A-Za-z_][\w-]*)\1')


def _heredoc_body_spans(cmd: str) -> list:
    """
    Character ranges of any heredoc bodies in `cmd`.

    A heredoc body is data the agent is writing, not arguments the shell will
    resolve, so nothing in it may be rewritten - see _rewrite_scenario_paths.
    """
    spans = []
    pos = 0
    while True:
        match = _HEREDOC_START_RE.search(cmd, pos)
        if not match:
            return spans

        delimiter = match.group(2)
        newline = cmd.find("\n", match.end())
        if newline == -1:
            # Opened but never started a body; nothing to protect.
            return spans
        body_start = newline + 1

        body_end = len(cmd)
        cursor = body_start
        while cursor <= len(cmd):
            line_end = cmd.find("\n", cursor)
            line = cmd[cursor:line_end if line_end != -1 else len(cmd)]
            if line.strip() == delimiter:
                body_end = cursor
                break
            if line_end == -1:
                break
            cursor = line_end + 1

        spans.append((body_start, body_end))
        pos = body_end


def _quoted_spans(text: str) -> list:
    """Character ranges inside single or double quotes."""
    spans = []
    quote = None
    start = 0
    i = 0
    while i < len(text):
        char = text[i]
        if quote is None and char in "\"'":
            quote, start = char, i + 1
        elif quote == char:
            spans.append((start, i))
            quote = None
        elif quote == '"' and char == "\\":
            i += 1
        i += 1
    if quote is not None:
        spans.append((start, len(text)))
    return spans
