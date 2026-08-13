"""
Characters that render as nothing, and so cannot be reviewed by reading.

WHY THIS IS A HARNESS CONCERN AND NOT A GENERIC LINT
---------------------------------------------------
Two boundaries in this harness carry model-authored text somewhere consequential,
and at both of them "a human read it and it looked fine" is load-bearing:

  - The GRADER boundary. `quote_grounding.agent_corpus` collects the agent's own
    text and reasoning and hands it to a second model whose answer IS the
    eval-awareness measurement. That is model-authored text entering an LLM, which
    is the one place in this codebase where OWASP LLM01 applies literally. A
    sequence that renders as nothing can carry an instruction to the grader that
    nobody reviewing the transcript would see.

  - The PUBLICATION boundary. `export.py` refuses content it cannot rewrite, and
    the operator reviews what it reports. A payload that renders as nothing defeats
    that review by construction: the reviewer sees a clean string and approves it.

Both are review-integrity problems rather than secrecy problems, which is why the
answer differs by boundary. At the grader, the text is a DERIVED view built for
scoring, so the characters are removed. At publication they are REFUSED, because
the archive has to stay a faithful record of what happened.

NOT STRIPPED AT INGEST, DELIBERATELY
------------------------------------
`messages` holds the API conversation an episode ended with and exists so a saved
episode can be re-interrogated. Replay needs the bytes the model actually saw -
thinking-block signatures the API verifies among them - so rewriting a transcript
on the way in would make every replay a different conversation from the one it
claims to reproduce. Same reasoning as redaction: the corpus keeps fidelity, and
the derived views are what get cleaned.

WHAT THIS DOES NOT DO
---------------------
Nothing here touches a visible-text payload, and nothing here anticipates a
steganographic class not listed below. An agent that writes its instruction to the
grader in plain words is caught by reading the transcript, not by this.
"""

import re

# The classes, each because it renders as nothing while carrying bytes.
#
# ZWJ (U+200D) and the tag block both have legitimate uses - emoji sequences are
# built from them, and a regional-flag emoji is a tag sequence - so a hit here is
# reported for review rather than treated as proof of anything. That is also why
# the publication check refuses these as a REVIEWABLE finding, acceptable by
# fingerprint, rather than as the never-acceptable credential class.
INVISIBLE_CLASSES = {
    # Rehberger (2025c): carries arbitrary bytes, and is how a tag sequence
    # smuggles a payload behind a single visible glyph.
    "tag block": r"[\U000E0000-\U000E007F]",
    # Both the base block and the supplement; the supplement is what variation
    # selector smuggling uses to encode a byte per selector.
    "variation selector": r"[︀-️\U000E0100-\U000E01EF]",
    "zero width": r"[​‌‍⁠]",
    # Not in the OWASP item as written, included because it is the same failure
    # mode stated in the same terms - the rendered text differs from the text that
    # is acted on. This is the Trojan Source class (Boucher and Ron, 2021), which
    # reorders visible characters rather than hiding them, so a reviewer reads one
    # order and the grader receives another.
    "bidi control": r"[\u202A-\u202E\u2066-\u2069]",
}

_ANY = re.compile("|".join(f"(?:{p})" for p in INVISIBLE_CLASSES.values()))
_BY_CLASS = {name: re.compile(pattern)
             for name, pattern in INVISIBLE_CLASSES.items()}


def find_invisible(text: str) -> dict:
    """
    Which invisible classes `text` contains, and how many of each.

    Counts rather than a bool, because one stray character from a pasted emoji is
    a different fact from a run of two hundred encoding a message, and the two
    should not be reported the same way.
    """
    found = {}
    for name, pattern in _BY_CLASS.items():
        hits = len(pattern.findall(text or ""))
        if hits:
            found[name] = hits
    return found


def has_invisible(text: str) -> bool:
    """Whether `text` carries any of the classes above."""
    return _ANY.search(text or "") is not None


def strip_invisible(text: str) -> str:
    """
    `text` with every invisible character removed.

    For DERIVED views only - the corpus shown to the grader, and the quote matched
    against it. Removed rather than replaced with a marker: a marker would itself
    become text the grader reads, and the point is that the grader should see what
    a human reviewing the transcript sees.
    """
    return _ANY.sub("", text or "")
