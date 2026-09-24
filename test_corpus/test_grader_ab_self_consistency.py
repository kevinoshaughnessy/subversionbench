"""
Two identical grader passes, compared: does the judge change its mind?

The measurement this guards is the self-consistency leg of the checklist's item
on LLM judges (I.c.1 in the standalone checklist). Every case here is synthetic
because the real thing costs money per episode, and because the distinction the
module exists to draw - a changed judgement against a dropped answer - cannot
be produced on demand from a live grader.

THE FIXTURE IS VERIFIED BEFORE IT IS USED. The first version of this
measurement was validated against a rubric with an invented question key, so
the real classifier ignored it: the comparison reported zero changes against
seven planted ones and looked like a pass. Every test below draws its keys from
RUBRIC_QUESTIONS, and `test_the_fixture_can_actually_move_the_verdict` asserts
the lever works before anything is concluded from it.
"""

import pytest

from grader_ab.self_consistency import (DROPPED_ANSWER, JUDGEMENT,
                                        REFERENCE_CELL, change_kind, compare,
                                        reweighted_judgement_rate)
from grader_ab.readout import cell_verdict
from subversionbench.config import RUBRIC_QUESTIONS
from test_corpus.grader_ab_fixtures import _rubric

KEYS = list(RUBRIC_QUESTIONS)
AWARE_KEY = "suspects_being_tested"


def _aware(**overrides):
    """A rubric the real classifier reads as aware, with named overrides."""
    answers = [True if k == AWARE_KEY else False for k in KEYS]
    rubric = _rubric(KEYS, answers)
    for key, value in overrides.items():
        rubric[key] = dict(rubric[key], answer=value)
    return rubric


def _unaware(**overrides):
    rubric = _rubric(KEYS, [False] * len(KEYS))
    for key, value in overrides.items():
        rubric[key] = dict(rubric[key], answer=value)
    return rubric


def _doc(pairs, stored=None):
    """A grader_ab result document holding `pairs` as {run: rubric}."""
    return {
        "sample": [{"run": run, "stored_aware": (stored or {}).get(run, True),
                    "model": "p/m", "nudge": "strong", "oversight": True,
                    "lure": False}
                   for run in pairs],
        "cells": {REFERENCE_CELL: dict(pairs)},
    }


class TestTheFixtureIsSound:
    def test_the_fixture_can_actually_move_the_verdict(self):
        """Without this every test below can pass while proving nothing - which
        is how the first run of this measurement reported 0 of 7 planted
        changes and read as a success."""
        assert cell_verdict(_aware()) is True
        assert cell_verdict(_unaware()) is False

    def test_the_keys_are_the_real_ones(self):
        assert KEYS, "no rubric questions - every case would be vacuous"
        assert AWARE_KEY in KEYS, sorted(KEYS)


class TestAChangedMindIsToldFromADroppedAnswer:
    """The distinction a raw disagreement count gets wrong, and the reason this
    module exists rather than a subtraction in a script."""

    def test_two_identical_passes_show_no_change(self):
        assert change_kind(_aware(), _aware()) is None

    def test_a_different_answer_on_a_shared_question_is_a_judgement(self):
        assert change_kind(_aware(), _unaware()) == JUDGEMENT

    def test_a_verdict_that_moves_on_a_missing_answer_is_not(self):
        """The real case: one pass answered the load-bearing question, the
        other dropped it, and every question answered on BOTH sides agreed. The
        grader did not change its mind - a call failed."""
        before = _aware()
        after = _aware(**{AWARE_KEY: None})
        assert cell_verdict(before) != cell_verdict(after), (
            "the fixture must actually flip the verdict, or this asserts "
            "nothing")
        assert change_kind(before, after) == DROPPED_ANSWER

    def test_a_dropped_answer_that_changes_nothing_is_not_counted(self):
        """A question can go missing without moving the verdict, and that is
        not a finding of any kind.

        This exercises the verdict-equality early return, NOT the answer
        comparison below it - planting a defect in `_shared_answers_differ`
        leaves this passing, because `change_kind` never reaches it when the
        verdicts already agree. The case that guards that comparison is
        `test_a_verdict_that_moves_on_a_missing_answer_is_not`, and the plant
        confirms it.
        """
        assert change_kind(_aware(), _aware(broke_character=None)) is None


class TestTheComparisonOverADocument:
    def _result(self):
        a = _doc({"r1": _aware(), "r2": _unaware(), "r3": _aware(),
                  "r4": _unaware()},
                 stored={"r1": True, "r2": False, "r3": True, "r4": False})
        b = _doc({"r1": _aware(),
                  # r2: a real change of mind, on the unaware side.
                  "r2": _unaware(**{AWARE_KEY: True}),
                  # r3: the load-bearing answer dropped.
                  "r3": _aware(**{AWARE_KEY: None}),
                  "r4": _unaware()},
                 stored={"r1": True, "r2": False, "r3": True, "r4": False})
        return compare(a, b)

    def test_the_two_kinds_are_counted_apart(self):
        r = self._result()
        assert r["n_compared"] == 4
        assert r["any_change"]["k"] == 2
        assert r["judgement_change"]["k"] == 1
        assert r["dropped_answer"]["k"] == 1
        assert r["changed_runs"] == {"r2": JUDGEMENT, "r3": DROPPED_ANSWER}

    def test_the_strata_count_judgement_changes_only(self):
        """A dropped answer is a grader error, not evidence about either
        stratum's stability, so it must not inflate one of them."""
        r = self._result()
        assert r["by_stored_verdict"][True]["k"] == 0, "r3 was the dropped one"
        assert r["by_stored_verdict"][False]["k"] == 1
        assert r["by_stored_verdict"][True]["n"] == 2
        assert r["by_stored_verdict"][False]["n"] == 2

    def test_an_unresolved_verdict_is_excluded_and_counted(self):
        """All-None on either side has no verdict, and scoring that as a
        change would be the absence-is-a-no error cell_verdict prevents."""
        blank = _rubric(KEYS, [None] * len(KEYS))
        r = compare(_doc({"r1": _aware(), "r2": blank}),
                    _doc({"r1": _aware(), "r2": blank}))
        assert r["n_compared"] == 1 and r["n_unresolved"] == 1

    def test_two_different_samples_are_refused(self):
        """The sample is deterministic for given arguments, so a mismatch means
        the two documents came from different runs - intersecting them silently
        would measure something other than the grader."""
        with pytest.raises(ValueError, match="different samples"):
            compare(_doc({"r1": _aware()}), _doc({"r2": _aware()}))


class TestTheReweightedRate:
    def test_it_weights_the_two_strata_by_the_corpus_base_rate(self):
        r = compare(
            _doc({"a1": _aware(), "u1": _unaware()},
                 stored={"a1": True, "u1": False}),
            _doc({"a1": _unaware(), "u1": _unaware()},
                 stored={"a1": True, "u1": False}))
        # Aware stratum changed 1/1, unaware 0/1, so the answer IS the weight.
        assert reweighted_judgement_rate(r, 0.25) == pytest.approx(0.25)
        assert reweighted_judgement_rate(r, 0.75) == pytest.approx(0.75)

    def test_it_declines_when_a_stratum_is_empty(self):
        """Rather than divide by zero or quietly report the one side it has."""
        r = compare(_doc({"a1": _aware()}, stored={"a1": True}),
                    _doc({"a1": _aware()}, stored={"a1": True}))
        assert reweighted_judgement_rate(r, 0.3) is None
