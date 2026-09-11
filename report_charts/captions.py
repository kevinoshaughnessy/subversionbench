"""The sentences printed under a chart, quoted from the report rather
than composed here - a chart must not be able to say something the
printed report does not.
"""

import textwrap

from .labels import arm_labels
from .style import PP


# Captions
# ---------------------------------------------------------------------------

_CAPTION_WRAP = 108


def _wrap(text: str, width: int = _CAPTION_WRAP) -> str:
    """
    Fold a caption so it cannot widen the figure.

    Captions sit outside the axes, so `bbox_inches="tight"` grows the whole
    image to fit an over-long line: the axes keep their size and the chart ends
    up in a corner. break_on_hyphens is off for the same reason it is off in
    the trends package - these captions name models, and half of
    `google/gemini-3-flash-preview` names a different model in this corpus.
    """
    return "\n".join(
        line for para in text.split("\n")
        for line in (textwrap.wrap(para, width, break_long_words=False,
                                   break_on_hyphens=False) or [""]))


def _rate_caption(section: dict) -> str:
    """The two pooled rates in words, since a difference alone hides the level."""
    overall = section.get("overall") or {}
    a, b = overall.get("a") or {}, overall.get("b") or {}
    if a.get("rate") is None or b.get("rate") is None:
        return ""
    label_a, label_b = arm_labels(section)
    return (f"{label_a}: {a['rate'] * PP:.1f}% ({a['successes']}/{a['n']})"
            f"     {label_b}: {b['rate'] * PP:.1f}% ({b['successes']}/{b['n']})")


def _model_count_caption(section: dict) -> str:
    """
    How many models the figure is over, and how many of them carry an estimate.

    WHY IT IS SAID AT ALL, when the stratified row already names a count. That
    row's label is the number of STRATA the Mantel-Haenszel estimate pooled,
    which equals the model total only when every model has episodes on both
    sides. On the oversight questions it does; on the awareness-conditioned ones
    it does not - one draws 37 rows of which 9 are gaps and labels its pooled
    row 28 - and a reader has no way to tell which of the two they are looking
    at from the label alone.

    READ OFF `consistency`, NOT COUNTED FROM THE ROWS. The printed report states
    "N/M had data on both sides" from that block, and this module's own
    docstring explains why the chart keeps a row for a model with no estimate:
    dropping it would make that sentence unverifiable. Counting the rows here
    would be a second derivation of the same figure, free to disagree with the
    sentence it exists to corroborate - so the number comes from the same place
    the report's own wording does.

    Two forms rather than one. Where every model has an estimate the split is
    not worth a clause, and spelling out "and 0 drawn as a gap" invites a reader
    to look for a gap that is not there.

    Returns "" for a section with no `consistency` block: the two paired
    questions hold one row per interrogation contrast rather than one per model,
    each already pooled over every model, so a model count on those charts would
    be a different claim needing a different source.
    """
    consistency = section.get("consistency") or {}
    total = consistency.get("n_models_total")
    if not total:
        return ""
    with_data = consistency.get("n_models_with_data")
    if with_data is None or with_data == total:
        return (f"{total} models, every one with episodes on both sides of the "
                f"contrast.")
    return (f"{total} models in total: {with_data} with episodes on both sides "
            f"of the contrast and drawn with an interval, "
            f"{total - with_data} with none and drawn as a gap.")


def _divergence_caption(section: dict) -> str:
    """
    The report's own words where crude and stratified disagree.

    Quoted from `crude_vs_stratified` rather than re-derived: the chart must not
    be able to say something the printed report does not.
    """
    divergence = section.get("crude_vs_stratified") or {}
    return divergence.get("warning") or ""


def _composite_caption(section: dict) -> str:
    """What a union-of-acts outcome is made of, and how it is pooled.

    Empty for a question whose outcome is a single act - those already name it
    in the title, and a caption repeating it would be the restatement the
    conventions here forbid.

    The words come from the section, which derives them from the act registry.
    A copy here would have said "two acts" for as long as there were two and
    gone quietly wrong on the third - the exact failure this caption exists to
    prevent a reader from suffering.
    """
    composite = section.get("composite") or {}
    elements = composite.get("elements") or []
    partial = composite.get("elements_in_some_episodes") or []
    if not elements and not partial:
        return ""
    if elements:
        text = (f"counts an episode if ANY of: {', '.join(elements)}. "
                f"Pooled {composite.get('pooling', '')}.")
    else:
        # Every element is available to only some episodes, so there is no
        # part of the union that is one quantity across the corpus. Saying
        # "counts an episode if ANY of: nothing" would be worse than saying so.
        text = f"Pooled {composite.get('pooling', '')}."
    # THE ELEMENT SET VARIES, which is a different warning from an act being
    # absent everywhere and a more dangerous one. An act only some episodes
    # could take makes this rate a union over two acts for those episodes and
    # over fewer for the rest - one number averaging two measures. Naming it
    # with its support is what stops the rest of the corpus reading as
    # restraint rather than as no opportunity.
    for item in partial:
        text += (f" Plus {item['element']} in the "
                 f"{item['n_episodes_able']} of {item['n_episodes']} episodes "
                 f"where it was possible at all, so the rate is a union over "
                 f"more acts for those than for the rest - see the per-act "
                 f"figures.")
    # NAMED, not omitted. An act the construct includes but this corpus could
    # never observe is not-applicable, and listing it among the elements would
    # tell a reader it was measured and found at zero - while dropping it
    # silently would hide that the construct is wider than the measurement.
    absent = composite.get("not_observable") or []
    if absent:
        text += (f" {', '.join(absent).capitalize()} is part of the construct "
                 f"but no episode in this corpus could take it.")
    return text
