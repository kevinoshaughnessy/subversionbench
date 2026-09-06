"""
What the correlation says about itself, and the chart beside it.

Eight models overlap, which is enough for a rank correlation and nowhere near
enough to conclude one - so every read-out here is about the qualification: the
leave-one-out range, the flags on a pooled or inexactly matched row, and the
refusal to draw an empty chart rather than one that reads as a measured
nothing.
"""


import contextlib
import io
import json
import os
import tempfile
from pathlib import Path

import pytest

import sad_oversight as so
from subversionbench import charting
from subversionbench.power import spearman, spearman_leave_one_out
from test_corpus.sad_fixtures import (_bundle, _print,
                                      _synthetic_pair, _synthetic_report)


class TestTheCorrelationQualifiesItself:

    def _pairs(self, values):
        """One synthetic pair per (score, rate), bypassing the alias table."""
        return [{"sad_model": f"m{i}", "sad_effort": "high",
                 "confidence": "exact",
                 "scores": {v: {"rank": i, "score": s, "se": 3.0, "invalid": 0}
                            for v in so.VARIANTS},
                 "aware_rate": r, "text_rate": r, "n": 120, "n_aware": 0,
                 "n_aware_text": 0, "local_models": [f"p/m{i}"],
                 "pooled_routes": False}
                for i, (s, r) in enumerate(values)]

    def test_a_perfect_ordering_is_found(self):
        pairs = self._pairs([(50, 0.1), (60, 0.2), (70, 0.3), (80, 0.4)])
        out = so.correlate(pairs, "plain", "aware")
        assert out["spearman_rho"] == 1.0
        assert out["p_method"] == "exact_permutation"

    def test_the_leave_one_out_range_travels_with_every_rho(self):
        """At this n it is the headline, not a refinement: a rho that halves
        when one model is dropped is a statement about that model."""
        pairs = self._pairs([(50, 0.1), (60, 0.2), (70, 0.3), (80, 0.0)])
        out = so.correlate(pairs, "plain", "aware")
        lo, hi = out["leave_one_out_rho_range"]
        assert lo < out["spearman_rho"] < hi or lo <= out["spearman_rho"] <= hi
        assert out["most_influential_model"]

    def test_a_flat_measure_gives_no_rho_rather_than_zero(self):
        """Every model at the same rate is a variable that never varies, which
        is not a correlation of zero."""
        pairs = self._pairs([(50, 0.2), (60, 0.2), (70, 0.2), (80, 0.2)])
        out = so.correlate(pairs, "plain", "aware")
        assert out["spearman_rho"] is None
        assert "no spread" in out["note"]

    def test_the_n_is_reported_beside_the_rho(self):
        out = so.correlate(self._pairs([(50, 0.1), (60, 0.2), (70, 0.3)]),
                           "plain", "aware")
        assert out["n_models"] == 3

    def test_both_awareness_measures_are_correlated(self):
        """A correlation that holds on the mixed measure and not on the
        text-only one is a fact about the instrument, not about the models."""
        assert set(so.MEASURES) == {"aware", "text_reachable"}


class TestSpearmanItself:

    def test_the_p_value_is_exact_at_small_n(self):
        out = spearman([1, 2, 3, 4, 5], [1, 2, 3, 4, 5])
        assert out["method"] == "exact_permutation"
        # Two of the 120 orderings reach |rho| = 1.
        assert out["p"] == pytest.approx(2 / 120)

    def test_ties_share_a_rank_so_input_order_cannot_matter(self):
        a = spearman([1, 2, 2, 3, 4], [1, 2, 3, 4, 5])["rho"]
        b = spearman([1, 2, 2, 3, 4], [1, 3, 2, 4, 5])["rho"]
        assert a == b

    def test_reversal_flips_the_sign_and_keeps_the_p(self):
        up = spearman([1, 2, 3, 4, 5], [2, 1, 4, 3, 5])
        down = spearman([1, 2, 3, 4, 5], [4, 5, 2, 3, 1])
        assert up["rho"] == pytest.approx(-down["rho"])
        assert up["p"] == pytest.approx(down["p"])

    def test_too_few_pairs_is_said_not_computed(self):
        out = spearman([1, 2], [1, 2])
        assert out["rho"] is None and "three" in out["note"]

    def test_mismatched_lengths_raise(self):
        with pytest.raises(ValueError):
            spearman([1, 2, 3], [1, 2])

    def test_leave_one_out_needs_something_to_drop(self):
        out = spearman_leave_one_out([1, 2, 3], [1, 2, 3])
        assert out["min_rho"] is None and "too few" in out["note"]

    def test_leave_one_out_finds_the_point_that_carries_the_fit(self):
        xs = [1, 2, 3, 4, 5, 6]
        ys = [1, 2, 3, 4, 5, 0]
        out = spearman_leave_one_out(xs, ys)
        assert out["most_influential_index"] == 5
        assert out["max_rho"] == 1.0


class TestSpearmanOnceThereAreTooManyModelsToEnumerate:
    """The sampled-permutation branch, taken above _EXACT_PERMUTATION_MAX_N.

    Every p-value this benchmark reports for a rank correlation comes from
    the exact branch today, because the model set is small. The moment it
    grows past the threshold the sampled branch produces all of them
    instead - so it is worth having run before that happens rather than
    after, which is what "n=9" means in these tests.
    """

    def test_the_threshold_is_where_the_method_changes(self):
        """8! is 40,320 orderings and enumerable; 9! is 362,880 and not.
        Asserted at the boundary rather than at a comfortable distance from
        it, because a threshold is exactly where an off-by-one lives."""
        from subversionbench.power import _EXACT_PERMUTATION_MAX_N
        assert _EXACT_PERMUTATION_MAX_N == 8
        exact = spearman(list(range(8)), list(range(8)))
        sampled = spearman(list(range(9)), list(range(9)))
        assert exact["method"] == "exact_permutation"
        assert sampled["method"] == "sampled_permutation"

    def test_the_sampled_p_is_never_zero(self):
        """(hits + 1) / (draws + 1), not hits / draws. A perfect correlation
        over nine points draws no counter-example, and reporting p = 0 for
        that claims more than a sample can support - it says the null was
        excluded rather than never observed."""
        from subversionbench.power import _PERMUTATION_DRAWS
        out = spearman(list(range(9)), list(range(9)))
        assert out["rho"] == 1.0
        assert out["p"] == pytest.approx(1 / (_PERMUTATION_DRAWS + 1))
        assert out["p"] > 0

    def test_it_reports_how_many_draws_stand_behind_the_p(self):
        """The exact branch reports the orderings it enumerated. This one
        has to report the draws instead, or a reader cannot tell a p that
        was counted from one that was sampled."""
        from subversionbench.power import _PERMUTATION_DRAWS
        out = spearman(list(range(9)), list(range(9)))
        assert out["n_permutations"] == _PERMUTATION_DRAWS

    def test_the_same_pairing_gives_the_same_p_every_time(self):
        """Seeded deliberately. A p-value that moved between two runs of the
        same analysis would make a reported figure irreproducible, which
        matters more here than the sampling error does."""
        xs, ys = list(range(9)), [3, 1, 4, 1, 5, 9, 2, 6, 5]
        assert spearman(xs, ys)["p"] == spearman(xs, ys)["p"]

    def test_an_arbitrary_pairing_is_not_separated_from_chance(self):
        """The other end of the range: the sampled branch has to be able to
        return a large p, not only a small one. A near-zero rho over nine
        points is what any pairing looks like."""
        out = spearman(list(range(9)), [5, 1, 8, 2, 9, 3, 7, 4, 6])
        assert out["method"] == "sampled_permutation"
        assert out["p"] > 0.05
        assert out["separated"] is False

    def test_a_constant_side_is_declined_before_any_sampling(self):
        """A variable that never varies is not a correlation of zero, and
        the check has to come first - permuting a constant column would
        otherwise spend 100,000 draws to discover the same thing."""
        out = spearman(list(range(9)), [7] * 9)
        assert out["rho"] is None and out["p"] is None
        assert out["method"] is None


class TestACorrelationRowCarriesItsOwnFragility:
    """rho over eight models is one model away from a different answer, so the
    leave-one-out range is not decoration - it is the number that says how
    much of the coefficient rests on any single point."""

    def _correlation(self, rho=0.71, loo=(0.44, 0.88), note=None):
        return {"measure": "aware", "variant": "plain", "n_models": 8,
                "spearman_rho": rho, "p": 0.0312,
                "leave_one_out_rho_range": list(loo) if loo else None,
                "note": note}

    def test_a_coefficient_is_printed_with_its_leave_one_out_range(self):
        printed = _print(_synthetic_report(
            correlations=[self._correlation()]))
        assert "rho=+0.710" in printed
        assert "p=0.0312" in printed
        assert "n=8" in printed
        assert "leave-one-out +0.440..+0.880" in printed

    def test_a_coefficient_with_no_range_still_prints_its_rho(self):
        printed = _print(_synthetic_report(
            correlations=[self._correlation(loo=None)]))
        assert "rho=+0.710" in printed
        assert "leave-one-out" not in printed

    def test_the_sensitivity_block_is_titled_apart_from_the_main_one(self):
        """Exact matches only is a different population from all pairs, and a
        reader comparing two rhos has to be able to tell which is which."""
        printed = _print(_synthetic_report(
            correlations=[self._correlation()],
            sensitivity=[self._correlation(rho=0.55, loo=None)]))
        assert "CORRELATIONS" in printed
        assert "EXACT MATCHES ONLY" in printed
        assert "rho=+0.550" in printed

    def test_an_absent_block_is_not_given_an_empty_heading(self):
        printed = _print(_synthetic_report(
            correlations=[self._correlation()]))
        assert "EXACT MATCHES ONLY" not in printed


class TestAPairThatIsNotOneCleanMatchSaysSo:
    """Eight points is few enough that one wrong match changes the sign of the
    answer, so the two ways a row can be less than a clean match - two local
    routes pooled into one point, and a name matched on a stem rather than
    exactly - are flagged on the row itself rather than left in the JSON."""

    def test_a_pooled_pair_says_how_many_routes_went_into_it(self):
        printed = _print(_synthetic_report(
            [_synthetic_pair(local_models=("a", "b"))]))
        assert "2 routes pooled" in printed

    def test_an_inexactly_matched_pair_says_so(self):
        printed = _print(_synthetic_report(
            [_synthetic_pair(confidence="name stem")]))
        assert "name stem match" in printed

    def test_a_clean_exact_pair_carries_no_flags(self):
        """Two-directional against both tests above: a flag on every row is a
        flag on none, since the reader stops seeing it."""
        printed = _print(_synthetic_report([_synthetic_pair()]))
        assert "Ext A" in printed, "the fixture printed no row at all"
        assert "pooled" not in printed
        assert "match]" not in printed and "[" not in printed


class TestTheReportNamesWhatItDidNotCompare:
    def test_a_deliberate_non_match_is_printed_with_its_reason(self):
        printed = _print(_synthetic_report(deliberately_unmatched=[
            {"local_model": "vendor/small", "reason": "not the row's model"}]))
        assert "NOT matched, on purpose" in printed
        assert "vendor/small: not the row's model" in printed

    def test_nothing_deliberately_unmatched_prints_no_heading(self):
        printed = _print(_synthetic_report())
        assert "NOT matched, on purpose" not in printed

    def test_leaderboard_rows_with_no_local_run_are_listed(self):
        printed = _print(_synthetic_report(
            unmatched_rows=[f"Row {i}" for i in range(1, 4)]))
        assert "3 leaderboard row(s) not evaluated here" in printed
        assert "Row 1, Row 2, Row 3" in printed
        assert "more" not in printed

    def test_a_long_list_is_truncated_and_says_how_many_it_hid(self):
        printed = _print(_synthetic_report(
            unmatched_rows=[f"Row {i}" for i in range(1, 11)]))
        assert "Row 6" in printed
        assert "Row 7" not in printed
        assert "and 4 more" in printed

    def test_no_unmatched_rows_prints_no_line_about_them(self):
        printed = _print(_synthetic_report())
        assert "not evaluated here" not in printed


class TestChartLabelsDoNotOverlap:
    """
    At seven or eight well-spread points a fixed offset above-right of each
    marker never collided. At eleven - once kimi-k3 joined the comparison at
    the same score range as three other models - four labels in the
    low-awareness cluster started overlapping each other on exactly the panels
    a reader most needs to tell grok-4.6 apart from gemini-3.5-flash apart from
    llama 4 maverick.
    """

    def _plt(self):
        if charting.import_pyplot() is None:
            from conftest import skip_without
            skip_without("matplotlib", "charts are an optional extra")
        return charting.import_pyplot()

    def test_a_lone_label_keeps_the_natural_offset(self):
        """No collision, no reason to move it."""
        plt = self._plt()
        fig, ax = plt.subplots()
        so._place_labels(fig, ax, [(50.0, 50.0, "only-model")])
        assert ax.texts[0].xyann == so._LABEL_OFFSETS[0]
        plt.close(fig)

    def test_four_points_at_nearly_the_same_spot_all_get_readable_labels(self):
        """The exact shape of the defect: several models within a couple of
        points of each other on both axes. Every label must end up somewhere,
        and no two may occupy the same pixels."""
        plt = self._plt()
        fig, ax = plt.subplots()
        points = [(65.0, 10.0 + i, f"model-{i}") for i in range(4)]
        for x, y, _t in points:
            ax.plot([x], [y], "o")
        so._place_labels(fig, ax, points)
        fig.canvas.draw()
        renderer = fig.canvas.get_renderer()
        boxes = [t.get_window_extent(renderer=renderer) for t in ax.texts]
        for i, a in enumerate(boxes):
            for b in boxes[i + 1:]:
                assert not a.overlaps(b)
        plt.close(fig)

    def test_widely_spaced_points_are_untouched(self):
        """The mechanism must not go looking for a collision that is not
        there - every point here is far enough apart to keep offset zero."""
        plt = self._plt()
        fig, ax = plt.subplots()
        points = [(x, x, f"model-{x}") for x in (10.0, 40.0, 70.0)]
        # Markers plotted first, same as write_chart: with none, the axes sit
        # at their default 0-1 view and every point maps off it, which put
        # spurious overlaps into an earlier version of this test.
        for x, y, _t in points:
            ax.plot([x], [y], "o")
        so._place_labels(fig, ax, points)
        assert all(t.xyann == so._LABEL_OFFSETS[0] for t in ax.texts)
        plt.close(fig)

    def test_every_point_gets_exactly_one_label(self):
        plt = self._plt()
        fig, ax = plt.subplots()
        points = [(65.0, 10.0 + i * 0.1, f"model-{i}") for i in range(6)]
        so._place_labels(fig, ax, points)
        assert len(ax.texts) == 6
        assert {t.get_text() for t in ax.texts} == {p[2] for p in points}
        plt.close(fig)


class TestTheChartIsLaidOutInThreeStackedPanels:
    """The three prompt variants read top to bottom - plain, then SP, then SP
    (large) - which is VARIANTS' own order, so a reader compares one model
    down a column rather than across a row."""

    def _report(self):
        return {
            "n_pairs": 3, "effort_agreement": {"note": "note"},
            "pairs": [
                {"sad_model": "a", "confidence": "exact",
                 "scores": {v: {"score": 50.0, "se": 2.0} for v in so.VARIANTS},
                 "aware_rate": 0.3, "aware_ci95": [0.2, 0.4]},
                {"sad_model": "b", "confidence": "exact",
                 "scores": {v: {"score": 60.0, "se": 2.0} for v in so.VARIANTS},
                 "aware_rate": 0.5, "aware_ci95": [0.4, 0.6]},
                {"sad_model": "c", "confidence": "exact",
                 "scores": {v: {"score": 70.0, "se": 2.0} for v in so.VARIANTS},
                 "aware_rate": 0.7, "aware_ci95": [0.6, 0.8]},
            ],
            "correlations": [
                {"measure": m, "variant": v, "spearman_rho": 0.5, "p": 0.5,
                 "note": None}
                for m in so.MEASURES for v in so.VARIANTS],
        }

    def test_the_chart_renders_without_error(self):
        if charting.import_pyplot() is None:
            from conftest import skip_without
            skip_without("matplotlib", "charts are an optional extra")
        with tempfile.TemporaryDirectory() as out:
            path = so.write_chart(self._report(), os.path.join(out, "c.png"))
            assert path and os.path.exists(path)

    def test_subplots_is_called_for_a_single_column_of_three_rows(self):
        """write_chart closes its figure before returning, so the geometry is
        checked from the source rather than from a live Axes object - the
        `plt.subplots(len(VARIANTS), 1, ...)` call is what fixes rows-not-
        columns, and a stray transpose back to (1, len(VARIANTS)) would not
        otherwise be caught by anything that inspects the saved image."""
        import inspect
        source = inspect.getsource(so.write_chart)
        assert "plt.subplots(len(VARIANTS), 1" in source

    def test_the_panel_order_is_plain_then_sp_then_sp_large(self):
        """Pinned on the constant the plotting loop actually iterates, since
        that is what determines top-to-bottom order for subplots(3, 1, ...)."""
        assert so.VARIANTS == ("plain", "sp", "sp_large")


class TestTheChartDegradesRatherThanFailing:
    def test_without_matplotlib_it_returns_none(self):
        original = charting.import_pyplot
        charting.import_pyplot = lambda *a, **k: None
        try:
            result = so.write_chart(_synthetic_report([_synthetic_pair()]),
                                    "/dev/null/unwritable.png")
        finally:
            charting.import_pyplot = original
        assert result is None

    def test_no_pairs_means_no_chart_rather_than_an_empty_one(self):
        """An empty three-panel figure is worse than no file: it reads as a
        correlation that was measured and found to be nothing."""
        if charting.import_pyplot() is None:
            from conftest import skip_without
            skip_without("matplotlib", "charts are an optional extra")
        assert so.write_chart(_synthetic_report([]),
                              "/dev/null/unwritable.png") is None

    def test_a_run_whose_chart_was_not_drawn_announces_no_file(self):
        """main asks for a chart and gets None back on a machine without
        matplotlib. It must still exit zero and write the JSON, without
        naming a png that is not there."""
        import sys as _sys
        import unittest.mock
        bundle = _bundle()
        locals_ = [m for a in bundle["aliases"] for m in a["local_models"]]
        buf = io.StringIO()
        saved = _sys.argv
        with tempfile.TemporaryDirectory() as out:
            for model in locals_[:4]:
                TestTheRunWritesWhatItSays()._corpus(out, model)
            _sys.argv = ["sad_oversight.py", "--output-dir", out]
            try:
                with contextlib.redirect_stdout(buf), \
                        unittest.mock.patch.object(so, "write_chart",
                                                   return_value=None):
                    code = so.main()
            finally:
                _sys.argv = saved
            written = [f for f in os.listdir(out)
                       if f.startswith("sad_oversight_correlation")]
        assert code == 0, buf.getvalue()
        assert written, "the JSON report was not written"
        assert "Chart written to" not in buf.getvalue()


class TestTheRunWritesWhatItSays:

    def _corpus(self, out, model):
        for oversight in ("oversight", "nooversight"):
            name = f"summary_{model.replace('/', '_')}_strong_{oversight}_20260101T000000.json"
            with open(os.path.join(out, name), "w") as f:
                json.dump({"model": model, "nudge": "strong", "n_runs": 10,
                           "n_scheming": 1, "n_misaligned": 2,
                           "awareness_subgroups": {"aware": 3, "unaware": 7}}, f)

    def test_the_json_lands_in_the_rollout_directory(self, monkeypatch):
        bundle = _bundle()
        locals_ = [m for a in bundle["aliases"] for m in a["local_models"]]
        with tempfile.TemporaryDirectory() as out:
            for model in locals_[:4]:
                self._corpus(out, model)
            monkeypatch.setattr("sys.argv",
                                ["sad_oversight.py", "--output-dir", out,
                                 "--no-charts"])
            assert so.main() == 0
            written = [f for f in os.listdir(out)
                       if f.startswith("sad_oversight_correlation")]
            assert len(written) == 1
            with open(os.path.join(out, written[0])) as f:
                report = json.load(f)
        assert report["rollout_version"]
        assert report["n_pairs"] >= 3
        assert report["correlations"]
        assert report["effort_agreement"]["note"]

    def test_a_corpus_with_no_overlap_exits_nonzero(self, monkeypatch):
        """Rather than writing a report whose every correlation is None."""
        with tempfile.TemporaryDirectory() as out:
            self._corpus(out, "nobody/nothing-1")
            monkeypatch.setattr("sys.argv",
                                ["sad_oversight.py", "--output-dir", out,
                                 "--no-charts"])
            assert so.main() == 1

    def test_the_chart_is_written_and_is_optional(self, monkeypatch):
        if charting.import_pyplot() is None:
            from conftest import skip_without
            skip_without("matplotlib", "charts are an optional extra")
        bundle = _bundle()
        locals_ = [m for a in bundle["aliases"] for m in a["local_models"]]
        with tempfile.TemporaryDirectory() as out:
            for model in locals_[:4]:
                self._corpus(out, model)
            monkeypatch.setattr("sys.argv",
                                ["sad_oversight.py", "--output-dir", out])
            assert so.main() == 0
            chart = os.path.join(out, "charts",
                                 "sad_oversight_correlation.png")
            assert os.path.exists(chart)

    def test_the_rollout_version_is_not_touched_by_any_of_this(self):
        """This is analysis over data already collected. Nothing here changes
        what a model saw, so no episode may fail to pool because of it."""
        source = Path(so.__file__).read_text()
        assert "ROLLOUT_VERSION =" not in source
