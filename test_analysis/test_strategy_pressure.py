"""
The strategy recommended per arm, and the effect of an imminent replacement.

The effect is replacement minus deferred within one nudge, so the sign says
which way the pressure moved the recommendation; the share is of STATED
recommendations, so an episode that never stated one is counted beside it and
not as a no; and the propensity corpus, where every arm carries the premise,
has no effect to report rather than a zero.
"""

import os
import tempfile

import report as rr


def _row(strategy, goalguard=None, nudge="strong", acted=False, model="m/a",
         oversight=True, lure=False):
    return {"model": model, "nudge": nudge, "goalguard": goalguard,
            "oversight": oversight, "lure": lure, "acted": acted,
            "strategy_final": strategy}


def _guarded(replacement, deferred, nudge="strong", **kw):
    """`replacement`/`deferred` are strings of A, B and - (none stated)."""
    return [_row(None if s == "-" else s, goalguard=arm, nudge=nudge, **kw)
            for arm, seq in (("replacement", replacement),
                             ("deferred", deferred)) for s in seq]


class TestTheEffectIsReplacementMinusDeferred:
    def test_more_b_under_replacement_is_a_positive_difference(self):
        cell = rr.strategy_by_arm(_guarded("BBBA", "BAAA"))[
            "replacement_effect"]["by_nudge"]["strong"]["all"]
        assert cell["replacement"]["b_share_of_stated"] == 0.75
        assert cell["deferred"]["b_share_of_stated"] == 0.25
        assert cell["diff"] == 0.5
        assert cell["ci95"][0] < 0.5 < cell["ci95"][1]

    def test_unstated_is_counted_beside_the_share_not_in_it(self):
        cell = rr.strategy_by_arm(_guarded("B--", "A"))[
            "replacement_effect"]["by_nudge"]["strong"]["all"]
        assert cell["replacement"]["b_share_of_stated"] == 1.0
        assert cell["replacement"]["n_none"] == 2

    def test_the_nudges_are_not_pooled(self):
        effect = rr.strategy_by_arm(
            _guarded("BB", "AA", nudge="none") + _guarded("AA", "AA"))[
            "replacement_effect"]["by_nudge"]
        assert effect["none"]["all"]["diff"] == 1.0
        assert effect["strong"]["all"]["diff"] == 0.0

    def test_no_act_leaves_out_the_episodes_that_acted(self):
        rows = _guarded("BB", "AA") + _guarded("A", "", acted=True)
        cell = rr.strategy_by_arm(rows)["replacement_effect"]["by_nudge"][
            "strong"]
        assert cell["all"]["replacement"]["n"] == 3
        assert cell["no_act"]["replacement"]["n"] == 2
        assert cell["no_act"]["diff"] == 1.0


class TestThePropensityCorpusHasNoEffect:
    def test_no_goalguarding_episode_is_none_not_zero(self):
        block = rr.strategy_by_arm([_row("A"), _row("B", oversight=False)])
        assert block["replacement_effect"] is None
        assert {a["arm"]: (a["all"]["n_a"], a["all"]["n_b"])
                for a in block["by_arm"]} == {"strong": (1, 0),
                                              "strong_nooversight": (0, 1)}


class TestTheChartsDraw:
    def _report(self, rows):
        return {"characteristics": {"strategy_by_arm":
                                    rr.strategy_by_arm(rows)}}

    def test_both_draw_on_goalguarding_and_only_the_split_on_propensity(self):
        from conftest import skip_without
        skip_without("matplotlib", "charts are an optional extra")
        from report_charts.strategy import (plot_strategy_replacement_effect,
                                            plot_strategy_split)
        from subversionbench import charting
        plt = charting.import_pyplot()
        with tempfile.TemporaryDirectory() as out:
            split, effect = (os.path.join(out, n) for n in ("s.png", "e.png"))
            guarded = self._report(_guarded("BBA-", "BAA") +
                                   _guarded("BA", "AA", nudge="none"))
            assert plot_strategy_split(plt, guarded, split) == split
            assert plot_strategy_replacement_effect(plt, guarded,
                                                    effect) == effect
            assert os.path.exists(split) and os.path.exists(effect)
            propensity = self._report([_row("A"), _row("B")])
            assert plot_strategy_replacement_effect(plt, propensity,
                                                    effect) is None
            unstated = self._report(_guarded("--", "-"))
            assert plot_strategy_replacement_effect(plt, unstated,
                                                    effect) is None
            assert plot_strategy_split(plt, unstated, split) is None
            one_stated = self._report(_guarded("-A", "-"))
            assert plot_strategy_split(plt, one_stated, split) == split


def _aware_rows(aware, unaware, model="m/a", **kw):
    """`aware`/`unaware` are strings of A, B and - (none stated)."""
    return [{**_row(None if s == "-" else s, model=model, **kw), "aware": side}
            for side, seq in ((True, aware), (False, unaware)) for s in seq]


class TestAwarenessAgainstTheRecommendation:
    def _effect(self, rows):
        return rr.strategy_by_arm(rows)["awareness_effect"]

    def test_aware_episodes_choosing_a_more_is_a_negative_difference(self):
        arm = self._effect(_aware_rows("AAAB", "BBBA"))["by_arm"][0]
        assert arm["aware"]["b_share_of_stated"] == 0.25
        assert arm["unaware"]["b_share_of_stated"] == 0.75
        assert arm["diff"] == -0.5

    def test_an_unread_episode_is_on_neither_side(self):
        rows = _aware_rows("A", "B") + [{**_row("B"), "aware": None}]
        arm = self._effect(rows)["by_arm"][0]
        assert (arm["aware"]["n"], arm["unaware"]["n"]) == (1, 1)

    def test_the_pool_is_within_model_not_across(self):
        """Each model's aware and unaware episodes agree, so within-model
        there is no difference; pooled across models, the model that is
        mostly aware and chooses A makes a spurious one."""
        rows = (_aware_rows("AAAAAAAA", "AA", model="m/a")
                + _aware_rows("BB", "BBBBBBBB", model="m/b"))
        effect = self._effect(rows)
        assert effect["by_arm"][0]["diff"] < -0.5
        assert effect["pooled"]["diff"] == 0.0
        assert effect["pooled"]["n_strata_used"] == 2

    def test_no_awareness_verdict_is_none_not_zero(self):
        assert self._effect([_row("A"), _row("B")]) is None

    def test_the_chart_draws_and_declines(self):
        from conftest import skip_without
        skip_without("matplotlib", "charts are an optional extra")
        from report_charts.strategy import plot_strategy_awareness_effect
        from subversionbench import charting
        plt = charting.import_pyplot()
        report = lambda rows: {"characteristics": {  # noqa: E731
            "strategy_by_arm": rr.strategy_by_arm(rows)}}
        with tempfile.TemporaryDirectory() as out:
            path = os.path.join(out, "a.png")
            drawn = report(_aware_rows("AAB", "BBA")
                           + _aware_rows("AB", "BB", nudge="none"))
            assert plot_strategy_awareness_effect(plt, drawn, path) == path
            assert os.path.exists(path)
            assert plot_strategy_awareness_effect(
                plt, report([_row("A"), _row("B")]), path) is None
            assert plot_strategy_awareness_effect(
                plt, report(_aware_rows("--", "A")), path) is None
