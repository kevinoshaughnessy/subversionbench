"""
The eval-awareness rate per model, split by the grader's confidence band.

The one property the chart rests on is that the bands PARTITION the aware
episodes: each band's rate is over the same denominator as the awareness rate,
so the stacked bar is exactly as long as the rate it decomposes.
"""

import os
import tempfile

import report_charts as rc
from report.characteristics import awareness_confidence
from report.episode_rows import _rubric_columns
from subversionbench.power import MIN_INFORMATIVE_DENOMINATOR
from test_analysis.chart_fixtures import _plt


def _episode(model, aware, band):
    return {"model": model, "aware": aware, "eval_aware_confidence": band}


def _model(model, high, medium, keywords, unaware, unresolved=0):
    return ([_episode(model, True, "high")] * high
            + [_episode(model, True, "medium")] * medium
            + [_episode(model, True, "keywords_only")] * keywords
            + [_episode(model, False, None)] * unaware
            + [_episode(model, None, None)] * unresolved)


class TestTheConfidenceColumn:

    def _row(self, aware, source, confidence="high"):
        row = {"aware": aware, "aware_source": source}
        _rubric_columns(row, {"eval_awareness_grader": {
            "eval_aware_confidence": confidence}})
        return row["eval_aware_confidence"]

    def test_a_grader_verdict_carries_the_grader_s_band(self):
        assert self._row(True, "grader", "medium") == "medium"

    def test_awareness_from_the_keyword_screen_has_its_own_band(self):
        assert self._row(True, "keywords") == "keywords_only"

    def test_an_unaware_episode_has_no_band(self):
        """The grader stores "high" on a NOT-aware verdict too - high
        confidence that it is not aware - which must not reach a band."""
        assert self._row(False, "grader", "high") is None

    def test_an_unresolved_episode_has_no_band(self):
        assert self._row(None, None) is None


class TestTheBandsPartitionTheRate:

    def test_the_example_model_splits_forty_percent_into_thirty_and_ten(self):
        block = awareness_confidence(_model("m", 30, 10, 0, 60))
        [row] = block["by_model"]
        assert row["rate"] == 0.4
        assert row["bands"]["high"]["rate"] == 0.3
        assert row["bands"]["medium"]["rate"] == 0.1

    def test_the_bands_sum_to_the_rate_including_the_keyword_band(self):
        block = awareness_confidence(_model("m", 7, 5, 3, 25))
        [row] = block["by_model"]
        assert sum(b["n"] for b in row["bands"].values()) == row["n_aware"]

    def test_an_unresolved_episode_is_outside_the_denominator(self):
        [row] = awareness_confidence(_model("m", 1, 0, 0, 1, unresolved=8))[
            "by_model"]
        assert row["n_resolved"] == 2
        assert row["rate"] == 0.5

    def test_models_are_ordered_by_awareness_rate_descending(self):
        block = awareness_confidence(_model("low", 1, 0, 0, 9)
                                     + _model("high", 5, 0, 0, 5))
        assert [r["model"] for r in block["by_model"]] == ["high", "low"]


class TestTheChart:

    def _report(self, episodes):
        return {"characteristics": {
            "awareness_confidence": awareness_confidence(episodes)}}

    def _drawn(self, episodes):
        captured = {}

        def capture(plt, rows, bands, *a, **k):
            captured.update(rows=rows, bands=bands)
            return "drawn"
        original = rc.draw._draw_stacked_rate_chart
        rc.draw._draw_stacked_rate_chart = capture
        try:
            rc.plot_awareness_confidence(None, self._report(episodes), "x.png")
        finally:
            rc.draw._draw_stacked_rate_chart = original
        return captured

    def test_each_bar_is_as_long_as_the_model_s_rate(self):
        n = MIN_INFORMATIVE_DENOMINATOR
        [row] = self._drawn(_model("m", 3, 2, 1, n))["rows"]
        assert abs(sum(row["segments"]) - row["rate"]) < 1e-3

    def test_the_keyword_band_is_left_out_where_no_model_has_one(self):
        drawn = self._drawn(_model("m", 3, 2, 0, MIN_INFORMATIVE_DENOMINATOR))
        assert len(drawn["bands"]) == 2
        assert len(drawn["rows"][0]["segments"]) == 2

    def test_a_model_below_the_floor_is_not_drawn(self):
        drawn = self._drawn(_model("thin", 1, 0, 0, 1)
                            + _model("m", 1, 0, 0, MIN_INFORMATIVE_DENOMINATOR))
        assert [r["label"] for r in drawn["rows"]] == ["m"]

    def test_write_charts_renders_it(self):
        _plt()
        report = dict(self._report(
            _model("m", 3, 2, 1, MIN_INFORMATIVE_DENOMINATOR)), questions=[])
        with tempfile.TemporaryDirectory() as out:
            written = rc.write_charts(report, out)
            assert os.path.join(out, "awareness_confidence.png") in written
