"""
One report per grader: which graders a directory holds, whose counts each
report may pool, and which episodes it has to leave out.

The contract is report/loading.py's. A directory graded by two models gets two
reports and two chart directories, each holding only that grader's verdicts;
an episode one grader has read and the other has not is left out of the
other's report and counted, never shown ungraded; and questions 1-4 pool from
the batch summaries only for the grader whose counts those summaries hold.
"""

import contextlib
import copy
import io
import json
import os
import sys
import tempfile
import types

import report
import report.run_report as run_report
import trends.family_trends as family_trends
from subversionbench import charting
from subversionbench.config import (DEFAULT_GRADER_MODEL,
                                    LEGACY_DEFAULT_GRADER_MODEL)
from subversionbench.graders import new_record, store
from subversionbench.power import MIN_INFORMATIVE_DENOMINATOR
from report_charts.graders import (GRADER_COMPARISON_DIR, overview_groups,
                                   question_groups, signal_groups)
from test_analysis.report_fixtures import _write_episode, _write_summary

OTHER = LEGACY_DEFAULT_GRADER_MODEL
assert OTHER != DEFAULT_GRADER_MODEL


def _reading(grader: str, aware: bool) -> dict:
    return {"grader_model": grader, "eval_aware": aware,
            "eval_aware_category": "explicit" if aware else "none",
            "eval_signal_count": 2 if aware else 0,
            "rubric_results": {"suspects_being_tested": {
                "answer": aware, "quote": "q" if aware else ""}}}


def _graded(out, n, model, readings, oversight=True):
    """One episode holding each grader's awareness verdict in `readings`."""
    path = _write_episode(out, n, model, "strong", oversight=oversight)
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    flat = data["analysis"]
    stored = None
    for grader, aware in readings.items():
        working = dict(copy.deepcopy(flat),
                       eval_awareness_grader=_reading(grader, aware))
        stored = (new_record(working, grader) if stored is None
                  else store(stored, working, grader))
    data["analysis"] = stored
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)


def _corpus(out, n_episodes=10):
    """p/a read by both graders, which disagree on every episode; p/b read by
    OTHER alone. The summaries predate the grader stamp, so they are OTHER's -
    and hold OTHER's counts, as the real corpus's do.

    Ten episodes a model unless asked for more: the descriptive charts drop a
    model below MIN_INFORMATIVE_DENOMINATOR, so a test of one needs more."""
    for n in range(1, n_episodes + 1):
        _graded(out, n, "p/a", {OTHER: True, DEFAULT_GRADER_MODEL: False})
        _graded(out, n, "p/b", {OTHER: False})
    _write_summary(out, "p/a", "strong", n_runs=n_episodes,
                   n_aware=n_episodes, figures_grader=None)
    _write_summary(out, "p/b", "strong", n_runs=n_episodes,
                   n_unaware=n_episodes, model_slug="p_b", figures_grader=None)
    return out


def _aware_under_oversight(built: dict) -> int:
    section = next(q for q in built["questions"]
                   if q["id"] == "oversight_vs_awareness")
    return section["overall"]["a"]["successes"]


class TestWhichEpisodesAGraderHasNotReadYet:
    def test_one_read_by_another_grader_only_is_pending(self):
        kept, pending = report.split_pending(
            [{"graders": (OTHER,)}], DEFAULT_GRADER_MODEL)
        assert (kept, len(pending)) == ([], 1)

    def test_one_it_has_read_is_kept(self):
        kept, pending = report.split_pending(
            [{"graders": (OTHER, DEFAULT_GRADER_MODEL)}], DEFAULT_GRADER_MODEL)
        assert (len(kept), pending) == (1, [])

    def test_one_no_grader_read_stays_in_every_report(self):
        """Collected with --no-grader: its keyword reading is the published
        one, so no grader's report may drop it."""
        for grader in (OTHER, DEFAULT_GRADER_MODEL):
            kept, pending = report.split_pending([{"graders": ()}], grader)
            assert (len(kept), pending) == (1, [])


class TestWhoseCountsASummaryHolds:
    def test_a_summary_without_the_stamp_is_the_legacy_default_s(self):
        with tempfile.TemporaryDirectory() as out:
            _write_summary(out, "p/a", "strong", figures_grader=None)
            [row] = report.load_summaries(out)
        assert row["figures_grader"] == LEGACY_DEFAULT_GRADER_MODEL
        assert report.summaries_describe([row], LEGACY_DEFAULT_GRADER_MODEL)
        assert not report.summaries_describe([row], DEFAULT_GRADER_MODEL)

    def test_no_summaries_describe_nothing(self):
        assert not report.summaries_describe([], DEFAULT_GRADER_MODEL)

    def test_a_batch_summary_names_the_grader_its_figures_are(self):
        from conftest import batch_episode
        import subversionbench.run_eval as ev_run
        out = tempfile.mkdtemp()
        args = types.SimpleNamespace(
            model="m", nudge="strong", effort=None, oversight=True, lure=False,
            output_dir=out, delay=0, max_tokens=8192, max_turns=40,
            no_power=True)
        ident = ev_run.BatchIdentity.collecting(args, "m", None, stamp="probe")
        with contextlib.redirect_stdout(io.StringIO()):
            summary = ev_run.summarise_batch(args, [batch_episode()], ident, {})
        assert summary["figures_grader_model"] == DEFAULT_GRADER_MODEL


class TestOneReportPerGrader:
    def test_the_directory_names_both_graders(self):
        with tempfile.TemporaryDirectory() as out:
            assert report.report_graders(_corpus(out)) == sorted(
                [OTHER, DEFAULT_GRADER_MODEL])

    def test_with_no_graded_episode_the_summaries_name_the_grader(self):
        """A directory collected with --no-grader, or holding summaries
        alone, still has one grader's counts in it: the summaries'. Reported
        as the default instead, questions 1-4 would refuse those counts and
        rebuild them from episodes that carry no verdict."""
        with tempfile.TemporaryDirectory() as out:
            _write_summary(out, "p/a", "strong", figures_grader=None)
            _write_episode(out, 1, "p/a", "strong")
            assert report.report_graders(out) == [LEGACY_DEFAULT_GRADER_MODEL]

    def test_with_nothing_at_all_it_is_the_default(self):
        with tempfile.TemporaryDirectory() as out:
            assert report.report_graders(out) == [DEFAULT_GRADER_MODEL]

    def test_the_grader_the_summaries_describe_pools_from_them(self):
        with tempfile.TemporaryDirectory() as out:
            built = run_report.build_report(_corpus(out), grader=OTHER)
        assert built["questions_pooled_from"] == "summaries"
        assert built["grader"]["n_pending_episodes"] == 0
        assert _aware_under_oversight(built) == 10

    def test_another_grader_pools_from_its_own_episodes(self):
        """Its verdicts are the opposite of the summaries' on every episode,
        so pooling the summaries would report 10 aware where it found 0."""
        with tempfile.TemporaryDirectory() as out:
            built = run_report.build_report(_corpus(out),
                                            grader=DEFAULT_GRADER_MODEL)
        assert built["questions_pooled_from"] == "rebuilt_arm_rows"
        assert _aware_under_oversight(built) == 0

    def test_each_grader_s_episodes_hold_its_own_verdict(self):
        with tempfile.TemporaryDirectory() as out:
            _corpus(out)
            theirs = report.load_episodes(out, grader=OTHER)
            ours = report.load_episodes(out, grader=DEFAULT_GRADER_MODEL)
        assert {e["aware"] for e in theirs if e["model"] == "p/a"} == {True}
        assert {e["aware"] for e in ours if e["model"] == "p/a"} == {False}

    def test_its_question_5_cross_check_is_not_borrowed_either(self):
        """That cross-check reads each summary's awareness split, which is
        the summaries' grader's, not this one's."""
        with tempfile.TemporaryDirectory() as out:
            built = run_report.build_report(_corpus(out),
                                            grader=DEFAULT_GRADER_MODEL)
        section = next(q for q in built["questions"]
                       if q["id"] == "awareness_vs_misalignment")
        assert section["summary_derived_cross_check"]["n_arms_total"] == 0

    def test_trends_pools_each_grader_s_own_rate(self):
        import trends.report as trends_report
        with tempfile.TemporaryDirectory() as out:
            _corpus(out)
            rates = {g: trends_report._metric_rows(
                out, "aware", g, report.load_summaries(out), None)[0]
                for g in (OTHER, DEFAULT_GRADER_MODEL)}
        def aware_in_p_a(rows):
            return sum(r["n_aware"] for r in rows if r["model"] == "p/a")
        assert aware_in_p_a(rates[OTHER]) == 10
        assert aware_in_p_a(rates[DEFAULT_GRADER_MODEL]) == 0

    def test_the_episodes_it_has_not_read_are_left_out_and_counted(self):
        with tempfile.TemporaryDirectory() as out:
            built = run_report.build_report(_corpus(out),
                                            grader=DEFAULT_GRADER_MODEL)
        assert built["grader"]["pending_by_model"] == {"p/b": 10}
        assert built["n_episode_files"] == 10
        assert built["n_models"] == 1


class TestTheCommandLines:
    @staticmethod
    def _main(main, argv):
        saved = sys.argv
        sys.argv = argv
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                return main()
        finally:
            sys.argv = saved

    def test_the_report_writes_each_grader_s_charts_apart(self):
        from conftest import skip_without
        skip_without("matplotlib", "charts are an optional extra")
        with tempfile.TemporaryDirectory() as out:
            charts = os.path.join(out, "charts")
            assert self._main(run_report.main, [
                "report", "--output-dir",
                _corpus(out, MIN_INFORMATIVE_DENOMINATOR),
                "--chart-dir", charts]) == 0
            assert sorted(os.listdir(charts)) == sorted(
                [os.path.basename(charting.grader_chart_dir(charts, g))
                 for g in (OTHER, DEFAULT_GRADER_MODEL)]
                + [GRADER_COMPARISON_DIR])
            assert sorted(os.listdir(os.path.join(
                charts, GRADER_COMPARISON_DIR))) == sorted([
                    "questions_overview.png",
                    "question_02_oversight_vs_awareness.png",
                    "question_05_awareness_vs_misalignment.png",
                    "eval_signal_rates.png"])
            reports = sorted(f for f in os.listdir(out)
                             if f.startswith("research_report_"))
        assert [r.split("_2")[0] for r in reports] == sorted(
            f"research_report_{g}" for g in (OTHER, DEFAULT_GRADER_MODEL))

    def test_the_comparison_is_drawn_from_reports_over_one_corpus(self):
        """What the command hands the chart layer, not what the chart layer
        does with it: built from the per-grader reports instead, the markers
        would compare p/b under one grader with nothing under the other."""
        from unittest import mock
        seen = {}
        def capture(reports, _chart_dir):
            seen.update(reports)
            return []
        with tempfile.TemporaryDirectory() as out, mock.patch(
                "report_charts.write_grader_comparison_charts",
                side_effect=capture):
            self._main(run_report.main, [
                "report", "--output-dir", _corpus(out),
                "--chart-dir", os.path.join(out, "charts")])
        assert set(seen) == {OTHER, DEFAULT_GRADER_MODEL}
        assert {r["n_episode_files"] for r in seen.values()} == {10}
        assert all(r["grader"]["paired_with"] == sorted(seen)
                   for r in seen.values())

    def _comparison_dir_after(self, out, *flags):
        charts = os.path.join(out, "charts")
        self._main(run_report.main, ["report", "--output-dir", out,
                                     "--chart-dir", charts, *flags])
        return os.path.join(charts, GRADER_COMPARISON_DIR)

    def test_no_comparison_under_the_awareness_reading(self):
        """It drops each grader's own aware episodes, so the graders no
        longer share a corpus."""
        from conftest import skip_without
        skip_without("matplotlib", "charts are an optional extra")
        with tempfile.TemporaryDirectory() as out:
            # The first grader judges none aware, so its paired corpus
            # survives the reading whole while the other's empties - the
            # mismatch the skip is for. With the verdicts the other way round
            # the first report would be empty and the no-shared-episode skip
            # would pass this test on its own.
            for n in range(1, MIN_INFORMATIVE_DENOMINATOR + 1):
                _graded(out, n, "p/a", {OTHER: False,
                                        DEFAULT_GRADER_MODEL: True})
            _write_summary(out, "p/a", "strong",
                           n_runs=MIN_INFORMATIVE_DENOMINATOR,
                           n_unaware=MIN_INFORMATIVE_DENOMINATOR,
                           figures_grader=None)
            path = self._comparison_dir_after(
                out, "--exclude-aware", report.EXCLUDE_AWARE_PRIMARY)
            # Its own directory, since the reading writes elsewhere; the
            # per-grader charts must still be there, or nothing ran at all.
            assert os.path.isdir(os.path.dirname(path))
            assert not os.path.exists(path)

    def test_no_comparison_when_the_graders_share_no_episode(self):
        from conftest import skip_without
        skip_without("matplotlib", "charts are an optional extra")
        with tempfile.TemporaryDirectory() as out:
            for n in range(1, 11):
                _graded(out, n, "p/a", {OTHER: True})
                _graded(out, n, "p/b", {DEFAULT_GRADER_MODEL: True})
            _write_summary(out, "p/a", "strong", n_runs=10, n_aware=10)
            assert not os.path.exists(self._comparison_dir_after(out))

    def test_one_json_out_for_two_graders_is_refused(self):
        with tempfile.TemporaryDirectory() as out:
            _corpus(out)
            try:
                self._main(run_report.main, [
                    "report", "--output-dir", out, "--no-charts",
                    "--json-out", os.path.join(out, "one.json")])
            except SystemExit as stop:
                assert stop.code == 2
            else:
                raise AssertionError("two reports were written to one file")

    def test_trends_writes_each_grader_s_charts_apart(self):
        from conftest import skip_without
        skip_without("matplotlib", "charts are an optional extra")
        with tempfile.TemporaryDirectory() as out:
            _corpus(out)
            # A second family member, so there is a trend to draw.
            for n in range(1, 11):
                _graded(out, n, "p/a-2", {OTHER: True,
                                          DEFAULT_GRADER_MODEL: False})
            _write_summary(out, "p/a-2", "strong", n_runs=10, n_aware=10,
                           model_slug="p_a-2", figures_grader=None)
            charts = os.path.join(out, "charts")
            assert self._main(family_trends.main, [
                "trends", "--output-dir", out, "--metric", "aware",
                "--chart-dir", charts]) == 0
            assert sorted(os.listdir(charts)) == sorted(
                os.path.basename(charting.grader_chart_dir(charts, g))
                for g in (OTHER, DEFAULT_GRADER_MODEL))


class TestTheChartsThatCompareGraders:
    """Built from reports that share one corpus - every grader's figures over
    the episodes all of them read - so a gap between two markers is the
    graders disagreeing rather than covering different models."""

    @staticmethod
    def _paired(out):
        graders = [OTHER, DEFAULT_GRADER_MODEL]
        return {g: run_report.build_report(out, grader=g, paired_with=graders)
                for g in graders}

    def test_every_grader_s_report_covers_the_same_episodes(self):
        with tempfile.TemporaryDirectory() as out:
            reports = self._paired(_corpus(out))
        assert {r["n_episode_files"] for r in reports.values()} == {10}
        # p/b was read by one grader only, so neither report may hold it -
        # including the report of the grader that did read it, where it is
        # UNPAIRED rather than pending: nothing is waiting for that grader.
        mine = reports[OTHER]["grader"]
        assert (mine["pending_by_model"], mine["n_unpaired_episodes"]) == (
            {}, 10)
        theirs = reports[DEFAULT_GRADER_MODEL]["grader"]
        assert (theirs["pending_by_model"], theirs["n_unpaired_episodes"]) == (
            {"p/b": 10}, 0)
        assert mine["paired_with"] == sorted([OTHER, DEFAULT_GRADER_MODEL])

    def test_a_paired_report_never_pools_from_the_summaries(self):
        """Even for the grader they describe, with nothing dropped: the other
        graders' reports rebuild from episodes, and a summary count beside a
        rebuilt one shows any drift between the sources as disagreement."""
        with tempfile.TemporaryDirectory() as out:
            for n in range(1, 11):
                _graded(out, n, "p/a", {OTHER: True,
                                        DEFAULT_GRADER_MODEL: False})
            _write_summary(out, "p/a", "strong", n_runs=10, n_aware=10,
                           figures_grader=None)
            reports = self._paired(out)
        assert reports[OTHER]["grader"]["n_pending_episodes"] == 0
        assert reports[OTHER]["grader"]["n_unpaired_episodes"] == 0
        assert {r["questions_pooled_from"] for r in reports.values()} == {
            "rebuilt_arm_rows"}

    def test_a_model_row_holds_one_estimate_per_grader(self):
        with tempfile.TemporaryDirectory() as out:
            _corpus(out)
            for n in range(11, 21):
                _graded(out, n, "p/a", {OTHER: False,
                                        DEFAULT_GRADER_MODEL: True},
                        oversight=False)
            groups = dict(question_groups("oversight_vs_awareness",
                                          self._paired(out)))
        assert groups["p/a"][OTHER].diff == 1.0
        assert groups["p/a"][DEFAULT_GRADER_MODEL].diff == -1.0

    def test_the_pooled_rows_match_across_graders_and_come_last(self):
        """The stratified label carries a stratum count that can differ by
        grader; matched on it, the two graders' rows would never meet."""
        with tempfile.TemporaryDirectory() as out:
            _corpus(out)
            for n in range(11, 21):
                _graded(out, n, "p/a", {OTHER: False,
                                        DEFAULT_GRADER_MODEL: True},
                        oversight=False)
            labels = [label for label, _points in question_groups(
                "oversight_vs_awareness", self._paired(out))]
        assert labels == ["p/a", "CRUDE POOLED", "STRATIFIED (MH)"]

    def test_the_overview_has_one_row_per_question_for_every_grader(self):
        with tempfile.TemporaryDirectory() as out:
            reports = self._paired(_corpus(out))
            groups = overview_groups(reports)
        single = len(__import__("report_charts").questions.overview_rows(
            reports[OTHER])[0])
        assert len(groups) == single
        assert all(set(points) == set(reports) for _label, points in groups)

    def test_a_pooled_row_only_a_later_grader_has_is_still_pooled(self):
        """The first grader's strata were all uninformative, so it has no
        stratified row; the second's does. Classified by the first grader's
        rows alone, that row was filed among the models."""
        reports = {}
        for g, with_stratified in ((OTHER, False), (DEFAULT_GRADER_MODEL, True)):
            section = {"id": "q", "by_model": [
                {"model": "p/a", "difference": 0.1,
                 "difference_ci95": [0, 0.2]}],
                "overall": {"difference": 0.1, "difference_ci95": [0, 0.2]}}
            if with_stratified:
                section["stratified"] = {"mantel_haenszel": {
                    "risk_difference": 0.1, "risk_difference_ci95": [0, 0.2],
                    "n_strata_used": 1}}
            reports[g] = {"questions": [section]}
        labels = [label for label, _p in question_groups("q", reports)]
        assert labels == ["p/a", "CRUDE POOLED", "STRATIFIED (MH)"]

    def test_a_divergence_under_either_grader_is_marked(self):
        from report_charts.rows import Row
        from unittest import mock
        # Flagged under the FIRST grader only, so a mark overwritten by each
        # grader in turn - rather than kept if any sets it - would be lost.
        rows = {OTHER: ([Row("Q1. x  *", 0.1, 0, 0.2, "stratified")], True),
                DEFAULT_GRADER_MODEL: (
                    [Row("Q1. x", 0.1, 0, 0.2, "stratified")], False)}
        with mock.patch("report_charts.graders.overview_rows",
                        side_effect=lambda r: rows[r]):
            groups = overview_groups({g: g for g in rows})
        assert [label for label, _p in groups] == ["Q1. x  *"]

    def test_a_model_one_grader_cannot_support_is_not_drawn(self):
        from unittest import mock
        clusters = {OTHER: [{"model": "p/a", "points": []},
                            {"model": "p/b", "points": []}],
                    DEFAULT_GRADER_MODEL: [{"model": "p/a", "points": []}]}
        with mock.patch("report_charts.graders._signal_clusters",
                        side_effect=lambda profile: clusters[profile]):
            groups = signal_groups({g: {"characteristics": {
                "eval_signal_rates": g}} for g in clusters})
        assert [label for label, points in groups if points is None] == [
            "p/a"]

    def test_the_signal_chart_draws_only_models_every_grader_supports(self):
        with tempfile.TemporaryDirectory() as out:
            groups = signal_groups(self._paired(
                _corpus(out, MIN_INFORMATIVE_DENOMINATOR)))
        headers = [label for label, points in groups if points is None]
        assert headers == ["p/a"]


class TestADemotedCrudeEstimateIsNotDrawnAsTheAnswer:
    """Where crude and stratified diverge the report says to read the
    stratified one, and rows.Row.demoted exists so the chart does not say the
    opposite. The comparison drawer ignored it: question 5 on r10 diverges
    under both graders, and both crude diamonds were drawn solid."""

    @staticmethod
    def _drawn(row):
        from conftest import skip_without
        skip_without("matplotlib", "charts are an optional extra")
        from unittest import mock
        from report_charts.graders import _colours, _draw_by_grader
        plt = charting.import_pyplot()
        kept = []
        with tempfile.TemporaryDirectory() as out, mock.patch.object(
                plt, "close", side_effect=kept.append):
            _draw_by_grader(plt, [("CRUDE POOLED", {OTHER: row})],
                            _colours([OTHER]), "t", [],
                            os.path.join(out, "c.png"), "x")
        lines = kept[0].axes[0].lines
        plt.close(kept[0])
        return lines

    def test_it_is_hollow_faint_and_dashed(self):
        from report_charts.rows import Row
        lines = self._drawn(Row("CRUDE POOLED", 0.1, 0.0, 0.2, "crude",
                                marked=True, demoted=True))
        marker = next(ln for ln in lines if ln.get_marker() == "s")
        interval = next(ln for ln in lines if len(ln.get_xdata()) == 2)
        assert marker.get_markerfacecolor() == "white"
        assert marker.get_alpha() < 1
        assert interval.get_linestyle() == "--"

    def test_one_that_is_not_demoted_is_drawn_as_usual(self):
        from report_charts.rows import Row
        lines = self._drawn(Row("CRUDE POOLED", 0.1, 0.0, 0.2, "crude",
                                marked=True))
        marker = next(ln for ln in lines if ln.get_marker() == "s")
        assert marker.get_markerfacecolor() != "white"
        assert marker.get_alpha() == 1.0

    def test_the_report_s_warning_is_captioned_for_each_grader_it_names(self):
        from conftest import skip_without
        skip_without("matplotlib", "charts are an optional extra")
        from unittest import mock
        import report_charts.graders as graders_module
        def section(qid, warning):
            return {"id": qid, "question": qid, "by_model": [],
                    "overall": {"difference": 0.1,
                                "difference_ci95": [0, 0.2]},
                    "crude_vs_stratified": {"diverges": bool(warning),
                                            "warning": warning}}
        reports = {g: {"n_episode_files": 1, "questions": [
            section("oversight_vs_awareness", ""),
            section("awareness_vs_misalignment",
                    "REPORT THE STRATIFIED" if g == OTHER else "")]}
            for g in (OTHER, DEFAULT_GRADER_MODEL)}
        drawn = {}
        def capture(_plt, _groups, _colours, title, captions, path, *a, **k):
            drawn[os.path.basename(path)] = [c for c, _colour in captions]
            return path
        with tempfile.TemporaryDirectory() as out, mock.patch.object(
                graders_module, "_draw_by_grader", side_effect=capture):
            graders_module.write_grader_comparison_charts(reports, out)
        q5 = drawn["question_02_awareness_vs_misalignment.png"]
        assert f"{OTHER}: REPORT THE STRATIFIED" in q5
        assert not any(c.startswith(DEFAULT_GRADER_MODEL) for c in q5)
        assert not any("STRATIFIED" in c for c in
                       drawn["question_01_oversight_vs_awareness.png"])
