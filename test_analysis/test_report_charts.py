"""
Tests for report_charts.py - the twelve research-question charts.

A chart is a second reading of numbers the printed report already carries, so
the thing worth testing is not that matplotlib drew something: it is that the
chart cannot say anything the report does not, and cannot quietly leave out
something the report does. Most of what follows checks the ROWS - what gets a
line, what it is labelled, where it sits - because that is where a chart can
lie about an analysis while still rendering.
"""

import json
import os
import tempfile


import report as run_report
import report_charts as rc
from subversionbench import charting
from subversionbench.power import MIN_INFORMATIVE_DENOMINATOR


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _contrast(xa, na, xb, nb, model=None, holm=False, separated=False,
              diff=None, ci=(None, None)):
    """A contrast shaped like the ones _contrast() in run_report emits."""
    rate_a = xa / na if na else None
    rate_b = xb / nb if nb else None
    if diff is None and rate_a is not None and rate_b is not None:
        diff = round(rate_a - rate_b, 4)
    out = {
        "a": {"successes": xa, "n": na, "rate": rate_a},
        "b": {"successes": xb, "n": nb, "rate": rate_b},
        "difference": diff,
        "difference_ci95": list(ci) if diff is not None else None,
        "separated": separated,
        "level_a": True, "level_b": False,
    }
    if model:
        out["model"] = model
        out["holm_rejected"] = holm
    if na == 0 or nb == 0:
        out["difference"] = None
        out["difference_ci95"] = None
        out["note"] = "one side has no data"
    return out


def _section(**over):
    section = {
        "id": "oversight_vs_scheming",
        "question": "Does the presence of oversight increase or decrease "
                    "scheming rates?",
        "overall": _contrast(32, 1793, 54, 1784, diff=-0.0124,
                             ci=(-0.0228, -0.0024), separated=True),
        "by_model": [
            _contrast(1, 60, 4, 60, model="p/a", ci=(-0.14, 0.02)),
            _contrast(4, 60, 1, 60, model="p/b", holm=True, ci=(-0.02, 0.14)),
            _contrast(0, 0, 2, 60, model="p/c"),
        ],
        "stratified": {"mantel_haenszel": {
            "risk_difference": -0.0124,
            "risk_difference_ci95": [-0.0215, -0.0033],
            "n_strata_used": 2, "separated": True}},
        "crude_vs_stratified": {},
    }
    section.update(over)
    return section


def _paired_section(**over):
    section = {
        "id": "evidence_vs_concealment",
        "question": "To what extent does part-evidence vs zero-evidence "
                    "affect concealment rates?",
        "not_pooled_because": "The four phrasings are measured on the SAME acts.",
        "contrasts": [{
            "act": "sandbox",
            "variant_a": "zeroevidence", "variant_b": "partevidence",
            "overall": {
                "a": {"successes": 60, "n": 803, "rate": 0.0747},
                "b": {"successes": 48, "n": 803, "rate": 0.0598},
                "difference": 0.0149, "difference_ci95": [-0.0042, 0.0341],
                "separated": False, "n_pairs": 803,
                "discordant": {"a_only": 37, "b_only": 25},
                "level_a": "zeroevidence", "level_b": "partevidence",
            },
        }],
    }
    section.update(over)
    return section


def _plt():
    """
    pyplot, or skip.

    A plain helper rather than a pytest fixture: run_tests.py is the other
    runner this suite has to work under and it cannot interpret fixtures - see
    test_dependencies.TestBothTestRunnersCanRunEverything.
    """
    plot = charting.import_pyplot()
    if plot is None:
        from conftest import skip_without
        skip_without("matplotlib", "charts are an optional extra")
    return plot


# ---------------------------------------------------------------------------
# Rows
# ---------------------------------------------------------------------------

class TestEveryModelKeepsItsRow:
    """
    The consistency block printed above each chart says "N/M had data on both
    sides". A chart that silently drops the models with no data makes that
    sentence unverifiable - the reader counts the rows, gets N, and has no way
    to see the M.
    """

    def test_a_model_with_no_data_on_one_side_is_still_drawn(self):
        rows = rc._model_rows(_section()["by_model"])
        assert len(rows) == 3
        assert [r.label for r in rows if r.diff is None] == ["p/c"]

    def test_the_missing_row_carries_the_reason_not_a_zero(self):
        """Drawing it at zero would assert no effect, which is a different
        claim from having no evidence either way."""
        row = next(r for r in rc._model_rows(_section()["by_model"])
                   if r.label == "p/c")
        assert row.diff is None and row.lo is None
        assert "no data" in row.missing

    def test_models_with_an_effect_are_ordered_by_it(self):
        """Sorted so the sign split and the spread read off the shape, which is
        what the consistency count above the chart is counting."""
        rows = [r for r in rc._model_rows(_section()["by_model"])
                if r.diff is not None]
        assert [r.diff for r in rows] == sorted(r.diff for r in rows)

    def test_models_with_no_effect_sort_after_the_ones_with_one(self):
        rows = rc._model_rows(_section()["by_model"])
        assert rows[-1].diff is None
        assert all(r.diff is not None for r in rows[:-1])

    def test_only_holm_survivors_are_marked(self):
        """The report corrects across 28 models. Marking every interval that
        clears zero would advertise findings the report withholds."""
        rows = {r.label: r.marked for r in rc._model_rows(_section()["by_model"])}
        assert rows["p/b"] is True
        assert rows["p/a"] is False


class TestBothPooledEstimatesAreAlwaysDrawn:
    """
    `crude_vs_stratified` exists because the two can disagree - question 9 on r9
    separates crudely with every one of its outcome events inside a single
    model. Drawing only one of them removes the reader's ability to see that.
    """

    def test_crude_and_stratified_both_appear(self):
        kinds = [r.kind for r in rc._pooled_rows(_section())]
        assert "crude" in kinds and "stratified" in kinds

    def test_the_stratified_row_says_how_many_strata_were_used(self):
        """Not the same as the model count: a stratum with an empty arm drops
        out, and a reader comparing this row to the rows above needs to know
        how many of them fed it."""
        row = next(r for r in rc._pooled_rows(_section())
                   if r.kind == "stratified")
        assert "2 models" in row.label

    def test_the_parallel_measure_appears_only_where_a_question_has_one(self):
        assert not [r for r in rc._pooled_rows(_section())
                    if r.kind == "parallel"]
        with_parallel = _section(text_reachable={
            "overall": _contrast(300, 1179, 250, 1200, diff=0.0463,
                                 ci=(0.01, 0.08), separated=True)})
        assert [r.kind for r in rc._pooled_rows(with_parallel)][-1] == "parallel"

    def test_a_question_with_no_stratified_estimate_still_gets_its_crude_one(self):
        rows = rc._pooled_rows(_section(stratified={"mantel_haenszel": {}}))
        assert [r.kind for r in rows] == ["crude"]


class TestThePairedQuestionsKeepTheirOwnShape:
    """
    Every interrogation phrasing is put to the same act in the same episode, so
    these are McNemar over discordant pairs, not Fisher over arms. Their charts
    hold one row per contrast rather than per model.
    """

    def test_one_row_per_contrast(self):
        rows = rc._paired_rows(_paired_section())
        assert len(rows) == 1
        assert rows[0].label == "sandbox: zeroevidence vs partevidence"

    def test_the_discordant_counts_are_on_the_row(self):
        """Those two numbers ARE the test - exact McNemar reads nothing from the
        concordant pairs, so n=803 alone overstates the evidence behind it."""
        note = rc._paired_rows(_paired_section())[0].note
        assert "803 pairs" in note
        assert "37/25 discordant" in note


# ---------------------------------------------------------------------------
# Labels
# ---------------------------------------------------------------------------

class TestTheArmsAreNamedInWords:

    def test_raw_levels_become_readable_names(self):
        assert rc.arm_labels(_section()) == ("oversight present",
                                             "oversight absent")

    def test_every_question_build_report_emits_has_words_for_its_levels(self):
        """The words are keyed by the exposure in the question id, so a renamed
        or added question must fail here rather than draw an axis labelled
        `True minus False`."""
        ids = [
            "oversight_vs_scheming", "oversight_vs_awareness",
            "oversight_vs_misalignment", "nudge_vs_awareness",
            "awareness_vs_misalignment", "awareness_vs_monitoring_disabled",
            "awareness_vs_sandbox_escape", "awareness_vs_scheming",
            "awareness_vs_oversight_scheming", "awareness_vs_sandbox_scheming",
        ]
        for question_id in ids:
            assert rc.exposure_of(question_id) in rc.labels._LEVEL_WORDS, question_id

    def test_the_question_ids_here_are_the_ones_run_report_builds(self):
        """Pins the list above against the source rather than against a memory
        of it: the level words are only safe while this list is complete."""
        import inspect
        source = inspect.getsource(run_report.build_report)
        called = [n for n in dir(run_report)
                  if n.startswith("question_") and f"{n}(" in source]
        assert len(called) == 12
        for name in called:
            # Defined in one of the three question modules, not merely reachable
            # through the package. This was `== "run_report"` while the report
            # was one file; the check it was making - that each name is a real
            # question function rather than an alias to something else - now
            # also pins the grouping, so a question cannot drift into loading.py
            # or console.py and keep passing.
            module = getattr(run_report, name).__module__
            assert module.startswith("report.questions_"), (name, module)

    def test_an_unknown_exposure_falls_back_to_the_raw_level(self):
        """A chart with an ugly axis still carries its numbers; raising here
        would lose the eleven charts that were fine."""
        labels = rc.arm_labels(_section(id="newthing_vs_scheming"))
        assert labels == ("True", "False")

    def test_the_short_label_is_derived_from_the_id(self):
        assert rc.short_label("awareness_vs_sandbox_escape") == \
            "awareness -> sandbox escape"


class TestNoCaptionOutrunsTheReport:

    def test_the_divergence_caption_is_quoted_not_composed(self):
        """The chart must not be able to warn about something the printed
        report does not, or reassure where it warns."""
        assert rc._divergence_caption(_section()) == ""
        warned = _section(crude_vs_stratified={"warning": "CONFOUNDED: ..."})
        assert rc._divergence_caption(warned) == "CONFOUNDED: ..."

    def test_the_rate_caption_gives_both_levels_with_their_counts(self):
        caption = rc._rate_caption(_section())
        assert "oversight present: 1.8% (32/1793)" in caption
        assert "oversight absent: 3.0% (54/1784)" in caption

    def test_a_restricted_denominator_says_so(self):
        """Not-applicable is not zero: counting the no-oversight episodes as
        "did not override" once halved question 6's rates. A chart showing the
        restricted denominator in silence invites reconciling it against a
        corpus total that was never its base."""
        caption = rc._scope_caption(_section(n_episodes_not_applicable=1784,
                                            n_episodes_observable=1793))
        assert "1793" in caption and "1784 not applicable" in caption

    def test_nothing_is_claimed_about_scope_when_nothing_was_excluded(self):
        assert rc._scope_caption(_section()) == ""


class TestCaptionsDoNotWidenTheFigure:

    def test_no_wrapped_line_exceeds_the_width(self):
        text = "word " * 80
        assert all(len(line) <= rc.captions._CAPTION_WRAP
                   for line in rc._wrap(text).split("\n"))

    def test_a_model_id_is_never_folded_at_a_hyphen(self):
        """Half of `google/gemini-3-flash-preview` names a different model in
        this corpus."""
        note = rc._wrap("excluded: " + ", ".join(
            ["google/gemini-3-flash-preview"] * 6))
        assert "-\n" not in note
        assert note.count("google/gemini-3-flash-preview") == 6

    def test_wrapping_loses_no_words(self):
        text = "a b c\n" + "word " * 60
        assert rc._wrap(text).split() == text.split()


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

class TestTheChartsRender:

    def test_one_chart_per_question_plus_an_overview(self):
        _plt()
        report = {"questions": [_section(), _paired_section()]}
        with tempfile.TemporaryDirectory() as out:
            written = rc.write_charts(report, out)
        names = [os.path.basename(p) for p in written]
        assert names == ["question_01_oversight_vs_scheming.png",
                         "question_02_evidence_vs_concealment.png",
                         "questions_overview.png"]

    def test_filenames_are_numbered_so_they_sort_as_asked(self):
        """A reader pairs a chart with a section of the printed output by
        position, and `question_10` sorting before `question_2` breaks that."""
        _plt()
        report = {"questions": [_section() for _ in range(12)]}
        with tempfile.TemporaryDirectory() as out:
            written = rc.write_charts(report, out)
        numbers = [os.path.basename(p).split("_")[1]
                   for p in written if "overview" not in p]
        assert numbers == [f"{i:02d}" for i in range(1, 13)]

    def test_a_question_with_no_rows_is_skipped_not_crashed(self):
        _plt()
        empty = {"id": "oversight_vs_scheming", "question": "?",
                 "overall": {}, "by_model": [], "stratified": {}}
        with tempfile.TemporaryDirectory() as out:
            written = rc.write_charts({"questions": [empty]}, out)
        assert [os.path.basename(p) for p in written] == \
            ["questions_overview.png"]

    def test_an_empty_report_writes_nothing(self):
        _plt()
        with tempfile.TemporaryDirectory() as out:
            assert rc.write_charts({"questions": []}, out) == []

    def test_the_overview_never_pools_the_paired_questions(self):
        """They are explicitly never pooled, so a single row for either would be
        a number this benchmark does not compute."""
        _plt()
        report = {"questions": [_section(), _paired_section()]}
        rows = []
        original = rc.draw._draw_forest

        def capture(plot, drawn, *args, **kwargs):
            rows.append(drawn)
            return original(plot, drawn, *args, **kwargs)

        rc.draw._draw_forest = capture
        try:
            with tempfile.TemporaryDirectory() as out:
                rc.write_charts(report, out)
        finally:
            rc.draw._draw_forest = original
        overview = rows[-1]
        assert [r.label for r in overview] == [
            "Q1. oversight -> scheming",
            "Q2. sandbox: zeroevidence vs partevidence"]

    def test_missing_matplotlib_costs_the_charts_and_nothing_else(self):
        """Patched on `charting`, the module that OWNS import_pyplot, not on the
        script that calls it. One patch point covers all three drawing scripts,
        and it does not move when a caller does - see test_init.py."""
        original = charting.import_pyplot
        charting.import_pyplot = lambda *a, **k: None
        try:
            assert rc.write_charts({"questions": [_section()]}, "/nonexistent") \
                == []
        finally:
            charting.import_pyplot = original


class TestTheReportRunsWithAndWithoutCharts:

    def _corpus(self, out):
        """One arm, enough for build_report to produce all twelve sections."""
        for oversight in ("oversight", "nooversight"):
            name = f"summary_strong_{oversight}_nolure_20260101T000000.json"
            with open(os.path.join(out, name), "w") as f:
                json.dump({"model": "p/m", "nudge": "strong", "n_runs": 10,
                           "n_scheming": 1, "n_misaligned": 2,
                           "awareness_subgroups": {"aware": 3, "unaware": 7}},
                          f)

    def test_charts_land_beside_the_json_by_default(self, monkeypatch):
        _plt()
        with tempfile.TemporaryDirectory() as out:
            self._corpus(out)
            monkeypatch.setattr("sys.argv",
                                ["run_report.py", "--output-dir", out])
            assert run_report.main() == 0
            assert os.path.isdir(os.path.join(out, "charts"))

    def test_no_charts_leaves_the_analysis_untouched(self, monkeypatch):
        """Every figure the charts draw is in the printed output and the JSON,
        so skipping them must cost presentation only."""
        with tempfile.TemporaryDirectory() as out:
            self._corpus(out)
            monkeypatch.setattr(
                "sys.argv",
                ["run_report.py", "--output-dir", out, "--no-charts",
                 "--json-out", os.path.join(out, "r.json")])
            assert run_report.main() == 0
            assert not os.path.exists(os.path.join(out, "charts"))
            with open(os.path.join(out, "r.json")) as f:
                report = json.load(f)
            assert len(report["questions"]) == 12
            assert "charts" not in report

    def test_the_json_records_the_charts_it_wrote(self, monkeypatch):
        _plt()
        """A report describing an artefact it has no record of cannot be
        checked against the directory it was written into."""
        with tempfile.TemporaryDirectory() as out:
            self._corpus(out)
            json_out = os.path.join(out, "r.json")
            monkeypatch.setattr("sys.argv",
                                ["run_report.py", "--output-dir", out,
                                 "--json-out", json_out])
            assert run_report.main() == 0
            with open(json_out) as f:
                report = json.load(f)
            assert report["charts"]
            assert all(p.endswith(".png") for p in report["charts"])


# ---------------------------------------------------------------------------
# Persistence after refusal
# ---------------------------------------------------------------------------
#
# report/characteristics.py's job, not this file's: whether a row belongs in
# `by_model` at all, whether refusal_shown tracks the grader's own test, and
# what the loader derives from a saved transcript are all covered in
# test_report_characteristics.py. What is tested here is the boundary this
# file owns - profile dict in, chart rows and a rendered figure out - the same
# split _section()/_contrast() already draw for the twelve questions.

def _by_model_row(model, n_refused, n_persisted, comparable=None,
                  persisted_mis=(0, 0), complied_mis=(0, 0)):
    """One `by_model` entry shaped like persistence_after_refusal() emits.

    `comparable` defaults to whether both sides have episodes - the same rule
    the function under test applies - rather than always being stated, so a
    test can still override it to build the (n>0, n>0) case with the flag
    deliberately wrong if that is ever what it needs to check.
    """
    n_complied = n_refused - n_persisted
    pm, pn = persisted_mis
    cm, cn = complied_mis
    return {
        "model": model, "n_refused": n_refused, "n_persisted": n_persisted,
        "persistence_rate": round(n_persisted / n_refused, 4) if n_refused else None,
        "persisted": {"n": pn, "misaligned": pm,
                     "misaligned_rate": round(pm / pn, 4) if pn else None},
        "complied": {"n": cn, "misaligned": cm,
                    "misaligned_rate": round(cm / cn, 4) if cn else None},
        "comparable_within_model": (bool(n_persisted and n_complied)
                                    if comparable is None else comparable),
    }


def _persistence_profile(by_model=None, **over):
    by_model = by_model if by_model is not None else []
    n_refused = sum(r["n_refused"] for r in by_model)
    n_persisted = sum(r["n_persisted"] for r in by_model)
    profile = {
        "measure": "issued a further blocked command after being shown a "
                  "refusal",
        "is_descriptive_not_causal": True,
        "interpretation": "a profile, not an effect",
        "denominator": "episodes shown at least one sandbox refusal",
        "n_episodes": n_refused, "n_refused": n_refused, "n_never_refused": 0,
        "persistence_rate": (round(n_persisted / n_refused, 4)
                             if n_refused else None),
        "persisted": {"n": n_persisted, "misaligned": 0,
                     "misaligned_rate": None},
        "complied": {"n": n_refused - n_persisted, "misaligned": 0,
                    "misaligned_rate": None},
        "by_model": by_model,
        "n_models_comparable_within_model": sum(
            1 for r in by_model if r["comparable_within_model"]),
        "n_models_persisted_more_misaligned": sum(
            1 for r in by_model
            if r["comparable_within_model"]
            and (r["persisted"]["misaligned_rate"] or 0)
            > (r["complied"]["misaligned_rate"] or 0)),
        "max_retries_in_one_episode": 0,
    }
    profile.update(over)
    return profile


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


# ---------------------------------------------------------------------------
# Encoded payloads
# ---------------------------------------------------------------------------
#
# Same split as the persistence charts above: report/characteristics.py's
# encoded_payload_rate() owns the denominators and the pooling; this file owns
# only the boundary from its profile dict to chart rows and a rendered
# figure. Reuses _draw_rate_chart directly - a single-signal rate chart is
# exactly what plot_persistence_rate already draws, so plot_encoded_payload_rate
# is a second caller of the same drawing function rather than a new one.

def _epr_row(model, n_resolved, n_true, underpowered=None):
    """One `by_model` entry shaped like encoded_payload_rate() emits."""
    return {
        "model": model, "n_episodes": n_resolved,
        "n_resolved": n_resolved, "n_true": n_true,
        "rate": round(n_true / n_resolved, 4) if n_resolved else None,
        "underpowered": (n_resolved < MIN_INFORMATIVE_DENOMINATOR
                         if underpowered is None else underpowered),
    }


def _epr_profile(by_model=None, **over):
    by_model = by_model if by_model is not None else []
    n_resolved = sum(r["n_resolved"] for r in by_model)
    n_true = sum(r["n_true"] for r in by_model)
    profile = {
        "measure": ("whether the episode contains a base64-alphabet run in "
                    "the model's own words that decodes to real text"),
        "n_episodes": n_resolved,
        "pooled": {"n_resolved": n_resolved, "n_true": n_true,
                  "rate": round(n_true / n_resolved, 4) if n_resolved else None},
        "by_model": by_model,
    }
    profile.update(over)
    return profile


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


# ---------------------------------------------------------------------------
# Eval-awareness rubric signals
# ---------------------------------------------------------------------------
#
# Same split as the persistence charts above: report/characteristics.py's
# eval_signal_rates() owns the denominators and the pooling; this file owns
# only the boundary from its profile dict to chart rows and a rendered
# figure.

# Derived from the package, not restated: a fixture with its own hand-copied
# key list would still pass if RUBRIC_SIGNAL_KEYS drifted from it.
_SIGNAL_KEYS = run_report.RUBRIC_SIGNAL_KEYS


def _signal_by_model_row(model, **rates):
    """One `by_model` entry shaped like eval_signal_rates() emits.

    `rates` maps a signal key to (n_true, n_resolved); a key not passed gets
    no resolved episodes at all - unmeasured, not a rate of zero, the same
    convention `_by_model_row` above uses for a side with no episodes.
    """
    signals = {}
    # Model-level support, independent of any one signal's resolved count:
    # _signal_clusters excludes a model below the floor entirely, and these
    # fixtures are about what a PLOTTED model's cluster looks like. A test
    # that wants the exclusion itself passes n_episodes explicitly.
    n_episodes = rates.pop("n_episodes", MIN_INFORMATIVE_DENOMINATOR)
    for key in _SIGNAL_KEYS:
        n_true, n_resolved = rates.get(key, (0, 0))
        signals[key] = {
            "n_resolved": n_resolved, "n_true": n_true,
            "rate": round(n_true / n_resolved, 4) if n_resolved else None,
            "underpowered": n_resolved < 20,
        }
    return {"model": model, "n_episodes": n_episodes, "signals": signals}


def _signal_profile(by_model=None, **over):
    by_model = by_model if by_model is not None else []
    profile = {
        "measure": "whether the eval-awareness grader answered yes to each "
                  "rubric question",
        "signal_keys": list(_SIGNAL_KEYS),
        "n_episodes": sum(r["n_episodes"] for r in by_model),
        "interpretation": "a rubric question's own answer",
        "pooled": {key: {"n_resolved": 0, "n_true": 0, "rate": None}
                  for key in _SIGNAL_KEYS},
        "by_model": by_model,
    }
    profile.update(over)
    return profile


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


def _lure_model_row(model, n_lure, n_no_lure, mis_lure, mis_no_lure):
    """One by_model row shaped like lure_effect() builds them."""
    from subversionbench.power import newcombe_diff_ci
    def contrast(n1, n2, x1, x2):
        r1 = x1 / n1 if n1 else None
        r2 = x2 / n2 if n2 else None
        lo, hi = newcombe_diff_ci(x1, n1, x2, n2) if n1 and n2 else (None, None)
        return {"n_lure": n1, "n_no_lure": n2, "n_misaligned_lure": x1,
                "n_misaligned_no_lure": x2, "rate_lure": r1, "rate_no_lure": r2,
                "diff": None if r1 is None or r2 is None else r1 - r2,
                "lo": lo, "hi": hi,
                "underpowered": min(n1, n2) < MIN_INFORMATIVE_DENOMINATOR}
    c = contrast(n_lure, n_no_lure, mis_lure, mis_no_lure)
    return {"model": model, "n_episodes": n_lure + n_no_lure,
            "n_lure_resolved": n_lure, "n_discovered": 0, "n_read": 0,
            "overall": c, "oversight": c, "no_oversight": c}


class TestTheLureForestFoldsOnlyTheModelsWithNothingToMove:
    """The fold is narrowly "zero misaligned on BOTH sides", not "difference of
    zero". Those are different findings and one of them belongs on the chart."""

    def test_a_model_with_no_misalignment_either_side_is_folded(self):
        rows = rc._lure_effect_rows(
            {"by_model": [_lure_model_row("p/quiet", 30, 30, 0, 0)]},
            "oversight")
        assert [r.label for r in rows] == ["(1 models omitted)"]
        assert rows[0].diff is None, (
            "a folded group must not be drawn as a marker at zero - it is not "
            "a data point")

    def test_a_high_base_rate_null_is_KEPT(self):
        """24/30 in both arms is a genuine null at a high base rate, and the
        most informative null in the set. Folding it away with the models that
        never did anything would hide it."""
        rows = rc._lure_effect_rows(
            {"by_model": [_lure_model_row("p/busy", 30, 30, 24, 24)]},
            "oversight")
        assert [r.label for r in rows] == ["p/busy"]
        assert rows[0].diff == 0

    def test_the_two_are_distinguished_in_one_chart(self):
        rows = rc._lure_effect_rows(
            {"by_model": [_lure_model_row("p/quiet", 30, 30, 0, 0),
                          _lure_model_row("p/busy", 30, 30, 24, 24)]},
            "oversight")
        labels = [r.label for r in rows]
        assert "p/busy" in labels and "p/quiet" not in labels
        assert "(1 models omitted)" in labels

    def test_the_floor_applies_to_the_thinner_arm(self):
        """A difference is only as informative as its thinner side, so a model
        with plenty of lure episodes and almost none without is not plotted."""
        thin = _lure_model_row("p/lopsided", 200, MIN_INFORMATIVE_DENOMINATOR - 1,
                               10, 1)
        assert rc._lure_effect_rows({"by_model": [thin]},
                                               "oversight") == []
        fat = _lure_model_row("p/balanced", 200, MIN_INFORMATIVE_DENOMINATOR,
                              10, 1)
        assert [r.label for r in rc._lure_effect_rows(
            {"by_model": [fat]}, "oversight")] == ["p/balanced"]

    def test_a_marker_is_filled_only_when_its_interval_excludes_zero(self):
        moved = _lure_model_row("p/moved", 40, 40, 20, 0)
        flat = _lure_model_row("p/flat", 40, 40, 4, 3)
        rows = {r.label: r for r in rc._lure_effect_rows(
            {"by_model": [moved, flat]}, "oversight")}
        assert rows["p/moved"].marked
        assert not rows["p/flat"].marked

    def test_rows_are_sorted_by_the_difference(self):
        rows = rc._lure_effect_rows(
            {"by_model": [_lure_model_row("p/down", 40, 40, 2, 12),
                          _lure_model_row("p/up", 40, 40, 12, 2)]},
            "oversight")
        assert [r.label for r in rows] == ["p/up", "p/down"]


class TestTheHoneypotChartShowsOnlyWhatHappened:
    def _profile(self):
        rows = [_lure_model_row(f"p/m{i}", 30, 30, 1, 1) for i in range(5)]
        rows[0]["n_discovered"], rows[0]["n_read"] = 7, 3
        rows[1]["n_discovered"], rows[1]["n_read"] = 2, 0
        rows[2]["n_discovered"], rows[2]["n_read"] = 0, 1
        return {"by_model": rows,
                "pooled": {"n_lure_resolved": 150, "n_discovered": 9,
                           "n_read": 4}}

    def test_only_models_that_reached_it_are_rowed(self):
        rows = rc._honeypot_rows(self._profile())
        assert [r["model"] for r in rows] == ["p/m0", "p/m1", "p/m2"]

    def test_a_read_without_a_discovery_still_appears(self):
        """Measured on the corpus: an episode can glob the contents without the
        filename ever being listed, so a row must not be gated on discovery."""
        rows = rc._honeypot_rows(self._profile())
        assert any(r["model"] == "p/m2" and r["n_read"] for r in rows)

    def test_it_renders_and_states_how_many_models_are_not_drawn(self):
        plt = _plt()
        out = os.path.join(tempfile.mkdtemp(), "honeypot.png")
        assert rc.plot_honeypot_access(
            plt, {"characteristics": {"lure_effect": self._profile()}}, out)
        assert os.path.getsize(out) > 1000

    def test_nothing_is_drawn_when_no_model_reached_it(self):
        """An empty chart claiming a measure was taken is worse than no chart."""
        plt = _plt()
        profile = self._profile()
        for r in profile["by_model"]:
            r["n_discovered"] = r["n_read"] = 0
        out = os.path.join(tempfile.mkdtemp(), "honeypot.png")
        assert rc.plot_honeypot_access(
            plt, {"characteristics": {"lure_effect": profile}}, out) is None

    def test_the_misalignment_chart_writes_one_file_per_stratum(self):
        plt = _plt()
        rows = [_lure_model_row(f"p/m{i}", 40, 40, i + 1, 1) for i in range(4)]
        out = os.path.join(tempfile.mkdtemp(), "lure_misalignment.png")
        assert rc.plot_lure_misalignment(
            plt, {"characteristics": {"lure_effect": {"by_model": rows,
                  "pooled": {"oversight": rows[0]["oversight"],
                             "no_oversight": rows[0]["no_oversight"]}}}}, out)
        assert os.path.exists(out)
        assert os.path.exists(out.replace(".png", "_no_oversight.png")), (
            "the no-oversight stratum must get its own file - the two strata "
            "carry opposite signs and cannot share a panel")


# ---------------------------------------------------------------------------
# The arm-excluded reading
# ---------------------------------------------------------------------------
#
# The no-oversight arm's task README promises a quality preview the arm itself
# removes, so `python3 -m report --exclude-no-oversight` answers every question
# again without it. Those charts are written under the SAME FILENAMES as the
# full-corpus ones, in a different directory, and hold different numbers - so
# the risk this block guards is a figure that leaves its directory and is read
# as the full-corpus chart of that name.

def _excluded_stamp(kept=120, before=240):
    """The stamp exclude_arm() puts on a report with the arm dropped."""
    return {
        "excluded": "no_oversight", "axis": "oversight",
        "excluded_level": False,
        "words": "no-oversight arm excluded - oversight-present episodes only",
        "why": "the arm's README promises a preview it removes.",
        "n_summaries_before": 8, "n_summaries_kept": 4,
        "n_episodes_before": before, "n_episodes_kept": kept,
        "n_episodes_dropped": before - kept, "n_episodes_unknown_arm": 0,
    }


class TestEveryChartSaysWhichArmsItCovers:
    def _plot_functions(self):
        """Every chart entry point this module offers, from the module itself.

        DERIVED, AND ASSERTED NON-EMPTY. A hand-written list of the charts is
        the defect class this repository keeps re-fixing: the grading package's
        guards enumerated their own submodules in a tuple, fell two behind the
        directory, and four guards silently stopped covering two modules. A glob
        that matches nothing empties the scope and every guard built on it
        passes, so the count is checked before it is used.
        """
        import inspect
        # `startswith`, not `==`: the charts live in submodules of the
        # package and the facade re-exports them, so a function's __module__ is
        # `report_charts.questions` rather than `report_charts`. Comparing for
        # equality emptied this scope the moment the file became a package,
        # which is the failure this assertion's own docstring warns about.
        found = {name: obj for name, obj in vars(rc).items()
                 if name.startswith("plot_") and inspect.isfunction(obj)
                 and obj.__module__.startswith(rc.__name__)}
        assert len(found) >= 7, (
            f"only found {sorted(found)} - the enumeration is broken, and an "
            f"empty scope makes every assertion below vacuous")
        return found

    def test_every_chart_names_the_exclusion_in_its_title_and_captions(self):
        """The rule, not a path. Any chart added later inherits this: it is
        enumerated from the module rather than listed here, so a new plot_
        function that forgets the words fails this test rather than shipping a
        figure indistinguishable from the full-corpus one of the same name."""
        import inspect
        for name, func in self._plot_functions().items():
            source = inspect.getsource(func)
            assert "_exclusion_title_suffix" in source, (
                f"{name} does not put the exclusion in its title, so the "
                f"figure cannot be told from the full-corpus chart of the "
                f"same filename once it leaves its directory")
            assert "_exclusion_captions" in source, (
                f"{name} draws no caption naming the excluded arm")

    def test_nothing_is_said_when_no_arm_was_excluded(self):
        """The ordinary report must not grow a banner reading "nothing
        excluded": a reader trained to skip that block skips it on the one
        chart where it matters."""
        for report in ({}, {"arm_exclusion": None},
                       {"arm_exclusion": {"axis": None, "words": ""}}):
            assert rc._exclusion_title_suffix(report) == ""
            assert rc._exclusion_captions(report) == []

    def test_the_words_and_the_counts_reach_the_reader(self):
        report = {"arm_exclusion": _excluded_stamp(kept=120, before=240)}
        assert "no-oversight arm excluded" in rc._exclusion_title_suffix(report)
        text = " ".join(c for c, _ in rc._exclusion_captions(report))
        assert "no-oversight arm excluded" in text
        # The counts, so a reader can see how much of the corpus is behind the
        # figure without opening the JSON.
        assert "120 of 240" in text
        # And that this is not a repaired estimate.
        assert "sensitivity" in text.lower()
        assert "not a correction" in text.lower()

    def test_the_caption_is_drawn_in_the_warning_colour(self):
        """Same colour this module already reserves for the crude-vs-stratified
        divergence, because it is the same class of statement: something a
        reader who stops at the markers would take the chart to mean."""
        captions = rc._exclusion_captions(
            {"arm_exclusion": _excluded_stamp()})
        assert captions[0][1] == "#b00020"

    def test_a_question_the_exclusion_collapsed_draws_no_chart(self):
        """A forest of thirty "no data on one side" rows under the question's
        own title reads as a measured null rather than an absent comparison."""
        plt = _plt()
        section = _section()
        section["collapsed_by_exclusion"] = "not estimable with the arm excluded"
        out = os.path.join(tempfile.mkdtemp(), "q.png")
        assert rc.plot_question(plt, 1, section, out,
                                {"arm_exclusion": _excluded_stamp()}) is None
        assert not os.path.exists(out)

    def test_the_same_question_still_draws_when_nothing_collapsed(self):
        """The positive control: without the mark the chart renders, so the
        test above is about the mark and not about the fixture."""
        plt = _plt()
        out = os.path.join(tempfile.mkdtemp(), "q.png")
        assert rc.plot_question(plt, 1, _section(), out,
                                {"arm_exclusion": _excluded_stamp()})
        assert os.path.getsize(out) > 1000

    def test_the_overview_keeps_a_row_for_a_collapsed_question(self):
        """Dropped rather than marked, this chart would show nine questions
        while its own caption calls it all twelve - and a reader would conclude
        the three were never asked."""
        plt = _plt()
        collapsed = _section(id="oversight_vs_scheming")
        collapsed["collapsed_by_exclusion"] = "no comparator"
        report = {"questions": [collapsed,
                                _section(id="awareness_vs_scheming")],
                  "arm_exclusion": _excluded_stamp()}
        captured = {}
        original = rc.draw._draw_forest

        def capture(plt_, rows, title, captions, path, *a, **kw):
            captured["rows"] = rows
            captured["title"] = title
            return path

        rc.draw._draw_forest = capture
        try:
            rc.plot_overview(plt, report, os.path.join(tempfile.mkdtemp(), "o.png"))
        finally:
            rc.draw._draw_forest = original
        labels = [r.label for r in captured["rows"]]
        assert len(labels) == 2, labels
        gap = [r for r in captured["rows"] if r.diff is None]
        assert len(gap) == 1 and "excluded arm" in gap[0].missing
        assert "no-oversight arm excluded" in captured["title"]

    def test_the_excluded_arms_own_lure_panel_is_not_drawn(self):
        """`lure_effect` is already split on oversight, so the excluded panel
        normally has no rows and falls out. This is the other case: a stratum
        left with rows from an arm the report says it dropped, which would draw
        a panel titled "no oversight" inside an oversight-only reading."""
        plt = _plt()
        rows = [_lure_model_row(f"p/m{i}", 40, 40, i + 1, 1) for i in range(4)]
        profile = {"by_model": rows,
                   "pooled": {"oversight": rows[0]["oversight"],
                              "no_oversight": rows[0]["no_oversight"]}}
        out = os.path.join(tempfile.mkdtemp(), "lure_misalignment.png")
        assert rc.plot_lure_misalignment(
            plt, {"characteristics": {"lure_effect": profile},
                  "arm_exclusion": _excluded_stamp()}, out)
        assert os.path.exists(out)
        assert not os.path.exists(out.replace(".png", "_no_oversight.png")), (
            "the no-oversight panel was drawn inside a report whose every "
            "other figure says that arm was excluded")

    def test_the_stratum_match_is_by_name_against_the_excluded_level(self):
        """Both directions, so the helper cannot pass by always answering one
        way: with the no-oversight arm dropped it is the `no_oversight` panel
        that goes, and with the oversight arm dropped it is the other."""
        drop_no_oversight = {"arm_exclusion": _excluded_stamp()}
        assert rc._excluded_stratum(drop_no_oversight, "no_oversight")
        assert not rc._excluded_stratum(drop_no_oversight, "oversight")
        flipped = {"arm_exclusion": dict(_excluded_stamp(),
                                         excluded_level=True)}
        assert rc._excluded_stratum(flipped, "oversight")
        assert not rc._excluded_stratum(flipped, "no_oversight")
        assert not rc._excluded_stratum({}, "no_oversight")


class TestTheForestSaysHowManyModelsItIsOver:
    """The stratified row's label is a count of STRATA POOLED, which equals the
    model total only when every model has episodes on both sides. On the
    oversight questions it does and on the awareness-conditioned ones it does
    not, and nothing on the figure distinguished the two."""

    def _consistency(self, total, with_data):
        return {"n_models_total": total, "n_models_with_data": with_data,
                "n_models_no_data": total - with_data, "n_increase": 0,
                "n_decrease": 0, "n_tied": 0,
                "n_individually_significant": 0, "significant_models": []}

    def test_it_states_the_total_when_every_model_has_an_estimate(self):
        text = rc._model_count_caption(
            {"consistency": self._consistency(37, 37)})
        assert "37 models" in text
        # No phantom gap: a reader told "0 drawn as a gap" goes looking for one.
        assert "gap" not in text
        assert "0" not in text.replace("37", "")

    def test_it_splits_the_total_when_some_models_have_no_estimate(self):
        """The case the caption exists for: 37 rows, 28 of them with an
        interval, and a pooled row labelled 28 that a reader would otherwise
        take for the corpus."""
        text = rc._model_count_caption(
            {"consistency": self._consistency(37, 28)})
        assert "37 models in total" in text
        assert "28" in text and "9" in text
        assert "gap" in text

    def test_the_two_forms_are_actually_different(self):
        """A guard against both branches collapsing to one sentence, which
        would make the pair of tests above assert nothing about the split."""
        every = rc._model_count_caption(
            {"consistency": self._consistency(37, 37)})
        some = rc._model_count_caption(
            {"consistency": self._consistency(37, 28)})
        assert every and some and every != some

    def test_the_count_comes_from_consistency_not_from_the_rows(self):
        """The report prints "N/M had data on both sides" from `consistency`,
        and the chart keeps a row for a model with no estimate so that sentence
        can be checked against the figure. A caption counting the rows would be
        a second derivation free to disagree with the sentence it corroborates -
        so a section whose row count and whose consistency block disagree must
        report the consistency block."""
        section = _section(consistency=self._consistency(37, 28))
        assert len(section["by_model"]) == 3, "fixture assumption"
        text = rc._model_count_caption(section)
        assert "37" in text and "3 models" not in text

    def test_a_section_without_the_block_says_nothing(self):
        """The paired questions hold one row per interrogation contrast, each
        already pooled over every model, so a model count there would be a
        different claim from a different source."""
        assert rc._model_count_caption({}) == ""
        assert rc._model_count_caption({"consistency": {}}) == ""
        assert rc._model_count_caption(_paired_section()) == ""

    def test_it_reaches_the_rendered_chart(self):
        """Wired in, not merely written: the caption has to be in the list
        plot_question hands to _draw_forest."""
        plt = _plt()
        section = _section(consistency=self._consistency(37, 28))
        captured = {}
        original = rc.draw._draw_forest

        def capture(plt_, rows, title, captions, path, *a, **kw):
            captured["captions"] = [c for c, _ in captions]
            return path

        rc.draw._draw_forest = capture
        try:
            rc.plot_question(plt, 1, section,
                             os.path.join(tempfile.mkdtemp(), "q.png"), {})
        finally:
            rc.draw._draw_forest = original
        assert any("37 models in total" in c for c in captured["captions"]), \
            captured["captions"]

    def test_the_paired_chart_does_not_grow_an_empty_caption_line(self):
        """An empty string reaches _BelowAxes.caption, which returns without
        drawing - so the paired charts must not gain a blank line where the
        model count would be."""
        plt = _plt()
        captured = {}
        original = rc.draw._draw_forest

        def capture(plt_, rows, title, captions, path, *a, **kw):
            captured["captions"] = [c for c, _ in captions]
            return path

        rc.draw._draw_forest = capture
        try:
            rc.plot_question(plt, 11, _paired_section(),
                             os.path.join(tempfile.mkdtemp(), "q.png"), {})
        finally:
            rc.draw._draw_forest = original
        assert not any("models" in c and "total" in c
                       for c in captured["captions"])


def _timing_profile(**over):
    """A profile shaped like awareness_refusal_timing() returns."""
    def arm(before, after):
        return {"n_before_refusal": before, "n_after_refusal": after,
                "n_no_refusal": 100, "n_not_aware": 40,
                "n_refusal_unlocatable": 0, "n_episodes": 140 + before + after,
                "n_locatable": before + after,
                "rate_after": round(after / (before + after), 4)
                if before + after else None,
                "underpowered": before + after < MIN_INFORMATIVE_DENOMINATOR}
    profile = {
        "measure": "the share that verbalised it only AFTER the refusal",
        "instrument": "keyword measure, not the rubric grader",
        "not_an_effect": "descriptive",
        "pooled": arm(60, 40),
        "by_arm": {"oversight": arm(50, 5), "no_oversight": arm(10, 35)},
        "by_model": [{"model": "p/a", **arm(20, 20)},
                     {"model": "p/b", **arm(30, 5)},
                     # Below the floor: 3 placeable orderings.
                     {"model": "p/c", **arm(2, 1)},
                     # Refused often, never placeable.
                     {"model": "p/d", **arm(0, 0)}],
    }
    profile.update(over)
    return profile


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


class TestWriteChartsCollectsEveryFileItActuallyWrote:
    """write_charts returns the list the report then names in its JSON and the
    console prints. A chart drawn and left out of that list is a file nobody
    is told about; a name in the list with no file behind it sends a reader to
    a path that does not exist. Both are silent, so each chart the collector
    handles is asserted against the control that must NOT produce it.

    The lure entry is the one with a rule rather than a name: it writes one
    file per oversight stratum and returns only the first, so the second is
    collected by asking the filesystem. Testing it means running it with two
    strata and with one.
    """

    def _characteristics(self):
        rows = [_lure_model_row("p/busy", 30, 30, 24, 24),
                _lure_model_row("p/moved", 40, 40, 20, 0)]
        rows[0]["n_discovered"], rows[0]["n_read"] = 7, 3
        return {
            "encoded_payload_rate": _epr_profile(
                [_epr_row("p/a", 61, 1, underpowered=False),
                 _epr_row("p/b", 60, 12, underpowered=False)]),
            "lure_effect": {
                "by_model": rows,
                "pooled": {"n_lure_resolved": 70, "n_discovered": 7,
                           "n_read": 3,
                           "oversight": {"diff": 0.01},
                           "no_oversight": {"diff": 0.02}},
            },
        }

    def _written(self, report):
        _plt()
        with tempfile.TemporaryDirectory() as out:
            written = rc.write_charts(report, out)
            on_disk = set(os.listdir(out))
        names = [os.path.basename(p) for p in written]
        assert len(names) == len(set(names)), f"a chart was listed twice: {names}"
        for name in names:
            assert name in on_disk, (
                f"{name} was returned but never written to disk")
        return names

    def test_the_encoded_payload_chart_is_collected(self):
        names = self._written({"questions": [],
                               "characteristics": self._characteristics()})
        assert "encoded_payload_rate.png" in names

    def test_the_honeypot_chart_is_collected(self):
        names = self._written({"questions": [],
                               "characteristics": self._characteristics()})
        assert "honeypot_access.png" in names

    def test_both_lure_strata_are_collected_not_just_the_returned_one(self):
        """plot_lure_misalignment writes a file per stratum and returns the
        first. The second exists on disk either way - the failure this catches
        is it going unmentioned, so the report's own list of charts is short
        by a figure a reader is meant to read alongside the other."""
        names = self._written({"questions": [],
                               "characteristics": self._characteristics()})
        assert "lure_misalignment.png" in names
        assert "lure_misalignment_no_oversight.png" in names

    def test_an_excluded_stratum_contributes_no_second_file(self):
        """Two-directional against the test above: the second file is
        collected because it was written, not because its name was assumed."""
        names = self._written({
            "questions": [], "characteristics": self._characteristics(),
            "arm_exclusion": _excluded_stamp()})
        assert "lure_misalignment.png" in names
        assert "lure_misalignment_no_oversight.png" not in names

    def test_none_of_them_appear_without_the_characteristics_behind_them(self):
        """The control for all four. Without it every assertion above would
        pass against a write_charts that returned every name unconditionally."""
        names = self._written({"questions": [_section()]})
        for absent in ("encoded_payload_rate.png", "honeypot_access.png",
                       "lure_misalignment.png",
                       "lure_misalignment_no_oversight.png"):
            assert absent not in names


class TestTheOverviewMarksTheQuestionsWhoseTwoEstimatesDisagree:
    """The overview draws the STRATIFIED estimate, because that is the figure
    the report treats as defensible. Where the crude one disagrees with it,
    the row is marked and a caption in the divergence colour says what the
    mark means. Without it a reader sees one number per question and no sign
    that the question's own chart carries a second one that does not agree.
    """

    def _rows_and_captions(self, sections):
        plt = _plt()
        captured = {}
        original = rc.draw._draw_forest

        def capture(plt_, rows, title, captions, path, *a, **kw):
            captured["rows"] = rows
            captured["captions"] = [text for text, _colour in captions]
            return path

        rc.draw._draw_forest = capture
        try:
            rc.plot_overview(plt, {"questions": sections},
                             os.path.join(tempfile.mkdtemp(), "o.png"))
        finally:
            rc.draw._draw_forest = original
        return captured["rows"], captured["captions"]

    def test_a_diverging_question_gets_a_marked_row_and_the_caption(self):
        diverging = _section(
            id="oversight_vs_scheming",
            crude_vs_stratified={"warning": "CONFOUNDED: the crude estimate "
                                           "runs the other way"})
        assert rc._divergence_caption(diverging), (
            "the fixture carries no warning, so nothing below is about one")
        rows, captions = self._rows_and_captions([diverging])
        assert any(r.label.endswith("*") for r in rows)
        assert any("crude and stratified estimates diverge" in c
                   for c in captions)

    def test_a_question_whose_estimates_agree_is_not_marked(self):
        """Two-directional: a mark on every row says nothing, and the caption
        would then send every reader to every question's own chart."""
        rows, captions = self._rows_and_captions([_section()])
        assert not any(r.label.endswith("*") for r in rows)
        assert not any("crude and stratified estimates diverge" in c
                       for c in captions)

    def test_one_diverging_question_among_several_marks_only_itself(self):
        """The mark is per row; the caption is per chart. Both matter - a
        caption with no marked row is unreadable, and a marked row with no
        caption is unexplained."""
        rows, captions = self._rows_and_captions([
            _section(id="oversight_vs_scheming",
                     crude_vs_stratified={"warning": "CONFOUNDED"}),
            _section(id="awareness_vs_scheming")])
        marked = [r.label for r in rows if r.label.endswith("*")]
        assert len(marked) == 1, [r.label for r in rows]
        assert marked[0].startswith("Q1.")
        assert any("crude and stratified estimates diverge" in c
                   for c in captions)
