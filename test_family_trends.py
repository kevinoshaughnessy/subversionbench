"""
family_trends.py: deriving model families from IDs, and trending along them.

The families are never enumerated, so the parse IS the feature - a rule that is
wrong about one ID puts a model in the wrong family, or in none, and the report
is quietly narrower than the corpus rather than visibly broken. These tests pin
every real ID in the r9 corpus and the shapes a future one is likely to take.
"""

import json
import os
import tempfile

import family_trends as ft
from test_run_report import _write_summary


class TestParsingRealModelIds:
    """Every ID below is one the corpus actually holds."""

    def test_a_dotted_version_splits_from_its_stem(self):
        parsed = ft.parse_model_id("x-ai/grok-4.5")
        assert parsed.provider == "x-ai"
        assert parsed.stem == "grok"
        assert parsed.version == (4, 5)

    def test_a_version_glued_to_the_stem_is_split(self):
        """qwen3.8-27b and hy3 carry the version inside the word."""
        assert ft.parse_model_id("tencent/hy3").version == (3,)
        assert ft.parse_model_id("tencent/hy3").stem == "hy"
        parsed = ft.parse_model_id("qwen/qwen3.8-27b")
        assert parsed.version == (3, 8)
        # A parameter count is family identity, not a version.
        assert parsed.stem == "qwen-27b"

    def test_a_leading_v_is_not_part_of_the_stem(self):
        """Otherwise deepseek-v4-pro and a future deepseek-5-pro are two
        families that never get compared."""
        assert ft.parse_model_id("deepseek/deepseek-v4-pro").stem == (
            "deepseek-pro")
        assert ft.parse_model_id("deepseek/deepseek-v4-pro").version == (4,)

    def test_dash_separated_version_components_merge(self):
        """Anthropic writes with dashes what everyone else writes with dots, so
        claude-haiku-4-5 is version (4, 5) and not two versions."""
        parsed = ft.parse_model_id("claude-haiku-4-5-20251001")
        assert parsed.version == (4, 5)
        assert parsed.stem == "claude-haiku"

    def test_a_date_stamp_is_not_a_version_component(self):
        """The regression: the version pattern matches a run of digits, so
        checking it first parsed deepseek-v4-pro-0813 as version (4, 813) -
        sorting it after a hypothetical v4.99 - and claude-haiku-4-5-20251001
        as version (4, 5, 20251001)."""
        parsed = ft.parse_model_id("deepseek/deepseek-v4-pro-0813")
        assert parsed.version == (4,), "0813 must not become a version part"
        assert parsed.date == "0813"
        assert ft.parse_model_id("claude-haiku-4-5-20251001").date == "20251001"
        assert ft.parse_model_id(
            "mistralai/mistral-small-2603").date == "2603"

    def test_a_single_digit_is_a_version_not_a_date(self):
        assert ft.parse_model_id("google/gemini-3-flash-preview").version == (3,)
        assert ft.parse_model_id("google/gemini-3-flash-preview").date is None

    def test_a_release_stage_word_becomes_a_tag(self):
        for model, tag in (("google/gemini-3-flash-preview", "preview"),
                           ("moonshotai/kimi-k2-thinking", "thinking")):
            parsed = ft.parse_model_id(model)
            assert parsed.tags == (tag,), model
            assert tag not in parsed.stem, model

    def test_an_id_with_no_version_parses_without_one(self):
        parsed = ft.parse_model_id("thinkingmachines/inkling-small")
        assert parsed.version == ()
        assert parsed.stem == "inkling-small"


class TestWhichModelsShareAFamily:
    def test_the_four_families_the_corpus_holds(self):
        expected = {
            "x-ai/grok": {"x-ai/grok-4.20", "x-ai/grok-4.3", "x-ai/grok-4.5",
                          "x-ai/grok-4.6"},
            "moonshotai/kimi-k": {"moonshotai/kimi-k2-thinking",
                                  "moonshotai/kimi-k2.5",
                                  "moonshotai/kimi-k2.6"},
            "deepseek/deepseek-pro": {"deepseek/deepseek-v4-pro",
                                      "deepseek/deepseek-v4-pro-0813"},
            "google/gemini-flash": {"google/gemini-3-flash-preview",
                                    "google/gemini-3.5-flash",
                                    "google/gemini-3.6-flash",
                                    "google/gemini-3.7-flash"},
        }
        for model in sorted({m for ms in expected.values() for m in ms}):
            key = ft.family_key(ft.parse_model_id(model))
            assert model in expected[key], f"{model} landed in {key}"

    def test_a_tier_word_does_split_a_family(self):
        """gemini-3.1-flash-lite is not a version of gemini-3.5-flash, and
        pooling them would compare two product lines and call it a trend."""
        lite = ft.family_key(ft.parse_model_id("google/gemini-3.1-flash-lite"))
        flash = ft.family_key(ft.parse_model_id("google/gemini-3.5-flash"))
        assert lite != flash
        pro = ft.family_key(ft.parse_model_id("deepseek/deepseek-v4-pro"))
        dsflash = ft.family_key(
            ft.parse_model_id("deepseek/deepseek-v4-flash-0731"))
        assert pro != dsflash

    def test_the_route_does_not_get_pooled_with_the_model(self):
        """gpt-5.6-luna and openai/gpt-5.6-luna are one model on two routes,
        which differ in how much reasoning they return - pooling them would
        compare instruments."""
        assert (ft.family_key(ft.parse_model_id("gpt-5.6-luna"))
                != ft.family_key(ft.parse_model_id("openai/gpt-5.6-luna")))

    def test_a_future_version_needs_no_change_here(self):
        """The whole point of deriving rather than listing."""
        models = ["google/gemini-3.5-flash", "google/gemini-3.6-flash",
                  "google/gemini-3.7-flash", "google/gemini-3.8-flash"]
        families = ft.group_families(models, "component")
        assert list(families) == ["google/gemini-flash"]
        assert [m.raw for m in families["google/gemini-flash"]] == models

    def test_a_lone_model_is_not_a_family(self):
        assert ft.group_families(["a/x-1", "b/y-2"], "component") == {}


class TestVersionOrdering:
    def test_a_minor_sorts_numerically(self):
        models = ["google/gemini-3.7-flash", "google/gemini-3-flash-preview",
                  "google/gemini-3.5-flash", "google/gemini-3.6-flash"]
        order = [m.raw for m in ft.group_families(
            models, "component")["google/gemini-flash"]]
        assert order == ["google/gemini-3-flash-preview",
                         "google/gemini-3.5-flash",
                         "google/gemini-3.6-flash",
                         "google/gemini-3.7-flash"]

    def test_a_dated_snapshot_follows_the_undated_one(self):
        models = ["deepseek/deepseek-v4-pro-0813", "deepseek/deepseek-v4-pro"]
        order = [m.raw for m in ft.group_families(
            models, "component")["deepseek/deepseek-pro"]]
        assert order == ["deepseek/deepseek-v4-pro",
                         "deepseek/deepseek-v4-pro-0813"]

    def test_the_two_styles_disagree_only_on_a_trailing_zero(self):
        """4.20 is major 4 minor 20 under `component`, so after 4.6; and 4.2
        under `decimal`, so before 4.3. Both are defensible."""
        models = ["x-ai/grok-4.20", "x-ai/grok-4.3", "x-ai/grok-4.5",
                  "x-ai/grok-4.6"]
        component = [m.raw for m in ft.group_families(
            models, "component")["x-ai/grok"]]
        decimal = [m.raw for m in ft.group_families(
            models, "decimal")["x-ai/grok"]]
        assert component[-1] == "x-ai/grok-4.20"
        assert decimal[0] == "x-ai/grok-4.20"

    def test_the_default_reads_a_version_as_a_decimal(self):
        """grok-4.20 is an OLDER release than grok-4.3, so 4.20 means 4.2 and
        not major-4-minor-20. The package-manager reading was the original
        default; it put 4.20 at the end of its family and reversed the sign of
        the family's trend, from falling to rising."""
        models = ["x-ai/grok-4.5", "x-ai/grok-4.20", "x-ai/grok-4.6",
                  "x-ai/grok-4.3"]
        expected = ["x-ai/grok-4.20", "x-ai/grok-4.3", "x-ai/grok-4.5",
                    "x-ai/grok-4.6"]
        assert [m.raw for m in ft.group_families(
            models, "decimal")["x-ai/grok"]] == expected
        # And by the default, reached without naming a style at all.
        assert [m.raw for m in sorted(
            [ft.parse_model_id(m) for m in models],
            key=ft.version_sort_key)] == expected

    def test_the_default_still_puts_a_future_minor_last(self):
        """The reason `component` was the original default: 3.8 must land after
        3.7, not between 3.1 and 3.5. Reading as a decimal does that too."""
        models = ["google/gemini-3.1-flash", "google/gemini-3.7-flash",
                  "google/gemini-3.8-flash", "google/gemini-3.5-flash"]
        assert [m.raw for m in sorted(
            [ft.parse_model_id(m) for m in models],
            key=ft.version_sort_key)] == [
                "google/gemini-3.1-flash", "google/gemini-3.5-flash",
                "google/gemini-3.7-flash", "google/gemini-3.8-flash"]

    def test_the_build_and_the_cli_agree_on_the_default(self):
        """A default that differs between the library call and the flag would
        make the JSON disagree with the chart beside it."""
        import inspect
        assert inspect.signature(
            ft.build_report).parameters["style"].default == "decimal"
        assert 'default="decimal"' in inspect.getsource(ft.main)

    def test_the_disagreement_is_detected(self):
        grok = [ft.parse_model_id(m) for m in
                ("x-ai/grok-4.20", "x-ai/grok-4.3", "x-ai/grok-4.6")]
        assert ft.ordering_is_ambiguous(grok) is True

    def test_an_unambiguous_family_is_not_flagged(self):
        gemini = [ft.parse_model_id(m) for m in
                  ("google/gemini-3.5-flash", "google/gemini-3.6-flash",
                   "google/gemini-3.7-flash")]
        assert ft.ordering_is_ambiguous(gemini) is False


class TestTheVerdictSeparatesTwoClaims:
    """"The trend falls" and "every step falls" are different claims, and a
    family can satisfy the first without the second."""

    def _family(self, pairs, models=None):
        models = models or [f"p/m-{i}" for i in range(1, len(pairs) + 1)]
        parsed = [ft.parse_model_id(m) for m in models]
        rates = {m: {"x": x, "n": n, "rate": x / n if n else None,
                     "ci95": [0.0, 1.0], "underpowered": n < 20}
                 for m, (x, n) in zip(models, pairs)}
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


class TestTheCharts:
    """Every figure plotted is already in the table and the JSON, so a chart is a
    second reading of the same numbers. That is why matplotlib is an optional
    extra and why its absence must degrade rather than fail."""

    def _skip_without_matplotlib(self):
        try:
            import matplotlib  # noqa: F401 - presence check only
        except ImportError:
            import pytest
            pytest.skip("matplotlib not installed")

    def _corpus(self, out):
        for model, misaligned in (("p/fall-1", 8), ("p/fall-2", 5),
                                  ("p/fall-3", 1),
                                  ("p/rise-1", 1), ("p/rise-2", 6)):
            _write_summary(out, model, "strong", n_runs=10,
                           n_misaligned=misaligned, n_scheming=1,
                           n_aware=2, n_unaware=8)
        return out

    def test_one_chart_per_family_plus_one_combined(self):
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


class TestWhereTheJsonGoes:
    """Two metrics of one corpus are two different reports. A directory of
    timestamped files gives no way to tell which is which without opening
    them - and the charts already name their metric, so the JSON beside them
    reading only `family_trends_<timestamp>` was the odd one out."""

    def _corpus(self, out):
        for model, misaligned in (("p/fall-1", 8), ("p/fall-2", 5),
                                  ("p/rise-1", 1), ("p/rise-2", 6)):
            _write_summary(out, model, "strong", n_runs=10,
                           n_misaligned=misaligned, n_scheming=1,
                           n_aware=2, n_unaware=8)
        return out

    def _run(self, out, *extra):
        import contextlib
        import io
        import sys
        argv = sys.argv
        sys.argv = ["family_trends.py", "--output-dir", out, "--no-charts",
                    *extra]
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                assert ft.main() == 0
        finally:
            sys.argv = argv
        return sorted(f for f in os.listdir(out)
                      if f.startswith("family_trends_"))

    def test_the_metric_is_in_the_default_filename(self):
        with tempfile.TemporaryDirectory() as out:
            written = self._run(self._corpus(out), "--metric", "aware")
            assert len(written) == 1
            assert written[0].startswith("family_trends_aware_")
            assert written[0].endswith(".json")

    def test_two_metrics_do_not_overwrite_each_other(self):
        with tempfile.TemporaryDirectory() as out:
            self._corpus(out)
            self._run(out, "--metric", "misaligned")
            written = self._run(out, "--metric", "scheming")
            assert len(written) == 2
            assert any("_misaligned_" in f for f in written)
            assert any("_scheming_" in f for f in written)

    def test_an_explicit_json_out_still_wins(self):
        with tempfile.TemporaryDirectory() as out:
            self._corpus(out)
            target = os.path.join(out, "named.json")
            self._run(out, "--json-out", target)
            assert os.path.exists(target)
            with open(target) as f:
                assert json.load(f)["metric"] == "misaligned"

    def test_the_default_matches_what_the_help_promises(self):
        """The help lives in main; the filename is built one call down, where
        `--metric all` loops over it."""
        import inspect
        assert "family_trends_<metric>_<timestamp>.json" in inspect.getsource(
            ft.main)
        assert 'f"family_trends_{metric}_' in inspect.getsource(
            ft._report_one_metric)


class TestRunningEveryMetric:
    """`--metric all` expands into ordinary single-metric runs rather than
    growing a second implementation beside them."""

    def _corpus(self, out):
        for model, misaligned in (("p/fall-1", 8), ("p/fall-2", 5),
                                  ("p/rise-1", 1), ("p/rise-2", 6)):
            _write_summary(out, model, "strong", n_runs=10,
                           n_misaligned=misaligned, n_scheming=1,
                           n_aware=2, n_unaware=8)
        return out

    def _run(self, out, *extra):
        import contextlib
        import io
        import sys
        argv = sys.argv
        sys.argv = ["family_trends.py", "--output-dir", out, "--no-charts",
                    *extra]
        try:
            with contextlib.redirect_stdout(io.StringIO()) as buf:
                code = ft.main()
        finally:
            sys.argv = argv
        return code, buf.getvalue(), sorted(
            f for f in os.listdir(out) if f.startswith("family_trends_"))

    def test_all_is_not_itself_a_metric(self):
        """It is expanded by the loop, never looked up as one."""
        assert ft.METRIC_ALL not in ft.METRICS

    def test_it_writes_one_report_per_metric(self):
        with tempfile.TemporaryDirectory() as out:
            code, _printed, written = self._run(self._corpus(out),
                                                "--metric", "all")
            assert code == 0
            assert len(written) == len(ft.METRICS)
            for metric in ft.METRICS:
                assert any(f"_{metric}_" in name for name in written), metric

    def test_the_reports_share_one_timestamp(self):
        """A single run should sort together, not be split by however long it
        took to produce."""
        with tempfile.TemporaryDirectory() as out:
            _code, _printed, written = self._run(self._corpus(out),
                                                 "--metric", "all")
            stamps = {name.rsplit("_", 1)[1] for name in written}
            assert len(stamps) == 1

    def test_each_metric_is_announced(self):
        with tempfile.TemporaryDirectory() as out:
            _code, printed, _written = self._run(self._corpus(out),
                                                 "--metric", "all")
            for metric in ft.METRICS:
                assert f"# metric: {metric}" in printed, metric

    def test_each_report_carries_its_own_metric(self):
        with tempfile.TemporaryDirectory() as out:
            _code, _printed, written = self._run(self._corpus(out),
                                                 "--metric", "all")
            for name in written:
                with open(os.path.join(out, name)) as f:
                    report = json.load(f)
                assert f"_{report['metric']}_" in name

    def test_a_single_metric_still_announces_nothing(self):
        """The banner is noise when there is only one report."""
        with tempfile.TemporaryDirectory() as out:
            _code, printed, _written = self._run(self._corpus(out),
                                                 "--metric", "aware")
            assert "# metric:" not in printed

    def test_json_out_with_all_is_refused(self):
        """One path cannot hold three reports, and silently overwriting twice
        would leave only the last."""
        import contextlib
        import io
        import sys
        with tempfile.TemporaryDirectory() as out:
            self._corpus(out)
            argv = sys.argv
            sys.argv = ["family_trends.py", "--output-dir", out, "--no-charts",
                        "--metric", "all", "--json-out",
                        os.path.join(out, "one.json")]
            try:
                with contextlib.redirect_stderr(io.StringIO()) as err:
                    try:
                        ft.main()
                        raised = False
                    except SystemExit:
                        raised = True
            finally:
                sys.argv = argv
            assert raised, "--json-out with --metric all must not proceed"
            assert "--json-out" in err.getvalue()

    def test_the_charts_of_each_metric_do_not_collide(self):
        try:
            import matplotlib  # noqa: F401 - presence check only
        except ImportError:
            import pytest
            pytest.skip("matplotlib not installed")
        import contextlib
        import io
        import sys
        with tempfile.TemporaryDirectory() as out:
            self._corpus(out)
            charts = os.path.join(out, "charts")
            argv = sys.argv
            sys.argv = ["family_trends.py", "--output-dir", out,
                        "--metric", "all", "--chart-dir", charts]
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    assert ft.main() == 0
            finally:
                sys.argv = argv
            # Two families plus one combined, for each metric.
            assert len(os.listdir(charts)) == 3 * len(ft.METRICS)


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
