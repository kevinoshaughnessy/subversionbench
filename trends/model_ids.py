"""
Model IDs into families, and families into an order.

WHY THIS IS NOT A LIST OF FAMILIES
----------------------------------
The families are DERIVED, never enumerated. A hand-written list is wrong the day
after the next model is collected, and it is wrong silently - a new ID simply
fails to appear in any family and the report is quietly narrower than the
corpus. So `gemini-3.8-flash` joins the gemini-flash family with no edit here,
and any model whose family gains a second member starts being reported.

The cost of deriving is that the parse has to be right about things a list would
never have to state, and those are the two constants below: which trailing words
are release-stage qualifiers rather than family identity, and how a version
string is ordered. Both are wrong for some future ID, so both are reported in
the output rather than applied silently.

Nothing here reads a results directory, a metric or a rate. It is the one module
in this package that changes for a reason outside the analysis: a provider ships
an ID shaped in a way the parse has not seen.
"""

import re
from collections import namedtuple


# Trailing words that mark a RELEASE STAGE or a decoding mode rather than a
# distinct model line, so they must not split a family. Without this,
# `gemini-3-flash-preview` is its own family of one and never gets compared with
# the gemini-flash versions that followed it - which is exactly the comparison
# being asked for. Same for `kimi-k2-thinking` against `kimi-k2.5`.
#
# Deliberately short, and deliberately NOT holding tier words. `flash`, `pro`,
# `lite`, `mini` and a size like `27b` DO define a family: gemini-3.1-flash-lite
# is not a version of gemini-3.5-flash, and grouping them would compare two
# product lines and call the difference a trend.
QUALIFIER_TAGS = frozenset({
    "preview", "thinking", "exp", "experimental", "latest", "beta", "rc",
    "instruct", "chat", "base", "nightly",
})

# A version token: 4, 4.5, v4, 3.0. The leading v is stripped rather than kept
# in the stem, so `deepseek-v4-pro` and a future `deepseek-5-pro` land in one
# family instead of two.
_VERSION_RE = re.compile(r"^v?(\d+(?:\.\d+)*)$")

# A version glued to its stem: qwen3.8, kimi-k2.5, hy3. Split so the stem joins
# its family and the digits are read as the version.
_STEM_VERSION_RE = re.compile(r"^([a-z]+)(\d+(?:\.\d+)*)$")

# A date-stamped snapshot: 0813, 20251001, 2603. Four, six or eight digits, and
# never fewer - a bare 3 is a version, not a date. Ordered AFTER an undated
# member of the same version, since the dated one is the later snapshot.
_DATE_RE = re.compile(r"^\d{4}(?:\d{2}){0,2}$")

# A parameter count, which is family identity rather than version: a 27b and a
# 7b of the same generation are different models.
_SIZE_RE = re.compile(r"^\d+(?:\.\d+)?[bm]$")

ModelId = namedtuple(
    "ModelId", "raw provider stem version date tags unparsed")

VERSION_STYLES = ("component", "decimal")


def parse_model_id(model: str) -> ModelId:
    """
    Split a model ID into the parts that decide its family and its position.

    `version` is a tuple of ints, empty when the ID names no version. `date` is
    the snapshot stamp as a string, or None. `tags` are the release-stage words
    that were removed from the stem; `unparsed` holds anything that matched
    nothing, kept so a surprising ID is visible in the output instead of being
    quietly dropped.

    Consecutive numeric tokens merge into one version, because Anthropic writes
    with dashes what everyone else writes with dots: claude-haiku-4-5 is version
    (4, 5) and not two versions of something.
    """
    raw = model.strip()
    provider, _, rest = raw.rpartition("/")
    tokens = [t for t in re.split(r"[-_]", rest.lower()) if t]

    # `stamp` rather than `date`: this module now imports datetime.date for the
    # release-date charts, and a local of that name would shadow it here.
    stem_parts, version, stamp, tags, unparsed = [], [], None, [], []
    for token in tokens:
        # Dates BEFORE versions, because a stamp is a run of digits and the
        # version pattern matches it: without this, deepseek-v4-pro-0813 parsed
        # as version (4, 813) - sorting it after a hypothetical v4.99 - and
        # claude-haiku-4-5-20251001 as version (4, 5, 20251001).
        if _DATE_RE.match(token):
            stamp = token
            continue
        match = _VERSION_RE.match(token)
        if match:
            # Consecutive version tokens are components of ONE version.
            version.extend(int(p) for p in match.group(1).split("."))
            continue
        if token in QUALIFIER_TAGS:
            tags.append(token)
            continue
        if _SIZE_RE.match(token):
            stem_parts.append(token)
            continue
        match = _STEM_VERSION_RE.match(token)
        if match:
            stem_parts.append(match.group(1))
            version.extend(int(p) for p in match.group(2).split("."))
            continue
        if re.fullmatch(r"[a-z.]+", token):
            stem_parts.append(token)
        else:
            # Recorded rather than guessed at, and it still joins the stem so
            # two IDs sharing it stay together.
            stem_parts.append(token)
            unparsed.append(token)
    return ModelId(raw=raw, provider=provider, stem="-".join(stem_parts),
                   version=tuple(version), date=stamp, tags=tuple(sorted(tags)),
                   unparsed=tuple(unparsed))


def family_key(parsed: ModelId) -> str:
    """
    The family this model belongs to.

    Provider is part of the key on purpose. `gpt-5.6-luna` and
    `openai/gpt-5.6-luna` are the same model on two routes, and the routes
    differ in how much reasoning they return - so pooling them would compare
    instruments and report it as a version trend.
    """
    return f"{parsed.provider}/{parsed.stem}" if parsed.provider else parsed.stem


def version_sort_key(parsed: ModelId, style: str = "decimal"):
    """
    Where this model sits in its family's order.

    THE ONE JUDGEMENT CALL IN THIS FILE
    -----------------------------------
    `decimal` reads 4.20 as 4.2, so it sorts BEFORE 4.3. `component` reads it as
    major 4, minor 20 - so it sorts AFTER 4.6, the way a package manager reads a
    semantic version.

    `decimal` is the default because it is what the model vendors mean. It was
    NOT the original default, and the correction is worth recording: grok-4.20
    is an older release than grok-4.3, so the package-manager reading put it at
    the END of its family and reversed the sign of the family's trend - from
    falling to rising. Reading it as a semantic version was a guess about
    someone else's naming, and the guess was wrong.

    Every version in this corpus sorts correctly under `decimal`: 3.1 < 3.5 <
    3.6 < 3.7, 2.5 < 2.6, and a future 3.8 still lands after 3.7. `component`
    stays available because `decimal` has its own failure mode - a family that
    genuinely reaches minor 10 or beyond, where 4.10 follows 4.9 rather than
    preceding it. Nothing in this corpus does; if something ever does, the
    ambiguity report below is what will say so.

    Only a minor that reads differently as a decimal can differ between the two,
    which on this corpus is exactly one model: grok-4.20.

    The date stamp breaks ties within one version: an undated member sorts
    before a dated snapshot of the same version, which is what
    deepseek-v4-pro before deepseek-v4-pro-0813 means.
    """
    if style == "decimal" and len(parsed.version) > 1:
        head, tail = parsed.version[0], parsed.version[1]
        primary = (head, float(f"0.{tail}")) + parsed.version[2:]
    else:
        primary = parsed.version
    # "" sorts before any real stamp, so undated comes first.
    return (primary, parsed.date or "", parsed.tags)


def ordering_is_ambiguous(members: list) -> bool:
    """
    Whether the two version styles would order this family differently.

    Reported rather than resolved: a family whose answer depends on how 4.20 is
    read has not been measured, it has been assumed.
    """
    by_component = [m.raw for m in sorted(
        members, key=lambda m: version_sort_key(m, "component"))]
    by_decimal = [m.raw for m in sorted(
        members, key=lambda m: version_sort_key(m, "decimal"))]
    return by_component != by_decimal
