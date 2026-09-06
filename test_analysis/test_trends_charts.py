"""
The trends charts: what they draw, where the labels sit, and what they refuse
to draw at all.

Losing matplotlib costs presentation and never analysis, so everything here
skips without it - which is also why these are apart from the report tests
rather than beside them.
"""


import os
import tempfile
from datetime import date

import trends as ft
from subversionbench import charting
from test_analysis.report_fixtures import _write_summary
from test_analysis.trends_fixtures import _pyplot_or_skip


class TestTheCharts:
    """Every figure plotted is already in the table and the JSON, so a chart is a
    second reading of the same numbers. That is why matplotlib is an optional
    extra and why its absence must degrade rather than fail."""

    def _skip_without_matplotlib(self):
        from conftest import skip_without
        skip_without("matplotlib", "charts are an optional extra")

    def _corpus(self, out):
        for model, misaligned in (("p/fall-1", 8), ("p/fall-2", 5),
                                  ("p/fall-3", 1),
                                  ("p/rise-1", 1), ("p/rise-2", 6)):
            _write_summary(out, model, "strong", n_runs=10,
                           n_misaligned=misaligned, n_scheming=1,
                           n_aware=2, n_unaware=8)
        return out

    def test_one_chart_per_family_plus_one_combined(self):
        """These are invented model IDs with no recorded release date, so the
        release-date charts are correctly absent - that path has its own class
        below. What this pins is the version-order set."""
        self._skip_without_matplotlib()
        with tempfile.TemporaryDirectory() as out:
            report = ft.build_report(self._corpus(out))
            charts = os.path.join(out, "charts")
            written = ft.write_charts(report, charts)
            names = sorted(os.path.basename(p) for p in written)
            assert names == ["family_misaligned_all.png",
                             "family_misaligned_p_fall.png",
                             "family_misaligned_p_rise.png"]
            for path in written:
                assert os.path.getsize(path) > 0

    def test_a_family_key_with_a_slash_does_not_become_a_directory(self):
        """The key is provider/stem, and a slash is a path separator."""
        self._skip_without_matplotlib()
        with tempfile.TemporaryDirectory() as out:
            report = ft.build_report(self._corpus(out))
            charts = os.path.join(out, "charts")
            written = ft.write_charts(report, charts)
            for path in written:
                assert os.path.dirname(path) == charts

    def test_the_chart_directory_is_created(self):
        self._skip_without_matplotlib()
        with tempfile.TemporaryDirectory() as out:
            report = ft.build_report(self._corpus(out))
            nested = os.path.join(out, "a", "b", "charts")
            assert ft.write_charts(report, nested)
            assert os.path.isdir(nested)

    def test_the_metric_is_in_the_filename(self):
        """Two metrics of one corpus must not overwrite each other."""
        self._skip_without_matplotlib()
        with tempfile.TemporaryDirectory() as out:
            self._corpus(out)
            charts = os.path.join(out, "charts")
            misaligned = ft.write_charts(ft.build_report(out, "misaligned"),
                                         charts)
            scheming = ft.write_charts(ft.build_report(out, "scheming"), charts)
            assert not (set(map(os.path.basename, misaligned))
                        & set(map(os.path.basename, scheming)))

    def test_a_missing_matplotlib_is_a_hint_not_a_crash(self):
        """The tables and the JSON carry every number either way, so an install
        without the extra must lose presentation and nothing else."""
        import builtins
        import contextlib
        import io
        real_import = builtins.__import__

        def no_matplotlib(name, *args, **kw):
            if name == "matplotlib":
                raise ImportError("no matplotlib")
            return real_import(name, *args, **kw)

        with tempfile.TemporaryDirectory() as out:
            report = ft.build_report(self._corpus(out))
            builtins.__import__ = no_matplotlib
            try:
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    written = ft.write_charts(report, os.path.join(out, "c"))
            finally:
                builtins.__import__ = real_import
            assert written == []
            assert "matplotlib is not installed" in buf.getvalue()
            assert "subversionbench[charts]" in buf.getvalue()

    def test_the_labels_name_the_version_not_the_model(self):
        """The IDs share a stem by construction - that is what put them in one
        family - so plotting the full ID spends the axis repeating it."""
        with tempfile.TemporaryDirectory() as out:
            report = ft.build_report(self._corpus(out))
            family = report["families"][0]
            labels = ft._member_labels(family)
            assert len(labels) == family["n_members"]
            assert not any("p/fall" in label for label in labels)

    def test_a_date_stamp_and_a_tag_reach_the_label(self):
        family = {"members": [
            {"version": "4", "date": "0813", "tags": []},
            {"version": "3", "date": None, "tags": ["preview"]},
        ]}
        labels = ft._member_labels(family)
        assert "0813" in labels[0]
        assert "preview" in labels[1]

    def test_a_member_with_no_version_is_still_labelled(self):
        labels = ft._member_labels(
            {"members": [{"version": None, "date": None, "tags": []}]})
        assert labels == ["?"]

    def test_well_separated_families_get_no_stagger(self):
        """A chart whose lines are far apart should not be nudged about."""
        families = [{"n_members": 2, "members": [{"rate": 0.05}, {"rate": 0.10}]},
                    {"n_members": 2, "members": [{"rate": 0.60}, {"rate": 0.80}]}]
        layout = ft._label_layout(families, 2, 100.0)
        assert {dy for _dx, dy in layout.values()} == {0}

    def test_coincident_families_are_pushed_apart(self):
        """Two families at the same point put their labels in the same place.
        grok sits at 0.0% where kimi sits at 13.3%, and the fixed offset that
        used to lift grok's label landed it on kimi's marker."""
        families = [{"n_members": 1, "members": [{"rate": 0.13}]},
                    {"n_members": 1, "members": [{"rate": 0.132}]}]
        layout = ft._label_layout(families, 1, 100.0)
        assert layout[(0, 0)][1] != layout[(1, 0)][1]

    def test_the_higher_of_two_is_the_one_that_moves(self):
        """Pushing the lower one down would walk it into whatever is beneath."""
        families = [{"n_members": 1, "members": [{"rate": 0.10}]},
                    {"n_members": 1, "members": [{"rate": 0.11}]}]
        layout = ft._label_layout(families, 1, 100.0)
        assert layout[(0, 0)][1] == 0
        assert layout[(1, 0)][1] > 0

    def test_labels_lean_inward_on_the_last_column(self):
        """Or a label on the rightmost point runs off the axis."""
        families = [{"n_members": 3, "members": [{"rate": 0.1}] * 3}]
        layout = ft._label_layout(families, 3, 100.0)
        assert layout[(0, 0)][0] > 0
        assert layout[(0, 2)][0] < 0

    def test_a_family_shorter_than_the_longest_is_not_laid_out_past_its_end(self):
        families = [{"n_members": 1, "members": [{"rate": 0.1}]},
                    {"n_members": 3, "members": [{"rate": 0.5}] * 3}]
        layout = ft._label_layout(families, 3, 100.0)
        assert (0, 1) not in layout and (0, 2) not in layout
        assert (1, 2) in layout


class TestTheReleaseCharts:
    """
    The same rates against the calendar instead of against version position.

    Position spaces every release equally, which hides that grok's four
    releases came four months apart and gemini's four came eight. A release
    date cannot be derived from an ID, so an unrecorded one is an error - and
    an error that must cost the release charts alone.
    """

    def _skip_without_matplotlib(self):
        from conftest import skip_without
        skip_without("matplotlib", "charts are an optional extra")

    def _dated_corpus(self, out):
        """Real IDs, because the dates come from the real table."""
        for model, misaligned in (("x-ai/grok-4.20", 8), ("x-ai/grok-4.3", 5),
                                  ("x-ai/grok-4.5", 1),
                                  ("moonshotai/kimi-k2.5", 2),
                                  ("moonshotai/kimi-k2.6", 6)):
            _write_summary(out, model, "strong", n_runs=10,
                           n_misaligned=misaligned, n_scheming=1,
                           n_aware=2, n_unaware=8)
        return out

    def test_a_release_chart_per_family_plus_one_combined(self):
        self._skip_without_matplotlib()
        with tempfile.TemporaryDirectory() as out:
            report = ft.build_report(self._dated_corpus(out))
            written = ft.write_charts(report, os.path.join(out, "charts"))
            names = sorted(os.path.basename(p) for p in written
                           if os.path.basename(p).startswith("release_"))
            assert names == ["release_misaligned_all.png",
                             "release_misaligned_moonshotai_kimi-k.png",
                             "release_misaligned_x-ai_grok.png"]
            for name in names:
                assert os.path.getsize(os.path.join(out, "charts", name)) > 0

    def test_the_release_charts_do_not_overwrite_the_version_charts(self):
        """Two views of one family, so two files."""
        self._skip_without_matplotlib()
        with tempfile.TemporaryDirectory() as out:
            report = ft.build_report(self._dated_corpus(out))
            written = ft.write_charts(report, os.path.join(out, "charts"))
            names = [os.path.basename(p) for p in written]
            assert len(names) == len(set(names)) == 6

    def test_no_line_joins_two_releases(self):
        """Nothing was measured between two release dates, so a connecting
        segment invites reading a slope off months of empty axis. The one line
        these charts draw is a straight fit, and it comes from
        _draw_release_fit rather than from joining the points up."""
        import inspect
        for plot in (ft._plot_family_dates, ft._plot_all_family_dates):
            source = inspect.getsource(plot)
            assert "scatter(" in source, plot.__name__
            assert "ax.plot(" not in source, plot.__name__
            assert "errorbar(" not in source, plot.__name__
            assert "_draw_release_fit(" in source, plot.__name__

    def test_the_fitted_line_is_dotted_and_sits_under_the_markers(self):
        """Dotted and behind, because it summarises the points rather than
        joining them."""
        import inspect
        source = inspect.getsource(ft._draw_release_fit)
        assert 'linestyle=":"' in source
        assert "zorder=2" in source

    def test_the_interval_survives_as_brackets_on_the_per_family_chart(self):
        """No error bars means the brackets are the only interval left, so the
        note has to say brackets alone rather than 'error bars and'."""
        import inspect
        source = inspect.getsource(ft._plot_family_dates)
        assert "WILSON_NOTE_BRACKETS_ONLY" in source
        assert "_point_label" in source
        assert "error bars" not in ft.WILSON_NOTE_BRACKETS_ONLY
        assert "Wilson" in ft.WILSON_NOTE_BRACKETS_ONLY

    def test_every_chart_that_fits_a_line_says_what_the_line_is(self):
        """Unlabelled, a dotted line through four points reads as a trend
        TEST. It is not one - the test runs on version position."""
        import inspect
        assert "no p-value" in ft.FIT_NOTE
        assert "weighted by episodes" in ft.FIT_NOTE
        for plot in (ft._plot_family_dates, ft._plot_all_family_dates):
            assert "FIT_NOTE" in inspect.getsource(plot), plot.__name__

    def test_the_combined_legend_carries_each_slope(self):
        """Five gradients cannot be read off one shared axis."""
        assert ft._slope_label({"slope_per_month": 0.165}) == ", +16.5 pts/month"
        assert ft._slope_label({"slope_per_month": -0.078}) == ", -7.8 pts/month"

    def test_a_family_with_no_fit_gets_no_slope_in_the_legend(self):
        """Empty rather than 'n/a': the same legend entry already says how many
        of its members are dated, which is why there is no line."""
        assert ft._slope_label(None) == ""
        assert ft._slope_label({"slope_per_month": None}) == ""


class TestTheReleaseLabelLayout:
    def _span(self):
        return (date(2025, 7, 1), date(2026, 7, 1))

    def test_two_points_close_on_both_axes_get_separate_rows(self):
        points = [("a", date(2026, 1, 1), 20.0),
                  ("b", date(2026, 1, 3), 21.0)]
        layout = ft._date_label_layout(points, self._span(), 100.0)
        assert layout["a"][1] != layout["b"][1]

    def test_points_close_in_time_but_far_apart_in_rate_are_not_staggered(self):
        """deepseek's flash and pro shipped the same day at very different
        rates. Staggering them would spend vertical space on a collision that
        is not happening."""
        points = [("a", date(2026, 4, 24), 22.0),
                  ("b", date(2026, 4, 24), 43.0)]
        layout = ft._date_label_layout(points, self._span(), 100.0)
        assert layout["a"][1] == layout["b"][1]

    def test_a_label_near_the_right_edge_is_written_leftward(self):
        points = [("early", date(2025, 8, 1), 10.0),
                  ("late", date(2026, 7, 1), 10.0)]
        layout = ft._date_label_layout(points, self._span(), 100.0)
        assert layout["early"][0] > 0 and layout["early"][2] == "left"
        assert layout["late"][0] < 0 and layout["late"][2] == "right"

    def test_a_label_at_the_ceiling_hangs_below_its_point(self):
        """100% is a real answer in this corpus, and a label above one prints
        over the title."""
        points = [("top", date(2026, 1, 1), 100.0),
                  ("mid", date(2025, 9, 1), 40.0)]
        layout = ft._date_label_layout(points, self._span(), 100.0)
        assert layout["top"][1] < 0 and layout["top"][3] == "top"
        assert layout["mid"][1] > 0 and layout["mid"][3] == "bottom"

    def test_a_label_at_zero_is_lifted_clear_of_the_axis(self):
        """Centred on the point, half of it prints over the spine."""
        points = [("floor", date(2026, 1, 1), 0.0)]
        layout = ft._date_label_layout(points, self._span(), 100.0)
        assert layout["floor"][1] > 0

    def test_two_labels_leaning_toward_each_other_are_separated(self):
        """Found by looking at the gemini-flash chart, not by reasoning about
        it. Comparing the distance between two POINTS misses this: gemini's 3.5
        and 3.6 sat 63 days apart with 3.6 near the right edge, so 3.6's label
        was written leftward into 3.5's, which was written rightward. The test
        has to be on the label boxes and the side each is written on."""
        span = (date(2025, 7, 1), date(2026, 8, 13))
        labels = {"a": "3.5\n0.5% [0.1, 2.7]", "b": "3.6\n0.0% [0.0, 3.1]"}
        points = [("a", date(2026, 5, 19), 0.5),
                  ("b", date(2026, 7, 21), 0.0)]
        layout = ft._date_label_layout(points, span, 30.0, labels,
                                       axis_width_pt=ft._PER_FAMILY_AXIS_PT)
        # b is near the right edge, so it leans left - into a.
        assert layout["b"][2] == "right"
        assert layout["a"][1] != layout["b"][1]

    def test_a_row_clears_the_whole_label_not_one_line_of_it(self):
        """The other half of the same chart's collision. A row height fixed at
        one line stacked two two-line labels on each other, which is a
        collision produced by the mechanism meant to prevent one."""
        span = (date(2025, 7, 1), date(2026, 8, 13))
        one = {"a": "3.6", "b": "3.7"}
        two = {"a": "3.6\n0.0% [0.0, 3.1]", "b": "3.7\n0.0% [0.0, 3.1]"}
        points = [("a", date(2026, 7, 21), 0.0),
                  ("b", date(2026, 8, 13), 0.0)]
        gap_one = abs(ft._date_label_layout(points, span, 30.0, one)["b"][1]
                      - ft._date_label_layout(points, span, 30.0, one)["a"][1])
        gap_two = abs(ft._date_label_layout(points, span, 30.0, two)["b"][1]
                      - ft._date_label_layout(points, span, 30.0, two)["a"][1])
        assert gap_two > gap_one

    def test_a_wide_label_reserves_more_room_than_a_narrow_one(self):
        """The layout runs before anything is drawn, so the width is estimated
        from the text. An estimate is enough - the question is only whether two
        labels are far enough apart."""
        narrow = ft._label_extent("4.5", 8.0, 520.0, 365)
        wide = ft._label_extent("4.5\n86.6% [81.7, 90.3]", 8.0, 520.0, 365)
        assert wide > narrow > 0


class TestTheReleasePointName:
    def test_a_dated_snapshot_keeps_its_stamp(self):
        """deepseek-v4-pro and deepseek-v4-pro-0813 are both version 4, and two
        points both labelled '4' read as a mistake."""
        assert ft._release_point_name(
            {"version": "4", "date": "0813", "tags": []}) == "4-0813"

    def test_a_qualifier_tag_is_kept_for_the_same_reason(self):
        """kimi-k2 and kimi-k2-thinking are both version 2."""
        assert ft._release_point_name(
            {"version": "2", "date": None, "tags": ["thinking"]}) == (
                "2 (thinking)")

    def test_a_plain_version_stays_plain(self):
        assert ft._release_point_name(
            {"version": "4.5", "date": None, "tags": []}) == "4.5"

    def test_an_unversioned_model_is_marked_rather_than_blank(self):
        assert ft._release_point_name(
            {"version": None, "date": None, "tags": []}) == "?"


class TestTheYAxisFitsTheData:
    """A fixed 0-100 axis puts a family that never exceeds 15% into the bottom
    sixth of the panel, where three steps of a few points each look like one flat
    line. The kimi family is exactly that shape."""

    def test_the_top_rounds_up_to_a_round_number(self):
        """Ticks should read 0/5/10/15, not 0/3.7/7.4."""
        assert ft.axis_top([16.0]) == 20
        assert ft.axis_top([15.0]) == 20
        assert ft.axis_top([52.1]) == 60
        assert ft.axis_top([1.7]) == 5

    def test_the_tallest_point_always_fits(self):
        for value in (0.4, 1.7, 4.9, 5.0, 12.3, 20.0, 47.5, 68.3, 86.6, 99.9):
            assert ft.axis_top([value]) > value, value

    def test_a_full_scale_rate_still_gets_a_full_axis(self):
        assert ft.axis_top([100.0]) == 100
        assert ft.axis_top([97.0]) == 100

    def test_it_reads_the_whole_series_not_the_last_point(self):
        assert ft.axis_top([2.0, 68.3, 5.8]) == ft.axis_top([68.3])

    def test_an_all_zero_family_still_gets_an_axis(self):
        """A zero-tall panel is not a chart."""
        assert ft.axis_top([0.0, 0.0]) == ft._MIN_AXIS_TOP
        assert ft.axis_top([]) == ft._MIN_AXIS_TOP

    def test_none_values_are_ignored_not_zeroed(self):
        assert ft.axis_top([None, 16.0, None]) == ft.axis_top([16.0])

    def test_a_max_landing_on_a_step_still_gets_clearance(self):
        """Otherwise the tallest point's own label sits outside the axis."""
        assert ft.axis_top([20.0]) > 20
        assert ft.axis_top([50.0]) > 50

    def test_the_combined_chart_shares_one_axis(self):
        """Its whole job is to put families on a common scale; per-family axes
        are what the per-family charts are for."""
        import inspect
        source = inspect.getsource(ft._plot_all_families)
        assert "for f in families for m in f[\"members\"]" in source, (
            "the combined y limit must be computed across every family")

    def test_both_charts_draw_wilson_intervals(self):
        import inspect
        for plot in (ft._plot_family, ft._plot_all_families):
            source = inspect.getsource(plot)
            assert "yerr=" in source, plot.__name__

    def test_both_charts_say_the_bars_are_wilson_intervals(self):
        """A whisker with no legend is a whisker the reader has to guess at."""
        import inspect
        assert "Wilson" in ft.WILSON_NOTE
        for plot in (ft._plot_family, ft._plot_all_families):
            assert "WILSON_NOTE" in inspect.getsource(plot), plot.__name__

    def test_the_point_label_carries_the_interval(self):
        """A whisker can be read off the axis only approximately, and the
        numbers are what a reader copies into a write-up."""
        label = ft._point_label({"rate": 0.683, "ci95": [0.596, 0.760]}, 68.3)
        assert label == "68.3% [59.6, 76.0]"

    def test_the_percent_sign_is_not_repeated_inside_the_brackets(self):
        """The axis is already in percent."""
        label = ft._point_label({"rate": 0.058, "ci95": [0.029, 0.116]}, 5.8)
        assert label.count("%") == 1

    def test_a_member_with_no_interval_gets_no_empty_brackets(self):
        assert ft._point_label({"rate": 0.5, "ci95": None}, 50.0) == "50.0%"
        assert ft._point_label({"rate": 0.0}, 0.0) == "0.0%"

    def test_a_zero_rate_still_shows_its_upper_bound(self):
        """0/120 is not the same claim as a rate that cannot be wrong."""
        label = ft._point_label({"rate": 0.0, "ci95": [0.0, 0.031]}, 0.0)
        assert label == "0.0% [0.0, 3.1]"

    def test_the_per_family_note_mentions_the_brackets(self):
        """They are the same interval as the whiskers, so one note covers both."""
        assert "[brackets]" in ft.WILSON_NOTE_WITH_BRACKETS
        assert "Wilson" in ft.WILSON_NOTE_WITH_BRACKETS
        import inspect
        assert "WILSON_NOTE_WITH_BRACKETS" in inspect.getsource(ft._plot_family)

    def test_the_interval_arms_are_asymmetric(self):
        """A Wilson interval near 0 is not centred on the estimate, which is the
        reason Wilson is used rather than the normal approximation."""
        member = {"rate": 0.008, "ci95": [0.001, 0.047]}
        assert ft._upper_error(member) > ft._lower_error(member)

    def test_a_member_with_no_interval_gets_no_bar(self):
        assert ft._lower_error({"rate": 0.5, "ci95": None}) == 0.0
        assert ft._upper_error({"rate": 0.5}) == 0.0

    def test_the_combined_axis_leaves_room_for_the_whiskers(self):
        """Its top is computed from the interval, not the point, or the bar on
        the tallest family escapes the axis."""
        import inspect
        source = inspect.getsource(ft._plot_all_families)
        assert "_upper_error(m)" in source and "axis_top(" in source

    def test_a_per_family_chart_scales_to_its_own_whiskers(self):
        """Including the error bars, or the whisker escapes the axis."""
        import inspect
        source = inspect.getsource(ft._plot_family)
        assert "axis_top([rate + up" in source


class TestTheChartsSayHowManyEpisodes:
    """An interval width means nothing without the denominator it came from, and
    the denominator is not constant within a family: gemini-3.5-flash carries 205
    against its siblings' 120, and grok-4.5 239 against 120."""

    def test_the_tick_label_carries_n(self):
        labels = ft._member_labels({"members": [
            {"version": "3.5", "date": None, "tags": [], "n": 205}]})
        assert labels == ["3.5\nn=205"]

    def test_n_comes_after_the_date_and_the_tags(self):
        labels = ft._member_labels({"members": [
            {"version": "4", "date": "0813", "tags": ["preview"], "n": 119}]})
        assert labels[0] == "4\n0813\n(preview)\nn=119"

    def test_a_member_with_no_denominator_gets_no_n(self):
        """Absent is not zero: a model with nothing collected should not read
        as one measured at n=0."""
        labels = ft._member_labels({"members": [
            {"version": "3.5", "date": None, "tags": [], "n": None}]})
        assert labels == ["3.5"]

    def test_the_per_family_title_totals_the_denominator(self):
        import inspect
        source = inspect.getsource(ft._plot_family)
        assert 'sum(m["n"] or 0 for m in members)' in source
        assert "den_label" in source

    def test_the_combined_legend_totals_each_family(self):
        import inspect
        source = inspect.getsource(ft._plot_all_families)
        assert "n={sum(m['n'] or 0 for m in members)}" in source

    def test_each_metric_names_what_its_n_counts(self):
        """Not always "episodes": the awareness denominator is the episodes
        whose verdict RESOLVED, which is fewer."""
        for metric, spec in ft.METRICS.items():
            assert spec["denominator_label"], metric
        assert ft.METRICS["aware"]["denominator_label"] != (
            ft.METRICS["misaligned"]["denominator_label"])

    def test_the_report_carries_the_denominator_label(self):
        with tempfile.TemporaryDirectory() as out:
            for model, n in (("p/a-1", 8), ("p/a-2", 5)):
                _write_summary(out, model, "strong", n_runs=10,
                               n_misaligned=n, n_aware=2, n_unaware=8)
            assert ft.build_report(out, "aware")[
                "metric_denominator_label"] == "graded episodes"
            assert ft.build_report(out, "misaligned")[
                "metric_denominator_label"] == "episodes"


class TestTheChartsDoNotEditorialise:
    """The verdict caption was removed from the charts. Its wording is
    directional - "consistently RISING, the opposite of falling" reads as a
    disappointment, which is right for misalignment and wrong for awareness,
    where a rise with capability is the expected result rather than a failure to
    improve. A caption that means different things by metric is worse than
    none, and the chart already shows the direction."""

    def test_no_chart_draws_the_verdict(self):
        import inspect
        for plot in (ft._plot_family, ft._plot_all_families):
            source = inspect.getsource(plot)
            assert 'family["verdict"]' not in source, plot.__name__
            assert '"verdict"' not in source, plot.__name__

    def test_the_verdict_is_still_computed_and_reported(self):
        """Removed from the charts only - the table and the JSON keep it, beside
        the counts it is derived from."""
        import contextlib
        import io
        with tempfile.TemporaryDirectory() as out:
            for model, n in (("p/a-1", 1), ("p/a-2", 6)):
                _write_summary(out, model, "strong", n_runs=10,
                               n_misaligned=n, n_aware=2, n_unaware=8)
            report = ft.build_report(out)
            assert report["families"][0]["verdict"]
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                ft._print_report(report)
            assert "=>" in buf.getvalue()


class TestTheBrandColourTable:
    """`_BRAND_COLOURS` is a hand-maintained lookup, and both ways it can go
    wrong are silent: a key that no `family_key()` ever produces falls back to
    the palette and looks merely unbranded, and two colours too close together
    read as one family on a chart that carries several."""

    # Below the table's tightest real pair (gemini-flash vs deepseek-pro, 15.4)
    # with headroom, so this rejects a duplicate or near-duplicate addition
    # without pretending the existing spacing is more generous than it is.
    MIN_DELTA_E = 12.0

    @staticmethod
    def _lab(hex_colour):
        """sRGB to CIE L*a*b*, so distance is perceptual rather than a
        difference between two byte triples - #0A192F and #000000 are far apart
        in RGB arithmetic and both read as black."""
        r, g, b = (int(hex_colour[i:i + 2], 16) / 255 for i in (1, 3, 5))

        def lin(c):
            return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

        r, g, b = lin(r), lin(g), lin(b)
        x = r * 0.4124 + g * 0.3576 + b * 0.1805
        y = r * 0.2126 + g * 0.7152 + b * 0.0722
        z = r * 0.0193 + g * 0.1192 + b * 0.9505

        def f(t):
            return t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116

        fx, fy, fz = f(x / 0.95047), f(y / 1.0), f(z / 1.08883)
        return (116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz))

    def _delta_e(self, a, b):
        return sum((p - q) ** 2
                   for p, q in zip(self._lab(a), self._lab(b), strict=True)) ** 0.5

    def test_the_table_is_not_empty(self):
        """Scope check: an empty table would make every guard below vacuous."""
        assert len(ft._BRAND_COLOURS) >= 5

    def test_every_value_is_a_six_digit_hex_colour(self):
        import re
        for family, colour in ft._BRAND_COLOURS.items():
            assert re.fullmatch(r"#[0-9A-Fa-f]{6}", colour), (family, colour)

    def test_no_two_families_share_a_colour(self):
        seen = {}
        for family, colour in ft._BRAND_COLOURS.items():
            assert colour.upper() not in seen, (
                f"{family} and {seen.get(colour.upper())} are the same colour")
            seen[colour.upper()] = family

    def test_no_two_colours_are_perceptually_indistinguishable(self):
        import itertools
        pairs = list(itertools.combinations(ft._BRAND_COLOURS.items(), 2))
        assert pairs, "no pairs to compare"
        too_close = [(a, b, round(self._delta_e(ca, cb), 1))
                     for (a, ca), (b, cb) in pairs
                     if self._delta_e(ca, cb) < self.MIN_DELTA_E]
        assert not too_close, (
            f"these families would read as one on a chart carrying both: "
            f"{too_close}")

    def test_every_key_is_a_family_key_something_can_actually_produce(self):
        """The failure this catches is a key that is merely misspelled. It
        cannot be seen on a chart - the family just renders in a palette colour,
        exactly as an unbranded family does - so nothing about the output says
        the entry was never consulted.

        The check is derived rather than listed: each key must be a fixed point
        of `family_key(parse_model_id(...))`, which is the function that
        actually looks the table up."""
        from trends.model_ids import family_key, parse_model_id
        for family in ft._BRAND_COLOURS:
            # A family key is provider/stem; the stem carries no version, so
            # appending one reconstructs an ID that maps back to the key.
            provider, _, stem = family.partition("/")
            base, _, suffix = stem.partition("-")
            candidate = (f"{provider}/{base}-9.9-{suffix}" if suffix
                         else f"{provider}/{base}-9.9")
            assert family_key(parse_model_id(candidate)) == family, (
                f"{family!r} is not a key family_key() produces (tried "
                f"{candidate!r} -> {family_key(parse_model_id(candidate))!r}), "
                f"so this entry is never consulted and the family silently "
                f"renders in a palette colour")

    def test_a_branded_family_gets_its_brand_colour_end_to_end(self):
        """Through `_family_colours`, not by reading the table back - the table
        being right and the lookup using it are different claims."""
        plt = _pyplot_or_skip()
        families = [{"family": "z-ai/glm"}, {"family": "not/branded"}]
        colours = ft._family_colours(plt, families)
        assert colours[0] == "#0A192F"
        assert colours[1] != "#0A192F"

    def test_a_branded_family_does_not_consume_a_palette_slot(self):
        """The documented reason the fallback counts only unbranded families:
        adding a branded one must not reshuffle the unbranded colours."""
        plt = _pyplot_or_skip()
        without = ft._family_colours(plt, [{"family": "a/unbranded"},
                                           {"family": "b/unbranded"}])
        with_brand = ft._family_colours(plt, [{"family": "z-ai/glm"},
                                              {"family": "a/unbranded"},
                                              {"family": "b/unbranded"}])
        assert with_brand[1:] == without, (
            "adding a branded family moved the unbranded families' colours")


class TestTheYAxisDoesNotBuyDeadSpace:
    """The rounding ladder sets the axis CAP. A step too coarse leaves a third
    of the panel empty above the tallest point, on charts whose subject is how
    low the remaining points sit."""

    def test_a_max_of_twenty_caps_at_twenty_five_not_thirty(self):
        """The case that prompted the change: the combined scheming chart tops
        out at 20.0%, which with headroom is 21.6, and the old ladder put that
        in a step of 10."""
        assert ft.axis_top([20.0]) == 25

    def test_the_five_step_band_reaches_fifty(self):
        for value, expected in ((22.0, 25), (26.0, 30), (33.0, 40), (44.0, 50)):
            assert ft.axis_top([value]) == expected, value

    def test_the_cap_still_clears_every_point_it_is_given(self):
        """The property the ladder must never break, whatever the steps are: a
        point drawn above its own axis is a chart that lies."""
        value = 0.1
        while value < 100:
            assert ft.axis_top([value]) >= value, value
            value *= 1.07

    def test_the_ladder_never_wastes_more_than_a_third_of_the_panel(self):
        """The rule the change is really about, asserted across the range
        rather than against the one value that motivated it - so a ladder
        edited later cannot reintroduce the gap somewhere else.

        FROM 10 UPWARD. Below that the step is necessarily coarse relative to
        the value - a max of 5.4 can only round to 10 on a 5-point step - and
        the padding there is deliberate: _MIN_AXIS_TOP exists so an all-but-zero
        family still gets an axis with height rather than a flat line. Every
        rate this corpus actually charts sits above 10 or below the floor.
        """
        value = 10.0
        while value < 95:
            top = ft.axis_top([value])
            assert top <= value * 1.5, (
                f"a max of {value:.1f} caps at {top}, leaving "
                f"{(top - value) / top:.0%} of the panel empty")
            value *= 1.03


class TestTheCombinedDateChartIsAsWideAsItsLegend:
    """Two properties, checked against two different things on purpose.

    The axes width is set by the figsize and tight_layout's margins, so it can
    be measured on any fixture. Whether it MATCHES the legend depends on the
    legend's own text - how many families, and how long their names are - so
    that half is checked against the real corpus the width was tuned for, and
    skipped when no corpus is present.
    """

    def _dated_corpus(self, out):
        """Models that are actually in RELEASE_DATES, so the chart has points.

        Taken from the table rather than invented: `_dated_members` drops any
        model with no recorded date, and a fixture of made-up ids would render
        an empty chart that every assertion below would then pass against.
        """
        from model_releases import RELEASE_DATES
        chosen = [m for m in RELEASE_DATES
                  if m.startswith(("qwen/qwen3.", "z-ai/glm-"))]
        assert len(chosen) >= 4, sorted(RELEASE_DATES)
        for i, model in enumerate(sorted(chosen)):
            _write_summary(out, model, "strong", n_runs=10,
                           n_misaligned=i % 5, n_scheming=1,
                           n_aware=2, n_unaware=8)
        return out

    def _render(self, report):
        """The real combined chart, kept open so it can be measured.

        RENDERED RATHER THAN REASONED ABOUT. Both numbers here come out of
        tight_layout and the legend's own text metrics, neither predictable
        from the figsize. The previous constant was wrong by 127pt for exactly
        that reason.
        """
        import conftest
        conftest.skip_without("matplotlib")
        plt = charting.import_pyplot()
        assert plt is not None
        from trends.chart_geometry import release_span
        from trends.chart_style import _family_colours
        from trends.date_charts import _dated_members, _plot_all_family_dates
        drawn = [f for f in report["families"] if _dated_members(f)]
        assert drawn, "no dated family to draw - the fixture proves nothing"
        held = {}

        class Shim:
            def __getattr__(self, name):
                return getattr(plt, name)

            def subplots(self, *a, **kw):
                fig, ax = plt.subplots(*a, **kw)
                held["fig"], held["ax"] = fig, ax
                return fig, ax

            def close(self, *a, **kw):
                pass

        out = os.path.join(tempfile.mkdtemp(), "combined.png")
        assert _plot_all_family_dates(Shim(), report,
                                      _family_colours(plt, drawn),
                                      release_span(report), out)
        held["fig"].canvas.draw()
        return plt, held["fig"], held["ax"]

    def _width_in(self, fig, artist):
        inv = fig.dpi_scale_trans.inverted()
        box = inv.transform(artist.get_window_extent())
        return box[1][0] - box[0][0]

    # Tolerance, in points. The axes width is not a constant of the figsize:
    # tight_layout takes the left margin from the y tick labels and the y label,
    # so the same figure measures 866pt on the fixture below and 803pt on the
    # real corpus, whose ylabel is longer. 90 admits that spread.
    #
    # WHAT THIS CATCHES, AND WHAT IT DOES NOT. It catches a constant that
    # describes no figure at all - the previous 700 is 166pt from the fixture's
    # measurement and fails. It does NOT catch the figsize being reverted while
    # the constant stays, because 1.8in of figure is 130pt and the spread above
    # is already 63: that case is caught by the ratio test below, where the axes
    # would fall to 0.71 of the legend.
    _AXIS_PT_TOLERANCE = 90

    def test_the_combined_axis_constant_matches_the_figure_it_describes(self):
        """_COMBINED_AXIS_PT converts a label's width into days BEFORE the
        figure exists, so it is a prediction of the axes width, and a wrong one
        silently mis-staggers every point label. It was 700 while the axes
        measured 573."""
        with tempfile.TemporaryDirectory() as out:
            report = ft.build_report(self._dated_corpus(out))
            plt, fig, ax = self._render(report)
            try:
                measured_pt = self._width_in(fig, ax) * 72
                assert (abs(measured_pt - ft._COMBINED_AXIS_PT)
                        <= self._AXIS_PT_TOLERANCE), (
                    f"_COMBINED_AXIS_PT is {ft._COMBINED_AXIS_PT} but the axes "
                    f"measure {measured_pt:.0f}pt - re-measure and move it")
            finally:
                plt.close(fig)

    def test_the_axes_are_about_as_wide_as_the_legend_beneath_them(self):
        """bbox_inches="tight" crops to whichever is wider, so an axes narrower
        than its legend puts empty margin into every saved file. Checked on the
        real corpus because the legend's width is its text: on a two-family
        fixture the legend is short and any figsize passes.

        Corpus-absent skip, which SUBVERSIONBENCH_NO_SKIPS still permits.
        """
        import glob
        import unittest
        corpus = os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "eval_results_r9")
        if not glob.glob(os.path.join(corpus, "summary_*.json")):
            raise unittest.SkipTest("no corpus in this checkout")
        report = ft.build_report(corpus, "scheming")
        plt, fig, ax = self._render(report)
        try:
            ratio = (self._width_in(fig, ax)
                     / self._width_in(fig, ax.get_legend()))
            assert 0.9 <= ratio <= 1.15, (
                f"the axes are {ratio:.2f} times the legend's width")
        finally:
            plt.close(fig)


class TestACaptionNeverWidensTheFigure:
    """
    Captions are drawn outside the axes, so `bbox_inches="tight"` grows the
    saved FIGURE to fit them - the axes keep their size and the chart ends up in
    one corner of a too-wide image. Saying more per caption made this visible:
    the combined awareness chart reached 2127px against 1212px for the same
    chart with no caption at all.
    """

    def test_no_caption_line_exceeds_the_wrap_width(self):
        cases = [
            [("google/gemini-3-flash-preview", 0.0), ("x-ai/grok-4.20", 0.0)]
            + [(f"a/model-with-a-long-name-{i}", 0.4 + i * 0.04)
               for i in range(13)],
            [("a/one", 0.5), ("a/two", 1.0)],
            [("a/quiet", 0.0), ("a/hush", 0.0)],
            [("a/quiet", 0.0), ("a/loud", 1.0)],
        ]
        for pairs in cases:
            for metric in ft.AWARENESS_METRICS:
                note = ft._exposure_range_note([{"family": "p/f", "members": [
                    {"model": m, "reasoning_exposure": {"share": s}}
                    for m, s in pairs]}], metric)
                for line in note.split("\n"):
                    assert len(line) <= ft._CAPTION_WRAP, (metric, line)

    def test_the_structural_breaks_survive_wrapping(self):
        """Wrapping must fold within each statement, not reflow them together -
        running the figures into the group read differently is the ambiguity the
        split was introduced to remove."""
        note = ft._wrap_caption("short first line\n" + "word " * 40)
        assert note.split("\n")[0] == "short first line"

    def test_an_unsplittable_token_is_left_long_rather_than_broken(self):
        """A model ID is useless cut in half, and one over-wide line is a
        smaller problem than an unsearchable one."""
        long_id = "provider/" + "x" * 120
        note = ft._wrap_caption(long_id)
        assert note == long_id

    def test_a_model_id_is_never_folded_at_a_hyphen(self):
        """textwrap breaks on hyphens by default, and these captions exist
        largely to name models. "gemini-3-flash" is a DIFFERENT model in this
        corpus from "gemini-3-flash-preview", so half an ID is worse than a
        long line - it names the wrong thing."""
        ids = ["google/gemini-3-flash-preview", "x-ai/grok-4.20",
               "deepseek/deepseek-v4-pro-0813"]
        note = ft._wrap_caption("the other 3 returned no trace at all - "
                                + ", ".join(ids))
        for model in ids:
            assert model in note, model
        assert "-\n" not in note

    def test_wrapping_preserves_every_word(self):
        text = ("separate reasoning trace returned in 36%-100% of episodes\n"
                "this rate reads both channels, so those models could only "
                "show awareness in visible text and the other 13 in either")
        assert ft._wrap_caption(text).split() == text.split()


class TestTheReleaseChartsDrawNothingRatherThanAnEmptyCalendar:
    """A family with no recorded release date has no position on a calendar.
    An empty axis with a title is worse than no file: it reads as a family
    that was measured and found flat."""

    def _plt(self):
        from conftest import skip_without
        skip_without("matplotlib", "charts are an optional extra")
        return charting.import_pyplot()

    def _undated_family(self):
        return {"family": "nobody/none", "n_members": 2, "members": [
            {"model": "nobody/none-1", "version": "1", "position": 1,
             "released": None, "date": None, "tags": [], "rate": 0.1,
             "n": 30, "successes": 3, "ci95": [0.0, 0.3],
             "underpowered": False, "reasoning_exposure": None},
            {"model": "nobody/none-2", "version": "2", "position": 2,
             "released": None, "date": None, "tags": [], "rate": 0.2,
             "n": 30, "successes": 6, "ci95": [0.1, 0.4],
             "underpowered": False, "reasoning_exposure": None},
        ]}

    def test_a_family_with_no_dated_member_writes_no_per_family_chart(self):
        plt = self._plt()
        family = self._undated_family()
        assert ft.date_charts._dated_members(family) == [], (
            "the fixture has a dated member, so this would pass however "
            "_plot_family_dates handled one that did not")
        path = os.path.join(tempfile.mkdtemp(), "release.png")
        assert ft.date_charts._plot_family_dates(
            plt, family, "rate", "episodes", "#4c72b0",
            (date(2025, 1, 1), date(2026, 1, 1)), path, "misaligned") is None
        assert not os.path.exists(path), (
            "a file was written for a family with nothing to place on it")

    def test_no_dated_family_at_all_writes_no_combined_chart(self):
        plt = self._plt()
        report = {"metric": "misaligned", "metric_label": "rate",
                  "metric_denominator_label": "episodes",
                  "families": [self._undated_family()],
                  "data_quality": {"plotted_models_without_release_date": []}}
        path = os.path.join(tempfile.mkdtemp(), "release_all.png")
        assert ft.date_charts._plot_all_family_dates(
            plt, report, ["#4c72b0"],
            (date(2025, 1, 1), date(2026, 1, 1)), path) is None
        assert not os.path.exists(path)


class TestTheChartWriterCollectsOnlyTheChartsThatExist:
    """write_charts returns the paths the console then prints, so a path in
    that list with no file behind it sends a reader to a chart that is not
    there."""

    def _plt_or_skip(self):
        from conftest import skip_without
        skip_without("matplotlib", "charts are an optional extra")

    def test_a_report_whose_families_are_all_empty_writes_no_combined_chart(self):
        """_plot_all_families returns None rather than an empty axis, and the
        collector must not name a file it did not write."""
        self._plt_or_skip()
        report = {"metric": "misaligned", "metric_label": "rate",
                  "metric_denominator_label": "episodes",
                  "families": [{"family": "p/f", "n_members": 0,
                                "ordering_ambiguous": False, "members": []}],
                  "data_quality": {"plotted_models_without_release_date": []}}
        with tempfile.TemporaryDirectory() as out:
            written = ft.charts.write_charts(report, out)
            assert not os.path.exists(
                os.path.join(out, "family_misaligned_all.png"))
        assert all(written), "a chart that was not drawn was still listed"
        assert "family_misaligned_all.png" not in [
            os.path.basename(path) for path in written]
