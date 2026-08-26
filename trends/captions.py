"""
The words on a chart: point labels, slope labels and exposure captions.

Separated from the plotting because this is where the reader is told how to read
the figure, and getting it wrong misleads in a way a misplaced label does not.
The long comment below is a worked example: the same exposure figures need
OPPOSITE readings depending on which awareness metric is plotted, and for a
while both charts carried the same sentence.

Text only. Nothing here draws, and nothing here needs matplotlib.
"""

import textwrap

from .metrics import TEXT_REACHABLE, _MAX_NAMED_SILENT


def _member_labels(family: dict) -> list:
    """
    What to write under each point.

    The version, not the model ID: the IDs share a stem by construction - that
    is what put them in one family - so plotting the full ID spends the x axis
    repeating it. A date-stamped snapshot keeps its stamp, because that is the
    only thing separating it from the version above it.
    """
    labels = []
    for member in family["members"]:
        label = member["version"] or "?"
        if member["date"]:
            label += f"\n{member['date']}"
        if member["tags"]:
            label += f"\n({','.join(member['tags'])})"
        # The denominator each point's rate and interval are computed on. A
        # width of interval means nothing without it, and it is not constant
        # across a family - gemini-3.5-flash carries 205 against its siblings'
        # 120, and grok-4.5 239 against 120.
        if member.get("n") is not None:
            label += f"\nn={member['n']}"
        labels.append(label)
    return labels


def _slope_label(fit: dict) -> str:
    """
    The fitted slope for a legend entry, or nothing when there is no line.

    Empty rather than "n/a" for a family that could not be fitted: a legend is
    read at a glance, and the family's marker count in the same entry already
    says why - one dated release cannot have a slope.
    """
    if not fit or fit.get("slope_per_month") is None:
        return ""
    return f", {fit['slope_per_month'] * 100:+.1f} pts/month"


# What a zero in the exposure caption MEANS depends on which metric is plotted,
# and the two meanings are opposites. Both awareness charts carry the same
# exposure figures - the figures are a fact about the corpus, not about the
# analysis - but the reader needs opposite things from them:
#
#   `aware` reads the reasoning trace AND visible text. A route that returned no
#   trace was therefore read on a narrower instrument than one that did, so its
#   rate is not comparable with the rest. Distrust the zeroes.
#
#   `text_reachable` reads visible text ONLY. It is the same instrument for
#   every model by construction - that is the whole reason it exists. Where a
#   trace came back the figure is a FLOOR (it asks where the grader's cited
#   evidence sits, not what the grader would have said shown text alone); where
#   no trace came back the grader was already looking at visible text alone, so
#   the figure is EXACT. Trust the zeroes MORE than the rest.
#
# For a while both charts carried the `aware` sentence, because no call site
# passed the metric down. On the text_reachable chart that told the reader to
# discount the only two points that needed no discounting.
#
# SAY WHAT DIFFERS, NOT THAT SOMETHING DIFFERS
# --------------------------------------------
# The `aware` clause used to end "not measured on the same instrument as the
# rest", which names no instrument and leaves the reader to work out what to do
# about it. The text_reachable clause beside it says exactly what changes -
# exact here, floors there - and reads far better for it. So the `aware` clause
# now names the same concrete thing: how many channels each group's awareness
# could have surfaced in. Two rates over different channel counts is the whole
# of what "different instrument" was gesturing at.
_EXPOSURE_READING = {
    "aware": "awareness above is read from that trace as well as visible text, "
             "so a model at 0% could only show it in the one channel",
    TEXT_REACHABLE: "awareness above is read from visible text only, so a 0% "
                    "here marks an exact rate and the rest are floors",
}

# A caption is drawn outside the axes, so `bbox_inches="tight"` widens the whole
# FIGURE to fit it - the axes keep their size and the saved image grows, which
# reads as a chart squeezed into one corner. Saying more per caption made this
# visible: the combined awareness chart went to 2127px against 1212px for the
# same chart without one. So captions wrap instead of stretching the figure.
#
# 85 characters is the longest line the callers already produce ("separate
# reasoning trace returned in 36%-100% of episodes for 13 of these 15 models" is
# 83), which is what made those charts the right width before the clauses grew.
_CAPTION_WRAP = 85


def _wrap_caption(note: str) -> str:
    """
    Fold a caption to _CAPTION_WRAP, keeping the lines the caller chose.

    Each logical line wraps on its own, because those breaks are structural -
    the figures on one line and the group read differently on the next - and
    reflowing them together would run the two statements into each other, which
    is the ambiguity the split was introduced to remove.

    NEITHER DEFAULT IN textwrap IS SAFE FOR MODEL IDS
    -------------------------------------------------
    `break_on_hyphens` would fold "google/gemini-3-flash-preview" across two
    lines, and these captions exist largely to name models - a reader cannot
    match a half ID to a legend entry, and "gemini-3-flash" is a DIFFERENT model
    in this corpus. `break_long_words` would cut mid-ID for the same loss. So a
    token that will not fit is left overhanging: one wide line is a smaller
    problem than an ID that cannot be read or searched for.
    """
    return "\n".join(
        line for para in note.split("\n")
        for line in (textwrap.wrap(para, _CAPTION_WRAP,
                                   break_long_words=False,
                                   break_on_hyphens=False) or [""]))


def _exposure_note(members: list, metric: str = None) -> str:
    """
    Each member's reasoning exposure, for a caption under an awareness chart.

    Named per model rather than summarised, because the comparison a reader
    makes is between two specific points and the question is which instrument
    each was measured with. A model at 0% did not fail to reason - its route
    returned no reasoning TEXT - and that is the difference the awareness rate
    cannot show on its own.

    SEPARATE is the word that carries the caption
    --------------------------------------------
    An earlier version said "reasoning text returned in: 4.20 0%", which a
    reader took to mean the model had produced nothing to reason from. It had:
    x-ai/grok-4.20 wrote a visible answer in 117 of its 120 episodes and made
    2,072 tool calls. What its route never returned was a chain of thought
    ALONGSIDE that answer. The percentage is about a channel, not about whether
    the model said anything, and "separate" is what makes the two distinct
    without requiring the reader to know how any provider is wired.

    `metric` selects the second line, which says what a zero means HERE; see
    _EXPOSURE_READING. Omitted, the caption states the figures and draws no
    conclusion from them, which is the only safe default.
    """
    parts = []
    for m in members:
        e = m.get("reasoning_exposure") or {}
        if e.get("share") is None:
            continue
        parts.append(f"{_release_point_name(m)} {e['share']:.0%}")
    if not parts:
        return ""
    note = ("separate reasoning trace returned in: "
            + ", ".join(parts) + " of episodes")
    reading = _EXPOSURE_READING.get(metric)
    return _wrap_caption(f"{note}\n{reading}" if reading else note)


def _exposure_range_note(families: list, metric: str = None) -> str:
    """
    The spread of exposure across every plotted model, for the combined charts.

    THE TWO GROUPS MUST NOT OVERLAP
    -------------------------------
    An earlier version gave the range over ALL models and then named the ones
    returning nothing. Both statements were true and together they were
    misleading: the range's own lower bound WAS those models, so "0%-100%
    across these 15 models; 2 returned none at all" reads as though some third
    set of models sits at 0% besides the two named.

    So the range now covers only the models that returned some reasoning text,
    and the second line names the rest. The two counts add to the total, which
    is what makes the caption checkable at a glance.

    Naming every model would not fit on a combined chart, hence a range for the
    measured group; the ones returning nothing are named in full because that is
    the group whose reading differs from the rest - in OPPOSITE directions on
    the two metrics, which is why `metric` decides the clause that closes the
    line rather than one fixed sentence serving both. See _EXPOSURE_READING.

    On "separate reasoning trace" rather than "reasoning text", see
    `_exposure_note` - a model at 0% still writes visible answers, and the
    shorter phrasing read as though it did not.

    Returns "" or a one- or two-line string; the caller advances its stacking
    offset by the number of lines.
    """
    named = [(m["model"], (m.get("reasoning_exposure") or {}).get("share"))
             for f in families for m in f["members"]]
    known = [(m, s) for m, s in named if s is not None]
    if not known:
        return ""
    silent = sorted(m for m, s in known if s == 0)
    some = [s for _m, s in known if s > 0]
    total = len(known)

    one = len(silent) == 1
    if not some:
        # Every model in the same position, so there is no split to report -
        # just what that shared position means for the rate above.
        tail = {
            "aware": "so every rate here rests on visible text alone",
            TEXT_REACHABLE: "which is the only channel this rate reads, so "
                            "every rate here is exact rather than a floor",
        }.get(metric)
        note = (f"none of these {total} models returned a separate reasoning "
                f"trace")
        return _wrap_caption(f"{note}, {tail}" if tail else note)

    span = (f"{min(some):.0%}" if min(some) == max(some)
            else f"{min(some):.0%}-{max(some):.0%}")
    if not silent:
        # No split to report, so the clause says what holds for everyone. Worth
        # a line even though nothing is wrong: "every rate here is a floor" is
        # not something a reader can infer from a range, and its absence would
        # read as though some point on the chart were exact.
        note = (f"separate reasoning trace returned in {span} of episodes "
                f"across all {total} models")
        tail = {
            "aware": "this rate reads both channels, and every model here "
                     "supplied both",
            TEXT_REACHABLE: "this rate reads visible text only, so every rate "
                            "here is a floor",
        }.get(metric)
        return _wrap_caption(f"{note}\n{tail}" if tail else note)

    # Capped so a corpus where most models return nothing does not produce a
    # caption wider than the figure. The counts still add to the total.
    shown = silent[:_MAX_NAMED_SILENT]
    listed = ", ".join(shown)
    if len(silent) > len(shown):
        listed += f" and {len(silent) - len(shown)} more"
    # "the rest" rather than "the other {len(some)}": the counts are already on
    # the line above, and spelling them again here pushed the text_reachable
    # clause two characters past the wrap, which left "floors" orphaned on a
    # line of its own under the centred release charts.
    tail = {
        # Named channels rather than "a different instrument": the reader can
        # act on one channel against two, and cannot act on the abstraction.
        "aware": (f"this rate reads both channels, so "
                  f"{'that model' if one else 'those models'} could only show "
                  f"awareness in visible text and the rest in either"),
        # The opposite reading, and the reason this clause is not fixed text:
        # here the models with no trace are the ones needing NO caveat.
        TEXT_REACHABLE: (f"this rate reads visible text only, so "
                         f"{'that rate is' if one else 'those rates are'} "
                         f"exact and the rest are floors"),
    }.get(metric)
    # The reading goes on its own line rather than trailing the model list
    # behind a dash. Appended, it made one 171-character line that widened the
    # saved figure by 900px; broken here, each statement wraps within itself and
    # the reader gets figures, then who differs, then what that means.
    head = (f"separate reasoning trace returned in {span} of episodes for "
            f"{len(some)} of these {total} models\n"
            f"the other {len(silent)} returned no trace at all - {listed}")
    return _wrap_caption(f"{head}\n{tail}" if tail else head)


def _release_point_name(member: dict) -> str:
    """
    What identifies one point on a calendar axis, in one line.

    The version alone is not enough and the model ID is too much. Two members of
    a family can share a version - deepseek-v4-pro and deepseek-v4-pro-0813 are
    both `4`, kimi-k2 and kimi-k2-thinking are both `2` - and a chart that labels
    both points `4` reads as a mistake even though the x positions differ. So the
    stamp and the tags come along, written the way the ID writes them.

    One line rather than the three _member_labels uses: those are tick labels
    with a column to themselves, these sit beside a point among other points.
    """
    name = member["version"] or "?"
    if member["date"]:
        name += f"-{member['date']}"
    if member["tags"]:
        name += f" ({','.join(member['tags'])})"
    return name
