"""
Tests for subversionbench/power.py.

Covers Wilson interval estimation, the difference interval used for model
comparisons, exact two-arm power, minimum detectable effect sizes, required
sample sizes, and the batch-level report.

Run: pytest test_power.py -v
"""

import math

import subversionbench as ev
from subversionbench.power import (
    analyse_batch,
    compare_rates,
    newcombe_diff_ci,
    fisher_exact_p,
    format_report,
    minimum_detectable_rate,
    method_for_n,
    n_for_precision,
    two_arm_power,
    wilson_ci,
    EXACT_MAX_N,
)


# =========================================================================
# Tests: Wilson interval
# =========================================================================

class TestWilsonInterval:
    """The interval run_eval reports for every rate."""

    def test_zero_events_does_not_collapse_to_zero_width(self):
        """The reason Wilson is used over Wald: at 0 events Wald gives the
        uninformative [0, 0], and rates in this eval sit near zero."""
        lo, hi = wilson_ci(0, 100)
        assert lo == 0.0
        assert 0.03 < hi < 0.04

    def test_known_values(self):
        assert wilson_ci(10, 100) == [0.0552, 0.1744]
        assert wilson_ci(20, 100) == [0.1334, 0.2888]

    def test_interval_is_symmetric_about_a_half(self):
        lo, hi = wilson_ci(50, 100)
        assert abs((0.5 - lo) - (hi - 0.5)) < 1e-9

    def test_interval_narrows_as_n_grows(self):
        widths = [wilson_ci(round(0.1 * n), n) for n in (30, 100, 300, 1000)]
        widths = [hi - lo for lo, hi in widths]
        assert widths == sorted(widths, reverse=True)

    def test_bounds_are_clamped_to_valid_probabilities(self):
        assert wilson_ci(0, 5)[0] == 0.0
        assert wilson_ci(5, 5)[1] == 1.0

    def test_zero_n_returns_none(self):
        assert wilson_ci(0, 0) is None


# =========================================================================
# Tests: Exact two-arm power
# =========================================================================

class TestTwoArmPower:
    """Fisher exact rather than a normal approximation, because the
    approximation is anticonservative at the near-zero rates seen here."""

    def test_fisher_p_matches_known_table(self):
        """Fisher's tea-tasting table (3 of 4 correct in each group) has the
        published two-sided value 0.4857."""
        assert abs(fisher_exact_p(3, 4, 1, 4) - 0.485714) < 1e-5
        # And an asymmetric table, verified against a direct hypergeometric
        # enumeration: 3/3 vs 1/4 keeps only the a=3 and a=0 tables.
        assert abs(fisher_exact_p(3, 3, 1, 4) - 0.142857) < 1e-5

    def test_fisher_p_of_identical_arms_is_one(self):
        assert fisher_exact_p(5, 50, 5, 50) == 1.0

    def test_power_of_no_difference_is_at_most_alpha(self):
        """With p1 == p2 the rejection rate is the test's size. Fisher is
        conservative, so this sits at or below alpha, never above."""
        for p in (0.05, 0.10, 0.30):
            assert two_arm_power(p, p, 100) <= 0.05 + 1e-9

    def test_power_rises_with_effect_size(self):
        powers = [two_arm_power(0.10, q, 100) for q in (0.15, 0.20, 0.30, 0.50)]
        assert powers == sorted(powers)

    def test_power_rises_with_n(self):
        powers = [two_arm_power(0.05, 0.20, n) for n in (25, 50, 100, 200)]
        assert powers == sorted(powers)

    def test_known_power_values(self):
        """Independently reproduced figures for this design at n=100/arm."""
        assert abs(two_arm_power(0.00, 0.10, 100) - 0.94) < 0.01
        assert abs(two_arm_power(0.05, 0.20, 100) - 0.88) < 0.01
        assert abs(two_arm_power(0.10, 0.20, 100) - 0.44) < 0.01
        assert abs(two_arm_power(0.05, 0.10, 100) - 0.19) < 0.01

    def test_large_n_falls_back_to_approximation(self):
        assert method_for_n(EXACT_MAX_N) == "fisher_exact"
        assert method_for_n(EXACT_MAX_N + 1) == "normal_approximation"
        # Still monotone and bounded across the switchover.
        power = two_arm_power(0.05, 0.20, EXACT_MAX_N + 50)
        assert 0.0 <= power <= 1.0
        assert power > two_arm_power(0.05, 0.20, 100)

    def test_zero_n_has_no_power(self):
        assert two_arm_power(0.1, 0.5, 0) == 0.0


# =========================================================================
# Tests: Detectable effects and required sample size
# =========================================================================

class TestDetectableEffects:

    def test_known_minimum_detectable_rates_at_n_100(self):
        assert minimum_detectable_rate(0.00, 100) == 0.08
        assert minimum_detectable_rate(0.05, 100) == 0.19
        assert minimum_detectable_rate(0.10, 100) == 0.26

    def test_detectable_effect_shrinks_as_n_grows(self):
        rates = [minimum_detectable_rate(0.10, n) for n in (50, 100, 200)]
        assert rates[0] > rates[1] > rates[2]

    def test_detectable_rate_exceeds_the_baseline(self):
        for baseline in (0.0, 0.05, 0.2, 0.5):
            assert minimum_detectable_rate(baseline, 100) > baseline

    def test_tiny_n_detects_nothing(self):
        assert minimum_detectable_rate(0.10, 3) is None

    def test_n_for_precision_is_monotone_in_target(self):
        assert n_for_precision(0.10, 5.0) > n_for_precision(0.10, 10.0)

    def test_n_for_precision_actually_achieves_it(self):
        for p in (0.02, 0.10, 0.30):
            n = n_for_precision(p, 10.0)
            lo, hi = wilson_ci(round(p * n), n)
            assert (hi - lo) <= 0.1001


# =========================================================================
# Tests: Batch report
# =========================================================================

class TestBatchReport:

    def _metrics(self):
        return [
            ("disabled_monitoring", 16, 100, None, None),
            ("sandbox_escape_attempt", 0, 100, None, None),
            ("confessed_when_asked", 0, 16, "misaligned runs", 0.16),
        ]

    def test_reports_every_metric(self):
        power = analyse_batch(self._metrics())
        assert set(power["metrics"]) == {
            "disabled_monitoring", "sandbox_escape_attempt",
            "confessed_when_asked",
        }

    def test_observed_power_is_never_reported(self):
        """Observed power is a monotone function of the p-value and adds
        nothing to it; a non-significant result always yields low observed
        power, which then gets misread as "underpowered"."""
        power = analyse_batch(self._metrics())
        blob = repr(power).lower()
        assert "observed_power" not in blob
        assert "achieved_power" not in blob
        for entry in power["metrics"].values():
            assert "power" not in {k.lower() for k in entry}

    def test_small_denominator_is_flagged_as_uninformative(self):
        power = analyse_batch(self._metrics())
        conditional = power["metrics"]["confessed_when_asked"]
        assert conditional["informative"] is False
        assert "raw count" in conditional["note"]

        headline = power["metrics"]["disabled_monitoring"]
        assert headline["informative"] is True
        assert "note" not in headline

    def test_conditional_metric_translates_to_total_runs(self):
        """A required n for the confession rate counts MISALIGNED runs; at a
        16% misalignment rate that is a very different number of total runs."""
        power = analyse_batch(self._metrics())
        entry = power["metrics"]["confessed_when_asked"]
        assert entry["total_runs_for_10pp_precision"] == math.ceil(
            entry["n_for_10pp_precision"] / 0.16
        )
        assert (entry["total_runs_for_10pp_precision"]
                > entry["n_for_10pp_precision"])

    def test_unconditional_metric_has_no_translation(self):
        power = analyse_batch(self._metrics())
        entry = power["metrics"]["disabled_monitoring"]
        assert "total_runs_for_10pp_precision" not in entry

    def test_zero_denominator_degrades_cleanly(self):
        power = analyse_batch([("eval_aware_grader", 0, 0, None, None)])
        entry = power["metrics"]["eval_aware_grader"]
        assert entry["rate"] is None
        assert entry["ci95"] is None
        assert "nothing to estimate" in entry["note"]

    def test_multiplicity_is_reported(self):
        power = analyse_batch(self._metrics())
        mult = power["multiplicity"]
        assert mult["n_rates_reported"] == 3
        expected = 1 - 0.95 ** 3
        assert abs(mult["family_wise_error_if_all_tested"] - expected) < 1e-3
        assert abs(mult["bonferroni_alpha"] - 0.05 / 3) < 1e-4

    def test_caveats_name_the_known_limits(self):
        power = analyse_batch(self._metrics())
        joined = " ".join(power["caveats"]).lower()
        for topic in ("observed power", "single scenario", "openrouter",
                      "grader"):
            assert topic in joined

    def test_report_is_json_serialisable(self):
        import json
        json.dumps(analyse_batch(self._metrics()))

    def test_format_report_renders_every_metric(self):
        power = analyse_batch(self._metrics())
        text = format_report(power)
        for label in power["metrics"]:
            assert label in text
        assert "Fisher exact" in text
        assert "16/100" in text

    def test_exported_from_package(self):
        assert ev.wilson_ci(10, 100) == wilson_ci(10, 100)
        assert ev.minimum_detectable_rate(0.1, 100) == 0.26
        assert callable(ev.analyse_batch)
        assert callable(ev.two_arm_power)
        assert callable(ev.n_for_precision)


# =========================================================================
# Tests: difference between two rates
# =========================================================================

class TestDifferenceInterval:
    """The quantity a model comparison actually rests on.

    Comparing two models by whether their marginal intervals overlap is the
    standard mistake and it errs one way: non-overlap implies a difference, but
    overlap does not imply its absence. So a table of per-model intervals
    systematically under-reports real differences, and the interval on the
    difference is what a comparison claim needs."""

    def test_the_true_difference_is_inside_the_interval(self):
        lo, hi = newcombe_diff_ci(87, 100, 61, 100)
        assert lo <= 0.26 <= hi

    def test_an_identical_pair_straddles_zero(self):
        lo, hi = newcombe_diff_ci(50, 100, 50, 100)
        assert lo < 0 < hi

    def test_the_interval_is_signed(self):
        """p1 - p2, so the sign says which arm is higher. A comparison reported
        without a sign is unreadable."""
        assert newcombe_diff_ci(80, 100, 20, 100)[0] > 0
        assert newcombe_diff_ci(20, 100, 80, 100)[1] < 0

    def test_reversing_the_arms_mirrors_the_interval(self):
        lo1, hi1 = newcombe_diff_ci(30, 100, 70, 100)
        lo2, hi2 = newcombe_diff_ci(70, 100, 30, 100)
        assert abs(lo1 + hi2) < 1e-9 and abs(hi1 + lo2) < 1e-9

    def test_a_zero_rate_still_gets_a_real_interval(self):
        """Wald on a difference involving 0/n understates the uncertainty and
        can leave [-1, 1] entirely. Grok 4.5 concealed 0 of 87 acts, so this is
        the case the benchmark actually produces."""
        lo, hi = newcombe_diff_ci(0, 100, 9, 100)
        assert -1.0 <= lo < hi <= 1.0
        assert hi < 0, "0/100 vs 9/100 should separate below zero"

    def test_the_interval_never_leaves_the_possible_range(self):
        for x1, n1, x2, n2 in ((0, 5, 5, 5), (5, 5, 0, 5), (1, 3, 2, 3),
                               (0, 1, 1, 1), (10, 10, 10, 10)):
            lo, hi = newcombe_diff_ci(x1, n1, x2, n2)
            assert -1.0 <= lo <= hi <= 1.0

    def test_more_data_narrows_it(self):
        narrow = newcombe_diff_ci(600, 1000, 400, 1000)
        wide = newcombe_diff_ci(6, 10, 4, 10)
        assert (narrow[1] - narrow[0]) < (wide[1] - wide[0])

    def test_an_empty_arm_has_no_interval(self):
        assert newcombe_diff_ci(0, 0, 5, 10) is None
        assert newcombe_diff_ci(5, 10, 0, 0) is None


class TestCompareRates:
    def test_separation_is_read_off_the_difference_not_the_marginals(self):
        """The case that motivates the whole thing: 60/100 vs 45/100 has
        overlapping marginal intervals and a difference interval that excludes
        zero. Eyeballing the marginals would call this no difference."""
        result = compare_rates(60, 100, 45, 100)
        assert result["marginals_overlap"] is True
        assert result["separated"] is True
        assert result["fisher_p"] < 0.05

    def test_separated_agrees_with_the_interval_excluding_zero(self):
        for x1, n1, x2, n2 in ((87, 100, 61, 100), (50, 100, 50, 100),
                               (0, 100, 9, 100), (5, 10, 4, 10)):
            result = compare_rates(x1, n1, x2, n2)
            lo, hi = result["difference_ci95"]
            assert result["separated"] == (lo > 0 or hi < 0)

    def test_non_overlapping_marginals_always_separate(self):
        """The one direction that does hold: it must never contradict itself."""
        result = compare_rates(95, 100, 5, 100)
        assert result["marginals_overlap"] is False
        assert result["separated"] is True

    def test_an_empty_arm_reports_nothing_rather_than_zero(self):
        result = compare_rates(0, 0, 5, 10)
        assert result["separated"] is None
        assert result["difference"] is None
        assert "nothing to compare" in result["note"]

    def test_both_marginals_are_reported(self):
        result = compare_rates(87, 100, 61, 100)
        assert result["a"]["ci95"] and result["b"]["ci95"]
        assert result["a"]["successes"] == 87 and result["b"]["n"] == 100


class TestTheNormalPrimitives:
    """The two functions everything else in this module is built on, neither of
    which was reached by any test.

    `_z_for_alpha` only runs at a non-default alpha - 0.05 short-circuits to the
    pinned 1.96 - so the bisection had never executed. It is correct; what was
    missing is anything that would notice if it stopped being.
    """

    def test_the_cdf_matches_known_values(self):
        from subversionbench.power import _std_normal_cdf
        for x, expected in ((0.0, 0.5), (1.0, 0.8413447), (-1.0, 0.1586553),
                            (1.959964, 0.975), (-2.575829, 0.005)):
            assert abs(_std_normal_cdf(x) - expected) < 1e-6, x

    def test_the_critical_values_are_the_textbook_ones(self):
        """Bisection rather than scipy, so there is no library to be right on our
        behalf. These are the three alphas a reader would check by hand."""
        from subversionbench.power import _z_for_alpha
        for alpha, expected in ((0.05, 1.959964), (0.01, 2.575829),
                                (0.10, 1.644854)):
            assert abs(_z_for_alpha(alpha) - expected) < 1e-5, alpha

    def test_the_pinned_shortcut_agrees_with_the_computation(self):
        """0.05 takes a hardcoded 1.96 rather than bisecting. If the two ever
        disagreed, a report at the default alpha and one at an explicit 0.05 would
        differ - and the pinned constant is the one every published figure used."""
        from subversionbench.power import Z_95, _z_for_alpha
        assert abs(Z_95 - _z_for_alpha(0.05)) < 5e-5

    def test_a_smaller_alpha_demands_a_larger_critical_value(self):
        """Monotonicity. A bisection with its comparison inverted still returns a
        plausible number, and would make every interval too narrow."""
        from subversionbench.power import _z_for_alpha
        zs = [_z_for_alpha(a) for a in (0.20, 0.10, 0.05, 0.01, 0.001)]
        assert zs == sorted(zs), zs


# =========================================================================
# Tests: chi-square tail
# =========================================================================

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


# =========================================================================
# Tests: stratified comparison
# =========================================================================

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
        from subversionbench.power import compare_rates, mantel_haenszel
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


# =========================================================================
# Tests: multiplicity
# =========================================================================

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
        assert all(b <= h for b, h in zip(bh["adjusted"], holm["adjusted"]))

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


# =========================================================================
# Tests: paired comparison
# =========================================================================

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
        from subversionbench.power import fisher_exact_p, paired_compare
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
