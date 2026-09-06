"""
report/pooling.py: pooling, contrasts, and what is done to them afterwards.

The bottom statistical layer, which knows nothing about which question is being
asked. Everything here is a property of the arithmetic - that a contrast pools
both keys independently, that stratifying can disagree with the crude figure,
that a multiplicity correction is applied to the family of model-level tests -
so it is tested without a report being built at all.
"""

import pytest

import report as rr

class TestPoolingAndContrasts:
    def test_pool_sums_both_keys_independently(self):
        rows = [{"x": 3, "n": 10}, {"x": 1, "n": 5}]
        assert rr._pool(rows, "x", "n") == (4, 15)

    def test_contrast_reports_the_pooled_difference(self):
        rows = [{"g": True, "x": 5, "n": 10}, {"g": False, "x": 1, "n": 10}]
        c = rr._contrast(rows, "g", True, False, "x", "n")
        assert c["a"]["n"] == 10 and c["b"]["n"] == 10
        assert c["difference"] == pytest.approx(0.4)
        assert c["level_a"] is True and c["level_b"] is False

    def test_contrast_is_none_data_when_one_side_is_empty(self):
        rows = [{"g": True, "x": 5, "n": 10}]
        c = rr._contrast(rows, "g", True, False, "x", "n")
        assert c["difference"] is None
        assert c["a"]["n"] == 10 and c["b"]["n"] == 0

    def test_rows_where_the_group_key_is_neither_level_are_dropped(self):
        """Awareness that resolved to neither grader nor keyword is None, and
        None must fall out of both sides rather than being coerced into one."""
        rows = [{"g": True, "x": 1, "n": 1}, {"g": None, "x": 1, "n": 1},
               {"g": False, "x": 0, "n": 1}]
        c = rr._contrast(rows, "g", True, False, "x", "n")
        assert c["a"]["n"] == 1 and c["b"]["n"] == 1

class TestConsistency:
    def test_counts_direction_across_models(self):
        by_model = [
            {"model": "a", "difference": 0.1, "separated": True, "p": 0.01},
            {"model": "b", "difference": -0.2, "separated": False, "p": 0.3},
            {"model": "c", "difference": 0.0, "separated": False, "p": 1.0},
            {"model": "d", "difference": None, "separated": None, "p": None},
        ]
        cons = rr._consistency(by_model)
        assert cons["n_models_total"] == 4
        assert cons["n_models_with_data"] == 3
        assert cons["n_models_no_data"] == 1
        assert cons["n_increase"] == 1
        assert cons["n_decrease"] == 1
        assert cons["n_tied"] == 1
        assert cons["n_individually_significant"] == 1
        assert cons["significant_models"][0]["model"] == "a"

    def test_significant_models_are_sorted_by_effect_size(self):
        by_model = [
            {"model": "small", "difference": 0.05, "separated": True, "p": 0.01},
            {"model": "large", "difference": -0.5, "separated": True, "p": 0.001},
        ]
        cons = rr._consistency(by_model)
        assert [m["model"] for m in cons["significant_models"]] == ["large", "small"]

class TestStratifiedBlock:
    """The crude pooled figure and the model-stratified one answer different
    questions, and this corpus is the standing condition for them to disagree.
    Both must reach the report, with a homogeneity verdict beside them."""

    def _by_model(self, rows):
        return rr._by_model(rows, "g", True, False, "x", "n")

    def test_it_carries_mh_breslow_day_and_a_reading(self):
        rows = [{"model": "a", "g": True, "x": 8, "n": 10},
               {"model": "a", "g": False, "x": 2, "n": 10},
               {"model": "b", "g": True, "x": 6, "n": 10},
               {"model": "b", "g": False, "x": 1, "n": 10}]
        strat = rr._stratified(self._by_model(rows))
        assert strat["mantel_haenszel"]["risk_difference"] is not None
        assert strat["breslow_day"]["p"] is not None
        assert "Holding model constant" in strat["interpretation"]

    def test_the_strata_come_from_the_same_rows_the_table_prints(self):
        """If the strata were rebuilt independently the stratified estimate
        could be computed over data the per-model table never showed."""
        by_model = self._by_model(
            [{"model": "a", "g": True, "x": 3, "n": 7},
             {"model": "a", "g": False, "x": 1, "n": 9}])
        assert rr._strata_from(by_model) == [(3, 7, 1, 9)]

    def test_heterogeneity_is_stated_in_the_reading(self):
        rows = [{"model": "a", "g": True, "x": 9, "n": 10},
               {"model": "a", "g": False, "x": 1, "n": 10},
               {"model": "b", "g": True, "x": 1, "n": 10},
               {"model": "b", "g": False, "x": 9, "n": 10}]
        strat = rr._stratified(self._by_model(rows))
        assert strat["breslow_day"]["heterogeneous"] is True
        assert "NOT share one effect" in strat["interpretation"]

    def test_homogeneity_is_also_stated(self):
        rows = [{"model": "a", "g": True, "x": 20, "n": 100},
               {"model": "a", "g": False, "x": 10, "n": 100},
               {"model": "b", "g": True, "x": 40, "n": 200},
               {"model": "b", "g": False, "x": 20, "n": 200}]
        strat = rr._stratified(self._by_model(rows))
        assert strat["breslow_day"]["heterogeneous"] is False
        assert "defensible" in strat["interpretation"]

    def test_a_corpus_with_nothing_to_stratify_says_so(self):
        strat = rr._stratified([])
        assert strat["mantel_haenszel"]["risk_difference"] is None
        assert "no stratified estimate" in strat["interpretation"].lower()

    def test_a_defined_effect_with_an_undefined_test_does_not_crash(self):
        """The CMH statistic has zero variance when no stratum's outcome
        varies, while the risk difference is still defined (it is 0). Reading
        the p-value unconditionally raised a TypeError on exactly the all-zero
        strata this eval produces most."""
        rows = [{"model": "a", "g": True, "x": 0, "n": 10},
               {"model": "a", "g": False, "x": 0, "n": 10}]
        strat = rr._stratified(self._by_model(rows))
        assert strat["mantel_haenszel"]["risk_difference"] == 0.0
        assert strat["mantel_haenszel"]["p"] is None
        assert "CMH test undefined" in strat["interpretation"]

class TestMultiplicityBlock:
    """27 per-model Fisher tests at alpha=0.05 expect ~1.35 rejections from
    noise, so the uncorrected count is not a count of effects."""

    def _by_model_with_ps(self, ps):
        return [{"model": f"m{i}", "difference": 0.1, "separated": pv < 0.05,
                "p": pv} for i, pv in enumerate(ps)]

    def test_corrections_are_attached_to_the_rows_themselves(self):
        by_model = self._by_model_with_ps([0.001, 0.02, 0.5])
        rr._consistency(by_model)
        assert all("holm_p" in r and "bh_p" in r for r in by_model)
        assert by_model[0]["holm_rejected"] is True

    def test_it_reports_both_corrections_and_the_noise_expectation(self):
        cons = rr._consistency(self._by_model_with_ps([0.5] * 27))
        mult = cons["multiplicity"]
        assert mult["n_hypotheses"] == 27
        assert mult["expected_false_positives_uncorrected"] == 1.35
        assert mult["n_rejected_holm"] == 0

    def test_a_borderline_result_can_survive_uncorrected_and_not_holm(self):
        """The case that motivated this: a p=0.006 per-model effect in a
        27-model family does not survive family-wise correction."""
        ps = [0.006] + [0.9] * 26
        cons = rr._consistency(self._by_model_with_ps(ps))
        mult = cons["multiplicity"]
        assert mult["n_rejected_uncorrected"] == 1
        assert mult["n_rejected_holm"] == 0

    def test_survivor_lists_name_the_models(self):
        cons = rr._consistency(self._by_model_with_ps([1e-9, 0.9, 0.9]))
        mult = cons["multiplicity"]
        assert [s["model"] for s in mult["holm_survivors"]] == ["m0"]
        assert [s["model"] for s in mult["benjamini_hochberg_survivors"]] == ["m0"]

    def test_a_model_with_no_data_is_not_a_hypothesis(self):
        by_model = self._by_model_with_ps([0.01, 0.02])
        by_model.append({"model": "empty", "difference": None,
                        "separated": None, "p": None})
        cons = rr._consistency(by_model)
        assert cons["multiplicity"]["n_hypotheses"] == 2
        assert by_model[-1]["holm_p"] is None

class TestCrudeVersusStratified:
    """A crude contrast can be separated at p<0.001 with no within-model
    evidence at all - r9 question 8 is exactly that. The divergence is stated
    rather than left for the reader to infer from two distant numbers."""

    def _sections(self, rows):
        by_model = rr._by_model(rows, "g", True, False, "x", "n")
        overall = rr._contrast(rows, "g", True, False, "x", "n")
        return overall, rr._stratified(by_model), by_model

    def test_a_purely_between_model_effect_is_flagged_confounded(self):
        """All outcome events in a model with an empty arm: the crude
        comparison is between models, not between the arms."""
        rows = [{"model": "has_events", "g": False, "x": 24, "n": 60},
               {"model": "has_events", "g": True, "x": 0, "n": 0},
               {"model": "clean_a", "g": True, "x": 0, "n": 200},
               {"model": "clean_a", "g": False, "x": 0, "n": 200},
               {"model": "clean_b", "g": True, "x": 0, "n": 250},
               {"model": "clean_b", "g": False, "x": 0, "n": 250}]
        overall, strat, by_model = self._sections(rows)
        cv = rr._crude_vs_stratified(overall, strat, by_model)
        assert overall["separated"] is True
        assert cv["diverges"] is True
        assert "CONFOUNDED" in cv["warning"]
        assert cv["n_outcome_events_outside_strata"] == 24
        assert "NO within-model evidence" in cv["warning"]

    def test_a_reproduced_effect_is_not_flagged(self):
        rows = [{"model": "a", "g": True, "x": 40, "n": 100},
               {"model": "a", "g": False, "x": 10, "n": 100},
               {"model": "b", "g": True, "x": 45, "n": 100},
               {"model": "b", "g": False, "x": 12, "n": 100}]
        overall, strat, by_model = self._sections(rows)
        cv = rr._crude_vs_stratified(overall, strat, by_model)
        assert cv["diverges"] is False
        assert cv["warning"] is None

    def test_a_sign_reversal_is_named_as_simpsons_paradox(self):
        rows = [{"model": "a", "g": True, "x": 81, "n": 87},
               {"model": "a", "g": False, "x": 234, "n": 270},
               {"model": "b", "g": True, "x": 192, "n": 263},
               {"model": "b", "g": False, "x": 55, "n": 80}]
        overall, strat, by_model = self._sections(rows)
        cv = rr._crude_vs_stratified(overall, strat, by_model)
        assert cv["crude_difference"] < 0 < cv["stratified_difference"]
        assert cv["diverges"] is True
        assert "SIGN REVERSAL" in cv["warning"]

    def test_it_is_silent_when_either_estimate_is_missing(self):
        cv = rr._crude_vs_stratified(
            {"difference": None, "separated": None},
            {"mantel_haenszel": {"risk_difference": None}}, [])
        assert cv["diverges"] is False
        assert cv["warning"] is None

    def test_some_events_outside_the_strata_are_quantified(self):
        """Between "all of them" and "none of them" there is a third case,
        and it is the common one: part of the evidence sits in models the
        stratified estimate had to drop for having an empty arm.

        The count is what makes the warning actionable - "24 of 30" tells a
        reader how much of the crude finding survives holding model constant,
        which neither the crude line nor the stratified line says on its own.
        """
        rows = [{"model": "empty_arm", "g": False, "x": 20, "n": 60},
                {"model": "empty_arm", "g": True, "x": 0, "n": 0},
                {"model": "both_arms", "g": True, "x": 4, "n": 200},
                {"model": "both_arms", "g": False, "x": 4, "n": 200},
                {"model": "clean_b", "g": True, "x": 0, "n": 250},
                {"model": "clean_b", "g": False, "x": 0, "n": 250}]
        overall, strat, by_model = self._sections(rows)
        cv = rr._crude_vs_stratified(overall, strat, by_model)
        assert cv["diverges"] is True, cv
        assert cv["n_outcome_events_total"] == 28
        assert cv["n_outcome_events_outside_strata"] == 20
        assert "20 of 28 outcome event(s)" in cv["warning"]
        assert "NO within-model evidence" not in cv["warning"], (
            "some evidence survives, so the stronger wording is wrong here")


class TestTheHomogeneityVerdictReachesTheConsole:
    """The stratified block prints the pooled effect and then, beside it, the
    test of whether there is one effect to pool. A pooled figure printed with
    no homogeneity verdict beside it is an average over genuinely different
    effects presented as "the" effect - and the reading of a heterogeneous
    result is the opposite of a homogeneous one.
    """

    def _printed(self, rows):
        import contextlib
        import io
        from report.console import _print_stratified
        strat = rr._stratified(rr._by_model(rows, "g", True, False, "x", "n"))
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            _print_stratified(strat)
        return strat, buf.getvalue()

    def test_heterogeneous_strata_are_printed_as_rejecting_homogeneity(self):
        strat, text = self._printed([
            {"model": "a", "g": True, "x": 9, "n": 10},
            {"model": "a", "g": False, "x": 1, "n": 10},
            {"model": "b", "g": True, "x": 1, "n": 10},
            {"model": "b", "g": False, "x": 9, "n": 10}])
        assert strat["breslow_day"]["heterogeneous"] is True
        assert "Breslow-Day REJECTS homogeneity" in text
        assert f"df={strat['breslow_day']['df']}" in text
        assert f"({strat['breslow_day']['n_strata_used']} informative" in text, (
            "the df has to be read against the strata that carried evidence, "
            "which is not the number of models")

    def test_homogeneous_strata_are_printed_as_not_rejecting(self):
        """Two-directional: one verdict for both would be worse than none."""
        strat, text = self._printed([
            {"model": "a", "g": True, "x": 20, "n": 100},
            {"model": "a", "g": False, "x": 10, "n": 100},
            {"model": "b", "g": True, "x": 40, "n": 200},
            {"model": "b", "g": False, "x": 20, "n": 200}])
        assert strat["breslow_day"]["heterogeneous"] is False
        assert "does not reject homogeneity" in text
        assert "REJECTS" not in text

    def test_strata_that_could_not_be_tested_say_why_instead(self):
        """Not "does not reject": a test that could not run has not failed to
        reject anything, and printing that would read as evidence for pooling
        where there is none."""
        strat, text = self._printed([
            {"model": "a", "g": True, "x": 3, "n": 10},
            {"model": "a", "g": False, "x": 1, "n": 10}])
        assert strat["breslow_day"]["p"] is None
        assert "Breslow-Day:" in text
        assert strat["breslow_day"]["note"] in text
        assert "REJECTS homogeneity" not in text
        assert "does not reject homogeneity" not in text


class TestARateThatCouldNotBeComputedPrintsItsCountsAnyway:
    """_fmt_rate is on every per-model row and every contrast line. A side
    with no episodes has no rate, and the two wrong answers are to print 0.0%
    - which claims a measurement - and to print nothing, which loses the count
    that says why the rate is absent. The counts alone are the honest form:
    0/0 says what happened."""

    def test_a_side_with_no_denominator_shows_its_counts_and_no_percentage(self):
        from report.console import _fmt_rate
        assert _fmt_rate({"successes": 0, "n": 0, "rate": None}) == "0/0"

    def test_a_measured_side_shows_the_percentage_too(self):
        """The control: a formatter that never printed a percentage would
        satisfy the test above and lose every rate in the report."""
        from report.console import _fmt_rate
        assert _fmt_rate({"successes": 3, "n": 10, "rate": 0.3}) == "3/10=30.0%"

    def test_a_zero_rate_over_real_episodes_is_still_a_rate(self):
        """The distinction the whole thing is for: 0/40 is a measured zero and
        must not be formatted like 0/0."""
        from report.console import _fmt_rate
        assert _fmt_rate({"successes": 0, "n": 40, "rate": 0.0}) == "0/40=0.0%"
