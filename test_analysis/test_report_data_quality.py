"""
report/data_quality.py: the things that would make the figures mean less.

Separate from the questions because it is a different claim. The questions say
what the corpus shows; these say where the corpus disagrees with itself, where
an arm was collected twice, and where episodes inside one published rate were
not collected alike. Each is reported rather than asserted, so the tests are
about whether it is SAID - a silent data-quality fact is the failure mode.
"""

import contextlib
import io
import json
import tempfile

import report as rr
from test_analysis.report_fixtures import _write_episode, _write_summary

class TestDataQuality:
    def test_a_keyword_sourced_verdict_is_reported_not_hidden(self):
        """Every episode in the current corpus has a grader verdict; one that
        fell back to keywords measures something else, and the harness itself
        refuses to pool the two silently."""
        out = tempfile.mkdtemp()
        _write_episode(out, 1, "m", "strong", aware=True)   # keywords only
        dq = rr.data_quality_facts(rr.load_episodes(out))
        assert dq["awareness_verdict_sources"] == {"keywords": 1}
        assert dq["awareness_all_from_grader"] is False

    def test_a_fully_graded_corpus_is_reported_as_such(self):
        out = tempfile.mkdtemp()
        path = _write_episode(out, 1, "m", "strong")
        d = json.load(open(path))
        d["analysis"]["eval_awareness_grader"] = {"eval_aware": True}
        json.dump(d, open(path, "w"))
        dq = rr.data_quality_facts(rr.load_episodes(out))
        assert dq["awareness_verdict_sources"] == {"grader": 1}
        assert dq["awareness_all_from_grader"] is True

    def test_an_empty_corpus_is_not_claimed_to_be_fully_graded(self):
        assert rr.data_quality_facts([])["awareness_all_from_grader"] is False

class TestDuplicateArmsArePooledAndSaid:
    """A partial batch re-run to full n leaves both on disk, and both are
    read. Legitimate as pooling, wrong as replacement - and indistinguishable
    without being told, so it is reported."""

    def test_two_batches_of_one_arm_are_reported_with_their_pooled_n(self):
        out = tempfile.mkdtemp()
        _write_summary(out, "m", "max", stamp="20260101T000000", n_runs=6)
        _write_summary(out, "m", "max", stamp="20260102T000000", n_runs=10)
        dupes = rr.duplicate_arms(rr.load_summaries(out))
        assert len(dupes) == 1
        assert dupes[0]["n_batches"] == 2
        assert dupes[0]["pooled_n_runs"] == 16

    def test_arms_differing_in_any_axis_are_not_duplicates(self):
        out = tempfile.mkdtemp()
        _write_summary(out, "m", "max", oversight=True, stamp="20260101T000000")
        _write_summary(out, "m", "max", oversight=False, stamp="20260102T000000")
        _write_summary(out, "m", "max", lure=True, stamp="20260103T000000")
        _write_summary(out, "m", "none", stamp="20260104T000000")
        assert rr.duplicate_arms(rr.load_summaries(out)) == []

    def test_a_single_batch_corpus_reports_none(self):
        out = tempfile.mkdtemp()
        _write_summary(out, "m", "max")
        dq = rr.data_quality_facts(rr.load_episodes(out), rr.load_summaries(out))
        assert dq["duplicate_arms"] == []

class TestMixedRoutingWithinAnArmIsReported:
    """A rate over episodes answered by different backends.

    Distinct from duplicate_arms, which needs the arm to be made of more than
    one BATCH. A batch resumed under different routing keeps its stamp and writes
    one summary, so the arm looks like a single clean batch and the two halves
    pool with nothing saying so.
    """

    def test_one_arm_routed_two_ways_is_reported_with_the_split(self):
        out = tempfile.mkdtemp()
        for i in range(1, 4):
            _write_episode(out, i, "m", "max", sort="throughput")
        for i in range(4, 6):
            _write_episode(out, i, "m", "max", sort=None)
        found = rr.mixed_routing_arms(rr.load_episodes(out))
        assert len(found) == 1, found
        assert found[0]["n_episodes"] == 5
        assert sorted(((r["sort"] or ""), r["n_episodes"])
                      for r in found[0]["routings"]) == [("", 2), ("throughput", 3)]

    def test_it_fires_under_a_single_stamp_where_duplicate_arms_cannot(self):
        """The gap this exists for, asserted as a pair so the distinction cannot
        quietly collapse into the other check."""
        out = tempfile.mkdtemp()
        for i in range(1, 3):
            _write_episode(out, i, "m", "max", stamp="20260101T000000",
                           sort="throughput")
        for i in range(3, 5):
            _write_episode(out, i, "m", "max", stamp="20260101T000000", sort=None)
        _write_summary(out, "m", "max", stamp="20260101T000000", n_runs=4)
        dq = rr.data_quality_facts(rr.load_episodes(out), rr.load_summaries(out))
        assert dq["duplicate_arms"] == [], (
            "one stamp is one batch, so duplicate_arms is silent - which is the "
            "whole reason the routing check is separate")
        assert len(dq["mixed_routing_arms"]) == 1

    def test_a_uniformly_routed_arm_is_not_reported(self):
        out = tempfile.mkdtemp()
        for i in range(1, 4):
            _write_episode(out, i, "m", "max", sort="throughput")
        assert rr.mixed_routing_arms(rr.load_episodes(out)) == []

    def test_an_arm_with_no_routing_recorded_at_all_is_not_reported(self):
        """Every non-OpenRouter episode has None for both, and so does anything
        collected before the fields existed. A corpus of those is uniform, not
        mixed."""
        out = tempfile.mkdtemp()
        for i in range(1, 4):
            _write_episode(out, i, "m", "max")
        assert rr.mixed_routing_arms(rr.load_episodes(out)) == []

    def test_the_provider_pin_counts_as_routing_too(self):
        """--openrouter-provider restricts routing to one named backend, which is
        a stronger version of the same choice; a mix of pinned and unpinned is
        the same defect."""
        out = tempfile.mkdtemp()
        _write_episode(out, 1, "m", "max", provider="deepinfra")
        _write_episode(out, 2, "m", "max", provider=None)
        found = rr.mixed_routing_arms(rr.load_episodes(out))
        assert len(found) == 1, found
        assert {r["provider"] for r in found[0]["routings"]} == {"deepinfra", None}

    def test_different_arms_routed_differently_are_each_uniform(self):
        """The key is the arm a rate is published for. Two arms that each used
        one routing are not a mix, even when the two routings differ."""
        out = tempfile.mkdtemp()
        _write_episode(out, 1, "m", "max", oversight=True, sort="throughput")
        _write_episode(out, 2, "m", "max", oversight=False, sort=None)
        assert rr.mixed_routing_arms(rr.load_episodes(out)) == []

    def test_the_console_names_the_arm_and_the_split(self):
        out = tempfile.mkdtemp()
        _write_episode(out, 1, "m", "max", sort="throughput")
        _write_episode(out, 2, "m", "max", sort=None)
        dq = rr.data_quality_facts(rr.load_episodes(out), rr.load_summaries(out))
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rr._print_data_quality(dq)
        text = buf.getvalue()
        assert "not all routed the same way: 1" in text, text
        assert "throughput x1" in text and "provider default x1" in text, text
        assert "different backends" in text

class TestCrossAnalysisRows:
    def test_builds_one_row_per_side_per_arm(self):
        cross = {"aware": {"n": 5, "misaligned": 2},
                 "unaware": {"n": 8, "misaligned": 1}}
        summaries = [{"model": "m", "nudge": "strong", "oversight": True,
                     "lure": False, "cross_analysis_awareness": cross}]
        rows = rr.cross_analysis_rows(summaries)
        assert len(rows) == 2
        aware_row = next(r for r in rows if r["aware"] is True)
        assert aware_row["misaligned"] == 2 and aware_row["n"] == 5

    def test_an_arm_with_no_cross_analysis_contributes_nothing(self):
        summaries = [{"model": "m", "nudge": "strong", "oversight": True,
                     "lure": False, "cross_analysis_awareness": None}]
        assert rr.cross_analysis_rows(summaries) == []

class TestTheAwarenessMeasureAgreement:
    """_measure_agreement and _model_rate_pairs: how the two awareness measures
    are compared, and the per-model gap between them.

    Both live in data_quality.py and neither needs a report built, so they are
    tested on rows built here. Sign alone is not enough and reading it alone
    would have misreported r9 question 4 - one measure is a null there and the
    other separates - so separation is classified alongside direction.
    """

    def test_the_gap_column_is_reasoning_only_awareness(self):
        rows = [{"model": "m", "nudge": "strong", "oversight": True,
                 "lure": False, "n_awareness_resolved": 10, "n_aware": 8,
                 "n_aware_text": 3, "n_text_undetermined": 0,
                 "n_reasoning_only": 5, "n_bounded": 10}]
        pair = rr._model_rate_pairs(rows)[0]
        assert pair["mixed_rate"] == 0.8
        assert pair["text_rate"] == 0.3
        assert pair["gap"] == 0.5
        assert pair["text_rate_is_exact"] is False

    def test_a_model_that_returned_no_reasoning_is_marked_exact(self):
        rows = [{"model": "m", "nudge": "strong", "oversight": True,
                 "lure": False, "n_awareness_resolved": 10, "n_aware": 2,
                 "n_aware_text": 2, "n_text_undetermined": 0,
                 "n_reasoning_only": 0, "n_bounded": 0}]
        assert rr._model_rate_pairs(rows)[0]["text_rate_is_exact"] is True

    def test_agreement_reports_a_null_against_an_effect(self):
        """Sign alone would call r9 question 4 "opposite direction". The finding
        is that one measure separates and the other does not."""
        mixed = {"difference": -0.012, "separated": False}
        text = {"difference": +0.034, "separated": True}
        a = rr._measure_agreement(mixed, text)
        assert a["code"] == "text_only_separates"

    def test_agreement_reports_a_surviving_conclusion(self):
        a = rr._measure_agreement({"difference": -0.03, "separated": True},
                                  {"difference": -0.034, "separated": True})
        assert a["code"] == "agree" and a["direction_same"] is True

    def test_agreement_reports_a_reversal(self):
        a = rr._measure_agreement({"difference": -0.03, "separated": True},
                                  {"difference": +0.034, "separated": True})
        assert a["code"] == "contradict" and a["direction_same"] is False

    def test_agreement_flags_an_effect_resting_on_the_reasoning_channel(self):
        a = rr._measure_agreement({"difference": -0.03, "separated": True},
                                  {"difference": -0.004, "separated": False})
        assert a["code"] == "mixed_only_separates"

    def test_agreement_needs_both_estimates(self):
        a = rr._measure_agreement({"difference": None}, {"difference": 0.1})
        assert a["code"] == "no_data" and a["direction_same"] is None
