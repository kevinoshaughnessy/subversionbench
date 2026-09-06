"""
The four figures, and the CLI that writes them.

Together because the CLI's job here IS the charts: which were drawn, which were
not, and what it says about each. The chart fixtures are shared between the two
- `TestTheChart._report()` is what the CLI tests hand to a patched
build_report - which is why they are one file rather than two.
"""


import json
import sys
import tempfile
from pathlib import Path

import agentic_misalignment as am
import conftest
from subversionbench.power import MIN_INFORMATIVE_DENOMINATOR


class TestSlug:
    """The only place a bundle-sourced name touches a filename - never a name
    written in this file, per _slug's own docstring."""

    def test_lowercases_and_replaces_each_non_alphanumeric_character(self):
        assert am._slug("Two Words") == "two_words"

    def test_strips_leading_and_trailing_separators(self):
        assert am._slug("  Edge Case  ") == "edge_case"

    def test_distinct_inputs_stay_distinct(self):
        assert am._slug("scenario one") != am._slug("scenario two")


class TestTheChart:
    """The chart adds no arithmetic - every number on it is already in
    `report` - so what these guard is presentation: that it renders at all
    without the corpus, and that the one thing a rho cannot show (which pairs
    disagree on the SIGN of the suppression gap) is visibly distinguished
    rather than merged into one dot colour."""

    def _bundle(self):
        # Three models, spread so the level and gap panels both have real
        # variation - and so gap signs differ, which is the case the right
        # panel exists to show. Awareness buckets sized above
        # MIN_INFORMATIVE_DENOMINATOR so no marker is hollow by construction;
        # one dedicated fixture below shrinks a bucket on purpose instead.
        def row(model, unaware, safety):
            return {"model": model, "scenario": am.OVERALL,
                   "buckets": {"unaware": {"harmful": unaware[0], "n": unaware[1]},
                               "safety_aware": {"harmful": safety[0], "n": safety[1]},
                               "capability_aware": {"harmful": 0, "n": 30}}}
        return {
            "source": "fixture", "rows": [
                row("Ext A", (60, 100), (10, 100)),   # gap positive
                row("Ext B", (10, 100), (40, 100)),   # gap negative
                row("Ext C", (50, 100), (50, 100)),   # gap ~zero
            ],
            "aliases": [
                {"external_model": "Ext A", "local_models": ["a"]},
                {"external_model": "Ext B", "local_models": ["b"]},
                {"external_model": "Ext C", "local_models": ["c"]},
            ],
        }

    def _local(self):
        def side(misaligned, n):
            return {"misaligned": misaligned, "n": n,
                   "rate": misaligned / n if n else None}
        # a: gap positive like Ext A (agrees). b: gap positive, UNLIKE Ext B's
        # negative gap (disagrees) - the case the right panel has to show as a
        # different colour from a. c: no aware episodes at all, so its gap is
        # None and it must be silently excluded rather than plotted as zero.
        rows = {
            "a": {"misaligned": 20, "n": 100,
                 "unaware": side(15, 60), "aware": side(2, 40)},
            "b": {"misaligned": 30, "n": 100,
                 "unaware": side(10, 60), "aware": side(2, 40)},
            "c": {"misaligned": 5, "n": 100,
                 "unaware": side(5, 100), "aware": side(0, 0)},
        }
        for row in rows.values():
            row["misaligned_rate"] = row["misaligned"] / row["n"]
            u, av = row["unaware"]["rate"], row["aware"]["rate"]
            row["suppression_gap"] = None if av is None else round(u - av, 4)
            row["aware_side_underpowered"] = (
                row["aware"]["n"] < MIN_INFORMATIVE_DENOMINATOR)
        return rows

    def _report(self, pooling="any_aware"):
        # Assembled with the same keys build_report() sets, rather than the
        # minimum write_chart happens to read, so a print_report() call on
        # this fixture (as the CLI test below makes) exercises the real
        # shape instead of one this test invented.
        bundle, local = self._bundle(), self._local()
        pairs = am.build_pairs(bundle, local, pooling)
        return {
            "version": "fixture", "rollout_version": "fixture",
            "source": "fixture source",
            "n_pairs": len(pairs),
            "interpretation": "fixture interpretation",
            "unmatched_external_models": [],
            "unmatched_local_models": [],
            "pairs_by_pooling": {pooling: pairs},
            "correlations": [
                am.correlate(pairs, "level"),
                am.correlate(pairs, "suppression", pooling),
            ],
        }

    def _plt_or_skip(self):
        from subversionbench import charting
        if charting.import_pyplot() is None:
            import unittest
            raise unittest.SkipTest("matplotlib not installed")
        return charting.import_pyplot()

    def test_the_chart_renders_without_error(self):
        self._plt_or_skip()
        with tempfile.TemporaryDirectory() as out:
            path = am.charts.write_chart(self._report(), str(Path(out) / "c.png"))
            assert path and Path(path).exists()

    def test_no_pairs_means_no_chart_rather_than_an_empty_one(self):
        assert am.charts.write_chart({"n_pairs": 0, "pairs_by_pooling": {}},
                              "/dev/null/unwritable.png") is None

    def test_without_matplotlib_it_returns_none_rather_than_raising(self):
        """The same degrade-don't-fail contract every chart in this repository
        makes: losing matplotlib costs presentation, not the report."""
        from subversionbench import charting as real_charting
        original = real_charting.import_pyplot
        real_charting.import_pyplot = lambda *a, **k: None
        try:
            with tempfile.TemporaryDirectory() as out:
                result = am.charts.write_chart(self._report(), str(Path(out) / "c.png"))
        finally:
            real_charting.import_pyplot = original
        assert result is None

    def test_a_disagreeing_pair_is_drawn_in_a_different_colour_than_agreeing(self):
        """The whole reason this chart exists rather than the rho alone: rho
        cannot show WHICH pairs disagree on the sign of the gap, and this is
        the assertion that the chart actually encodes that rather than just
        plotting every point the same way."""
        self._plt_or_skip()
        import inspect
        source = inspect.getsource(am.charts.write_chart)
        assert "agree" in source and "#c44e52" in source and "#4c72b0" in source

    def test_a_pair_with_no_suppression_gap_is_excluded_not_zeroed(self):
        """model c has no aware episodes, so its local gap is None. Plotting
        it at 0 would claim awareness had no effect, which is a different and
        unsupported claim from "not measured" - and is indistinguishable from
        a genuinely near-zero gap to anyone reading the chart. Checked on the
        actual scatter calls, not on write_chart merely surviving: a version
        that plots (0, 0) for the excluded pair still returns a path."""
        plt = self._plt_or_skip()
        pairs = am.build_pairs(self._bundle(), self._local(), "any_aware")
        c_pair = next(p for p in pairs if p["local_model"] == "c")
        assert c_pair["local"]["suppression_gap"] is None, (
            "the fixture no longer reproduces an unmeasurable gap, so this "
            "test would pass however write_chart handled it")
        import unittest.mock
        calls = []
        original = plt.Axes.scatter
        def spy(self, x, y, *a, **k):
            calls.append((x, y))
            return original(self, x, y, *a, **k)
        with unittest.mock.patch.object(plt.Axes, "scatter", spy):
            with tempfile.TemporaryDirectory() as out:
                path = am.charts.write_chart(self._report(), str(Path(out) / "c.png"))
        assert path
        assert len(calls) == 2, (
            f"expected one gap point per pair with a measurable gap (a, b), "
            f"got {len(calls)}: {calls}")
        assert (0, 0) not in calls, (
            "the pair with no measurable gap was plotted at the origin")

    def test_an_underpowered_pair_draws_a_hollow_marker(self):
        """The gap panel carries no confidence interval - a difference of two
        rates has none computed anywhere in this file - so the underpowered
        flag already on each pair is the marker's only caution. A filled dot
        promises more certainty than a bucket this small can support."""
        self._plt_or_skip()
        import inspect
        source = inspect.getsource(am.charts.write_chart)
        assert "aware_side_underpowered" in source
        assert 'facecolors=("none"' in source

    def test_subplots_is_called_for_two_side_by_side_panels(self):
        """write_chart closes its figure before returning, so the panel
        geometry is checked from the source - `plt.subplots(1, 2, ...)` is
        what keeps this a level-panel/gap-panel pair rather than a stack."""
        import inspect
        source = inspect.getsource(am.charts.write_chart)
        assert "plt.subplots(1, 2" in source

    def test_both_panel_titles_carry_a_p_value_beside_rho(self):
        """sad_oversight.py's chart shows rho beside p; an earlier version of
        this one showed rho and n but dropped p, an inconsistency with no
        reason behind it - the console output two lines away prints p for the
        same numbers. Checked on the rendered titles, not the source text, so
        a rewording that keeps the value out would still be caught."""
        plt = self._plt_or_skip()
        titles = []
        original = plt.Axes.set_title
        def spy(self, label, *a, **k):
            titles.append(label)
            return original(self, label, *a, **k)
        import unittest.mock
        with unittest.mock.patch.object(plt.Axes, "set_title", spy):
            with tempfile.TemporaryDirectory() as out:
                am.charts.write_chart(self._report(), str(Path(out) / "c.png"))
        assert len(titles) == 2, titles
        # The shared fixture's gap panel legitimately has no rho - model c's
        # local gap is None, leaving only two usable pairs, one short of what
        # a coefficient needs - so its title correctly shows the `note`
        # instead. The level panel has all three and is what this test checks.
        assert "p=" in titles[0], titles

    def test_the_gap_panel_shows_p_too_when_it_has_a_rho(self):
        """The case the test above cannot reach: a corpus where the gap
        correlation itself has enough pairs to compute. A fourth model, so
        three (not two) pairs carry a measurable gap on both sides."""
        plt = self._plt_or_skip()
        bundle, local = self._bundle(), self._local()
        bundle["rows"].append({"model": "Ext D", "scenario": am.OVERALL,
                               "buckets": {"unaware": {"harmful": 20, "n": 100},
                                          "safety_aware": {"harmful": 5, "n": 100},
                                          "capability_aware": {"harmful": 0, "n": 30}}})
        bundle["aliases"].append({"external_model": "Ext D", "local_models": ["d"]})
        local["d"] = {"misaligned": 10, "n": 100, "misaligned_rate": 0.1,
                     "unaware": {"misaligned": 8, "n": 60, "rate": 8 / 60},
                     "aware": {"misaligned": 1, "n": 40, "rate": 1 / 40},
                     "suppression_gap": round(8 / 60 - 1 / 40, 4),
                     "aware_side_underpowered": False}
        pairs = am.build_pairs(bundle, local, "any_aware")
        report = {"n_pairs": len(pairs), "interpretation": "fixture",
                  "pairs_by_pooling": {"any_aware": pairs},
                  "correlations": [am.correlate(pairs, "level"),
                                   am.correlate(pairs, "suppression", "any_aware")]}
        gap_stat = next(c for c in report["correlations"]
                        if c["measure"] == "suppression")
        assert gap_stat["spearman_rho"] is not None, (
            "the fixture still has fewer than three usable gap pairs, so this "
            "test would pass without reaching the code path it targets")
        titles = []
        original = plt.Axes.set_title
        def spy(self, label, *a, **k):
            titles.append(label)
            return original(self, label, *a, **k)
        import unittest.mock
        with unittest.mock.patch.object(plt.Axes, "set_title", spy):
            with tempfile.TemporaryDirectory() as out:
                am.charts.write_chart(report, str(Path(out) / "c.png"))
        assert "p=" in titles[1], titles


class TestChartLabelsDoNotOverlap:
    """The same measured-bbox collision guard sad_oversight.py's chart needed,
    exercised here because this file owns its own copy rather than importing a
    private name across a module boundary - see write_chart's docstring."""

    def _plt(self):
        from subversionbench import charting
        if charting.import_pyplot() is None:
            import unittest
            raise unittest.SkipTest("matplotlib not installed")
        return charting.import_pyplot()

    def test_a_lone_label_keeps_the_natural_offset(self):
        plt = self._plt()
        fig, ax = plt.subplots()
        am._place_labels(fig, ax, [(50.0, 50.0, "only-model")])
        assert ax.texts[0].xyann == am._LABEL_OFFSETS[0]
        plt.close(fig)

    def test_several_points_at_nearly_the_same_spot_all_get_readable_labels(self):
        plt = self._plt()
        fig, ax = plt.subplots()
        points = [(65.0, 10.0 + i, f"model-{i}") for i in range(4)]
        for x, y, _t in points:
            ax.plot([x], [y], "o")
        am._place_labels(fig, ax, points)
        fig.canvas.draw()
        renderer = fig.canvas.get_renderer()
        boxes = [t.get_window_extent(renderer=renderer) for t in ax.texts]
        for i, a in enumerate(boxes):
            for b in boxes[i + 1:]:
                assert not a.overlaps(b)
        plt.close(fig)

    def test_every_point_gets_exactly_one_label(self):
        plt = self._plt()
        fig, ax = plt.subplots()
        points = [(65.0, 10.0 + i * 0.1, f"model-{i}") for i in range(5)]
        am._place_labels(fig, ax, points)
        assert len(ax.texts) == 5
        assert {t.get_text() for t in ax.texts} == {p[2] for p in points}
        plt.close(fig)


class TestScenarioCharts:
    """One chart per non-OVERALL scenario. No local side here - unlike
    TestTheChart's fixture, SubversionBench has one scenario, so there is
    nothing to pair a scenario against."""

    def _bundle(self):
        def row(model, scenario, unaware, aware):
            return {"model": model, "scenario": scenario,
                    "buckets": {"unaware": {"harmful": unaware[0], "n": unaware[1]},
                                "safety_aware": {"harmful": aware[0], "n": aware[1]},
                                "capability_aware": {"harmful": 0, "n": 30}}}
        return {
            "source": "fixture",
            "rows": [
                row("Ext A", "scenario one", (60, 100), (10, 100)),
                row("Ext B", "scenario one", (20, 100), (30, 100)),
                row("Ext A", "scenario two", (40, 100), (5, 100)),
                row("Ext A", am.OVERALL, (50, 100), (8, 100)),
            ],
        }

    def _plt_or_skip(self):
        from subversionbench import charting
        if charting.import_pyplot() is None:
            import unittest
            raise unittest.SkipTest("matplotlib not installed")
        return charting.import_pyplot()

    def test_one_chart_is_written_per_non_overall_scenario(self):
        self._plt_or_skip()
        with tempfile.TemporaryDirectory() as out:
            paths = am.charts.write_scenario_charts(self._bundle(), out)
            assert len(paths) == 2
            for p in paths:
                assert Path(p).exists()

    def test_filenames_are_derived_from_the_bundles_scenario_names(self):
        self._plt_or_skip()
        with tempfile.TemporaryDirectory() as out:
            paths = {Path(p).name for p in am.charts.write_scenario_charts(
                self._bundle(), out)}
        assert paths == {
            "agentic_misalignment_scenario_scenario_one.png",
            "agentic_misalignment_scenario_scenario_two.png",
        }

    def test_a_model_absent_from_a_scenario_is_not_plotted_in_it(self):
        """Ext B only has a "scenario one" row; the "scenario two" chart must
        not invent a rate for it."""
        self._plt_or_skip()
        by_scenario = am.external_rates_by_scenario(self._bundle())
        assert "Ext B" not in by_scenario["scenario two"]

    def test_without_matplotlib_it_returns_an_empty_list_rather_than_raising(self):
        from subversionbench import charting as real_charting
        original = real_charting.import_pyplot
        real_charting.import_pyplot = lambda *a, **k: None
        try:
            with tempfile.TemporaryDirectory() as out:
                result = am.charts.write_scenario_charts(self._bundle(), out)
        finally:
            real_charting.import_pyplot = original
        assert result == []

    def test_no_scenarios_means_no_charts_rather_than_an_empty_one(self):
        self._plt_or_skip()
        bundle = {"source": "fixture", "rows": [
            {"model": "M", "scenario": am.OVERALL,
             "buckets": {"unaware": {"harmful": 1, "n": 10},
                        "safety_aware": {"harmful": 0, "n": 5},
                        "capability_aware": {"harmful": 0, "n": 5}}}]}
        with tempfile.TemporaryDirectory() as out:
            assert am.charts.write_scenario_charts(bundle, out) == []

    def test_the_unaware_and_aware_ticks_are_both_drawn(self):
        """The suppression story this whole file exists to report has to
        survive the per-scenario breakdown too, not just the pooled chart."""
        self._plt_or_skip()
        import inspect
        source = inspect.getsource(am.charts.write_scenario_charts)
        assert '"unaware"' in source and '"aware"' in source
        assert "#c44e52" in source and "#55a868" in source


class TestScenarioActChart:
    """The single strongest (scenario, act) pair, drawn from
    report["best_scenario_act_pairing"] - never a scenario or an act chosen
    in this test file's expectations, only whatever the fixture correlates
    strongest."""

    def _pair(self, local_model, external_model, ext_rate, ext_n, act_rate, act_n):
        return {
            "local_model": local_model, "external_model": external_model,
            "external": {"overall_rate": ext_rate,
                        "harmful": round(ext_rate * ext_n), "n": ext_n},
            "local_act": {"rate": act_rate, "taken": round(act_rate * act_n),
                         "n": act_n},
        }

    def _best(self, n_models=3, rho=0.9, p=0.05, loo=(0.7, 0.95)):
        return {
            "scenario": "s1", "act": "oversight", "n_models": n_models,
            "spearman_rho": rho, "p": p, "p_method": "exact_permutation",
            "leave_one_out_rho_range": list(loo) if loo else None,
            "pairs": [
                self._pair("a", "Ext A", 0.10, 100, 0.05, 40),
                self._pair("b", "Ext B", 0.50, 100, 0.45, 40),
                self._pair("c", "Ext C", 0.90, 100, 0.85, 40),
            ][:n_models],
        }

    def _plt_or_skip(self):
        from subversionbench import charting
        if charting.import_pyplot() is None:
            import unittest
            raise unittest.SkipTest("matplotlib not installed")
        return charting.import_pyplot()

    def test_the_chart_renders_when_a_pairing_exists(self):
        self._plt_or_skip()
        with tempfile.TemporaryDirectory() as out:
            path = am.charts.write_scenario_act_chart(
                {"best_scenario_act_pairing": self._best()},
                str(Path(out) / "c.png"))
            assert path and Path(path).exists()

    def test_no_pairing_means_no_chart_rather_than_an_empty_one(self):
        assert am.charts.write_scenario_act_chart(
            {"best_scenario_act_pairing": None}, "/dev/null/unwritable.png"
        ) is None

    def test_a_pairing_with_no_pairs_means_no_chart(self):
        best = self._best()
        best["pairs"] = []
        assert am.charts.write_scenario_act_chart(
            {"best_scenario_act_pairing": best}, "/dev/null/unwritable.png"
        ) is None

    def test_without_matplotlib_it_returns_none_rather_than_raising(self):
        from subversionbench import charting as real_charting
        original = real_charting.import_pyplot
        real_charting.import_pyplot = lambda *a, **k: None
        try:
            with tempfile.TemporaryDirectory() as out:
                result = am.charts.write_scenario_act_chart(
                    {"best_scenario_act_pairing": self._best()},
                    str(Path(out) / "c.png"))
        finally:
            real_charting.import_pyplot = original
        assert result is None

    def test_the_title_and_axis_labels_name_the_winning_scenario_and_act(self):
        """Read off `best` at runtime, not hardcoded - swapping in a
        different winning pair must change what the chart says without
        touching this file's source."""
        plt = self._plt_or_skip()
        import unittest.mock
        captured = {}
        original_set_title = plt.Axes.set_title

        def spy(self, label, *a, **k):
            captured["title"] = label
            return original_set_title(self, label, *a, **k)

        with tempfile.TemporaryDirectory() as out, \
                unittest.mock.patch.object(plt.Axes, "set_title", spy):
            am.charts.write_scenario_act_chart(
                {"best_scenario_act_pairing": self._best()},
                str(Path(out) / "c.png"))
        assert "s1" in captured["title"] and "oversight" in captured["title"]


class TestAScenarioChartOnlyTicksTheAwarenessSidesItHas:
    """The dot is the overall rate; the two ticks are the unaware/aware split
    that feeds the suppression-gap correlation elsewhere. A side with no
    trajectories has no rate, and a tick drawn at zero for it would claim the
    model was measured as never harmful when aware - the opposite reading from
    "not measured".
    """

    def _plt_or_skip(self):
        from subversionbench import charting
        if charting.import_pyplot() is None:
            import unittest
            raise unittest.SkipTest("matplotlib not installed")
        return charting.import_pyplot()

    def _bundle(self, aware_n, unaware_n):
        return {"source": "fixture", "rows": [
            {"model": "Ext A", "scenario": "one",
             "buckets": {"unaware": {"harmful": 3, "n": unaware_n},
                         "safety_aware": {"harmful": 1, "n": aware_n},
                         "capability_aware": {"harmful": 0, "n": 0}}}]}

    def _ticks(self, bundle):
        """The (x, y) of every tick marker the scenario charts draw."""
        import unittest.mock
        plt = self._plt_or_skip()
        calls = []
        original = plt.Axes.scatter

        def spy(self, x, y, *a, **k):
            calls.append((x, y, k.get("label")))
            return original(self, x, y, *a, **k)

        with unittest.mock.patch.object(plt.Axes, "scatter", spy), \
                tempfile.TemporaryDirectory() as out:
            paths = am.charts.write_scenario_charts(bundle, out)
        assert paths, "no chart was drawn, so no tick could have been"
        return calls

    def test_both_sides_measured_gets_both_ticks(self):
        labels = {label for _x, _y, label in
                  self._ticks(self._bundle(aware_n=40, unaware_n=40))}
        assert labels == {"unaware", "aware"}

    def test_a_side_with_no_trajectories_gets_no_tick(self):
        stats = am.external_rates_by_scenario(
            self._bundle(aware_n=0, unaware_n=40))["one"]["Ext A"]
        assert stats["aware"]["rate"] is None, (
            "the fixture still measures the aware side, so this would pass "
            "however the chart handled an unmeasured one")
        labels = {label for _x, _y, label in
                  self._ticks(self._bundle(aware_n=0, unaware_n=40))}
        assert labels == {"unaware"}, (
            "a tick was drawn for a side with no trajectories in it")

    def test_the_other_side_missing_drops_the_other_tick(self):
        labels = {label for _x, _y, label in
                  self._ticks(self._bundle(aware_n=40, unaware_n=0))}
        assert labels == {"aware"}


class TestTheScenarioActCaptionOnlyClaimsWhatItHas:
    def _plt_or_skip(self):
        from subversionbench import charting
        if charting.import_pyplot() is None:
            import unittest
            raise unittest.SkipTest("matplotlib not installed")
        return charting.import_pyplot()

    def _captions(self, best):
        plt = self._plt_or_skip()
        import unittest.mock
        texts = []
        original = plt.Figure.text

        def spy(self, x, y, s, *a, **k):
            texts.append(s)
            return original(self, x, y, s, *a, **k)

        with unittest.mock.patch.object(plt.Figure, "text", spy), \
                tempfile.TemporaryDirectory() as out:
            am.charts.write_scenario_act_chart({"best_scenario_act_pairing": best},
                                        str(Path(out) / "c.png"))
        return " ".join(texts)

    def test_a_pairing_with_a_leave_one_out_range_states_it(self):
        captions = self._captions(TestScenarioActChart()._best(loo=(0.7, 0.95)))
        assert "leave-one-out rho ranges +0.700 to +0.950" in captions
        assert "dropping any single model" in captions

    def test_a_pairing_without_one_does_not_claim_a_range(self):
        """Two-directional. n is small enough here that a leave-one-out range
        is the caption a reader leans on, so printing one that was not
        computed would be worse than omitting it."""
        captions = self._captions(TestScenarioActChart()._best(loo=None))
        assert "leave-one-out" not in captions
        assert "independent measurements" in captions, (
            "no caption at all was drawn, so the absence above proves nothing")


class TestWhatHasNoRateIsLeftOffTheChartsRatherThanDrawnAtZero:
    """The same rule the gap panel already follows, applied to the two places
    it was not measured: a level point with no external rate, and a whole
    scenario in which no model has one."""

    def _plt_or_skip(self):
        from subversionbench import charting
        if charting.import_pyplot() is None:
            import unittest
            raise unittest.SkipTest("matplotlib not installed")
        return charting.import_pyplot()

    def test_a_pair_with_no_external_rate_is_left_off_the_level_panel(self):
        """Checked on the errorbar calls rather than on write_chart merely
        surviving: a version that plots the pair at zero also returns a
        path."""
        plt = self._plt_or_skip()
        import unittest.mock
        report = TestTheChart()._report()
        pairs = report["pairs_by_pooling"]["any_aware"]
        assert len(pairs) >= 2
        with_rate = sum(1 for p in pairs
                        if p["external"]["overall_rate"] is not None
                        and p["local"]["misaligned_rate"] is not None)

        calls = []
        original = plt.Axes.errorbar

        def spy(self, x, y, *a, **k):
            calls.append((x, y))
            return original(self, x, y, *a, **k)

        pairs[0]["external"] = dict(pairs[0]["external"], overall_rate=None)
        with unittest.mock.patch.object(plt.Axes, "errorbar", spy), \
                tempfile.TemporaryDirectory() as out:
            path = am.charts.write_chart(report, str(Path(out) / "c.png"))
        assert path
        assert len(calls) == with_rate - 1, (
            f"expected one level point per pair with a rate, got {len(calls)}")
        assert not any(x is None or y is None for x, y in calls)

    def test_a_scenario_in_which_no_model_has_a_rate_gets_no_chart(self):
        """An external scenario every model has a row for and none has a
        trajectory in. An empty chart file is worse than none: it looks like a
        measured zero."""
        self._plt_or_skip()
        empty_buckets = {"unaware": {"harmful": 0, "n": 0},
                         "safety_aware": {"harmful": 0, "n": 0},
                         "capability_aware": {"harmful": 0, "n": 0}}
        bundle = {"source": "fixture", "rows": [
            {"model": "Ext A", "scenario": "measured",
             "buckets": {"unaware": {"harmful": 5, "n": 10},
                         "safety_aware": {"harmful": 1, "n": 10},
                         "capability_aware": {"harmful": 0, "n": 10}}},
            {"model": "Ext A", "scenario": "unmeasured",
             "buckets": dict(empty_buckets)},
            {"model": "Ext B", "scenario": "unmeasured",
             "buckets": dict(empty_buckets)},
        ]}
        by_scenario = am.external_rates_by_scenario(bundle)
        assert all(s["overall_rate"] is None
                   for s in by_scenario["unmeasured"].values()), (
            "the fixture no longer produces a rateless scenario, so this "
            "would pass however write_scenario_charts handled one")
        with tempfile.TemporaryDirectory() as out:
            names = {Path(p).name for p in am.charts.write_scenario_charts(bundle, out)}
        assert names == {"agentic_misalignment_scenario_measured.png"}, (
            "a scenario with no rate to plot still got a chart file")


class TestTheCLIWritesTheChart:
    """Not the correlation arithmetic - the classes above already exercise
    that against fixtures - but the wiring: does main() call write_chart, does
    the file land under --output-dir/charts by default, and does --no-charts
    actually skip it. build_report is patched to a canned report so this does
    not depend on the shipped bundle pairing a real local model with episodes
    this test would otherwise have to fabricate."""

    def _report(self):
        return TestTheChart()._report()

    def _run(self, output_dir, *extra_args):
        import unittest.mock
        argv = sys.argv
        sys.argv = ["agentic_misalignment", "--output-dir", output_dir,
                   "--json-out", str(Path(output_dir) / "r.json"), *extra_args]
        try:
            with unittest.mock.patch.object(am.comparison, "build_report",
                                            return_value=self._report()):
                return am.main()
        finally:
            sys.argv = argv

    def test_a_normal_run_writes_a_chart_under_output_dir(self):
        from subversionbench import charting
        if charting.import_pyplot() is None:
            import unittest
            raise unittest.SkipTest("matplotlib not installed")
        out = tempfile.mkdtemp()
        assert self._run(out) == 0
        chart = Path(out) / "charts" / "agentic_misalignment_correlation.png"
        assert chart.exists(), "main() did not write a chart to the default path"

    def test_a_normal_run_also_writes_a_chart_per_scenario(self):
        """load_bundle() is not mocked by _run, so this exercises the real
        shipped bundle - >=1 rather than a fixed count, so this does not pin
        how many scenarios the external table happens to carry today."""
        from subversionbench import charting
        if charting.import_pyplot() is None:
            import unittest
            raise unittest.SkipTest("matplotlib not installed")
        out = tempfile.mkdtemp()
        assert self._run(out) == 0
        found = list((Path(out) / "charts").glob(
            "agentic_misalignment_scenario_*.png"))
        assert found, "main() did not write any per-scenario chart"

    def test_a_normal_run_writes_the_scenario_act_chart_when_a_pairing_exists(self):
        from subversionbench import charting
        if charting.import_pyplot() is None:
            import unittest
            raise unittest.SkipTest("matplotlib not installed")
        import unittest.mock
        report = self._report()
        report["best_scenario_act_pairing"] = TestScenarioActChart()._best()
        out = tempfile.mkdtemp()
        argv = sys.argv
        sys.argv = ["agentic_misalignment", "--output-dir", out,
                   "--json-out", str(Path(out) / "r.json")]
        try:
            with unittest.mock.patch.object(am.comparison, "build_report",
                                            return_value=report):
                assert am.main() == 0
        finally:
            sys.argv = argv
        chart = Path(out) / "charts" / "agentic_misalignment_scenario_act_correlation.png"
        assert chart.exists(), "main() did not write the scenario/act chart"

    def test_no_charts_flag_skips_the_chart_file(self):
        out = tempfile.mkdtemp()
        assert self._run(out, "--no-charts") == 0
        assert not (Path(out) / "charts").exists(), (
            "--no-charts wrote a chart directory anyway")

    def test_chart_dir_is_honoured(self):
        from subversionbench import charting
        if charting.import_pyplot() is None:
            import unittest
            raise unittest.SkipTest("matplotlib not installed")
        out = tempfile.mkdtemp()
        chart_dir = str(Path(out) / "somewhere-else")
        assert self._run(out, "--chart-dir", chart_dir) == 0
        assert (Path(chart_dir) /
               "agentic_misalignment_correlation.png").exists()


class TestARunWithoutChartsSaysNothingAboutThem:
    """Every chart in this file degrades to None or [] rather than raising -
    matplotlib is optional and a pair can be unplottable - so main has to be
    able to finish having drawn nothing, without announcing files it did not
    write."""

    def _run(self, output_dir, patches):
        import contextlib
        import io
        import unittest.mock
        buf = io.StringIO()
        saved = sys.argv
        sys.argv = ["agentic_misalignment", "--output-dir", output_dir]
        stack = contextlib.ExitStack()
        try:
            with contextlib.redirect_stdout(buf):
                stack.enter_context(unittest.mock.patch.object(
                    am.comparison, "build_report", return_value=TestTheChart()._report()))
                for name, value in patches.items():
                    stack.enter_context(unittest.mock.patch.object(
                        am.charts, name, return_value=value))
                code = am.main()
        finally:
            stack.close()
            sys.argv = saved
        return code, buf.getvalue()

    def test_a_chart_that_could_not_be_drawn_is_not_announced(self):
        with tempfile.TemporaryDirectory() as out:
            code, text = self._run(out, {"write_chart": None})
        assert code == 0, text
        assert "Chart written to" not in text
        assert "agentic_misalignment_correlation.png" not in text

    def test_scenario_charts_that_were_not_written_are_not_counted(self):
        with tempfile.TemporaryDirectory() as out:
            code, text = self._run(out, {"write_scenario_charts": []})
        assert code == 0, text
        assert "scenario chart(s) written" not in text

    def test_a_run_that_does_draw_them_does_announce_them(self):
        """The control. Without it both tests above would pass against a main
        that announced nothing at all."""
        self._plt_or_skip()
        with tempfile.TemporaryDirectory() as out:
            code, text = self._run(out, {})
        assert code == 0, text
        assert "Chart written to" in text
        assert "scenario chart(s) written" in text

    def _plt_or_skip(self):
        from subversionbench import charting
        if charting.import_pyplot() is None:
            import unittest
            raise unittest.SkipTest("matplotlib not installed")


class TestTheCLIRefusesBeforeItReads:
    """Both refusals are before load_bundle, which is the point: a mistyped
    --output-dir and a corpus that pairs with nothing produce different exit
    codes because the operator's next move differs - fix the path, or collect
    the models the external table names."""

    def _run(self, argv, build_report=None):
        import contextlib
        import io
        import unittest.mock
        out, err = io.StringIO(), io.StringIO()
        saved = sys.argv
        sys.argv = ["agentic_misalignment", *argv]
        try:
            with contextlib.redirect_stdout(out), \
                    contextlib.redirect_stderr(err):
                if build_report is None:
                    code = am.main()
                else:
                    with unittest.mock.patch.object(
                            am.comparison, "build_report", return_value=build_report):
                        code = am.main()
        finally:
            sys.argv = saved
        return code, out.getvalue() + err.getvalue()

    def test_a_missing_output_directory_exits_two_and_names_it(self):
        with tempfile.TemporaryDirectory() as parent:
            missing = str(Path(parent) / "not-a-directory")
            code, text = self._run(["--output-dir", missing, "--no-charts"])
        assert code == 2, text
        assert "no such results directory" in text
        assert missing in text, (
            "the operator has to be told which path was wrong; there are two "
            "directory arguments on this command line")

    def test_a_corpus_that_pairs_with_nothing_exits_one(self):
        """A different code from the one above, and deliberately so: the
        directory was found and read, and what is missing is the models. An
        exit code shared with the path error would send an operator looking at
        the wrong thing."""
        with tempfile.TemporaryDirectory() as out:
            code, text = self._run(
                ["--output-dir", out, "--no-charts"],
                build_report={"n_pairs": 0})
        assert code == 1, text
        assert "matches a row in the external table" in text


class TestTheBundleEditingModes:
    """--decode and --encode. Both paths are redirected at a temporary copy,
    because --encode WRITES the tracked bundle and a test against the real
    one would rewrite the published artefact."""

    def _redirected(self, tmpdir):
        import contextlib
        from pathlib import Path
        import agentic_misalignment as am

        @contextlib.contextmanager
        def _ctx():
            saved = (am.bundle._BUNDLE_PATH, am.bundle._PLAIN_PATH)
            try:
                copy = Path(tmpdir) / "agentic_misalignment.enc"
                copy.write_text(saved[0].read_text(encoding="utf-8"),
                                encoding="utf-8")
                am.bundle._BUNDLE_PATH = copy
                am.bundle._PLAIN_PATH = Path(tmpdir) / "agentic_misalignment.json"
                yield am
            finally:
                am.bundle._BUNDLE_PATH, am.bundle._PLAIN_PATH = saved
        return _ctx()

    def test_decode_and_encode_are_refused_together(self):
        """Opposites. Accepting both would run whichever the code checks
        first and silently ignore the other."""
        import agentic_misalignment as am
        with tempfile.TemporaryDirectory() as d:
            with self._redirected(d):
                try:
                    conftest.run_tool_main(am, ["--decode", "--encode"])
                except SystemExit as exit_code:
                    assert exit_code.code == 2
                else:
                    raise AssertionError("both flags were accepted")

    def test_decode_writes_a_gitignored_copy_and_says_so(self):
        with tempfile.TemporaryDirectory() as d:
            with self._redirected(d) as am:
                code, text = conftest.run_tool_main(am, ["--decode"])
                assert code == 0, text
                assert am.bundle._PLAIN_PATH.is_file()
        assert "gitignored" in text

    def test_encode_without_a_decoded_copy_exits_two(self):
        """Distinct from the exit code a bad results directory gives, so a
        caller can tell "you skipped a step" from "that path is wrong"."""
        import agentic_misalignment as am
        with tempfile.TemporaryDirectory() as d:
            with self._redirected(d):
                before = am.bundle._BUNDLE_PATH.read_text(encoding="utf-8")
                code, _text = conftest.run_tool_main(am, ["--encode"])
                assert am.bundle._BUNDLE_PATH.read_text(encoding="utf-8") == before
        assert code == 2

    def test_an_edit_round_trips_without_becoming_readable(self):
        with tempfile.TemporaryDirectory() as d:
            with self._redirected(d) as am:
                conftest.run_tool_main(am, ["--decode"])
                edited = json.loads(am.bundle._PLAIN_PATH.read_text(encoding="utf-8"))
                edited["_edit_marker"] = "round-tripped"
                am.bundle._PLAIN_PATH.write_text(json.dumps(edited), encoding="utf-8")
                code, text = conftest.run_tool_main(am, ["--encode"])
                assert code == 0, text
                assert am.load_bundle(am.bundle._BUNDLE_PATH)["_edit_marker"] == \
                    "round-tripped"
                raw = am.bundle._BUNDLE_PATH.read_bytes()
        assert b"round-tripped" not in raw
        assert "folded" in text
