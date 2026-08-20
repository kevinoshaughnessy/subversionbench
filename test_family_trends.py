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

    def test_every_family_gets_its_own_label_corner(self):
        """A vertical-only stagger cannot separate two families a couple of
        points apart, because the offset moves the label about as far as the gap
        between the lines. 3.6 and 2.6 collided that way."""
        assert len(set(ft._LABEL_OFFSETS)) == len(ft._LABEL_OFFSETS)
        assert len(ft._LABEL_OFFSETS) >= 4
