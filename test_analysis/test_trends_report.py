"""
The analysis half of the trends package: what a family did, and what the
report is allowed to say about it.

Nothing here draws. `trends/report.py` imports no drawing code and needs no
matplotlib, which is the property test_trends_layering.py guards and the reason
these tests can run on a machine without the charts extra.
"""


import json
import os
import tempfile
from datetime import date

import trends as ft
from test_analysis.report_fixtures import _write_summary


class TestTheVerdictSeparatesTwoClaims:
    """"The trend falls" and "every step falls" are different claims, and a
    family can satisfy the first without the second."""

    def _family(self, pairs, models=None):
        models = models or [f"p/m-{i}" for i in range(1, len(pairs) + 1)]
        parsed = [ft.parse_model_id(m) for m in models]
        rates = {m: {"x": x, "n": n, "rate": x / n if n else None,
                     "ci95": [0.0, 1.0], "underpowered": n < 20}
                 for m, (x, n) in zip(models, pairs, strict=True)}
        return ft.family_trend(parsed, rates, "misaligned", "component")

    def test_every_step_down_is_consistently_falling(self):
        out = self._family([(80, 100), (50, 100), (20, 100), (5, 100)])
        assert out["steps_summary"]["monotone_falling"] is True
        assert out["verdict"].startswith("CONSISTENTLY FALLING")

    def test_every_step_up_says_the_opposite(self):
        out = self._family([(1, 100), (13, 100), (15, 100)])
        assert out["steps_summary"]["monotone_rising"] is True
        assert "RISING" in out["verdict"]

    def test_a_falling_trend_with_one_step_up_is_not_consistent(self):
        """The gemini-flash shape: up then sharply down twice."""
        out = self._family([(68, 100), (82, 100), (13, 100), (6, 100)])
        assert out["steps_summary"]["monotone_falling"] is False
        assert out["trend"]["direction"] == "falling"
        assert out["verdict"].startswith("NOT consistent")
        assert "falling" in out["verdict"]

    def test_steps_and_first_vs_last_can_disagree(self):
        """grok under `component`: two of three steps fall, yet the last
        version sits ABOVE the first."""
        out = self._family([(0, 120), (207, 239), (49, 120), (8, 120)])
        assert out["steps_summary"]["n_down"] == 2
        assert out["first_vs_last"]["difference"] > 0

    def test_a_two_member_family_still_reports_one_step(self):
        out = self._family([(52, 120), (62, 119)])
        assert out["steps_summary"]["n_steps"] == 1
        assert out["n_members"] == 2

    def test_a_family_with_no_variation_is_not_a_trend_of_zero(self):
        out = self._family([(0, 100), (0, 100)])
        assert out["trend"]["z"] is None
        assert out["trend"]["note"]


class TestAStepWithNothingOnOneSideIsNotAStepOfZero:
    """A member with no episodes has no rate. The step into it and the step
    out of it are not differences of zero - they are comparisons that did not
    happen - and the first-versus-last contrast that spans them is not a null
    result either."""

    def _family(self, pairs):
        models = [f"p/m-{i}" for i in range(1, len(pairs) + 1)]
        parsed = [ft.parse_model_id(m) for m in models]
        rates = {m: {"x": x, "n": n, "rate": x / n if n else None,
                     "ci95": [0.0, 1.0], "underpowered": n < 20}
                 for m, (x, n) in zip(models, pairs, strict=True)}
        return ft.family_trend(parsed, rates, "misaligned", "component")

    def test_a_step_into_an_empty_member_says_so(self):
        out = self._family([(20, 100), (0, 0), (5, 100)])
        notes = [s.get("note") for s in out["steps"]]
        assert notes == ["one side has no data", "one side has no data"]
        assert all(s["difference"] is None for s in out["steps"]), (
            "a comparison that did not happen was reported as a difference")

    def test_a_first_or_last_with_no_episodes_leaves_no_contrast(self):
        out = self._family([(20, 100), (5, 100), (0, 0)])
        assert out["first_vs_last"] is None, (
            "the span contrast was computed against a member with nothing "
            "in it")

    def test_a_family_with_episodes_throughout_does_get_both(self):
        """The control for both."""
        out = self._family([(20, 100), (5, 100)])
        assert out["first_vs_last"] is not None
        assert all(s.get("note") != "one side has no data"
                   for s in out["steps"])


class TestTheReportEndToEnd:
    def _corpus(self, out):
        """Two families, one falling at every step and one rising."""
        for model, misaligned in (("p/fall-1", 8), ("p/fall-2", 5),
                                  ("p/fall-3", 1),
                                  ("p/rise-1", 1), ("p/rise-2", 6)):
            _write_summary(out, model, "strong", n_runs=10,
                           n_misaligned=misaligned, n_scheming=1,
                           n_aware=2, n_unaware=8)
        return out

    def test_families_are_found_and_ordered(self):
        with tempfile.TemporaryDirectory() as out:
            report = ft.build_report(self._corpus(out))
            keys = [f["family"] for f in report["families"]]
            assert keys == ["p/fall", "p/rise"]
            assert report["families"][0]["version_order"] == [
                "p/fall-1", "p/fall-2", "p/fall-3"]

    def test_the_two_verdicts_are_opposite(self):
        with tempfile.TemporaryDirectory() as out:
            report = ft.build_report(self._corpus(out))
            fall, rise = report["families"]
            assert fall["steps_summary"]["monotone_falling"] is True
            assert rise["steps_summary"]["monotone_rising"] is True

    def test_the_across_family_block_counts_steps(self):
        with tempfile.TemporaryDirectory() as out:
            report = ft.build_report(self._corpus(out))
            overall = report["across_all_families"]
            assert overall["n_down"] == 2 and overall["n_up"] == 1
            assert overall["n_families_monotone_falling"] == 1
            assert overall["n_families_monotone_rising"] == 1

    def test_trend_pvalues_are_corrected_across_families(self):
        with tempfile.TemporaryDirectory() as out:
            report = ft.build_report(self._corpus(out))
            for family in report["families"]:
                if family["trend"]["p"] is not None:
                    assert "holm_p" in family["trend"]
                    assert "bh_p" in family["trend"]

    def test_an_act_derived_metric_is_declared_safe(self):
        """Misalignment comes from the act keys, so a batch whose grading failed
        still carries a sound figure; scheming does not."""
        with tempfile.TemporaryDirectory() as out:
            self._corpus(out)
            assert ft.build_report(out, "misaligned")[
                "data_quality"]["metric_is_llm_dependent"] is False
            assert ft.build_report(out, "scheming")[
                "data_quality"]["metric_is_llm_dependent"] is True

    def test_models_outside_a_family_are_named_not_dropped(self):
        with tempfile.TemporaryDirectory() as out:
            self._corpus(out)
            _write_summary(out, "p/lonely-1", "strong", n_runs=10,
                           n_misaligned=3)
            dq = ft.build_report(out)["data_quality"]
            assert "p/lonely-1" in dq["models_without_a_family"]
            assert dq["n_models_in_a_family"] == 5

    def test_a_thin_denominator_is_flagged(self):
        with tempfile.TemporaryDirectory() as out:
            for model in ("p/thin-1", "p/thin-2"):
                _write_summary(out, model, "strong", n_runs=5, n_misaligned=1)
            dq = ft.build_report(out)["data_quality"]
            assert dq["models_below_informative_denominator"] == [
                "p/thin-1", "p/thin-2"]

    def test_an_empty_directory_reports_no_families(self):
        with tempfile.TemporaryDirectory() as out:
            report = ft.build_report(out)
            assert report["families"] == []

    def test_the_report_prints_and_serialises(self):
        import contextlib
        import io
        with tempfile.TemporaryDirectory() as out:
            report = ft.build_report(self._corpus(out))
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                ft._print_report(report)
            printed = buf.getvalue()
            assert "ACROSS ALL FAMILIES" in printed
            assert "DATA QUALITY" in printed
            # A report that cannot be written is not a report.
            json.dumps(report)


class TestTheReportCarriesTheReleaseDate:
    def test_every_member_holds_its_release_date(self):
        with tempfile.TemporaryDirectory() as out:
            _write_summary(out, "x-ai/grok-4.5", "strong", n_runs=10)
            _write_summary(out, "x-ai/grok-4.6", "strong", n_runs=10)
            members = ft.build_report(out)["families"][0]["members"]
            assert [m["released"] for m in members] == ["2026-07-08",
                                                        "2026-08-12"]

    def test_an_unrecorded_model_carries_none_rather_than_a_guess(self):
        with tempfile.TemporaryDirectory() as out:
            _write_summary(out, "p/fall-1", "strong", n_runs=10)
            _write_summary(out, "p/fall-2", "strong", n_runs=10)
            members = ft.build_report(out)["families"][0]["members"]
            assert [m["released"] for m in members] == [None, None]

    def test_the_stamp_in_the_id_is_not_confused_with_the_release_date(self):
        """`date` is parsed out of the ID and says nothing about when the model
        shipped; `released` is the recorded date. deepseek-v4-pro-0813 was
        listed on the 12th, not the 13th."""
        with tempfile.TemporaryDirectory() as out:
            _write_summary(out, "deepseek/deepseek-v4-pro", "strong", n_runs=10)
            _write_summary(out, "deepseek/deepseek-v4-pro-0813", "strong",
                           n_runs=10)
            members = ft.build_report(out)["families"][0]["members"]
            assert members[1]["date"] == "0813"
            assert members[1]["released"] == "2026-08-12"

    def test_the_release_date_survives_the_json_round_trip(self):
        with tempfile.TemporaryDirectory() as out:
            _write_summary(out, "x-ai/grok-4.5", "strong", n_runs=10)
            _write_summary(out, "x-ai/grok-4.6", "strong", n_runs=10)
            loaded = json.loads(json.dumps(ft.build_report(out)))
            assert loaded["families"][0]["members"][0]["released"] == (
                "2026-07-08")


class TestTheReleaseFit:
    """
    The straight dotted line, one per family. Descriptive: it says how fast in
    time, which the position axis cannot, and it carries no p-value because the
    trend test in this file already runs on version position.
    """

    def _member(self, released, rate, n=120):
        return {"released": released, "rate": rate, "n": n}

    def test_a_rising_family_gets_a_positive_slope(self):
        fit = ft.release_fit([self._member("2026-01-01", 0.10),
                              self._member("2026-04-01", 0.20),
                              self._member("2026-07-01", 0.40)])
        assert fit["slope_per_month"] > 0

    def test_a_falling_family_gets_a_negative_slope(self):
        fit = ft.release_fit([self._member("2025-12-17", 0.683),
                              self._member("2026-05-19", 0.824),
                              self._member("2026-07-21", 0.127),
                              self._member("2026-08-13", 0.058)])
        assert fit["slope_per_month"] < 0

    def test_the_line_spans_the_family_not_the_axis(self):
        """Extending it across months in which the family shipped nothing would
        draw a claim about models that do not exist."""
        fit = ft.release_fit([self._member("2026-03-31", 0.067),
                              self._member("2026-08-12", 0.408)])
        assert fit["from"]["released"] == "2026-03-31"
        assert fit["to"]["released"] == "2026-08-12"
        assert fit["span_days"] == 134

    def test_the_slope_is_reported_per_month_not_per_year(self):
        """grok's four releases span 134 days, and per year its fit reads +197.9
        points - a rise no rate can make. A month is the largest unit no family
        in this corpus outruns."""
        fit = ft.release_fit([self._member("2026-03-31", 0.0),
                              self._member("2026-04-30", 0.10)])
        assert "slope_per_year" not in fit
        assert abs(fit["slope_per_month"] - 0.10) < 0.01

    def test_a_heavier_denominator_pulls_the_line(self):
        """gemini-3.5-flash carries 205 episodes against its siblings' 120, and
        an unweighted fit would treat them as equals."""
        # Exactly 60 days apart each: calendar months are not equal, and
        # Jan-Apr-Jul is 90 days then 91, which is enough to tilt the "even"
        # fit off zero and make this test look like it had caught something.
        even = ft.release_fit([self._member("2026-01-01", 0.0, 120),
                               self._member("2026-03-02", 0.6, 120),
                               self._member("2026-05-01", 0.0, 120)])
        pulled = ft.release_fit([self._member("2026-01-01", 0.0, 120),
                                 self._member("2026-03-02", 0.6, 120),
                                 self._member("2026-05-01", 0.0, 2000)])
        assert abs(even["slope_per_month"]) < 1e-9
        assert pulled["slope_per_month"] < 0
        assert even["weighted_by"] == "episodes"

    def test_two_points_are_fitted_but_flagged(self):
        """Two points determine a line exactly, so the fit repeats them and adds
        nothing. Said rather than left for the reader to notice."""
        fit = ft.release_fit([self._member("2026-04-24", 0.22),
                              self._member("2026-07-31", 0.35)])
        assert fit["n_points"] == 2
        assert "exact" in fit["note"]

    def test_three_points_carry_no_such_note(self):
        fit = ft.release_fit([self._member("2026-01-27", 0.01),
                              self._member("2026-04-20", 0.13),
                              self._member("2026-07-16", 0.15)])
        assert fit["note"] is None

    def test_one_dated_member_is_no_fit_at_all(self):
        assert ft.release_fit([self._member("2026-01-01", 0.1),
                               {"released": None, "rate": 0.2, "n": 120}]) is None

    def test_a_family_released_on_one_day_has_no_slope_in_time(self):
        """The three gpt-5.6 variants shipped together. They are separate
        families here, but the shape is one a future family could take."""
        fit = ft.release_fit([self._member("2026-07-09", 0.1),
                              self._member("2026-07-09", 0.5)])
        assert fit["slope_per_month"] is None
        assert "same x" in fit["note"]

    def test_a_member_with_no_rate_is_not_fitted_as_zero(self):
        """No episodes is not a rate of zero."""
        fit = ft.release_fit([self._member("2026-01-01", 0.2),
                              self._member("2026-04-01", 0.4),
                              {"released": "2026-07-01", "rate": None, "n": 0}])
        assert fit["n_points"] == 2

    def test_the_report_carries_the_fit_so_the_chart_cannot_disagree(self):
        with tempfile.TemporaryDirectory() as out:
            _write_summary(out, "x-ai/grok-4.5", "strong", n_runs=10,
                           n_misaligned=2)
            _write_summary(out, "x-ai/grok-4.6", "strong", n_runs=10,
                           n_misaligned=6)
            loaded = json.loads(json.dumps(ft.build_report(out)))
            fit = loaded["families"][0]["release_fit"]
            assert fit["slope_per_month"] > 0
            assert fit["from"]["released"] == "2026-07-08"

    def test_an_undated_family_carries_no_fit_and_still_reports(self):
        with tempfile.TemporaryDirectory() as out:
            _write_summary(out, "p/fall-1", "strong", n_runs=10, n_misaligned=8)
            _write_summary(out, "p/fall-2", "strong", n_runs=10, n_misaligned=2)
            family = ft.build_report(out)["families"][0]
            assert family["release_fit"] is None
            assert family["trend"]["z"] is not None

    def test_the_printed_report_states_the_slope_and_calls_it_descriptive(self):
        """The chart is a second reading of a number the report already holds,
        which is the rule the rest of this file follows."""
        import contextlib
        import io
        with tempfile.TemporaryDirectory() as out:
            _write_summary(out, "x-ai/grok-4.5", "strong", n_runs=10,
                           n_misaligned=2)
            _write_summary(out, "x-ai/grok-4.6", "strong", n_runs=10,
                           n_misaligned=6)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                ft._print_report(ft.build_report(out))
            printed = buf.getvalue()
            assert "release-date fit" in printed
            assert "no p-value" in printed
            assert "points/month" in printed


class TestTheReleaseSpan:
    def _report(self, *dates):
        return {"families": [{"members": [{"released": d} for d in dates]}]}

    def test_it_runs_from_the_floor_to_the_newest_model(self):
        span = ft.release_span(self._report("2026-01-27", "2026-04-20"))
        assert span == (ft.RELEASE_AXIS_START, date(2026, 4, 20))

    def test_the_floor_does_not_clip_the_earliest_model_in_this_corpus(self):
        """The floor is only useful while it stays behind every plotted point.
        r9's earliest family member is kimi-k2-thinking on 2025-11-06, so a
        floor later than that would push a real point off the axis - and
        release_span would silently drag it back, undoing the setting."""
        assert ft.RELEASE_AXIS_START <= date(2025, 11, 6)

    def test_the_start_is_fixed_rather_than_the_earliest_model(self):
        """Otherwise adding an older model silently rescales every chart in the
        corpus and changes what the spacing looks like."""
        span = ft.release_span(self._report("2026-06-01"))
        assert span[0] == ft.RELEASE_AXIS_START

    def test_a_model_older_than_the_floor_still_fits_on_the_axis(self):
        """The floor is a default, not a clip: a point drawn outside the axis is
        worse than an axis that starts earlier than asked for."""
        span = ft.release_span(self._report("2024-03-01", "2026-06-01"))
        assert span[0] == date(2024, 3, 1)

    def test_no_recorded_date_anywhere_is_none_rather_than_an_empty_axis(self):
        assert ft.release_span(self._report(None, None)) is None
        assert ft.release_span({"families": []}) is None

    def test_a_corpus_entirely_older_than_the_floor_gets_a_usable_width(self):
        """matplotlib cannot draw a zero-width or inverted axis."""
        span = ft.release_span(self._report("2024-03-01"))
        assert span[1] > span[0]

    def test_a_malformed_stamp_is_dropped_rather_than_raised(self):
        """A chart must never be the thing that stops the analysis."""
        assert ft._member_release_date({"released": "not-a-date"}) is None
        assert ft._member_release_date({}) is None


class TestAMissingReleaseDateIsAnErrorNotAStop:
    """
    Every rate, interval, trend and p-value here is computed from version
    order. A missing release date costs the release charts and nothing else, so
    it is reported loudly and then worked around.
    """

    def _undated_corpus(self, out):
        for model, misaligned in (("p/fall-1", 8), ("p/fall-2", 5)):
            _write_summary(out, model, "strong", n_runs=10,
                           n_misaligned=misaligned, n_scheming=1,
                           n_aware=2, n_unaware=8)
        return out

    def test_the_report_names_every_model_it_has_no_date_for(self):
        with tempfile.TemporaryDirectory() as out:
            dq = ft.build_report(self._undated_corpus(out))["data_quality"]
            assert dq["models_without_release_date"] == ["p/fall-1", "p/fall-2"]

    def test_a_recorded_date_does_not_appear_in_that_list(self):
        with tempfile.TemporaryDirectory() as out:
            _write_summary(out, "x-ai/grok-4.5", "strong", n_runs=10)
            _write_summary(out, "x-ai/grok-4.6", "strong", n_runs=10)
            dq = ft.build_report(out)["data_quality"]
            assert dq["models_without_release_date"] == []
            assert dq["plotted_models_without_release_date"] == []

    def test_an_undated_singleton_is_separated_from_an_undated_family_member(self):
        """A singleton is in no family and therefore on no chart, so its
        missing date costs nothing. The distinction is what stops the error
        line from overstating the damage."""
        with tempfile.TemporaryDirectory() as out:
            self._undated_corpus(out)
            _write_summary(out, "p/lonely-1", "strong", n_runs=10)
            dq = ft.build_report(out)["data_quality"]
            assert "p/lonely-1" in dq["models_without_release_date"]
            assert "p/lonely-1" not in dq["plotted_models_without_release_date"]

    def test_the_error_is_printed_and_names_the_fix(self):
        import contextlib
        import io
        with tempfile.TemporaryDirectory() as out:
            report = ft.build_report(self._undated_corpus(out))
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                ft._print_report(report)
            printed = buf.getvalue()
            assert "ERROR" in printed
            assert "model_releases.py" in printed
            assert "p/fall-1" in printed

    def test_the_analysis_still_runs_and_still_succeeds(self):
        """The whole point: an unrecorded date must not cost a single figure."""
        import contextlib
        import io
        import sys
        with tempfile.TemporaryDirectory() as out:
            argv = sys.argv
            sys.argv = ["family_trends.py", "--output-dir",
                        self._undated_corpus(out)]
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    assert ft.main() == 0
            finally:
                sys.argv = argv
            report = ft.build_report(out)
            assert report["families"][0]["trend"]["p"] is not None

    def test_a_family_with_one_undated_member_still_gets_a_chart(self):
        """Three of four versions is still worth drawing, as long as the chart
        says it is three of four."""
        from conftest import skip_without
        skip_without("matplotlib", "charts are an optional extra")
        with tempfile.TemporaryDirectory() as out:
            _write_summary(out, "x-ai/grok-4.5", "strong", n_runs=10)
            _write_summary(out, "x-ai/grok-4.6", "strong", n_runs=10)
            _write_summary(out, "x-ai/grok-9.9", "strong", n_runs=10)
            report = ft.build_report(out)
            family = report["families"][0]
            assert family["n_members"] == 3
            assert len(ft._dated_members(family)) == 2
            written = ft.write_charts(report, os.path.join(out, "charts"))
            assert any("release_misaligned_x-ai_grok.png" in p for p in written)
