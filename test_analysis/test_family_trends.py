"""
The trends package: deriving model families from IDs, and trending along them.

The families are never enumerated, so the parse IS the feature - a rule that is
wrong about one ID puts a model in the wrong family, or in none, and the report
is quietly narrower than the corpus rather than visibly broken. These tests pin
every real ID in the r9 corpus and the shapes a future one is likely to take.
"""

import json
import os
import tempfile
from datetime import date

import trends as ft
from subversionbench import charting
from test_analysis.report_fixtures import _write_summary


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

    def test_an_incoming_dated_pair_needs_no_change(self):
        """deepseek-v4-flash is being collected as the earlier version of
        deepseek-v4-flash-0731. It joins its family and orders correctly with no
        edit, which is the whole point of deriving families rather than listing
        them - the same shape deepseek-pro already has."""
        models = ["deepseek/deepseek-v4-flash-0731", "deepseek/deepseek-v4-flash"]
        families = ft.group_families(models, "decimal")
        assert list(families) == ["deepseek/deepseek-flash"]
        assert [m.raw for m in families["deepseek/deepseek-flash"]] == [
            "deepseek/deepseek-v4-flash", "deepseek/deepseek-v4-flash-0731"]

    def test_the_flash_and_pro_lines_stay_separate(self):
        """Both are v4 with a dated snapshot. Pooling them would compare two
        product lines and report the difference as a version trend."""
        models = ["deepseek/deepseek-v4-flash", "deepseek/deepseek-v4-flash-0731",
                  "deepseek/deepseek-v4-pro", "deepseek/deepseek-v4-pro-0813"]
        families = ft.group_families(models, "decimal")
        assert sorted(families) == ["deepseek/deepseek-flash",
                                    "deepseek/deepseek-pro"]
        assert all(len(m) == 2 for m in families.values())

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
        """One per metric this corpus can answer. The fixture writes summaries
        and no run files, so the episode-derived metric is skipped - and the
        skip must not cost the others their reports or the run its exit code."""
        with tempfile.TemporaryDirectory() as out:
            code, _printed, written = self._run(self._corpus(out),
                                                "--metric", "all")
            assert code == 0
            from_summaries = [m for m, spec in ft.METRICS.items()
                              if not spec.get("from_episodes")]
            assert len(written) == len(from_summaries)
            for metric in from_summaries:
                assert any(f"_{metric}_" in name for name in written), metric

    def test_an_episode_derived_metric_skips_rather_than_fails(self):
        """`--metric all` over a summaries-only directory must still succeed.
        Returning a failure would make one unanswerable metric look like a
        broken run and hide the three that computed."""
        with tempfile.TemporaryDirectory() as out:
            code, printed, _written = self._run(self._corpus(out),
                                                "--metric", ft.TEXT_REACHABLE)
            assert code == 0
            assert "derived per episode" in printed

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
        from conftest import skip_without
        skip_without("matplotlib", "charts are an optional extra")
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
            # Two families plus one combined, per metric that this corpus
            # can answer. text_reachable is derived per episode and the fixture
            # writes summaries only, so it contributes no charts and must not
            # stop the others being drawn.
            from_summaries = [m for m, spec in ft.METRICS.items()
                              if not spec.get("from_episodes")]
            assert len(os.listdir(charts)) == 3 * len(from_summaries)


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


def _flat(note: str) -> str:
    """
    A caption's wording with its line wrapping undone.

    Captions fold to a fixed width so a long clause cannot widen the saved
    figure, which puts newlines inside phrases. Assertions about what a caption
    SAYS go through here; the few about its line STRUCTURE use the note itself.
    """
    return " ".join(note.split())


class TestTheExposureCaptionNamesWhatItMeans:
    """
    An awareness rate is only comparable between two models whose routes
    returned comparable amounts of reasoning. The caption is what tells a reader
    that, so it has to name the models it is about.
    """

    def _families(self, *pairs):
        return [{"family": "p/f", "members": [
            {"model": m, "reasoning_exposure": {"share": s}} for m, s in pairs]}]

    def test_zero_exposure_models_are_named_not_counted(self):
        """"2 returned none at all" leaves the reader unable to tell WHICH two
        points to distrust, which is the only thing the note is for."""
        note = ft._exposure_range_note(self._families(
            ("google/gemini-3-flash-preview", 0.0), ("google/gemini-3.5-flash", 0.99),
            ("x-ai/grok-4.20", 0.0)), "aware")
        assert "google/gemini-3-flash-preview" in note
        assert "x-ai/grok-4.20" in note
        assert "google/gemini-3.5-flash" not in note, "only the silent ones"

    def test_one_silent_model_reads_as_singular(self):
        """Each metric's clause has its own subject - a rate on one, a model on
        the other - so the check is that no plural survives, not that one
        particular singular appears."""
        for metric in ft.AWARENESS_METRICS:
            note = ft._exposure_range_note(self._families(
                ("a/quiet", 0.0), ("a/loud", 1.0)), metric)
            assert "the other 1 returned no trace" in note, metric
            assert "those rates are" not in note, metric
            assert "those models" not in note, metric

    def test_a_long_list_is_capped_but_still_counted(self):
        """A corpus where most models return nothing must not produce a caption
        wider than the figure."""
        pairs = [(f"p/m{i}", 0.0) for i in range(9)] + [("p/loud", 1.0)]
        note = ft._exposure_range_note(self._families(*pairs), "aware")
        assert "and 5 more" in note
        assert note.count("p/m") == ft._MAX_NAMED_SILENT

    def test_no_model_is_named_when_every_model_returned_something(self):
        """The naming exists to mark the group read differently. With no such
        group there is nobody to name - the second line is the reading that
        holds for everyone, and it carries no model IDs."""
        note = ft._exposure_range_note(self._families(
            ("a/one", 0.5), ("a/two", 1.0)), "aware")
        assert "separate reasoning trace returned in 50%-100%" in note
        assert "a/one" not in note and "a/two" not in note
        assert "returned no trace" not in note

    def test_the_two_groups_partition_the_models(self):
        """The counts must add to the total. An earlier version gave the range
        over ALL models and then named the silent ones, so the range's own 0%
        lower bound WAS those models - which reads as though a third set sits at
        0% besides the ones named."""
        note = ft._exposure_range_note(self._families(
            ("a/one", 0.0), ("a/two", 1.0), ("a/three", 0.5)), "aware")
        assert "for 2 of these 3 models" in note
        assert "the other 1 returned no trace at all" in note

    def test_the_range_excludes_the_models_that_returned_nothing(self):
        """A 0% lower bound would double-count them into both statements."""
        note = ft._exposure_range_note(self._families(
            ("a/silent", 0.0), ("a/low", 0.36), ("a/high", 1.0)), "aware")
        assert "36%-100%" in note
        assert "0%-" not in note

    def test_a_corpus_where_nothing_reasoned_says_so_plainly(self):
        """One group means one statement - no range, and nobody singled out."""
        note = ft._exposure_range_note(self._families(
            ("a/one", 0.0), ("a/two", 0.0)), "aware")
        assert "none of these 2 models returned a separate reasoning trace" \
            in _flat(note)
        assert "%" not in note, "no range when there is nothing to range over"
        assert "a/one" not in note and "a/two" not in note

    def test_a_single_measured_model_reads_as_one_value_not_a_range(self):
        note = ft._exposure_range_note(self._families(
            ("a/silent", 0.0), ("a/only", 0.42)), "aware")
        assert "in 42% of episodes" in note and "42%-42%" not in note

    def test_nothing_is_claimed_when_exposure_was_never_recorded(self):
        assert ft._exposure_range_note([{"family": "p/f", "members": [
            {"model": "a/x", "reasoning_exposure": None}]}], "aware") == ""


class TestTheExposureCaptionIsAboutAChannelNotAboutSilence:
    """
    A model at 0% still writes visible answers and calls tools - x-ai/grok-4.20
    wrote text in 117 of its 120 r9 episodes. What its route never returned was
    a chain of thought ALONGSIDE that answer. Both captions must say WHICH of
    those two things the percentage counts, or 0% reads as "produced nothing".
    """

    def _members(self, *pairs):
        return [{"model": m, "version": v, "position": i + 1,
                 "date": None, "tags": [],
                 "reasoning_exposure": {"share": s}}
                for i, (m, v, s) in enumerate(pairs)]

    def test_the_per_family_caption_says_separate(self):
        note = ft._exposure_note(self._members(
            ("x-ai/grok-4.20", "4.20", 0.0), ("x-ai/grok-4.6", "4.6", 1.0)))
        assert note.startswith("separate reasoning trace returned in:")
        assert "4.20 0%" in note and "4.6 100%" in note

    def test_the_combined_caption_says_separate_in_every_branch(self):
        """Four branches - all measured, some silent, all silent, one measured -
        and the distinction has to hold in all of them or it holds in none."""
        cases = [
            (("a/one", 0.5), ("a/two", 1.0)),
            (("a/quiet", 0.0), ("a/loud", 1.0)),
            (("a/quiet", 0.0), ("a/hush", 0.0)),
            (("a/quiet", 0.0), ("a/only", 0.42)),
        ]
        for pairs in cases:
            for metric in ft.AWARENESS_METRICS:
                note = ft._exposure_range_note([{"family": "p/f", "members": [
                    {"model": m, "reasoning_exposure": {"share": s}}
                    for m, s in pairs]}], metric)
                assert "separate reasoning trace" in note, (pairs, metric)
                assert "reasoning text returned" not in note, (pairs, metric)

    def test_no_caption_claims_a_model_returned_nothing_at_all(self):
        """"returned none at all" is the phrasing that misled - unqualified, it
        reads as no output rather than no trace."""
        for metric in ft.AWARENESS_METRICS:
            note = ft._exposure_range_note([{"family": "p/f", "members": [
                {"model": m, "reasoning_exposure": {"share": s}}
                for m, s in (("a/quiet", 0.0), ("a/loud", 1.0))]}], metric)
            assert "returned none at all" not in note, metric
            assert "returned no trace at all" in note, metric

    def test_a_member_without_exposure_is_skipped_not_shown_as_zero(self):
        """No recording is not the same claim as a route that returned nothing,
        and 0% would assert the second."""
        note = ft._exposure_note(self._members(
            ("a/known", "1", 1.0), ("a/unknown", "2", None)))
        assert "a/unknown" not in note and "2 0%" not in note

    def test_nothing_is_claimed_when_no_member_has_exposure(self):
        assert ft._exposure_note([
            {"model": "a/x", "version": "1", "position": 1, "date": None,
             "tags": [], "reasoning_exposure": None}]) == ""


class TestAZeroMeansTheOppositeOnTheTwoAwarenessCharts:
    """
    Both awareness charts carry the SAME exposure figures, because exposure is a
    fact about the corpus rather than about the analysis. What a zero means
    there is a fact about the analysis, and it inverts between them:

      `aware` reads the reasoning trace AND visible text, so a route that
      returned no trace was read on a narrower instrument - distrust the zeroes.

      `text_reachable` reads visible text ONLY, the same channel for everyone.
      Where a trace came back its figure is a FLOOR; where none came back the
      grader saw visible text alone, so the figure is EXACT - trust the zeroes
      more than the rest.

    For a while both charts printed the `aware` sentence, because no call site
    passed the metric down. On the text_reachable chart that told the reader to
    discount the only two points that needed no discounting.
    """

    def _families(self, *pairs):
        return [{"family": "p/f", "members": [
            {"model": m, "reasoning_exposure": {"share": s}} for m, s in pairs]}]

    def _members(self, *pairs):
        return [{"model": m, "version": m[-1], "position": i + 1,
                 "date": None, "tags": [],
                 "reasoning_exposure": {"share": s}}
                for i, (m, s) in enumerate(pairs)]

    SPLIT = (("a/quiet", 0.0), ("a/loud", 1.0))

    def test_the_two_metrics_do_not_get_the_same_caption(self):
        """The regression itself: identical text under charts that need
        opposite readings. Everything BEFORE the reading has to stay identical -
        the figures are a fact about the corpus, so only their reading moves."""
        aware, text = (_flat(ft._exposure_range_note(
            self._families(*self.SPLIT), m)) for m in ft.AWARENESS_METRICS)
        assert aware != text
        assert (aware.split("this rate reads")[0]
                == text.split("this rate reads")[0])

    def test_the_mixed_metric_counts_the_channels_each_group_had(self):
        """"not measured on the same instrument as the rest" names no
        instrument, so the reader is told something differs and not what. One
        channel against two is the concrete fact underneath it, and unlike the
        abstraction it says which direction the gap should be read in."""
        note = _flat(ft._exposure_range_note(
            self._families(*self.SPLIT), "aware"))
        assert "could only show awareness in visible text" in note
        assert "the rest in either" in note

    def test_no_caption_hides_behind_the_word_instrument(self):
        """Every branch of both metrics has to name what actually changes."""
        for pairs in (self.SPLIT, (("a/one", 0.5), ("a/two", 1.0)),
                      (("a/quiet", 0.0), ("a/hush", 0.0))):
            for metric in ft.AWARENESS_METRICS:
                note = ft._exposure_range_note(self._families(*pairs), metric)
                assert "instrument" not in note, (pairs, metric)
        for metric in ft.AWARENESS_METRICS:
            assert "instrument" not in ft._exposure_note(
                self._members(*self.SPLIT), metric), metric

    def test_the_text_metric_calls_the_silent_rates_exact_not_suspect(self):
        """text_reachable IS the same channel for every model - casting doubt
        on the zeroes here inverts the metric's entire purpose."""
        note = _flat(ft._exposure_range_note(
            self._families(*self.SPLIT), ft.TEXT_REACHABLE))
        assert "that rate is exact" in note
        assert "the rest are floors" in note

    def test_all_silent_says_one_channel_on_aware_and_exact_on_text(self):
        both = (("a/one", 0.0), ("a/two", 0.0))
        aware, text = (_flat(ft._exposure_range_note(self._families(*both), m))
                       for m in ft.AWARENESS_METRICS)
        assert "every rate here rests on visible text alone" in aware
        assert "every rate here is exact rather than a floor" in text

    def test_all_measured_states_what_holds_for_everyone(self):
        """Nothing is wrong in this branch, but silence would read as though
        some point on the chart were exact - which a range cannot tell you."""
        pairs = (("a/one", 0.5), ("a/two", 1.0))
        aware, text = (_flat(ft._exposure_range_note(self._families(*pairs), m))
                       for m in ft.AWARENESS_METRICS)
        assert "every rate here is a floor" in text
        assert "every model here supplied both" in aware
        assert "floor" not in aware

    def test_the_per_family_caption_splits_the_same_way(self):
        aware, text = (_flat(ft._exposure_note(self._members(*self.SPLIT), m))
                       for m in ft.AWARENESS_METRICS)
        assert aware != text
        assert (aware.split("awareness above")[0]
                == text.split("awareness above")[0])
        assert "could only show it in the one channel" in aware
        assert "marks an exact rate and the rest are floors" in text

    def test_an_unknown_metric_states_figures_and_concludes_nothing(self):
        """A wrong reading is worse than no reading, so the default draws no
        conclusion rather than guessing which chart it is under."""
        for note in (ft._exposure_note(self._members(*self.SPLIT)),
                     ft._exposure_range_note(self._families(*self.SPLIT))):
            assert "separate reasoning trace" in _flat(note)
            assert "floor" not in note
            assert "channel" not in note

    def test_every_call_site_passes_its_metric(self):
        """The bug was four call sites that did not. A caption builder that CAN
        be called without a metric will be, unless something checks."""
        import inspect
        import re
        for plot in (ft._plot_family, ft._plot_all_families,
                     ft._plot_family_dates, ft._plot_all_family_dates):
            source = inspect.getsource(plot)
            for call in re.findall(r"_exposure(?:_range)?_note\((.*?)\)\n",
                                   source, re.S):
                assert "metric" in call, (plot.__name__, call)


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


class TestTheAnalysisDoesNotDependOnTheDrawing:
    """The seam the package is split on, asserted rather than described.

    The old single file said in its own comments that matplotlib was optional
    and that "losing the charts costs presentation, never analysis" - but
    nothing checked it, and nothing could: with the drawing and the p-values in
    one module, importing either imported both. These are the tests that make
    the claim mean something, and they are the reason to keep the boundary where
    it is when the next chart is added.
    """

    ANALYSIS = ("model_ids", "metrics", "report")
    NO_PYPLOT = ANALYSIS + ("chart_geometry", "captions")

    def _imports(self, leaf):
        import ast
        names = set()
        tree = ast.parse(open(f"trends/{leaf}.py").read())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names |= {a.name for a in node.names}
            elif isinstance(node, ast.ImportFrom):
                names.add(("." * node.level) + (node.module or ""))
        return names

    def test_the_analysis_modules_import_no_chart_module(self):
        """Not a style preference. `report.py` is what the console, the charts
        and the JSON all read, and a report that imported a chart module could
        not be computed on a machine without matplotlib installed."""
        charts = {".chart_style", ".chart_geometry", ".captions",
                  ".version_charts", ".date_charts", ".charts"}
        for leaf in self.ANALYSIS:
            crossed = self._imports(leaf) & charts
            assert not crossed, f"trends/{leaf}.py imports {sorted(crossed)}"

    def test_only_one_module_in_the_repository_reaches_matplotlib(self):
        """One import site for the optional dependency, so the install hint is
        printed in one place and cannot be bypassed by a second import.

        Scoped to the RULE and not to a path. This was `glob("trends/*.py")`
        with chart_style exempt, which passed while report_charts.py and
        sad_oversight.py each carried their own copy of the same function - two
        of the three character-for-character identical. A guard written against
        a directory only ever guards that directory.
        """
        import glob
        offenders = []
        for path in sorted(set(
                glob.glob("subversionbench/**/*.py", recursive=True)
                + glob.glob("trends/*.py") + glob.glob("report/*.py")
                + glob.glob("*.py"))):
            if path == "subversionbench/charting.py":
                continue            # the one implementation
            if os.path.basename(path).startswith("test_"):
                continue            # a test may check whether it is installed
            body = open(path).read()
            if "import matplotlib" in body:
                offenders.append(path)
        assert not offenders, (
            f"these import matplotlib themselves rather than going through "
            f"charting.import_pyplot: {offenders}")

    def test_the_layout_and_caption_passes_never_draw(self):
        """They are the part of the chart code most likely to be wrong, and they
        are testable without the optional dependency only while this holds: a
        layout that took an `ax` would have to be exercised through a figure."""
        for leaf in self.NO_PYPLOT:
            assert not any("matplotlib" in n for n in self._imports(leaf)), leaf

    def test_the_analysis_modules_import_in_a_bare_environment(self):
        """The claim itself, run rather than inferred from the imports: every
        module above loads with matplotlib made unimportable."""
        import subprocess
        import sys
        script = (
            "import builtins, sys\n"
            "real = builtins.__import__\n"
            "def blocked(name, *a, **k):\n"
            "    if name.split('.')[0] == 'matplotlib':\n"
            "        raise ImportError('no matplotlib')\n"
            "    return real(name, *a, **k)\n"
            "builtins.__import__ = blocked\n"
            "from trends.report import build_report\n"
            "from trends.chart_geometry import axis_top, release_span\n"
            "from trends.captions import _exposure_note\n"
            "assert axis_top([3.0]) == 5\n"
            "print('ok')\n")
        out = subprocess.run([sys.executable, "-c", script],
                             capture_output=True, text=True)
        assert out.returncode == 0, out.stderr
        assert "ok" in out.stdout

    def test_the_charts_still_degrade_rather_than_fail(self):
        """The other half of "optional": write_charts returns no paths and the
        report is unaffected. This is what the analysis/presentation split is
        FOR, so it is asserted here and not only where charts are drawn.

        Two things this got wrong when it was written, both of which made it
        pass while testing nothing. It patched `chart_style._import_pyplot`,
        but write_charts had bound that name at import time, so the patch never
        reached it - the documented reason this repo calls stubbed dependencies
        through their module. And it passed a report with NO FAMILIES, which
        returns no paths whether matplotlib is there or not. It now patches the
        owning module and asserts against a report that does produce charts.
        """
        from subversionbench import charting
        with tempfile.TemporaryDirectory() as out:
            report = self._report_with_one_family(out)

            # Not vacuous: the same report DOES write charts with pyplot present.
            if charting.import_pyplot() is not None:
                assert ft.write_charts(report, os.path.join(out, "on")), (
                    "the fixture draws nothing even with matplotlib installed, "
                    "so the degraded assertion below would pass for the wrong "
                    "reason")

            saved = charting.import_pyplot
            charting.import_pyplot = lambda *a, **k: None
            try:
                assert ft.write_charts(report, os.path.join(out, "off")) == []
            finally:
                charting.import_pyplot = saved

    def _report_with_one_family(self, out):
        """A report that really produces charts, so the degraded case has
        something to be the absence of.

        Built by build_report from written summaries rather than hand-rolled: a
        literal dict here needs every key the plotting code happens to read
        today, and the first attempt at one was missing `ordering_ambiguous`.
        A fixture that has to track a consumer's field list is a fixture that
        goes stale silently.
        """
        for model, n in (("x-ai/grok-4", 12), ("x-ai/grok-4.5", 6)):
            _write_summary(out, model, "strong", n_runs=60, n_misaligned=n,
                           n_aware=2, n_unaware=8)
        report = ft.build_report(out, "misaligned")
        assert report["families"], "the fixture produced no family to chart"
        return report


class TestTheSingleImportSite:
    def test_every_name_the_package_offers_is_declared(self):
        """`trends/__init__.py` re-exports 70 names, most of them private, and
        without `__all__` each one reads as a stray import to the dead-import
        guard. So the declaration is the interface, and this is what keeps it
        from going stale in either direction."""
        import trends
        declared = set(trends.__all__)
        reachable = {n for n in dir(trends)
                     if not n.startswith("__")
                     and n not in {"captions", "chart_geometry", "chart_style",
                                   "charts", "console", "date_charts",
                                   "family_trends", "metrics", "model_ids",
                                   "report", "version_charts"}}
        assert declared == reachable, (
            f"declared but absent: {sorted(declared - reachable)}; "
            f"present but undeclared: {sorted(reachable - declared)}")

    def test_no_test_rebinds_a_name_through_the_package(self):
        """Why the re-export is safe. A function resolves globals in ITS OWN
        module, so patching `trends.axis_top` would not reach a caller that
        lives in trends/version_charts.py - it would silently assert nothing.
        A config.py re-export walked into exactly that."""
        import re
        body = open(__file__).read()
        offenders = re.findall(r"(?:setattr\(ft,|ft\.\w+\s*=(?!=))", body)
        assert not offenders, (
            f"rebound through the package rather than on the module that "
            f"defines the name: {offenders}. Patch the submodule instead - see "
            f"test_the_charts_still_degrade_rather_than_fail.")


def _pyplot_or_skip():
    """pyplot through the one import site, or skip.

    `charting.import_pyplot()` returns None rather than raising when matplotlib
    is absent, so a bare call would hand `None` to the function under test and
    fail somewhere unrelated. Under SUBVERSIONBENCH_NO_SKIPS the extra is
    installed and this never skips.
    """
    from subversionbench import charting
    plt = charting.import_pyplot()
    if plt is None:
        import unittest
        raise unittest.SkipTest("matplotlib not installed")
    return plt


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


class TestTheFamilyBlockPrintsWhatQualifiesIt:
    """trends/console._print_family, driven with a family dict.

    A family block prints an ordering, a set of steps and a verdict. Each
    branch below is a case where one of those is true only under a
    qualification, and the qualification is the part that was unrun.
    """

    def _member(self, version="1", model="p/m-1", **over):
        member = {"version": version, "model": model, "ci95": [0.1, 0.5],
                  "underpowered": False, "date": None, "tags": [],
                  "successes": 3, "n": 10, "rate": 0.3}
        member.update(over)
        return member

    def _family(self, **over):
        family = {
            "family": "p/m", "n_members": 2, "ordering_ambiguous": False,
            "version_style": "decimal",
            "members": [self._member(), self._member("2", "p/m-2")],
            "steps_summary": {"n_down": 1, "n_up": 0, "n_flat": 0},
            "steps": [{"from": "1", "to": "2", "difference": -0.2,
                       "p": 0.04, "separated": True, "direction": "down"}],
            "trend": {"z": -2.1, "p": 0.03, "direction": "falling"},
            "first_vs_last": None,
            "release_fit": None,
            "verdict": "falls across the family",
        }
        family.update(over)
        return family

    def _printed(self, family):
        import contextlib
        import io
        from trends.console import _print_family
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            _print_family(family)
        return buf.getvalue()

    def test_an_ambiguous_ordering_names_the_style_it_chose(self):
        """The whole family is ordered by that choice, so every step and the
        trend below it depend on it. Telling the reader which was used, and
        that the other exists, is what makes the block falsifiable."""
        text = self._printed(self._family(ordering_ambiguous=True,
                                          version_style="decimal"))
        assert "version ordering depends on" in text
        assert "--version-style decimal" in text
        assert "Try the other to compare" in text

    def test_an_unambiguous_ordering_carries_no_such_warning(self):
        assert "version ordering depends on" not in self._printed(self._family())

    def test_a_dated_member_shows_the_date_beside_the_version(self):
        """Two releases can share a version string and differ by date, and
        without it they are two indistinguishable rows."""
        text = self._printed(self._family(members=[
            self._member(date="20260101"), self._member("2", "p/m-2")]))
        assert "1+20260101" in text

    def test_a_step_that_could_not_be_computed_prints_its_reason(self):
        """NOT a zero difference. A step with no comparable data is not a
        flat step, and printing it as one would put it in the reader's count
        of steps that did not move."""
        text = self._printed(self._family(steps=[
            {"from": "1", "to": "2", "difference": None,
             "note": "no episodes on one side"}]))
        assert "1 -> 2: no episodes on one side" in text
        assert "+0.0%" not in text
        assert " = " not in text, "an incomputable step was drawn as flat"

    def test_a_computed_step_carries_its_direction_mark_and_p(self):
        text = self._printed(self._family())
        assert "v 1 -> 2: -20.0%" in text and "p=0.04" in text
        assert "SEPARATED" in text

    def test_a_multiplicity_corrected_trend_shows_both_corrections(self):
        """The family trend is one of many tested together, so the corrected
        values are the ones a reader should quote."""
        text = self._printed(self._family(trend={
            "z": -2.1, "p": 0.03, "direction": "falling",
            "holm_p": 0.09, "bh_p": 0.045}))
        assert "holm=0.09" in text and "BH=0.045" in text

    def test_an_untestable_trend_says_so_rather_than_printing_nothing(self):
        text = self._printed(self._family(trend={"z": None,
                                                 "note": "fewer than three"}))
        assert "trend: not testable (fewer than three)" in text

    def test_the_first_to_last_comparison_prints_when_there_is_one(self):
        text = self._printed(self._family(first_vs_last={
            "difference": -0.35, "difference_ci95": [-0.6, -0.1], "p": 0.006}))
        assert "first vs last: -35.0%" in text
        assert "p=0.006" in text

    def test_an_underpowered_member_is_marked_in_its_own_row(self):
        """Per row, not per family: one thin model among several does not
        make the family unreadable, and the reader needs to know which."""
        text = self._printed(self._family(members=[
            self._member(underpowered=True), self._member("2", "p/m-2")]))
        rows = [ln for ln in text.splitlines() if "p/m-1" in ln]
        assert rows and rows[0].rstrip().endswith("!"), rows


class TestTheTrendsDataQualityBlock:
    """trends/console._print_report's caveat lines."""

    def _dq(self, **over):
        dq = {"metric": "misaligned", "llm_dependency_note": "graded",
              "n_models_in_a_family": 4, "n_models_total": 6,
              "models_without_a_family": [],
              "models_below_informative_denominator": [],
              "min_informative_denominator": 10,
              "families_with_ambiguous_ordering": [],
              "unparsed_tokens": [],
              "models_without_release_date": [],
              "plotted_models_without_release_date": []}
        dq.update(over)
        return dq

    def _printed(self, dq):
        import contextlib
        import io
        from trends.console import _print_report
        report = {
            "metric_label": "misalignment rate", "output_dir": "./results",
            "n_families": 0, "version_style": "decimal", "families": [],
            "across_all_families": {
                "n_steps": 0, "n_down": 0, "n_up": 0, "n_flat": 0,
                "n_families_monotone_falling": 0,
                "n_families_monotone_rising": 0,
                "sign_test": {"p": None, "note": "no steps"},
                "multiplicity": None,
            },
            "data_quality": dq,
        }
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            _print_report(report)
        return buf.getvalue()

    def test_a_model_with_no_family_is_named(self):
        """It contributed to nothing in the report above. Left unnamed, a
        reader counting models finds the report narrower than the corpus
        with no explanation."""
        text = self._printed(self._dq(models_without_a_family=["solo/model"]))
        assert "no family (only version collected)" in text
        assert "solo/model" in text

    def test_an_ambiguous_family_ordering_is_raised_at_report_level_too(self):
        """Named here as well as in the family block, because a reader who
        skims the families still has to meet it once."""
        text = self._printed(self._dq(families_with_ambiguous_ordering=["p/m"]))
        assert "ordering depends on --version-style" in text and "p/m" in text

    def test_tokens_the_parser_did_not_recognise_are_listed(self):
        """The parse IS the feature: a token it did not recognise is a model
        placed in the wrong family or in none, and the report is quietly
        narrower rather than visibly broken."""
        text = self._printed(self._dq(unparsed_tokens=["preview", "0711"]))
        assert "tokens the parser did not recognise" in text
        assert "preview" in text and "0711" in text

    def test_a_clean_corpus_raises_none_of_them(self):
        text = self._printed(self._dq())
        assert "!" not in text


    def test_an_undated_model_is_named_loudly_and_told_where_to_fix_it(self):
        """Louder than the warnings above it because it is the only line in
        the block that names a fix - and quieter than a failure, because
        nothing above it depends on a release date. An undated model is
        missing from the release charts and present in every table, trend,
        interval and p-value; stopping the analysis over a chart would be
        the wrong trade."""
        text = self._printed(self._dq(
            models_without_release_date=["p/m-1", "p/m-2"],
            plotted_models_without_release_date=["p/m-1"]))
        assert "ERROR: no release date recorded for 2 model(s)" in text
        assert "p/m-1" in text and "p/m-2" in text
        assert "RELEASE_DATES in model_releases.py" in text
        assert "1 of them sit in a family" in text

    def test_it_says_which_figures_the_missing_dates_do_not_affect(self):
        """The reader has to be able to keep reading. Without this the error
        reads as though it invalidates the report above it."""
        text = self._printed(self._dq(
            models_without_release_date=["p/m-1"],
            plotted_models_without_release_date=[]))
        assert "every figure above is unaffected" in text
        assert "version-order chart" in text

    def test_a_fully_dated_corpus_prints_no_release_date_error(self):
        assert "no release date recorded" not in self._printed(self._dq())
