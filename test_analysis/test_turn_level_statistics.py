"""
Odds ratios over matched sets (turn_level/statistics.py).

What matters: on matched pairs the Mantel-Haenszel odds ratio and the conditional logistic
regression both reduce to the ratio of the two kinds of discordant pair, which can be counted by
hand; a set whose units share one exposure carries no information; the categories follow the
interval; and the detectable odds ratio moves the right way with the design's size.
"""

from turn_level.statistics import (category, conditional_logit, matched_odds_ratio,
                                   ratio_of_odds_ratios, set_table,
                                   smallest_detectable_odds_ratio)

# 1:1 pairs: 6 with only the case exposed, 3 with only the control, 5 concordant.
PAIRS = [(True, [False])] * 6 + [(False, [True])] * 3 + [(True, [True])] * 3 + [(False, [False])] * 2


class TestMatchedOddsRatio:
    def test_pairs_give_the_discordant_ratio(self):
        result = matched_odds_ratio([set_table(c, k) for c, k in PAIRS])
        assert result["odds_ratio"] == 2.0
        assert result["informative_sets"] == 9 and result["sets"] == 14

    def test_a_set_table(self):
        assert set_table(True, [False, True, False, False]) == (1, 2, 0, 3)

    def test_categories(self):
        assert category([0.4, 0.9]) == "upper bound below 1"
        assert category([1.1, 2.0]) == "lower bound above 1"
        assert category([0.9, 1.1]) == "includes 1"
        assert category(None) is None


class TestConditionalLogit:
    def test_pairs_give_the_discordant_ratio(self):
        rows = [[(True, [float(c)]), (False, [float(k[0])])] for c, k in PAIRS]
        assert abs(conditional_logit(rows)["odds_ratio"] - 2.0) < 1e-3

    def test_a_covariate_constant_within_every_set_cannot_be_fitted(self):
        rows = [[(True, [1.0, 5.0]), (False, [0.0, 5.0])], [(True, [0.0, 2.0]), (False, [1.0, 2.0])]]
        assert conditional_logit(rows) is None


class TestRatioAndPower:
    def test_equal_odds_ratios_have_a_ratio_of_one(self):
        r = ratio_of_odds_ratios({"odds_ratio": 0.5, "ci95": [0.25, 1.0]},
                                 {"odds_ratio": 0.5, "ci95": [0.25, 1.0]})
        assert r["ratio"] == 1.0 and r["ci95"][0] < 1 < r["ci95"][1]

    def test_a_larger_design_detects_an_odds_ratio_nearer_one(self):
        small = smallest_detectable_odds_ratio(100, 4, 0.15)
        large = smallest_detectable_odds_ratio(400, 4, 0.15)
        assert small < large < 1

    def test_degenerate_prevalence_detects_nothing(self):
        assert smallest_detectable_odds_ratio(100, 4, 0.0) is None
