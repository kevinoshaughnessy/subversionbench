"""Turning a question id and its levels into the words a reader sees.
"""


# ---------------------------------------------------------------------------
# Naming the arms
# ---------------------------------------------------------------------------
#
# A contrast stores its levels as the raw values it split on - True/False for
# oversight and for awareness, "max"/"none" for nudge - and the words that make
# those readable live at each question's call site in report/, inside a
# `finding` sentence that is already composed by the time it reaches here.
#
# So the words are rebuilt from the exposure named in the question id. Keyed by
# exposure rather than by question, because three questions share `oversight`
# and six share `awareness`, and a per-question table would let two questions
# drift into labelling the same split differently.
#
# test_report_charts pins this against the ids build_report actually emits, so a
# renamed or added question fails the suite rather than silently drawing a chart
# with an unlabelled axis.
_LEVEL_WORDS = {
    "oversight": {True: "oversight present", False: "oversight absent"},
    "nudge": {"max": "nudge=max", "strong": "nudge=strong", "none": "nudge=none"},
    "awareness": {True: "verbalised awareness", False: "no verbalised awareness"},
}


def exposure_of(question_id: str) -> str:
    """The manipulated axis named on the left of a question id."""
    return question_id.split("_vs_")[0]


def arm_labels(section: dict) -> tuple:
    """
    Readable names for the two sides of a contrast, or the raw levels.

    Falling back to the raw level rather than raising: a chart with an ugly
    label still carries its numbers, and a report that dies on a new question id
    loses eleven charts that were fine.
    """
    overall = section.get("overall") or {}
    words = _LEVEL_WORDS.get(exposure_of(section["id"]), {})
    return (words.get(overall.get("level_a"), str(overall.get("level_a"))),
            words.get(overall.get("level_b"), str(overall.get("level_b"))))


def short_label(question_id: str) -> str:
    """
    "oversight -> scheming", from the id.

    Derived rather than tabulated: the ids are already written as
    `<exposure>_vs_<outcome>`, so a hand-kept table of pretty names would be a
    second place to update and a place for the two to disagree.
    """
    return question_id.replace("_vs_", " -> ").replace("_", " ")
