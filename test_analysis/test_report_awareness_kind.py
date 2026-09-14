"""
`safety_aware`/`capability_aware`: episode_rows.py's _kind_flag, tested apart
from test_report_loading.py because that file is already near the 1000-line
limit and this is a self-contained slice - one derivation, one fixture, one
class - rather than a division the rest of that file's tests share.
"""

import json
import tempfile

import report as rr
from conftest import batch_episode
from subversionbench.reporting.facts import normalise_analyses


def _write_kind_episode(out, n, kind, grading_failed=False, keywords=None,
                        model="m", nudge="strong", oversight=True,
                        stamp="20260101T000000"):
    """One run file with the grader's `eval_awareness_kind` set directly.

    `kind` is whatever the grader would have written: "safety", "capability",
    "both", "unspecified", "ambiguous", or None for an episode the grader
    found unaware (which is what grader.py itself writes when eval_aware is
    False - see grader.py's own eval_awareness_kind derivation). `eval_aware`
    is derived from `kind` rather than passed separately, because the two
    cannot disagree in real grader output: a kind other than None only exists
    because eval_aware was True.
    """
    ep = batch_episode()
    normalise_analyses([ep])
    analysis = dict(ep["analysis"])
    if grading_failed:
        analysis["eval_awareness_grader"] = {
            "eval_aware": None, "grading_failed": True,
            "eval_awareness_kind": None, "rubric_results": {}}
    else:
        analysis["eval_awareness_grader"] = {
            "eval_aware": kind is not None, "grading_failed": False,
            "eval_awareness_kind": kind, "rubric_results": {}}
    if keywords is None:
        analysis.pop("eval_awareness_keywords", None)
    else:
        analysis["eval_awareness_keywords"] = {"eval_aware": keywords,
                                               "goal_conflict_noted": False}
    parts = ["run", str(n), model.replace("/", "_"), nudge]
    if not oversight:
        parts.append("nooversight")
    path = f"{out}/{'_'.join(parts)}_{stamp}.json"
    with open(path, "w") as f:
        json.dump({"model": model, "nudge": nudge, "oversight": oversight,
                   "lure": False, "analysis": analysis,
                   "transcript": [{"turn": 1, "type": "text",
                                   "content": "I recommend B."}]}, f)
    return path


class TestTheAwarenessKindColumns:
    """`safety_aware`/`capability_aware` are derived from the grader's
    `eval_awareness_kind` by _kind_flag in episode_rows.py: True/False only
    where the flavour is classifiable, None where it is not - which is a
    different set of episodes than `kind is None` alone, because a
    keyword-only `aware` verdict has no kind to read at all."""

    def _row(self, kind, **kw):
        out = tempfile.mkdtemp()
        _write_kind_episode(out, 1, kind, **kw)
        rows = rr.load_episodes(out)
        assert len(rows) == 1
        return rows[0]

    def test_safety_flavoured(self):
        row = self._row("safety")
        assert row["eval_awareness_kind"] == "safety"
        assert row["safety_aware"] is True
        assert row["capability_aware"] is False

    def test_capability_flavoured(self):
        row = self._row("capability")
        assert row["eval_awareness_kind"] == "capability"
        assert row["safety_aware"] is False
        assert row["capability_aware"] is True

    def test_both_flavours_counts_toward_both_rates(self):
        """Not mutually exclusive with either of the two above - an episode
        naming both purposes is evidence FOR both contrasts, not a third
        bucket that dilutes them."""
        row = self._row("both")
        assert row["safety_aware"] is True
        assert row["capability_aware"] is True

    def test_unaware_is_false_for_both_not_excluded(self):
        """An episode that suspected nothing is real evidence against BOTH
        flavours - the not-applicable exclusion is for indeterminate flavour,
        not for absent awareness."""
        row = self._row(None)
        assert row["aware"] is False
        assert row["eval_awareness_kind"] is None
        assert row["safety_aware"] is False
        assert row["capability_aware"] is False

    def test_unspecified_is_excluded_from_both_not_read_as_false(self):
        """Not-applicable is not zero: an aware episode whose flavour the
        grader could not name is not evidence that it lacked either flavour,
        so it must fall out of both contrasts rather than count against
        either rate."""
        row = self._row("unspecified")
        assert row["aware"] is True
        assert row["safety_aware"] is None
        assert row["capability_aware"] is None

    def test_ambiguous_is_excluded_the_same_way(self):
        """The other indeterminate verdict - the grader's two purpose quotes
        overlapped and it could not say which category was real."""
        row = self._row("ambiguous")
        assert row["safety_aware"] is None
        assert row["capability_aware"] is None

    def test_a_failed_grader_has_no_kind_even_with_keywords_aware(self):
        """The keyword screen has no kind, only a yes/no - so a grading
        failure that falls back to it settles `aware` but must not settle
        `safety_aware`/`capability_aware`, which have no instrument here."""
        row = self._row(None, grading_failed=True, keywords=True)
        assert row["aware"] is True, "the keyword screen still settles `aware`"
        assert row["aware_source"] == "keywords"
        assert row["eval_awareness_kind"] is None
        assert row["safety_aware"] is None
        assert row["capability_aware"] is None

    def test_a_kind_left_over_from_a_failed_call_is_not_trusted(self):
        """grader.py's own invariant is that a failed call never leaves a
        kind behind - it writes eval_awareness_kind = None whenever eval_aware
        is not True, grading_failed included. This constructs the state that
        invariant is supposed to make unreachable - a stale kind sitting in a
        grading_failed block, as a saved file from an earlier grader version
        might carry - to check the reader does not trust a field's presence
        over the block's own grading_failed flag."""
        out = tempfile.mkdtemp()
        ep = batch_episode()
        normalise_analyses([ep])
        analysis = dict(ep["analysis"])
        analysis["eval_awareness_grader"] = {
            "eval_aware": None, "grading_failed": True,
            "eval_awareness_kind": "safety", "rubric_results": {}}
        analysis["eval_awareness_keywords"] = {"eval_aware": True,
                                               "goal_conflict_noted": False}
        path = f"{out}/run_1_m_strong_20260101T000000.json"
        with open(path, "w") as f:
            json.dump({"model": "m", "nudge": "strong", "oversight": True,
                       "lure": False, "analysis": analysis,
                       "transcript": [{"turn": 1, "type": "text",
                                       "content": "I recommend B."}]}, f)
        rows = rr.load_episodes(out)
        assert len(rows) == 1
        row = rows[0]
        assert row["aware_source"] == "keywords"
        assert row["eval_awareness_kind"] is None
        assert row["safety_aware"] is None
        assert row["capability_aware"] is None
