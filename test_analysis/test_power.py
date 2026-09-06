"""
Interval estimation, exact two-arm power, and the precision block a finished
batch carries.

Rates in this eval sit near zero, which is where a normal approximation is
anticonservative, so the two-arm calculations enumerate Fisher's test - and
what these pin is that the enumeration is used where it should be and said to
be used where it is not.
"""


import math

import subversionbench as ev
from subversionbench.power import (EXACT_MAX_N, analyse_batch, compare_rates,
                                   fisher_exact_p, format_report, method_for_n,
                                   minimum_detectable_rate, n_for_precision,
                                   newcombe_diff_ci, two_arm_power, wilson_ci)


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


class TestThePowerApproximationHandlesTheDegenerateArms:
    """Above EXACT_MAX_N the exact grid is abandoned for the normal
    approximation, whose standard error is zero when neither arm can vary.
    Dividing by it would raise; the two cases either side of that division
    are opposite answers and must not be collapsed."""

    def _big(self):
        return EXACT_MAX_N + 1

    def test_two_arms_that_cannot_differ_have_only_the_false_positive_rate(self):
        """Both rates zero: the test can only reject by chance, so the power
        of the design against this alternative IS alpha."""
        assert two_arm_power(0.0, 0.0, self._big(), alpha=0.05) == 0.05

    def test_two_arms_that_always_differ_are_always_caught(self):
        assert two_arm_power(0.0, 1.0, self._big()) == 1.0

    def test_the_exact_path_is_not_what_answered_either(self):
        """Both above use the approximation only because n exceeds the exact
        cap. Stated as an assertion so a change to EXACT_MAX_N shows up here
        rather than silently moving both tests onto the other branch."""
        assert method_for_n(self._big()) != method_for_n(EXACT_MAX_N)


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


class TestTheReportRendersAnEntryWrittenBeforeAFigureExisted:
    """analyse_batch's output is stored in every summary and re-rendered
    later, so format_report reads its entries with .get - a report written by
    an earlier analysis version does not carry every key this one emits. It
    has to render what is there rather than raise on what is not."""

    def _power(self):
        return analyse_batch([("misaligned", 12, 60, None, None)])

    def test_a_metric_with_no_required_sample_size_still_renders(self):
        power = self._power()
        entry = next(iter(power["metrics"].values()))
        assert entry.pop("n_for_10pp_precision") is not None, (
            "the fixture never carried the key, so removing it proves "
            "nothing about a report that lacks it")
        text = format_report(power)
        assert "misaligned" in text
        assert "12/60" in text
        assert "10pp wide" not in text

    def test_the_same_metric_with_it_does_state_it(self):
        """The control."""
        text = format_report(self._power())
        assert "10pp wide" in text


class TestWhereAFigureCannotBeComputedItIsAbsentRatherThanZero:
    """The rule this module is built on, applied to the guards that had no
    test. Every one of these returns None or a note instead of a number, and
    every one of them would be a plausible-looking figure if it returned 0.0
    or 1.0 by accident."""

    def test_a_precision_target_no_sample_size_reaches_is_none(self):
        """n_for_precision walks n upward to a cap. Hitting the cap means the
        target is not achievable, which is a different answer from the cap
        itself - a caller that read the cap as the answer would report a
        reachable sample size for an unreachable interval."""
        from subversionbench.power import n_for_precision
        assert n_for_precision(0.5, 20.0, cap=50) is None
        assert n_for_precision(0.5, 40.0, cap=50) is not None, (
            "the cap now defeats every target, so the None above says "
            "nothing about the target")

    def test_a_trend_across_groups_that_share_one_score_is_undefined(self):
        """Scores can be supplied rather than defaulting to rank position -
        the reason the release charts can trend against a calendar. Supplying
        one score for every group leaves nothing to order along, which is not
        a trend of zero."""
        from subversionbench.power import cochran_armitage
        out = cochran_armitage([(2, 10), (5, 10)], scores=[3, 3])
        assert out["z"] is None
        assert out["p"] is None
        assert out["direction"] is None
        assert "no ordering" in out["note"]

    def test_two_distinct_scores_over_the_same_groups_do_trend(self):
        """The control: the groups are informative, so what the test above
        catches is the scores and not the counts."""
        from subversionbench.power import cochran_armitage
        out = cochran_armitage([(2, 10), (5, 10)], scores=[0, 1])
        assert out["z"] is not None and out["direction"] == "rising"
