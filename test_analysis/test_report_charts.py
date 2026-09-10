"""
The twelve research-question charts, and the overview that holds all twelve.

A chart is a second reading of numbers the printed report already carries, so
the thing worth testing is not that matplotlib drew something: it is that the
chart cannot say anything the report does not, and cannot quietly leave out
something the report does. Most of what follows checks the ROWS - what gets a
line, what it is labelled, where it sits - because that is where a chart can lie
about an analysis while still rendering.
"""


import json
import os
import tempfile

import report as run_report
import report.run_report as rr
import report_charts as rc
import report_charts.questions  # noqa: F401
from subversionbench import charting
from test_analysis.test_run_report import _two_arm_dir
from test_analysis.chart_fixtures import (
    _contrast, _paired_section, _plt, _section)


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


class TestACollapsedRowSaysWhyTheSectionSaysItCollapsed:
    """The overview must not invent a cause.

    `collapsed_by_exclusion` is attached by TWO different narrowings - dropping
    an arm, and the awareness reading - and build_report puts both on that one
    field, justified in as many words by "the two consumers of it - the console
    banner and the chart layer's skip - already do the right thing with
    whatever reason is attached".

    The banner did. This layer read the field as a boolean and printed
    "no comparator - the excluded arm was one side of this contrast", which
    names an arm exclusion; under --exclude-aware no arm is excluded and 8 of
    the 12 questions collapse, so 8 rows named a cause that had not occurred.
    The claim was half true and nothing checked the other half.

    Reasons come from real reports under both readings rather than from a list
    written here, so a third narrowing - or a reworded reason - inherits these
    checks instead of escaping them.
    """

    def _collapsed_reasons(self):
        """Every reason build_report actually attaches, both readings."""
        out = _two_arm_dir()
        reasons = {}
        for exclusion, awareness in ((rr.EXCLUDE_NO_OVERSIGHT,
                                      rr.NO_AWARENESS_EXCLUSION),
                                     (rr.NO_EXCLUSION,
                                      rr.EXCLUDE_AWARE_PRIMARY)):
            report = rr.build_report(out, exclusion, awareness)
            for section in report["questions"]:
                if section.get("collapsed_by_exclusion"):
                    reasons[section["id"]] = section["collapsed_by_exclusion"]
        return reasons

    def test_both_narrowings_actually_collapse_something(self):
        """Without this the three tests below pass on an empty set."""
        out = _two_arm_dir()
        by_reading = {}
        for name, (exclusion, awareness) in (
                ("arm", (rr.EXCLUDE_NO_OVERSIGHT, rr.NO_AWARENESS_EXCLUSION)),
                ("awareness", (rr.NO_EXCLUSION, rr.EXCLUDE_AWARE_PRIMARY))):
            report = rr.build_report(out, exclusion, awareness)
            by_reading[name] = [s["id"] for s in report["questions"]
                                if s.get("collapsed_by_exclusion")]
        assert by_reading["arm"], "the arm reading collapsed nothing"
        assert by_reading["awareness"], "the awareness reading collapsed nothing"

    def test_the_row_label_is_the_sections_own_reason(self):
        """A prefix, not merely non-empty: the label has to be shortened to
        render at fontsize 7, and shortening is the only liberty it may take."""
        for qid, reason in self._collapsed_reasons().items():
            label = rc.questions._missing_label(reason)
            assert reason.startswith(label), (
                f"{qid}: the row says {label!r}, which is not what the "
                f"section says: {reason!r}")
            assert label, f"{qid}: the row says nothing"

    def test_no_row_blames_an_arm_exclusion_on_the_awareness_reading(self):
        """The defect itself, stated as the thing a reader would be told."""
        out = _two_arm_dir()
        report = rr.build_report(out, rr.NO_EXCLUSION,
                                 rr.EXCLUDE_AWARE_PRIMARY)
        collapsed = [s for s in report["questions"]
                     if s.get("collapsed_by_exclusion")]
        assert collapsed, "nothing collapsed, so this checks nothing"
        for section in collapsed:
            label = rc.questions._missing_label(
                section["collapsed_by_exclusion"])
            assert "arm" not in label, (
                f"{section['id']} tells the reader an arm was excluded, and "
                f"none was: {label!r}")
            assert "unaware corpus" in label, label

    def _overview_rows(self, report):
        """The rows plot_overview actually hands the drawing layer."""
        captured = {}
        original = rc.draw._draw_forest

        def capture(plt_, rows, *a, **kw):
            captured["rows"] = rows
            return a[2] if len(a) > 2 else "p.png"

        rc.draw._draw_forest = capture
        try:
            rc.plot_overview(_plt(), report,
                             os.path.join(tempfile.mkdtemp(), "o.png"))
        finally:
            rc.draw._draw_forest = original
        return captured["rows"]

    def test_the_drawn_row_carries_it_end_to_end(self):
        """THE DISCRIMINATING ONE. Every test above calls `_missing_label`
        directly, so all of them pass with the call site reverted to a
        hardcoded string - which is the defect. This runs plot_overview and
        reads what it handed the drawing layer.
        """
        out = _two_arm_dir()
        report = rr.build_report(out, rr.NO_EXCLUSION,
                                 rr.EXCLUDE_AWARE_PRIMARY)
        # Keyed by the row prefix plot_overview builds, so the collapsed rows
        # can be told from the paired questions' own "no paired units" rows -
        # 11 and 12 name awareness on neither side and fall out on their own,
        # which is a different fact and legitimately worded differently.
        reasons = {f"Q{i}.": section["collapsed_by_exclusion"]
                   for i, section in enumerate(report["questions"], start=1)
                   if section.get("collapsed_by_exclusion")}
        assert reasons, "nothing collapsed, so this checks nothing"

        checked = 0
        for row in self._overview_rows(report):
            prefix = row.label.split(" ", 1)[0]
            if prefix not in reasons:
                continue
            checked += 1
            reason = reasons[prefix]
            assert row.missing, f"{row.label} was drawn with no reason on it"
            assert reason.startswith(row.missing), (
                f"{row.label} was drawn saying {row.missing!r}, which is not "
                f"the start of what its section says: {reason!r}")
            assert "excluded arm" not in row.missing, (
                f"{row.label} still blames an arm exclusion: {row.missing!r}")
        assert checked == len(reasons), (
            f"{checked} of {len(reasons)} collapsed questions reached a row")

    def test_the_label_is_short_enough_to_draw(self):
        """Why the full reason cannot simply be passed through: it is a
        sentence of 145 characters or more, drawn beside a row at fontsize 7."""
        for qid, reason in self._collapsed_reasons().items():
            assert len(reason) > 60, (
                f"{qid}: this reason is short enough to pass whole, so the "
                f"shortening below is not being exercised")
            assert len(rc.questions._missing_label(reason)) <= 60, qid

    def test_a_reason_with_no_colon_is_passed_through_whole(self):
        """The headline split is a convention the producers keep, not a
        guarantee. A reason that does not follow it must not become empty."""
        assert rc.questions._missing_label("nothing to compare") == (
            "nothing to compare")


class TestTheCrudeEstimateIsDemotedWhenTheReportSaysNotToReadIt:
    """`crude_vs_stratified` already prints a red caption saying to report the
    stratified result. Drawn in full colour beside it, the crude diamond
    contradicted that caption in the channel a reader trusts first."""

    def _section(self, diverges: bool) -> dict:
        return {
            "overall": {"difference": -0.037, "difference_ci95": [-0.05, -0.024],
                        "separated": True},
            "stratified": {"mantel_haenszel": {
                "risk_difference": 0.002,
                "risk_difference_ci95": [-0.017, 0.022],
                "n_strata_used": 29, "separated": False}},
            "crude_vs_stratified": {"diverges": diverges, "warning": "x"},
        }

    def _crude(self, diverges: bool):
        rows = rc._pooled_rows(self._section(diverges))
        return next(r for r in rows if r.kind == "crude")

    def test_it_is_demoted_where_the_two_disagree(self):
        assert self._crude(True).demoted is True

    def test_it_is_not_demoted_where_they_agree(self):
        """The other direction. A version that demoted the crude row always
        would pass the check above and make the warning meaningless."""
        assert self._crude(False).demoted is False

    def test_the_stratified_row_is_never_demoted(self):
        """It is the row the warning tells the reader to use."""
        for diverges in (True, False):
            rows = rc._pooled_rows(self._section(diverges))
            strat = next(r for r in rows if r.kind == "stratified")
            assert strat.demoted is False

    def test_a_demoted_row_is_drawn_in_the_demoted_colour(self):
        """Wiring, not just the flag: setting the flag and never reading it
        would leave the chart identical and every check above passing."""
        from report_charts.draw import _row_colour
        from report_charts.style import _COLOURS, _DEMOTED_COLOUR
        demoted = rc.Row("x", -0.037, -0.05, -0.024, "crude",
                             marked=True, demoted=True)
        plain = rc.Row("x", -0.037, -0.05, -0.024, "crude", marked=True)
        assert _row_colour(demoted) == _DEMOTED_COLOUR
        assert _row_colour(plain) == _COLOURS["crude"]

    def test_demotion_outranks_the_significance_colour(self):
        """A demoted per-model row must not come back red for having cleared
        zero - the loudest colour on the chart for the row being disowned."""
        from report_charts.draw import _row_colour
        from report_charts.style import _DEMOTED_COLOUR
        row = rc.Row("m", 0.5, 0.1, 0.9, "model", marked=True,
                         demoted=True)
        assert _row_colour(row) == _DEMOTED_COLOUR


class TestThePooledEstimatesCarryTheirNumbers:
    """The pooled intervals cannot be judged by eye at any usable axis: the
    model intervals have a median width near 30pp, so the axis is at least
    ~40pp wide, and the crude pooled interval is 2.6pp. Clipping the axis was
    tried and removed - it cannot make that legible without clipping away the
    models the forest exists to show."""

    def _rows(self):
        return rc._pooled_rows({
            "overall": {"difference": -0.037, "difference_ci95": [-0.05, -0.024],
                        "separated": True},
            "stratified": {"mantel_haenszel": {
                "risk_difference": 0.0018,
                "risk_difference_ci95": [-0.017, 0.0221],
                "n_strata_used": 29, "separated": False}},
        })

    def test_both_pooled_rows_state_their_estimate_and_interval(self):
        for row in self._rows():
            assert row.note, f"{row.label} carries no number"
            assert "[" in row.note and "]" in row.note

    def test_the_numbers_are_the_ones_in_the_report(self):
        """Read off the row, not recomputed: a note showing a different
        number from the mark beside it is worse than no note."""
        crude = next(r for r in self._rows() if r.kind == "crude")
        assert crude.note == "-3.7 [-5.0, -2.4]"

    def test_a_sign_is_always_shown(self):
        """+0.2 and 0.2 read differently beside a row about a difference."""
        strat = next(r for r in self._rows() if r.kind == "stratified")
        assert strat.note.startswith("+")

    def test_a_model_row_carries_no_number(self):
        """Twenty-nine of these would be noise, and the axis places them well
        enough - it is only the pooled rows the axis cannot serve."""
        rows = rc._model_rows([
            {"model": "m", "difference": 0.1,
             "difference_ci95": [0.0, 0.2],
             "a": {"successes": 1, "n": 10}, "b": {"successes": 0, "n": 10}}])
        assert all(not r.note for r in rows)

    def test_a_missing_interval_still_states_the_estimate(self):
        assert rc._effect_note(-0.037, None, None) == "-3.7"

    def test_nothing_is_stated_for_a_missing_estimate(self):
        assert rc._effect_note(None, None, None) == ""


class TestTheLegendShowsWhatIsActuallyDrawn:
    """A legend keyed off the palette said "crude pooled" beside an orange
    line while the crude diamond on the chart was grey - the same fault as a
    caption contradicting its marks, one box lower."""

    def _handles(self, demoted: bool):
        rows = [rc.Row("m", 0.1, 0.0, 0.2, "model"),
                rc.Row("CRUDE", -0.037, -0.05, -0.024, "crude",
                       demoted=demoted),
                rc.Row("MH", 0.002, -0.017, 0.022, "stratified")]
        from report_charts.draw import _legend_handles
        return {h.get_label(): h for h in _legend_handles(rows)}

    def test_a_demoted_kind_is_greyed_in_the_legend_too(self):
        from report_charts.style import _DEMOTED_COLOUR
        entry = next(h for label, h in self._handles(True).items()
                     if label.startswith("crude pooled"))
        assert entry.get_color() == _DEMOTED_COLOUR

    def test_an_undemoted_kind_keeps_its_own_colour(self):
        """The other direction: greying it always would make the legend say
        nothing about which estimate the report disowned."""
        from report_charts.style import _COLOURS
        entry = self._handles(False)["crude pooled"]
        assert entry.get_color() == _COLOURS["crude"]

    def test_the_demoted_entry_points_at_the_caption(self):
        assert any(label.startswith("crude pooled") and "caption" in label
                   for label in self._handles(True))

    def test_the_other_kinds_are_untouched_by_a_demotion(self):
        from report_charts.style import _COLOURS
        handles = self._handles(True)
        assert handles["stratified (Mantel-Haenszel)"].get_color() == (
            _COLOURS["stratified"])
        assert handles["per model"].get_color() == _COLOURS["model"]

    def test_the_lookup_is_per_kind_and_not_the_first_row(self):
        """Demoting a MODEL row must not grey the pooled entries. The check
        above cannot see that fault: the model row comes first in a real
        forest, so a lookup that took the first row regardless of kind found
        an undemoted one and greyed nothing."""
        from report_charts.draw import _legend_handles
        from report_charts.style import _COLOURS
        rows = [rc.Row("m", 0.1, 0.0, 0.2, "model", demoted=True),
                rc.Row("CRUDE", -0.037, -0.05, -0.024, "crude"),
                rc.Row("MH", 0.002, -0.017, 0.022, "stratified")]
        handles = {h.get_label(): h for h in _legend_handles(rows)}
        assert handles["crude pooled"].get_color() == _COLOURS["crude"]
        assert handles["stratified (Mantel-Haenszel)"].get_color() == (
            _COLOURS["stratified"])

    def test_only_the_kinds_present_are_listed(self):
        """The behaviour the function already had, pinned before it was
        rewritten around it."""
        assert "parallel measure (visible text only)" not in self._handles(False)
