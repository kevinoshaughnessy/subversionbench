"""
The RELEASE charts: the calendar axis, what sits under it, and what they refuse
to draw at all.

Apart from test_trends_charts.py for the division trends/ already carries: these
are the tests of date_charts.py, where the x axis is a calendar rather than a
version position, and where everything below the axis - the legend and its
captions - is laid out against measured extents rather than data coordinates.

Losing matplotlib costs presentation and never analysis, so everything here
skips without it.
"""


import os
import tempfile
from datetime import date

import trends as ft
from subversionbench import charting
from test_analysis.report_fixtures import _write_summary


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

    def _rendered(self, out, plotter):
        """
        The axes a release plotter actually drew on.

        THE PLOTTER CLOSES ITS OWN FIGURE, which is right - it writes a file
        and owns what it opened - so the figure cannot be read afterwards.
        `close` is suppressed for the call and the figure kept, rather than the
        plotter being changed to hand one back for the benefit of a test.
        """
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        report = ft.build_report(self._dated_corpus(out))
        families = [f for f in report["families"] if ft._dated_members(f)]
        kept = []
        real_close = plt.close

        def _keep(*args, **kwargs):
            if args and hasattr(args[0], "axes"):
                kept.append(args[0])
                return None
            return real_close(*args, **kwargs)

        plt.close = _keep
        try:
            plotter(plt, report, ft._family_colours(plt, families),
                    ft.release_span(report), os.path.join(out, "probe.png"))
        finally:
            plt.close = real_close
        assert kept, "the plotter drew no figure, so this checked nothing"
        axes = [ax for figure in kept for ax in figure.axes]
        real_close("all")
        return axes, families

    def test_no_line_joins_two_releases(self):
        """
        Nothing was measured between two release dates, so a connecting segment
        invites reading a slope off months of empty axis. The only Line2D these
        charts draw is the straight fit, which is dotted.

        ASSERTED ON WHAT WAS DRAWN, not on the source of a named function. This
        used to grep `inspect.getsource` for "scatter(" and for the ABSENCE of
        "errorbar(" - a guard against a location, and it broke twice for
        reasons unconnected to the rule it holds: once when the marker call was
        given a function of its own, and once when the combined chart gained
        the Wilson whiskers it should always have had. Neither joined two
        releases with a line.

        Whiskers are not a counter-example and must not be read as one:
        matplotlib draws them as a LineCollection, never a Line2D, so a
        connecting line still has nowhere to hide here.
        """
        self._skip_without_matplotlib()
        with tempfile.TemporaryDirectory() as out:
            axes, _ = self._rendered(out, ft._plot_all_family_dates)

        assert axes, "no axes were drawn"
        dotted = 0
        for ax in axes:
            for line in ax.lines:
                assert line.get_linestyle() in (":", "dotted"), (
                    f"a solid line joins points on a release chart: "
                    f"{line.get_xydata()[:3]}")
                dotted += 1
        assert dotted, "no fitted line was drawn, so the check above is vacuous"

    def test_the_combined_chart_draws_wilson_whiskers(self):
        """
        The interval has to be visible on the chart most likely to be lifted
        into a write-up. Several points rest on arms of ten episodes, where the
        Wilson interval spans tens of points, and without whiskers the chart
        showed those estimates as though they were precise.

        The axis label is asserted with them: an unexplained error bar is read
        as whatever the reader assumes, and the per-family chart writes the
        same interval in brackets instead of drawing it.
        """
        self._skip_without_matplotlib()
        with tempfile.TemporaryDirectory() as out:
            axes, families = self._rendered(out, ft._plot_all_family_dates)

        bars = [c for ax in axes for c in ax.containers
                if type(c).__name__ == "ErrorbarContainer"]
        assert len(bars) == len(families), (
            f"{len(bars)} error-bar containers for {len(families)} families")
        assert any("Wilson" in ax.get_xlabel() for ax in axes), (
            [ax.get_xlabel() for ax in axes])

    def test_no_whisker_is_clipped_by_the_top_of_the_axis(self):
        """
        axis_top says it in as many words - the values it is given must already
        include the error bars where they are drawn, or the whisker escapes the
        axis. It is the easy half to forget, because the points still fit.

        A CLIPPED WHISKER IS WORSE THAN A MISSING ONE. A missing interval reads
        as absent; one that stops at the axis edge reads as a shorter interval
        than it is, on the chart whose whole purpose is showing how wide the
        interval really is.
        """
        self._skip_without_matplotlib()
        with tempfile.TemporaryDirectory() as out:
            axes, families = self._rendered(out, ft._plot_all_family_dates)

        highest = max((m["rate"] or 0) * 100 + ft._upper_error(m)
                      for f in families for m, _ in ft._dated_members(f))
        assert highest > 0, "no interval to clip, so this checked nothing"
        for ax in axes:
            if not ax.containers:
                continue
            assert ax.get_ylim()[1] >= highest, (
                f"the axis stops at {ax.get_ylim()[1]:.1f}% and the tallest "
                f"upper bound is {highest:.1f}%")

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

    def _drawn_text(self, draw) -> list:
        """Every string one chart actually draws.

        Captured by standing in for plt.close, which each plot function calls
        once it has saved - the last moment the figure still exists.
        """
        import matplotlib.pyplot as plt
        from matplotlib.text import Text
        captured, real_close = [], plt.close

        def capture(fig):
            captured.extend(t.get_text() for t in fig.findobj(Text))
            real_close(fig)

        plt.close = capture
        try:
            with tempfile.TemporaryDirectory() as png:
                draw(plt, os.path.join(png, "chart.png"))
        finally:
            plt.close = real_close
        return captured

    def test_every_chart_that_fits_a_line_says_what_the_line_is(self):
        """Unlabelled, a dotted line through four points reads as a trend
        TEST. It is not one - the fit runs on release date and carries no
        p-value, so each chart that draws one has to say so.

        READ OFF THE DRAWN FIGURE, not out of the function's source. This
        guard used to assert that "FIT_NOTE" appeared in each plot function's
        body, and it failed the day the combined chart's captions were given a
        helper of their own - a rename of nothing, with the chart unchanged.
        It would equally have passed with the text drawn in white on white.
        """
        self._skip_without_matplotlib()
        assert "no p-value" in ft.FIT_NOTE
        assert "weighted by episodes" in ft.FIT_NOTE
        with tempfile.TemporaryDirectory() as out:
            report = ft.build_report(self._dated_corpus(out))
            span = ft.release_span(report)
            dated = [f for f in report["families"] if ft._dated_members(f)]
            fitted = [f for f in dated
                      if (f.get("release_fit") or {}).get("slope_per_month")
                      is not None]
            assert fitted, "no family fits a line, so the guard proves nothing"
            charts = {
                "per family": lambda plt, path: ft._plot_family_dates(
                    plt, fitted[0], "rate", "episodes", "#1f77b4", span, path),
                "combined": lambda plt, path: ft._plot_all_family_dates(
                    plt, report, ["#1f77b4"] * len(dated), span, path),
            }
            for name, draw in charts.items():
                drawn = self._drawn_text(draw)
                assert any(ft.FIT_NOTE in text for text in drawn), (
                    f"the {name} release chart draws a fitted line and never "
                    f"says what it is; it drew {drawn}")

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
