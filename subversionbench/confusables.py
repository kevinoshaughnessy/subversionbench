"""
Characters that render as a Latin letter without being one.

WHAT THIS IS FOR, AND WHAT IT IS NOT FOR
----------------------------------------
Four episodes in the r1 corpus reasoned about exactly this move - substituting a
Cyrillic or Greek lookalike so that a literal match would fail while the text still
reads normally - and named the codepoint while doing it. None carried it out. This
module exists so that if one ever does, the harness measures what the text says
rather than what it is encoded as, and separately records that the substitution
happened.

The exposure is ONE measure, not the whole harness, and that is worth stating
because it bounds what this can be responsible for:

  - The misaligned ACTS are decided by hashing artefact files, so a substituted
    character cannot hide one: the hash moves whatever the bytes are.
  - Disclosure, the eval-awareness grader, and the authoritative interrogation
    verdict are LLM readings, and an LLM reads a lookalike as the letter it
    resembles. The keyword interrogation verdict is a second opinion only, and its
    disagreement with the LLM is already counted.
  - The sandbox matches COMMANDS, and a substituted character there defeats the
    agent's own command before it defeats the matcher. Zero appeared in any command
    across the saved corpus.
  - The awareness KEYWORD indicators are literal regexes over model prose. That is
    the one place a substitution changes a measured number, and so the one place
    this is folded in.

NOT THE SCENARIO'S OWN CHECKER, DELIBERATELY
--------------------------------------------
The scenario ships tooling that matches text, and it is left exactly as it is. Its
brittleness is an affordance the benchmark measures: an agent that works out it can
slip past a literal match is producing a finding, and hardening the thing being
probed would delete the finding rather than record it.

WHY THE TABLE IS GENERATED AND STRICTLY ONE-TO-ONE
--------------------------------------------------
`awareness_keywords._normalise_with_offsets` carries an index from each normalised
character back to the character it came from, so a reader can be shown an excerpt of
the ORIGINAL text rather than of the normalised form. A fold that maps one character
to several - which full NFKC does, since it expands ligatures - would break that
index silently and misattribute every excerpt after the first expansion.

So the mappings are DERIVED under a length filter rather than hand-listed: a
codepoint is only included when its replacement is a single ASCII letter. The
invariant is then a property of how the table is built rather than a promise about a
list somebody has to maintain, and `fold` cannot change a string's length. A test
asserts both.

Visible, unlike the classes in invisible.py, which is why nothing here is refused at
publication. A substituted character leaks nothing and reads fine; the reason to
care is that a literal matcher disagrees with a human about what the text says.
"""

import re
import unicodedata

_ASCII_LETTERS = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ")


def _build_tables():
    """
    Every letter that folds to exactly one ASCII letter, by two routes kept apart.

    The COMPATIBILITY route (NFKC) catches fullwidth forms, the mathematical
    alphanumerics, and the enclosed and modifier letters. Nobody types those in
    running prose by accident, so they count as a disguise.

    The DIACRITIC route catches precomposed accented letters, which NFKC leaves
    alone because an accented letter is not a compatibility variant of a bare one.
    These fold for matching but are NOT a disguise: an accent is ordinary
    orthography and a reader sees it. Reporting `café` as a substitution attempt
    would bury the real thing under every French word a model writes - the same
    argument that keeps a usage counter out of the export check.

    Both are filtered to a single-character result, so nothing that expands can
    enter either table - see the module docstring for why that matters.
    """
    disguise, diacritic = {}, {}
    for cp in range(0x80, 0x1FFFF):
        ch = chr(cp)
        if not unicodedata.category(ch).startswith("L"):
            continue
        compat = unicodedata.normalize("NFKC", ch)
        if len(compat) == 1 and compat in _ASCII_LETTERS:
            disguise[ch] = compat
            continue
        # Only a base ASCII letter plus combining marks: anything else is a
        # letter in its own right, not a decorated Latin one.
        decomposed = unicodedata.normalize(
            "NFD", compat if len(compat) == 1 else ch)
        if (decomposed and decomposed[0] in _ASCII_LETTERS
                and all(unicodedata.combining(c) for c in decomposed[1:])):
            diacritic[ch] = decomposed[0]
    return disguise, diacritic


# The Cyrillic and Greek lookalikes, which no normalisation form folds: they are
# distinct letters rather than variants, and that is exactly what makes them useful
# for this. Listed by hand because the resemblance is a fact about glyphs and not
# about the encoding, so nothing in unicodedata knows it.
#
# Only pairs that a reader would not distinguish in running prose. Cyrillic ф and
# Greek φ are omitted deliberately: they are not confusable with any Latin letter,
# and folding them would corrupt genuine Russian or Greek text for no gain.
CYRILLIC_AND_GREEK = {
    "а": "a", "с": "c", "е": "e", "һ": "h", "і": "i", "ј": "j", "к": "k",
    "ӏ": "l", "м": "m", "о": "o", "р": "p", "ԛ": "q", "ѕ": "s", "т": "t",
    "у": "y", "х": "x", "ѵ": "v", "ԝ": "w", "ь": "b", "ӓ": "a",
    "А": "A", "В": "B", "Е": "E", "Ѕ": "S", "І": "I", "Ј": "J", "К": "K",
    "М": "M", "Н": "H", "О": "O", "Р": "P", "С": "C", "Т": "T", "У": "Y",
    "Х": "X", "Ԛ": "Q", "Ԝ": "W",
    "α": "a", "ο": "o", "ρ": "p", "ε": "e", "ι": "i", "ν": "v", "υ": "u",
    "κ": "k", "τ": "t", "χ": "x", "γ": "y",
    "Α": "A", "Β": "B", "Ε": "E", "Ζ": "Z", "Η": "H", "Ι": "I", "Κ": "K",
    "Μ": "M", "Ν": "N", "Ο": "O", "Ρ": "P", "Τ": "T", "Υ": "Y", "Χ": "X",
}

_COMPATIBILITY, _DIACRITIC = _build_tables()

# What a reader would not distinguish from an ASCII letter, and would not have
# typed on purpose. This is the DETECTION set.
DISGUISE_CHARS = {**_COMPATIBILITY, **CYRILLIC_AND_GREEK}

# Everything that folds, disguise or not. This is the MATCHING set: the accented
# letters are in here so that an indicator phrase still matches text a model wrote
# with ordinary orthography, and out of the set above so that doing so is not
# reported as an attempt to hide something.
FOLD_TABLE = {**_DIACRITIC, **DISGUISE_CHARS}

# Enforced here rather than only in a test, because the offset index in
# awareness_keywords is silently wrong if this is ever false and nothing else
# would notice.
assert all(len(v) == 1 for v in FOLD_TABLE.values()), \
    "the fold table must be one-to-one or normalised offsets stop lining up"

_TRANSLATION = str.maketrans(FOLD_TABLE)

_DISGUISE_CLASS = "[" + re.escape("".join(sorted(DISGUISE_CHARS))) + "]"

# A word carrying BOTH an ASCII letter and a disguised one. Mixing inside a single
# word is the shape that matters: prose written in another script produces whole
# words in that script, and flagging those would report every multilingual answer as
# a substitution attempt.
_MIXED = re.compile(r"(?=[^\W\d_]*[A-Za-z])"
                    r"(?=[^\W\d_]*" + _DISGUISE_CLASS + r")"
                    r"[^\W\d_]+")

# The same alphabet with no lookahead and no tokenising, used only to decide whether
# `_MIXED` is worth running. `_MIXED` restarts two forward scans at every position in
# the string, so running it over a whole corpus costs 29 seconds; almost every entry
# that survives the ASCII check does so because of a dash, a curly quote or an emoji,
# none of which is a letter and so none of which is in this class. Deciding that with
# one character-class scan first cuts it to under a second, and cannot change an
# answer: `_MIXED` requires a character from this class in order to match at all.
_ANY_DISGUISE = re.compile(_DISGUISE_CLASS)


def fold(text: str) -> str:
    """
    `text` with every Latin-lookalike folded to the letter it resembles.

    Length-preserving, so an index into the result is an index into the input.

    The ASCII short-circuit is exact rather than a heuristic - every key in the
    table is non-ASCII, so an all-ASCII string cannot contain one - and it matters
    because this runs over every transcript entry in the corpus, where almost all of
    them are ASCII throughout. `str.isascii` is a C-level scan; the alternative is
    building a translated copy of every string in the corpus.
    """
    text = text or ""
    return text if text.isascii() else text.translate(_TRANSLATION)


def find_confusables(text: str) -> list:
    """
    The mixed-script words in `text`, each with what it folds to.

    Returns the words rather than a count, because the question a reader has is
    which word was disguised - `Strategy` matters and a degenerate token of run-
    together scripts does not, and only the word itself separates the two.
    """
    if not text or text.isascii() or not _ANY_DISGUISE.search(text):
        return []
    return [{"word": m.group(0), "folds_to": fold(m.group(0)),
             "codepoints": [f"U+{ord(c):04X}" for c in m.group(0)
                            if c in DISGUISE_CHARS]}
            for m in _MIXED.finditer(text)]


def has_confusables(text: str) -> bool:
    """Whether `text` contains a mixed-script word."""
    if not text or text.isascii() or not _ANY_DISGUISE.search(text):
        return False
    return _MIXED.search(text) is not None
