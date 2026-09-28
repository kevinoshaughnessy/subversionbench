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


def _corpus(out):
    """p/a read by both graders, which disagree on every episode; p/b read by
    OTHER alone. The summaries predate the grader stamp, so they are OTHER's -
    and hold OTHER's counts, as the real corpus's do."""
    for n in range(1, 11):
        _graded(out, n, "p/a", {OTHER: True, DEFAULT_GRADER_MODEL: False})
        _graded(out, n, "p/b", {OTHER: False})
    _write_summary(out, "p/a", "strong", n_runs=10, n_aware=10,
                   figures_grader=None)
    _write_summary(out, "p/b", "strong", n_runs=10, n_unaware=10,
                   model_slug="p_b", figures_grader=None)
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
                "report", "--output-dir", _corpus(out),
                "--chart-dir", charts]) == 0
            assert sorted(os.listdir(charts)) == sorted(
                os.path.basename(charting.grader_chart_dir(charts, g))
                for g in (OTHER, DEFAULT_GRADER_MODEL))
            reports = sorted(f for f in os.listdir(out)
                             if f.startswith("research_report_"))
        assert [r.split("_2")[0] for r in reports] == sorted(
            f"research_report_{g}" for g in (OTHER, DEFAULT_GRADER_MODEL))

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
