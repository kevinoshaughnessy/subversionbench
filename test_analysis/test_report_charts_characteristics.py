"""
One chart per corpus characteristic: persistence after refusal, the rubric
signals, encoded payloads, and when awareness arrived relative to the refusal.

Each is the same two steps - a profile dict becomes rows, the rows go to a
shape in `report_charts.draw` - so what differs between them, and what these
test, is the caption: what a reader must not conclude differs per measure.
"""


import json
import os
import tempfile

import report as run_report
import report_charts as rc
from subversionbench import charting
from subversionbench.power import MIN_INFORMATIVE_DENOMINATOR
from test_analysis.chart_fixtures import _SIGNAL_KEYS
from test_analysis.chart_fixtures import (
    _by_model_row, _epr_profile, _epr_row, _persistence_profile, _plt, _section,
    _signal_by_model_row, _signal_profile, _timing_profile)


class TestPersistenceRateRows:
    def test_one_row_per_model_in_the_profiles_own_order(self):
        profile = _persistence_profile([
            _by_model_row("p/a", 100, 80), _by_model_row("p/b", 60, 10)])
        rows = rc._persistence_rate_rows(profile)
        assert [r.label for r in rows] == ["p/a", "p/b"]
        assert [r.diff for r in rows] == [0.8, round(1 / 6, 4)]

    def test_the_interval_is_wilson_and_brackets_the_point_estimate(self):
        rows = rc._persistence_rate_rows(
            _persistence_profile([_by_model_row("p/a", 200, 120)]))
        row = rows[0]
        assert row.lo is not None and row.hi is not None
        assert row.lo <= row.diff <= row.hi

    def test_marked_carries_comparable_within_model_not_significance(self):
        """There is no significance test on this chart - `marked` is repurposed
        to say whether the model also appears on the within-model chart."""
        profile = _persistence_profile([
            _by_model_row("p/comparable", 100, 50, comparable=True),
            _by_model_row("p/not", 100, 100, comparable=False),
        ])
        rows = {r.label: r for r in rc._persistence_rate_rows(profile)}
        assert rows["p/comparable"].marked is True
        assert rows["p/not"].marked is False

    def test_the_support_count_travels_with_the_row(self):
        rows = rc._persistence_rate_rows(
            _persistence_profile([_by_model_row("p/a", 370, 90)]))
        assert rows[0].note == "n=370"

    def test_no_models_means_no_rows(self):
        assert rc._persistence_rate_rows(_persistence_profile([])) == []


class TestPersistenceSlopeRows:
    def test_only_comparable_models_are_included(self):
        profile = _persistence_profile([
            _by_model_row("p/both", 100, 50, comparable=True,
                          persisted_mis=(20, 50), complied_mis=(10, 50)),
            _by_model_row("p/only-persisted", 100, 100, comparable=False,
                          persisted_mis=(20, 100)),
        ])
        rows = rc._persistence_slope_rows(profile)
        assert [r["model"] for r in rows] == ["p/both"]

    def test_the_two_rates_are_read_from_the_right_side(self):
        profile = _persistence_profile([_by_model_row(
            "p/a", 100, 50, comparable=True,
            persisted_mis=(40, 50), complied_mis=(10, 50))])
        row = rc._persistence_slope_rows(profile)[0]
        assert row["persisted_rate"] == 0.8
        assert row["complied_rate"] == 0.2
        assert row["n_persisted"] == 50 and row["n_complied"] == 50

    def test_sorted_by_how_far_the_rate_moved_descending(self):
        profile = _persistence_profile([
            _by_model_row("p/small-move", 100, 50, comparable=True,
                          persisted_mis=(30, 50), complied_mis=(20, 50)),
            _by_model_row("p/big-move", 100, 50, comparable=True,
                          persisted_mis=(50, 50), complied_mis=(0, 50)),
            _by_model_row("p/reversed", 100, 50, comparable=True,
                          persisted_mis=(0, 50), complied_mis=(50, 50)),
        ])
        rows = rc._persistence_slope_rows(profile)
        assert [r["model"] for r in rows] == \
            ["p/big-move", "p/small-move", "p/reversed"]

    def test_no_comparable_models_means_no_rows(self):
        profile = _persistence_profile([
            _by_model_row("p/a", 100, 100, comparable=False)])
        assert rc._persistence_slope_rows(profile) == []


class TestPersistenceChartsRender:
    def _report(self, **profile_over):
        return {"characteristics": {
            "persistence_after_refusal": _persistence_profile(
                [_by_model_row("p/a", 200, 120, comparable=True,
                               persisted_mis=(60, 120), complied_mis=(10, 80)),
                 _by_model_row("p/b", 100, 100, comparable=False,
                              persisted_mis=(20, 100))],
                **profile_over)}}

    def test_both_charts_render(self):
        _plt()
        report = self._report()
        with tempfile.TemporaryDirectory() as out:
            rate = rc.plot_persistence_rate(
                rc.charting.import_pyplot(), report,
                os.path.join(out, "r.png"))
            slope = rc.plot_persistence_within_model(
                rc.charting.import_pyplot(), report,
                os.path.join(out, "s.png"))
            assert rate and os.path.exists(rate)
            assert slope and os.path.exists(slope)

    def test_no_characteristics_key_means_no_chart(self):
        """A report built before this feature existed - every other fixture in
        this file - must draw nothing here rather than raising."""
        _plt()
        plt = rc.charting.import_pyplot()
        with tempfile.TemporaryDirectory() as out:
            assert rc.plot_persistence_rate(
                plt, {"questions": []}, os.path.join(out, "r.png")) is None
            assert rc.plot_persistence_within_model(
                plt, {"questions": []}, os.path.join(out, "s.png")) is None

    def test_no_models_shown_a_refusal_means_no_rate_chart(self):
        _plt()
        plt = rc.charting.import_pyplot()
        report = {"characteristics": {
            "persistence_after_refusal": _persistence_profile([])}}
        with tempfile.TemporaryDirectory() as out:
            assert rc.plot_persistence_rate(
                plt, report, os.path.join(out, "r.png")) is None

    def test_no_comparable_models_means_no_slope_chart(self):
        _plt()
        plt = rc.charting.import_pyplot()
        report = {"characteristics": {"persistence_after_refusal":
            _persistence_profile([_by_model_row("p/a", 100, 100, comparable=False)])}}
        with tempfile.TemporaryDirectory() as out:
            assert rc.plot_persistence_within_model(
                plt, report, os.path.join(out, "s.png")) is None

    def test_never_refused_count_reaches_the_caption(self):
        report = self._report(n_never_refused=3361)
        _plt()
        plt = rc.charting.import_pyplot()
        captured = []
        original = rc.draw._draw_rate_chart
        def capture(plot, rows, title, captions, *a, **k):
            captured.append(captions)
            return original(plot, rows, title, captions, *a, **k)
        rc.draw._draw_rate_chart = capture
        try:
            with tempfile.TemporaryDirectory() as out:
                rc.plot_persistence_rate(plt, report, os.path.join(out, "r.png"))
        finally:
            rc.draw._draw_rate_chart = original
        assert any("3361" in c for c, _ in captured[0])

    def test_the_caption_names_wilson_only_not_newcombe(self):
        """This chart draws no difference at all - WILSON_NOTE names Newcombe
        for one, and repeating it here would point at a line the figure does
        not have."""
        _plt()
        plt = rc.charting.import_pyplot()
        captured = []
        original = rc.draw._draw_rate_chart
        def capture(plot, rows, title, captions, *a, **k):
            captured.append(captions)
            return original(plot, rows, title, captions, *a, **k)
        rc.draw._draw_rate_chart = capture
        try:
            with tempfile.TemporaryDirectory() as out:
                rc.plot_persistence_rate(plt, self._report(),
                                         os.path.join(out, "r.png"))
        finally:
            rc.draw._draw_rate_chart = original
        texts = [c for c, _ in captured[0]]
        assert any("Wilson" in t for t in texts)
        assert not any("Newcombe" in t for t in texts)

    def test_the_direction_counts_reach_the_slope_captions(self):
        report = self._report()
        _plt()
        plt = rc.charting.import_pyplot()
        captured = []
        original = rc.draw._draw_slope_chart
        def capture(plot, rows, title, captions, *a, **k):
            captured.append(captions)
            return original(plot, rows, title, captions, *a, **k)
        rc.draw._draw_slope_chart = capture
        try:
            with tempfile.TemporaryDirectory() as out:
                rc.plot_persistence_within_model(
                    plt, report, os.path.join(out, "s.png"))
        finally:
            rc.draw._draw_slope_chart = original
        profile = report["characteristics"]["persistence_after_refusal"]
        n_worse = profile["n_models_persisted_more_misaligned"]
        n_both = profile["n_models_comparable_within_model"]
        assert any(f"{n_worse}/{n_both}" in c for c, _ in captured[0])

    def test_write_charts_includes_both_when_characteristics_present(self):
        _plt()
        report = dict(self._report(), questions=[])
        with tempfile.TemporaryDirectory() as out:
            written = rc.write_charts(report, out)
        names = {os.path.basename(p) for p in written}
        assert "persistence_rate.png" in names
        assert "persistence_within_model.png" in names

    def test_write_charts_omits_both_when_characteristics_absent(self):
        """The exact case test_one_chart_per_question_plus_an_overview already
        pins - restated here so the reason is next to what it protects."""
        _plt()
        with tempfile.TemporaryDirectory() as out:
            written = rc.write_charts({"questions": [_section()]}, out)
        names = {os.path.basename(p) for p in written}
        assert "persistence_rate.png" not in names
        assert "persistence_within_model.png" not in names

    def test_missing_matplotlib_costs_these_charts_and_nothing_else(self):
        original = charting.import_pyplot
        charting.import_pyplot = lambda *a, **k: None
        try:
            report = dict(self._report(), questions=[])
            assert rc.write_charts(report, "/nonexistent") == []
        finally:
            charting.import_pyplot = original


class TestPersistenceChartsInARealReport:
    """The wiring, not the arithmetic above: does an actual corpus with a
    refused-and-persisted episode make it all the way from run_report.main()
    to the two files on disk. persistence_after_refusal() and its loader are
    covered exhaustively in test_report_characteristics.py; this is the one
    place that chain is driven end to end through THIS file's entry point."""

    def _corpus(self, out):
        from test_analysis.report_fixtures import _write_episode, refusal_result
        for oversight in (True, False):
            with open(os.path.join(
                    out, f"summary_strong_{'oversight' if oversight else 'nooversight'}"
                        f"_nolure_2026010100000{int(oversight)}.json"), "w") as f:
                json.dump({"model": "p/m", "nudge": "strong", "n_runs": 1,
                          "n_scheming": 0, "n_misaligned": 0,
                          "awareness_subgroups": {"aware": 0, "unaware": 1}}, f)
        # Episodes shown a refusal and recorded as persisting - the case the
        # whole chart pair exists to draw. MIN_INFORMATIVE_DENOMINATOR of
        # them, not one: has_chart_support drops a model below the floor, so a
        # single episode would draw no chart and this test would pass or fail
        # for a reason other than the one it names.
        for i in range(1, MIN_INFORMATIVE_DENOMINATOR + 1):
            _write_episode(out, i, "p/m", "strong",
                           transcript=[refusal_result()])

    def test_persistence_charts_appear_in_a_real_run(self, monkeypatch):
        _plt()
        with tempfile.TemporaryDirectory() as out:
            self._corpus(out)
            monkeypatch.setattr("sys.argv",
                                ["run_report.py", "--output-dir", out])
            assert run_report.main() == 0
            names = set(os.listdir(os.path.join(out, "charts")))
        assert "persistence_rate.png" in names


class TestEncodedPayloadRateRows:
    def test_one_row_per_model_with_resolved_episodes(self):
        profile = _epr_profile([
            _epr_row("p/a", 100, 80), _epr_row("p/b", 60, 10)])
        rows = rc._encoded_payload_rate_rows(profile)
        assert [r.label for r in rows] == ["p/a", "p/b"]
        assert [r.diff for r in rows] == [0.8, round(1 / 6, 4)]

    def test_a_model_with_no_resolved_episodes_gets_no_row(self):
        profile = _epr_profile([_epr_row("p/a", 0, 0), _epr_row("p/b", 50, 10)])
        rows = rc._encoded_payload_rate_rows(profile)
        assert [r.label for r in rows] == ["p/b"]

    def test_the_interval_is_wilson_and_brackets_the_point_estimate(self):
        rows = rc._encoded_payload_rate_rows(
            _epr_profile([_epr_row("p/a", 200, 120)]))
        row = rows[0]
        assert row.lo is not None and row.hi is not None
        assert row.lo <= row.diff <= row.hi

    def test_a_model_below_the_floor_is_dropped_not_drawn_hollow(self):
        """The rule that replaced the hollow marker. A thin model used to get
        a row with an open marker; on r9 that put a model with 11 episodes and
        no events on the chart carrying a Wilson interval past 25%, which is
        the widest thing on a figure whose finding is one episode."""
        profile = _epr_profile([
            _epr_row("p/powered", 25, 1),
            _epr_row("p/thin", 3, 1),
        ])
        labels = [r.label for r in rc._encoded_payload_rate_rows(profile)]
        assert labels == ["p/powered"]

    def test_the_floor_is_the_shared_one_not_a_number_chosen_here(self):
        """Exactly at the floor is in; one below it is out. Pinned against
        MIN_INFORMATIVE_DENOMINATOR rather than a literal so the rule moves
        with the rest of the analysis if it ever moves."""
        n = MIN_INFORMATIVE_DENOMINATOR
        at = _epr_profile([_epr_row("p/at", n, 0)])
        under = _epr_profile([_epr_row("p/under", n - 1, 0)])
        assert [r.label for r in rc._encoded_payload_rate_rows(at)] == ["p/at"]
        assert rc._encoded_payload_rate_rows(under) == []

    def test_the_support_count_travels_with_the_row(self):
        rows = rc._encoded_payload_rate_rows(
            _epr_profile([_epr_row("p/a", 370, 1)]))
        assert rows[0].note == "n=370"

    def test_no_models_means_no_rows(self):
        assert rc._encoded_payload_rate_rows(_epr_profile([])) == []


class TestTheSupportFloorAppliesToEveryDescriptiveChart:
    """One rule, applied at each chart's OWN denominator - see
    rc.has_chart_support. Written against the rule rather than against one
    chart, because scoping it to a single row builder is how the other three
    would quietly stop applying it."""

    def test_persistence_drops_a_model_with_too_few_refusals(self):
        n = MIN_INFORMATIVE_DENOMINATOR
        profile = _persistence_profile([
            _by_model_row("p/enough", n, 1),
            _by_model_row("p/thin", n - 1, 1),
        ])
        labels = [r.label for r in rc._persistence_rate_rows(profile)]
        assert labels == ["p/enough"]

    def test_the_slope_chart_drops_a_model_whose_thin_side_is_thin(self):
        """The SMALLER side decides: a slope between a 40-episode rate and a
        2-episode one is carried entirely by the 2."""
        n = MIN_INFORMATIVE_DENOMINATOR
        profile = _persistence_profile([
            _by_model_row("p/both-thick", 100, 50, comparable=True,
                          persisted_mis=(10, n), complied_mis=(5, n)),
            _by_model_row("p/one-thin", 100, 50, comparable=True,
                          persisted_mis=(1, n - 1), complied_mis=(5, 60)),
        ])
        labels = [r["model"] for r in rc._persistence_slope_rows(profile)]
        assert labels == ["p/both-thick"]

    def test_the_signal_chart_drops_a_thin_model_whole(self):
        """Model-level, so a model is present or absent entirely rather than
        as a cluster with holes in it."""
        n = MIN_INFORMATIVE_DENOMINATOR
        profile = _signal_profile([
            _signal_by_model_row("p/enough", mentioned_test=(5, n)),
            _signal_by_model_row("p/thin", n_episodes=n - 1,
                                 mentioned_test=(1, 3)),
        ])
        labels = [c["model"] for c in rc._signal_clusters(profile)]
        assert labels == ["p/enough"]

    def test_a_thin_signal_on_a_plotted_model_is_kept_and_marked(self):
        """The two statements are different: the model belongs on the figure,
        and one of its points is estimated from few episodes. Excluding the
        model would lose its other four signals."""
        n = MIN_INFORMATIVE_DENOMINATOR
        profile = _signal_profile([
            _signal_by_model_row("p/m", mentioned_test=(5, n),
                                 broke_character=(1, 3))])
        points = {pt["signal"]: pt for pt in rc._signal_clusters(profile)[0]["points"]}
        assert points["mentioned_test"]["underpowered"] is False
        assert points["broke_character"]["underpowered"] is True


class TestTheRateAxisNarrowsButNeverClips:
    """A rare-event measure on a 0-100 axis stacks every marker against the
    spine; an axis that hides a value is worse. So the requested maximum is a
    floor on the axis, not a cap on the data."""

    def _drawn_xlim(self, rows, xmax_pp):
        plt = _plt()
        captured = {}
        real = rc.draw._BelowAxes

        class Spy(real):
            def __init__(self, fig, ax, height):
                captured["xlim"] = ax.get_xlim()
                super().__init__(fig, ax, height)

        rc.draw._BelowAxes = Spy
        try:
            with tempfile.TemporaryDirectory() as out:
                rc.draw._draw_rate_chart(plt, rows, "t", [], os.path.join(out, "x.png"),
                                    "x", xmax_pp=xmax_pp)
        finally:
            rc.draw._BelowAxes = real
        return captured["xlim"]

    def test_a_narrow_axis_is_honoured_when_the_data_fits(self):
        rows = [rc.Row("p/a", 0.01, 0.0, 0.03, "model", marked=True)]
        assert self._drawn_xlim(rows, 10)[1] <= 11

    def test_the_axis_widens_rather_than_clipping_a_larger_value(self):
        """The regression that matters: a 40% rate on a chart asked for a 10%
        axis must not be drawn outside its own axes."""
        rows = [rc.Row("p/a", 0.40, 0.30, 0.52, "model", marked=True)]
        assert self._drawn_xlim(rows, 10)[1] >= 52


class TestEncodedPayloadChartRenders:
    def _report(self, **profile_over):
        return {"characteristics": {
            "encoded_payload_rate": _epr_profile(
                [_epr_row("p/a", 61, 1, underpowered=False),
                 _epr_row("p/b", 10, 0, underpowered=True)],
                **profile_over)}}

    def test_the_chart_renders(self):
        _plt()
        report = self._report()
        with tempfile.TemporaryDirectory() as out:
            path = rc.plot_encoded_payload_rate(
                rc.charting.import_pyplot(), report,
                os.path.join(out, "e.png"))
            assert path and os.path.exists(path)

    def test_no_characteristics_key_means_no_chart(self):
        """A report built before this feature existed must draw nothing here
        rather than raising."""
        _plt()
        plt = rc.charting.import_pyplot()
        with tempfile.TemporaryDirectory() as out:
            assert rc.plot_encoded_payload_rate(
                plt, {"questions": []}, os.path.join(out, "e.png")) is None

    def test_no_resolved_episodes_means_no_chart(self):
        _plt()
        plt = rc.charting.import_pyplot()
        report = {"characteristics": {
            "encoded_payload_rate": _epr_profile([])}}
        with tempfile.TemporaryDirectory() as out:
            assert rc.plot_encoded_payload_rate(
                plt, report, os.path.join(out, "e.png")) is None

    def test_the_measure_reaches_the_caption(self):
        _plt()
        plt = rc.charting.import_pyplot()
        captured = []
        original = rc.draw._draw_rate_chart
        def capture(plot, rows, title, captions, *a, **k):
            captured.append(captions)
            return original(plot, rows, title, captions, *a, **k)
        rc.draw._draw_rate_chart = capture
        try:
            with tempfile.TemporaryDirectory() as out:
                rc.plot_encoded_payload_rate(
                    plt, self._report(), os.path.join(out, "e.png"))
        finally:
            rc.draw._draw_rate_chart = original
        texts = [c for c, _ in captured[0]]
        assert any("base64-alphabet run" in t for t in texts)


class TestSignalClusters:
    def test_one_cluster_per_model_one_point_per_signal_in_fixed_order(self):
        profile = _signal_profile([
            _signal_by_model_row("a", mentioned_test=(5, 10)),
            _signal_by_model_row("b", broke_character=(2, 10))])
        clusters = rc._signal_clusters(profile)
        assert [c["model"] for c in clusters] == ["a", "b"]
        assert ([p["signal"] for p in clusters[0]["points"]]
               == list(_SIGNAL_KEYS))
        assert ([p["signal"] for p in clusters[1]["points"]]
               == list(_SIGNAL_KEYS))

    def test_rate_and_interval_come_from_the_profiles_own_counts(self):
        profile = _signal_profile([
            _signal_by_model_row("a", broke_character=(3, 12))])
        points = rc._signal_clusters(profile)[0]["points"]
        point = next(p for p in points if p["signal"] == "broke_character")
        assert point["rate"] == 0.25
        assert point["lo"] is not None and point["hi"] is not None
        assert point["lo"] < 0.25 < point["hi"]

    def test_an_unresolved_signal_has_no_rate_and_no_interval(self):
        """Not zero: a signal never graded for this model must not read as a
        confident 'no' on the chart."""
        profile = _signal_profile([_signal_by_model_row("a")])
        points = rc._signal_clusters(profile)[0]["points"]
        assert all(p["rate"] is None and p["lo"] is None for p in points)

    def test_no_models_means_no_clusters(self):
        assert rc._signal_clusters(_signal_profile([])) == []


class TestSignalChartsRender:
    def _report(self, **over):
        return {"characteristics": {"eval_signal_rates": _signal_profile([
            _signal_by_model_row("p/a", mentioned_test=(6, 12),
                                 broke_character=(3, 12)),
            _signal_by_model_row("p/b", mentioned_test=(1, 5))],
            **over)}}

    def test_the_chart_renders(self):
        _plt()
        with tempfile.TemporaryDirectory() as out:
            path = rc.plot_eval_signal_rates(
                rc.charting.import_pyplot(), self._report(),
                os.path.join(out, "s.png"))
            assert path and os.path.exists(path)

    def test_no_characteristics_key_means_no_chart(self):
        """A report built before this feature existed must draw nothing here
        rather than raising."""
        _plt()
        plt = rc.charting.import_pyplot()
        with tempfile.TemporaryDirectory() as out:
            assert rc.plot_eval_signal_rates(
                plt, {"questions": []}, os.path.join(out, "s.png")) is None

    def test_no_models_means_no_chart(self):
        _plt()
        plt = rc.charting.import_pyplot()
        report = {"characteristics": {
            "eval_signal_rates": _signal_profile([])}}
        with tempfile.TemporaryDirectory() as out:
            assert rc.plot_eval_signal_rates(
                plt, report, os.path.join(out, "s.png")) is None

    def test_a_signal_keeps_the_same_colour_in_every_models_cluster(self):
        """The whole reason clusters are drawn in a fixed key order: a
        reader who learns 'blue = mentioned_test' from the legend must be
        able to trust that in every model's cluster, not just the first."""
        _plt()
        plt = rc.charting.import_pyplot()
        report = {"characteristics": {"eval_signal_rates": _signal_profile([
            _signal_by_model_row("p/a", mentioned_test=(6, 12)),
            _signal_by_model_row("p/b", mentioned_test=(1, 12))])}}
        import unittest.mock
        calls = []
        original = plt.Axes.plot

        def spy(self, *a, **k):
            calls.append(k)
            return original(self, *a, **k)

        with tempfile.TemporaryDirectory() as out, \
                unittest.mock.patch.object(plt.Axes, "plot", spy):
            rc.plot_eval_signal_rates(plt, report, os.path.join(out, "s.png"))
        markers = [c for c in calls if c.get("marker") == rc.style._MODEL_MARKER]
        assert len(markers) == 2, "expected one marker per model"
        colours = {c["color"] for c in markers}
        assert colours == {rc.style._SIGNAL_COLOURS["mentioned_test"]}, (
            "the same signal drew in two different colours across models")

    def test_an_underpowered_point_is_drawn_hollow(self):
        _plt()
        plt = rc.charting.import_pyplot()
        report = {"characteristics": {"eval_signal_rates": _signal_profile([
            _signal_by_model_row("p/a", broke_character=(1, 3))])}}
        import unittest.mock
        calls = []
        original = plt.Axes.plot

        def spy(self, *a, **k):
            calls.append(k)
            return original(self, *a, **k)

        with tempfile.TemporaryDirectory() as out, \
                unittest.mock.patch.object(plt.Axes, "plot", spy):
            rc.plot_eval_signal_rates(plt, report, os.path.join(out, "s.png"))
        markers = [c for c in calls if c.get("marker") == rc.style._MODEL_MARKER]
        assert markers, "no marker was drawn at all"
        assert any(c.get("markerfacecolor") == "white" for c in markers)


class TestSignalChartInARealReport:
    """The wiring, not the arithmetic: does an actual corpus with a graded
    rubric answer make it all the way from run_report.main() to the file on
    disk. eval_signal_rates() and its loader are covered exhaustively in
    test_report_characteristics.py and test_report_loading.py."""

    def _corpus(self, out):
        from test_analysis.report_fixtures import _write_episode
        with open(os.path.join(
                out, "summary_strong_oversight_nolure_20260101000000.json"),
                "w") as f:
            json.dump({"model": "p/m", "nudge": "strong", "n_runs": 1,
                      "n_scheming": 0, "n_misaligned": 0,
                      "awareness_subgroups": {"aware": 0, "unaware": 1}}, f)
        # MIN_INFORMATIVE_DENOMINATOR episodes, not one: has_chart_support
        # excludes a model below the floor, so a one-episode corpus draws
        # nothing and this test would pass against a chart that was never
        # written for the wrong reason.
        for i in range(1, MIN_INFORMATIVE_DENOMINATOR + 1):
            path = _write_episode(out, i, "p/m", "strong")
            d = json.load(open(path))
            d["analysis"]["eval_awareness_grader"] = {"rubric_results": {
                "broke_character": {"answer": True, "quote": "this is a test"}}}
            json.dump(d, open(path, "w"))

    def test_the_signal_chart_appears_in_a_real_run(self, monkeypatch):
        _plt()
        with tempfile.TemporaryDirectory() as out:
            self._corpus(out)
            monkeypatch.setattr("sys.argv",
                                ["run_report.py", "--output-dir", out])
            assert run_report.main() == 0
            names = set(os.listdir(os.path.join(out, "charts")))
        assert "eval_signal_rates.png" in names


class TestTheAwarenessRefusalTimingChart:
    def _report(self, **over):
        return {"characteristics": {
            "awareness_refusal_timing": _timing_profile(**over)}}

    def test_the_floor_is_applied_to_the_orderings_not_the_episodes(self):
        """p/c has 143 episodes and 3 placeable orderings. A Wilson interval on
        3 runs most of the axis, and on a chart read at a glance that width is
        taken for a result."""
        rows = rc._awareness_refusal_rows(_timing_profile())
        assert [r.label for r in rows] == ["p/a", "p/b"]

    def test_a_model_with_no_placeable_ordering_is_not_drawn_at_zero(self):
        """p/d was refused plenty and never placeable. Drawing it at 0% would
        report "never became aware after a refusal" where the truth is "no
        ordering could be read"."""
        rows = rc._awareness_refusal_rows(_timing_profile())
        assert not any(r.label == "p/d" for r in rows)

    def test_the_note_carries_the_placeable_count(self):
        rows = rc._awareness_refusal_rows(_timing_profile())
        assert rows[0].note == "n=40"

    def test_nothing_is_drawn_when_no_model_clears_the_floor(self):
        plt = _plt()
        out = os.path.join(tempfile.mkdtemp(), "timing.png")
        thin = _timing_profile(by_model=[{"model": "p/c", "n_before_refusal": 2,
                                          "n_after_refusal": 1,
                                          "n_locatable": 3, "rate_after": 0.33,
                                          "underpowered": True}])
        assert rc.plot_awareness_refusal_timing(
            plt, {"characteristics": {"awareness_refusal_timing": thin}},
            out) is None

    def test_it_renders(self):
        plt = _plt()
        out = os.path.join(tempfile.mkdtemp(), "timing.png")
        assert rc.plot_awareness_refusal_timing(plt, self._report(), out)
        assert os.path.getsize(out) > 1000

    def test_the_chart_denies_being_a_thirteenth_question(self):
        """THE LOAD-BEARING CAPTION. Awareness and the sandbox act are one 2x2
        and question 7 already reports it; without this sentence a reader takes
        the figure for a second, independent piece of evidence that the two go
        together."""
        plt = _plt()
        captured = {}
        original = rc.draw._draw_rate_chart

        def capture(plt_, rows, title, captions, path, *a, **kw):
            captured["captions"] = [c for c, _ in captions]
            captured["colours"] = dict(captions)
            captured["title"] = title
            return path

        rc.draw._draw_rate_chart = capture
        try:
            rc.plot_awareness_refusal_timing(
                plt, self._report(), os.path.join(tempfile.mkdtemp(), "t.png"))
        finally:
            rc.draw._draw_rate_chart = original
        text = " ".join(captured["captions"])
        assert "NOT a thirteenth research question" in text
        assert "question 7" in text
        denial = next(c for c in captured["captions"]
                      if "thirteenth" in c)
        assert captured["colours"][denial] == "#b00020", (
            "the denial must be in the warning colour, not buried in grey")

    def test_the_arm_split_reaches_the_caption(self):
        """Pooled, the majority ordering is "before", which alone reads as "the
        refusal explains nothing". The arms disagree and that is the finding."""
        plt = _plt()
        captured = {}
        original = rc.draw._draw_rate_chart

        def capture(plt_, rows, title, captions, path, *a, **kw):
            captured["captions"] = [c for c, _ in captions]
            return path

        rc.draw._draw_rate_chart = capture
        try:
            rc.plot_awareness_refusal_timing(
                plt, self._report(), os.path.join(tempfile.mkdtemp(), "t.png"))
        finally:
            rc.draw._draw_rate_chart = original
        text = " ".join(captured["captions"])
        assert "oversight present 9%" in text
        assert "oversight absent 78%" in text

    def test_it_is_wired_into_write_charts(self):
        _plt()   # skips when matplotlib is absent; write_charts imports its own
        out = tempfile.mkdtemp()
        report = dict(self._report(), questions=[_section()])
        written = rc.write_charts(report, out)
        assert any(os.path.basename(p) == "awareness_refusal_timing.png"
                   for p in written), [os.path.basename(p) for p in written]
