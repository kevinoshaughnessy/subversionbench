"""
The comparisons that hold something constant: paired, stratified, and trend.

Each answers a question the crude pooled figure cannot, and each has a way of
being undefined that is not a value of zero - no stratum carrying evidence, no
discordant pair, no variation to trend along. What these mostly pin is that
absent comes back absent.
"""



from subversionbench.power import (compare_rates,
                                   fisher_exact_p)


class TestChiSquareTail:
    """No scipy in this package, so the incomplete gamma is implemented here
    and there is no library being right on our behalf. These are the values a
    reader would look up in a table."""

    def test_it_matches_the_textbook_critical_values(self):
        from subversionbench.power import chi2_sf
        for stat, df, expected in ((3.841459, 1, 0.05), (6.634897, 1, 0.01),
                                   (5.991465, 2, 0.05), (16.918978, 9, 0.05),
                                   (2.705543, 1, 0.10), (1.0, 1, 0.3173105)):
            assert abs(chi2_sf(stat, df) - expected) < 1e-5, (stat, df)

    def test_both_branches_of_the_incomplete_gamma_are_exercised(self):
        """x < a+1 takes the series, x >= a+1 the continued fraction. A test
        that only ever reached one would leave the other unverified."""
        from subversionbench.power import chi2_sf
        # df=20 -> a=10; small statistic takes the series, large the fraction.
        assert abs(chi2_sf(10.851, 20) - 0.95) < 1e-3
        assert abs(chi2_sf(31.410, 20) - 0.05) < 1e-3

    def test_a_degenerate_test_reports_no_evidence_rather_than_raising(self):
        from subversionbench.power import chi2_sf
        assert chi2_sf(0.0, 1) == 1.0
        assert chi2_sf(-5.0, 1) == 1.0
        assert chi2_sf(10.0, 0) == 1.0

    def test_it_is_monotone_decreasing_in_the_statistic(self):
        from subversionbench.power import chi2_sf
        ps = [chi2_sf(s, 3) for s in (0.5, 1, 2, 5, 10, 20)]
        assert ps == sorted(ps, reverse=True), ps


class TestMcNemarExact:
    """Every interrogation phrasing is put to the same act, so a phrasing
    contrast is repeated measures. The exact binomial form is used because the
    discordant counts in this eval are single digits."""

    def test_it_matches_the_binomial_by_hand(self):
        from math import comb
        from subversionbench.power import mcnemar_exact_p
        for b, c in ((10, 2), (8, 1), (3, 3), (5, 0), (20, 5)):
            n, tail = b + c, min(b, c)
            hand = min(1.0, 2 * sum(comb(n, k) for k in range(tail + 1)) / 2 ** n)
            assert abs(mcnemar_exact_p(b, c) - hand) < 1e-12, (b, c)

    def test_no_discordant_pairs_is_no_evidence(self):
        """Nothing disagreed, so there is nothing to test - not a significant
        absence of difference."""
        from subversionbench.power import mcnemar_exact_p
        assert mcnemar_exact_p(0, 0) == 1.0

    def test_it_is_symmetric_in_its_arguments(self):
        from subversionbench.power import mcnemar_exact_p
        assert mcnemar_exact_p(7, 2) == mcnemar_exact_p(2, 7)

    def test_an_even_split_is_maximally_unsurprising(self):
        from subversionbench.power import mcnemar_exact_p
        assert mcnemar_exact_p(6, 6) == 1.0


class TestPairedCompare:
    def test_the_marginals_and_difference_come_from_the_four_cells(self):
        from subversionbench.power import paired_compare
        # 12 concealed under both, 8 under A only, 0 under B only, 80 neither.
        pc = paired_compare(12, 8, 0, 80)
        assert pc["a"]["successes"] == 20 and pc["b"]["successes"] == 12
        assert pc["n_pairs"] == 100
        assert abs(pc["difference"] - 0.08) < 1e-9
        assert pc["discordant"] == {"a_only": 8, "b_only": 0}

    def test_pairing_is_more_powerful_than_treating_the_arms_as_independent(self):
        """The whole reason this exists. Same marginals, correlated responses:
        the paired test finds the difference and the unpaired one does not."""
        from subversionbench.power import paired_compare
        pc = paired_compare(12, 8, 0, 80)
        unpaired = fisher_exact_p(20, 100, 12, 100)
        assert pc["exact_p"] < 0.01 < unpaired

    def test_only_discordant_pairs_drive_the_p_value(self):
        """Concordant pairs carry no evidence about a difference, so adding
        more of them must not change the test."""
        from subversionbench.power import paired_compare
        a = paired_compare(5, 7, 1, 10)
        b = paired_compare(500, 7, 1, 1000)
        assert a["exact_p"] == b["exact_p"]

    def test_separation_is_taken_from_the_exact_test_not_the_interval(self):
        """The interval is a Wald approximation and the test is not, so a
        disagreement must not be resolved in the approximation's favour."""
        from subversionbench.power import paired_compare
        pc = paired_compare(0, 9, 1, 90)
        assert pc["separated"] is (pc["exact_p"] < 0.05)

    def test_no_units_is_reported_not_raised(self):
        from subversionbench.power import paired_compare
        pc = paired_compare(0, 0, 0, 0)
        assert pc["difference"] is None
        assert pc["n_pairs"] == 0
        assert "note" in pc

    def test_perfect_agreement_gives_a_zero_difference(self):
        from subversionbench.power import paired_compare
        pc = paired_compare(5, 0, 0, 5)
        assert pc["difference"] == 0.0
        assert pc["exact_p"] == 1.0
        assert pc["separated"] is False

    def test_it_declares_its_method_and_leaves_fisher_unset(self):
        """A caller formatting either kind of contrast must be able to tell
        which it has; reporting a paired contrast as unpaired changes the
        interval substantially."""
        from subversionbench.power import paired_compare
        pc = paired_compare(1, 2, 3, 4)
        assert pc["method"] == "mcnemar_exact"
        assert pc["fisher_p"] is None
        assert pc["p"] == pc["exact_p"]

    def test_the_variance_never_goes_negative(self):
        """(b + c) - (b - c)^2/n can go below zero when every discordant pair
        points one way and n is small."""
        from subversionbench.power import paired_compare
        pc = paired_compare(0, 2, 0, 0)
        assert pc["difference_se"] >= 0
        assert pc["difference_ci95"][0] >= -1.0


class TestMantelHaenszel:
    def test_the_odds_ratio_matches_the_definition(self):
        from subversionbench.power import mantel_haenszel
        strata = [(10, 100, 5, 100), (20, 100, 10, 100)]
        # sum(a*d/T) / sum(b*c/T)
        r = 10 * 95 / 200 + 20 * 90 / 200
        s = 90 * 5 / 200 + 80 * 10 / 200
        assert abs(mantel_haenszel(strata)["odds_ratio"] - r / s) < 1e-4

    def test_it_reproduces_the_kidney_stone_simpsons_paradox(self):
        """The canonical worked example. The crude difference says arm 1 is
        worse; every stratum says it is better. If the stratified estimate did
        not flip the sign here it would not be doing its job."""
        from subversionbench.power import mantel_haenszel
        strata = [(81, 87, 234, 270), (192, 263, 55, 80)]
        crude = compare_rates(81 + 192, 87 + 263, 234 + 55, 270 + 80)
        mh = mantel_haenszel(strata)
        assert crude["difference"] < 0 < mh["risk_difference"]
        assert abs(mh["odds_ratio"] - 1.45) < 0.01

    def test_identical_strata_reduce_to_the_crude_difference(self):
        """A stratified estimate that disagreed with the crude one when there
        is nothing to stratify on would be wrong by construction."""
        from subversionbench.power import mantel_haenszel
        strata = [(20, 100, 10, 100), (20, 100, 10, 100)]
        assert abs(mantel_haenszel(strata)["risk_difference"] - 0.10) < 1e-9

    def test_an_empty_arm_removes_that_stratum_only(self):
        from subversionbench.power import mantel_haenszel
        mh = mantel_haenszel([(20, 100, 10, 100), (0, 0, 5, 50)])
        assert mh["n_strata_given"] == 2
        assert mh["n_strata_used"] == 1
        assert abs(mh["risk_difference"] - 0.10) < 1e-9

    def test_no_usable_stratum_is_reported_not_raised(self):
        from subversionbench.power import mantel_haenszel
        mh = mantel_haenszel([(0, 0, 0, 0)])
        assert mh["risk_difference"] is None
        assert mh["n_strata_used"] == 0
        assert "note" in mh

    def test_all_zero_strata_keep_a_defined_risk_difference(self):
        """Rates here sit at zero, so this is the common case, and it is
        exactly where the odds ratio gives up and the risk difference must
        not."""
        from subversionbench.power import mantel_haenszel
        mh = mantel_haenszel([(0, 60, 0, 60), (0, 60, 0, 60)])
        assert mh["risk_difference"] == 0.0
        assert mh["odds_ratio"] is None
        assert "odds_ratio_note" in mh

    def test_the_interval_narrows_as_n_grows(self):
        from subversionbench.power import mantel_haenszel
        def width(n):
            ci = mantel_haenszel([(n // 5, n, n // 10, n)])["risk_difference_ci95"]
            return ci[1] - ci[0]
        assert width(1000) < width(200) < width(50)


class TestBreslowDay:
    def test_homogeneous_strata_are_not_rejected(self):
        from subversionbench.power import breslow_day, mantel_haenszel
        strata = [(10, 100, 5, 100), (20, 200, 10, 200), (30, 300, 15, 300)]
        bd = breslow_day(strata, mantel_haenszel(strata)["odds_ratio"])
        assert bd["p"] > 0.05
        assert bd["heterogeneous"] is False

    def test_opposite_direction_strata_are_rejected(self):
        from subversionbench.power import breslow_day, mantel_haenszel
        strata = [(80, 100, 20, 100), (20, 100, 80, 100)]
        bd = breslow_day(strata, mantel_haenszel(strata)["odds_ratio"])
        assert bd["p"] < 1e-6
        assert bd["heterogeneous"] is True
        assert bd["df"] == 1

    def test_strata_where_the_outcome_never_varies_carry_no_evidence(self):
        """An all-zero stratum is consistent with every odds ratio, so it must
        not inflate the degrees of freedom - which is how a heterogeneity test
        over sparse data manufactures significance."""
        from subversionbench.power import breslow_day
        strata = [(0, 60, 0, 60), (0, 60, 0, 60),
                  (10, 100, 5, 100), (20, 200, 10, 200)]
        bd = breslow_day(strata)
        assert bd["n_strata_given"] == 4
        assert bd["n_strata_used"] == 2
        assert bd["df"] == 1

    def test_fewer_than_two_informative_strata_is_not_testable(self):
        from subversionbench.power import breslow_day
        bd = breslow_day([(10, 100, 5, 100)])
        assert bd["p"] is None
        assert "note" in bd

    def test_a_degenerate_common_odds_ratio_is_declined(self):
        from subversionbench.power import breslow_day
        bd = breslow_day([(0, 60, 0, 60), (0, 60, 0, 60)], odds_ratio=None)
        assert bd["p"] is None

    def test_an_odds_ratio_of_zero_is_declined_with_a_reason(self):
        """There is nothing to test homogeneity AGAINST. Passing zero into
        the fitted-count solve would divide the test's own null by nothing;
        declining says which of the two questions failed."""
        from subversionbench.power import breslow_day
        strata = [(10, 100, 5, 100), (20, 200, 10, 200)]
        bd = breslow_day(strata, odds_ratio=0.0)
        assert bd["p"] is None and bd["statistic"] is None
        assert "odds ratio" in bd["note"]

    def test_a_negative_odds_ratio_is_declined_too(self):
        """Not reachable from mantel_haenszel, which cannot produce one -
        guarded rather than assumed, because the argument is also passed in
        by callers that computed it their own way."""
        from subversionbench.power import breslow_day
        bd = breslow_day([(10, 100, 5, 100), (20, 200, 10, 200)],
                         odds_ratio=-1.5)
        assert bd["p"] is None and "odds ratio" in bd["note"]

    def test_strata_that_fit_degenerately_leave_the_degrees_of_freedom(self):
        """The count that survives is `contributing`, not `usable`.

        A stratum can pass the has-both-outcomes screen and still yield a
        fitted table with a zero cell, which has no variance and so carries
        no evidence about heterogeneity. Counting it would give the chi2 a
        degree of freedom nothing paid for - the same defect the all-zero
        stratum test guards at the earlier screen, one stage later.

        An implausible common odds ratio is what drives it here: it pushes
        every fitted count to the edge of its margin-feasible range, which
        is the general shape of the case rather than a contrived one.
        """
        from subversionbench.power import breslow_day
        strata = [(10, 100, 5, 100), (20, 200, 10, 200)]
        bd = breslow_day(strata, odds_ratio=1e12)
        assert bd["p"] is None and bd["df"] is None
        assert "non-degenerate" in bd["note"]
        # Both strata passed the earlier screen, and neither survived the
        # fit. The reported count is the one that carried evidence.
        assert bd["n_strata_given"] == 2
        assert bd["n_strata_used"] == 0

    def test_the_reported_strata_count_is_the_one_the_df_came_from(self):
        """n_strata_used and df have to agree, or a reader reconciling them
        against the printed table finds a discrepancy with no explanation."""
        from subversionbench.power import breslow_day
        bd = breslow_day([(10, 100, 5, 100), (20, 200, 10, 200),
                          (30, 300, 15, 300)])
        assert bd["df"] == bd["n_strata_used"] - 1


class TestTrendAcrossOrderedGroups:
    """A family of model versions is ORDERED, and that ordering carries
    information a pairwise test throws away. Cochran-Armitage asks the question
    being asked - does the rate move with position - in one degree of freedom."""

    def test_a_falling_sequence_gives_a_negative_z(self):
        """Sign convention: negative reads as falling, the way the question is
        asked, so a reader cannot invert it by accident."""
        from subversionbench.power import cochran_armitage
        out = cochran_armitage([(80, 100), (50, 100), (20, 100), (5, 100)])
        assert out["z"] < 0
        assert out["direction"] == "falling"
        assert out["separated"] is True

    def test_a_rising_sequence_gives_a_positive_z(self):
        from subversionbench.power import cochran_armitage
        out = cochran_armitage([(1, 117), (16, 120), (18, 120)])
        assert out["z"] > 0 and out["direction"] == "rising"

    def test_a_flat_sequence_is_not_separated(self):
        from subversionbench.power import cochran_armitage
        out = cochran_armitage([(10, 100), (10, 100), (10, 100)])
        assert out["z"] == 0.0 and out["separated"] is False

    def test_no_variation_is_undefined_not_zero(self):
        """Every episode the same outcome is not a trend of zero - there is
        nothing to have a trend in, and returning 0.0 would put that in the
        same bucket as a measured flat."""
        from subversionbench.power import cochran_armitage
        for groups in ([(0, 100), (0, 100)], [(100, 100), (100, 100)]):
            out = cochran_armitage(groups)
            assert out["z"] is None and out["p"] is None
            assert out["note"]

    def test_one_group_is_not_a_trend(self):
        from subversionbench.power import cochran_armitage
        out = cochran_armitage([(5, 100)])
        assert out["z"] is None and out["n_groups_used"] == 1

    def test_an_empty_group_does_not_shift_the_others(self):
        """Dropping a group must not renumber the scores of the ones that
        remain, or the trend is measured along the wrong axis."""
        from subversionbench.power import cochran_armitage
        with_gap = cochran_armitage([(80, 100), (0, 0), (5, 100)])
        assert with_gap["n_groups_used"] == 2
        # Scores 0 and 2 are kept, so the estimate is the same as the
        # two-group fit at those positions.
        direct = cochran_armitage([(80, 100), (5, 100)], scores=[0, 2])
        assert with_gap["z"] == direct["z"]

    def test_rescaling_the_scores_changes_nothing(self):
        """The statistic is invariant to an affine change of score, so using
        position 0,1,2 rather than 1,2,3 or 0,10,20 cannot move a verdict."""
        from subversionbench.power import cochran_armitage
        base = cochran_armitage([(80, 100), (50, 100), (5, 100)],
                                scores=[0, 1, 2])
        scaled = cochran_armitage([(80, 100), (50, 100), (5, 100)],
                                  scores=[10, 30, 50])
        assert base["z"] == scaled["z"]

    def test_but_respacing_them_does(self):
        """Equal spacing is therefore a real assumption, not a formality - which
        is why the TEST runs on position even though release dates are recorded.
        Scoring by date would assume the rate moves a constant amount per month.
        The dates get a descriptive fit instead; see weighted_least_squares."""
        from subversionbench.power import cochran_armitage
        even = cochran_armitage([(80, 100), (50, 100), (5, 100)],
                                scores=[0, 1, 2])
        uneven = cochran_armitage([(80, 100), (50, 100), (5, 100)],
                                  scores=[0, 1, 10])
        assert even["z"] != uneven["z"]


class TestCountingTheSteps:
    """"Consistently falling" is a claim about the steps, not about a fitted
    direction, so the two are counted separately."""

    def test_every_step_down_is_monotone_falling(self):
        from subversionbench.power import step_directions
        out = step_directions([0.8, 0.5, 0.2, 0.05])
        assert out["n_down"] == 3 and out["n_up"] == 0
        assert out["monotone_falling"] is True

    def test_one_step_up_breaks_it(self):
        from subversionbench.power import step_directions
        out = step_directions([0.68, 0.82, 0.13, 0.06])
        assert out["monotone_falling"] is False
        assert out["n_down"] == 2 and out["n_up"] == 1

    def test_a_flat_step_is_neither(self):
        from subversionbench.power import step_directions
        out = step_directions([0.5, 0.5])
        assert out["n_flat"] == 1
        assert out["monotone_falling"] is False
        assert out["monotone_rising"] is False

    def test_a_missing_rate_is_skipped_not_zeroed(self):
        from subversionbench.power import step_directions
        assert step_directions([0.5, None, 0.2])["steps"] == [-0.3]

    def test_one_rate_has_no_steps(self):
        from subversionbench.power import step_directions
        out = step_directions([0.5])
        assert out["n_steps"] == 0 and out["monotone_falling"] is False


class TestTheSignTestOnStepDirection:
    def test_all_one_way_is_separated(self):
        from subversionbench.power import sign_test
        assert sign_test(8, 0)["p"] < 0.05

    def test_an_even_split_is_not(self):
        from subversionbench.power import sign_test
        out = sign_test(4, 5)
        assert abs(out["p"] - 1.0) < 1e-9 and out["separated"] is False

    def test_it_is_symmetric(self):
        from subversionbench.power import sign_test
        assert sign_test(7, 2)["p"] == sign_test(2, 7)["p"]

    def test_flat_steps_are_excluded_rather_than_split(self):
        """A family that never moves is not evidence that rates fall, so its
        steps carry no vote."""
        from subversionbench.power import sign_test
        out = sign_test(3, 1)
        assert out["n"] == 4

    def test_no_directed_step_is_no_test(self):
        from subversionbench.power import sign_test
        out = sign_test(0, 0)
        assert out["p"] is None and out["note"]


class TestWeightedLeastSquares:
    """
    The descriptive line family_trends.py draws against release date. It carries
    no p-value on purpose: the trend test in that file is Cochran-Armitage on
    version position, and refitting on the calendar with an interval would be a
    second test of one hypothesis on one dataset.
    """

    def test_it_recovers_a_line_it_was_given(self):
        from subversionbench.power import weighted_least_squares
        out = weighted_least_squares([0, 1, 2, 3], [1.0, 3.0, 5.0, 7.0])
        assert abs(out["slope"] - 2.0) < 1e-9
        assert abs(out["intercept"] - 1.0) < 1e-9

    def test_a_falling_series_gets_a_negative_slope(self):
        from subversionbench.power import weighted_least_squares
        out = weighted_least_squares([0, 100, 200], [0.68, 0.13, 0.06])
        assert out["slope"] < 0

    def test_weights_move_the_line_toward_the_heavier_point(self):
        """A rate measured on 239 episodes is a better estimate than one
        measured on 120, and an unweighted fit treats them as equals."""
        from subversionbench.power import weighted_least_squares
        xs, ys = [0, 1, 2], [0.0, 1.0, 0.0]
        flat = weighted_least_squares(xs, ys)
        pulled = weighted_least_squares(xs, ys, [1, 1, 100])
        assert abs(flat["slope"]) < 1e-9
        assert pulled["slope"] < 0

    def test_equal_weights_match_an_unweighted_fit(self):
        from subversionbench.power import weighted_least_squares
        xs, ys = [0, 3, 7, 11], [0.2, 0.4, 0.35, 0.9]
        plain = weighted_least_squares(xs, ys)
        weighted = weighted_least_squares(xs, ys, [5, 5, 5, 5])
        assert abs(plain["slope"] - weighted["slope"]) < 1e-12

    def test_one_point_is_no_line_rather_than_a_flat_one(self):
        """The same distinction cochran_armitage draws: returning 0.0 would put
        "flat" and "unfittable" in one bucket."""
        from subversionbench.power import weighted_least_squares
        out = weighted_least_squares([5], [0.5])
        assert out["slope"] is None and out["note"]

    def test_every_point_at_one_x_is_no_line(self):
        """Three models released on the same day have no slope in time."""
        from subversionbench.power import weighted_least_squares
        out = weighted_least_squares([4, 4, 4], [0.1, 0.5, 0.9])
        assert out["slope"] is None
        assert "same x" in out["note"]

    def test_a_zero_weight_point_does_not_count_toward_a_fit(self):
        """A model with no episodes must not be fitted as though it had some."""
        from subversionbench.power import weighted_least_squares
        out = weighted_least_squares([0, 1, 2], [0.0, 0.5, 1.0], [0, 3, 4])
        assert out["n_points"] == 3 and out["n_points_used"] == 2
        assert abs(out["slope"] - 0.5) < 1e-9

    def test_only_one_point_carries_weight_is_no_line(self):
        from subversionbench.power import weighted_least_squares
        out = weighted_least_squares([0, 1], [0.0, 1.0], [0, 5])
        assert out["slope"] is None and "positive weight" in out["note"]

    def test_mismatched_inputs_raise_rather_than_truncate(self):
        """zip would silently drop the extra point and fit the rest."""
        import pytest
        from subversionbench.power import weighted_least_squares
        with pytest.raises(ValueError):
            weighted_least_squares([0, 1, 2], [0.0, 1.0])

    def test_it_reports_no_p_value_and_no_interval(self):
        """Descriptive by construction. A caller that found a p here would be
        entitled to treat it as a second trend test, which it is not."""
        from subversionbench.power import weighted_least_squares
        out = weighted_least_squares([0, 1, 2], [0.1, 0.2, 0.3])
        assert "p" not in out and "separated" not in out
        assert not any(k.startswith("ci") for k in out)


class TestHolmBonferroni:
    def test_the_adjusted_values_are_hand_checkable(self):
        from subversionbench.power import holm_bonferroni
        r = holm_bonferroni([0.001, 0.008, 0.039])
        assert abs(r["adjusted"][0] - 0.003) < 1e-9      # 3 * 0.001
        assert abs(r["adjusted"][1] - 0.016) < 1e-9      # 2 * 0.008
        assert abs(r["adjusted"][2] - 0.039) < 1e-9      # 1 * 0.039

    def test_it_is_monotone_non_decreasing_in_rank(self):
        """Without the running max a later hypothesis can be adjusted below an
        earlier one, which would let a weaker result be reported as stronger."""
        from subversionbench.power import holm_bonferroni
        r = holm_bonferroni([0.01, 0.02, 0.021, 0.5, 0.9])
        adj = sorted(a for a in r["adjusted"])
        assert adj == sorted(adj)
        assert r["adjusted"] == sorted(r["adjusted"])

    def test_it_is_stricter_than_no_correction(self):
        from subversionbench.power import holm_bonferroni
        ps = [0.001, 0.02, 0.03, 0.04, 0.045]
        r = holm_bonferroni(ps)
        assert r["n_rejected_uncorrected"] == 5
        assert r["n_rejected"] < 5

    def test_the_order_given_is_the_order_returned(self):
        """Adjusted values are written back onto the rows they came from, so a
        sort-order leak here would attach a p-value to the wrong model."""
        from subversionbench.power import holm_bonferroni
        r = holm_bonferroni([0.5, 0.001, 0.2])
        assert r["adjusted"][1] < r["adjusted"][2] < r["adjusted"][0]


class TestBenjaminiHochberg:
    def test_the_adjusted_values_are_hand_checkable(self):
        from subversionbench.power import benjamini_hochberg
        r = benjamini_hochberg([0.001, 0.008, 0.039])
        assert abs(r["adjusted"][0] - 0.003) < 1e-9      # 3*0.001/1
        assert abs(r["adjusted"][1] - 0.012) < 1e-9      # 3*0.008/2
        assert abs(r["adjusted"][2] - 0.039) < 1e-9      # 3*0.039/3

    def test_it_keeps_more_power_than_holm(self):
        from subversionbench.power import benjamini_hochberg, holm_bonferroni
        ps = [0.001, 0.008, 0.039, 0.041, 0.042, 0.06, 0.5]
        bh = benjamini_hochberg(ps)
        holm = holm_bonferroni(ps)
        assert all(b <= h for b, h in zip(bh["adjusted"],
                                          holm["adjusted"], strict=True))

    def test_it_is_monotone_after_the_step_up(self):
        from subversionbench.power import benjamini_hochberg
        r = benjamini_hochberg([0.01, 0.039, 0.041, 0.042, 0.06])
        assert r["adjusted"] == sorted(r["adjusted"])


class TestMultiplicityEdgeCases:
    def test_an_untested_hypothesis_leaves_the_family(self):
        """None means the comparison could not be made. Counting it in the
        family size would penalise every other test for a hypothesis nobody
        tested."""
        from subversionbench.power import holm_bonferroni
        r = holm_bonferroni([0.01, None, 0.02])
        assert r["n_hypotheses"] == 2
        assert r["n_not_tested"] == 1
        assert r["adjusted"][1] is None
        assert r["rejected"][1] is None
        assert abs(r["adjusted"][0] - 0.02) < 1e-9       # 2 * 0.01

    def test_an_all_none_family_is_handled(self):
        from subversionbench.power import benjamini_hochberg
        r = benjamini_hochberg([None, None])
        assert r["n_hypotheses"] == 0
        assert r["n_rejected"] == 0

    def test_an_empty_family_is_handled(self):
        from subversionbench.power import holm_bonferroni
        assert holm_bonferroni([])["n_hypotheses"] == 0

    def test_the_expected_false_positive_count_is_reported(self):
        """The number that makes an uncorrected count readable: 27 tests at
        alpha=0.05 expects about 1.35 rejections from noise alone."""
        from subversionbench.power import holm_bonferroni
        r = holm_bonferroni([0.5] * 27)
        assert r["expected_false_positives_uncorrected"] == 1.35
