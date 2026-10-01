"""
Which scenario a chart came from, and what its composite rate counts.

"Agentic misalignment rate" named no act, and the goal-guarding corpus charted
it beside the mainline one under the same words while counting a third act -
one most of its flagged episodes did not take. Every chart now names its
scenario, the composite is labelled with the acts the corpus could observe,
and the goal-guarding act has a rate of its own.
"""

import json
import os
import tempfile
from unittest import mock

import report.run_report as run_report
import trends.family_trends as family_trends
from report.pooling import composite_of, composite_rate_label, scenario_of
from subversionbench.grading import MISALIGNED_ACTS
from subversionbench.power import MIN_INFORMATIVE_DENOMINATOR
from test_analysis.report_fixtures import _write_episode, _write_summary


def _corpus(out, goalguard=None, models=("p/a",)):
    """Both oversight arms per model, half the oversight arm tampering, and -
    in a goal-guarding corpus - a third of every arm goal-guarding."""
    n = MIN_INFORMATIVE_DENOMINATOR
    for model in models:
        for oversight in (True, False):
            for i in range(1, n + 1):
                path = _write_episode(out, i if oversight else 100 + i, model,
                                      "strong", oversight=oversight,
                                      goalguard=goalguard,
                                      tampered=oversight and i % 2 == 0)
                if goalguard:
                    with open(path, encoding="utf-8") as f:
                        data = json.load(f)
                    data["analysis"]["goal_guarded"] = i % 3 == 0
                    with open(path, "w", encoding="utf-8") as f:
                        json.dump(data, f)
        _write_summary(out, model, "strong", n_runs=n, goalguard=goalguard,
                       model_slug=model.replace("/", "_"))
    return out


class TestTheCompositeIsLabelledWithItsActs:
    def test_mainline(self):
        rows = [{"oversight_observable": o, "sandbox_observable": True,
                 "goalguard_observable": False} for o in (True, False)]
        assert composite_rate_label(composite_of(MISALIGNED_ACTS, rows)) == (
            "oversight subversion and sandbox escape attempt rate")

    def test_goal_guarding_leads_with_its_own_act(self):
        rows = [{"oversight_observable": o, "sandbox_observable": True,
                 "goalguard_observable": True} for o in (True, False)]
        assert composite_rate_label(composite_of(MISALIGNED_ACTS, rows)) == (
            "goal-guarding, oversight subversion and sandbox escape attempt "
            "rate")

    def test_question_3_says_so_in_each_corpus(self):
        def q3(out):
            built = run_report.build_report(out)
            return next(q for q in built["questions"]
                        if q["id"] == "oversight_vs_misalignment")["question"]
        with tempfile.TemporaryDirectory() as main, \
                tempfile.TemporaryDirectory() as gg:
            mainline = q3(_corpus(main))
            guarding = q3(_corpus(gg, goalguard="deferred"))
        assert "agentic misalignment" not in mainline + guarding
        assert "goal-guarding" not in mainline
        assert "goal-guarding, oversight subversion" in guarding


class TestEveryChartNamesItsScenario:
    """Held at the one point every chart passes through: what each figure's
    titles say at the moment it is saved."""

    @staticmethod
    def _titles_at_save(write):
        from conftest import skip_without
        skip_without("matplotlib", "charts are an optional extra")
        from matplotlib.figure import Figure
        seen, real = [], Figure.savefig

        def recording(fig, *args, **kwargs):
            seen.append(" ".join(
                [t.get_text() for ax in fig.axes
                 for t in (getattr(ax, "_left_title", None), ax.title) if t]
                + [fig._suptitle.get_text() if fig._suptitle else ""]))
            return real(fig, *args, **kwargs)

        with mock.patch.object(Figure, "savefig", recording):
            write()
        return seen

    def test_scenario_of_reads_the_arm(self):
        assert scenario_of([{"goalguard": None}]) == "Mainline"
        assert scenario_of([{"goalguard": "deferred"}]) == "Goal-guarding"
        assert scenario_of([{"goalguard": None},
                            {"goalguard": "replacement"}]) == (
            "Mainline and goal-guarding")
        assert scenario_of([]) is None

    def test_every_report_chart(self):
        import report_charts
        with tempfile.TemporaryDirectory() as out:
            built = run_report.build_report(_corpus(out, goalguard="deferred"))
            titles = self._titles_at_save(lambda: report_charts.write_charts(
                built, os.path.join(out, "charts")))
        assert titles, "nothing was drawn - the check below would be vacuous"
        unmarked = [t for t in titles if "Goal-guarding scenario" not in t]
        assert not unmarked, unmarked

    def test_every_trend_chart(self):
        import trends.report as trends_report
        from trends.charts import write_charts
        with tempfile.TemporaryDirectory() as out:
            _corpus(out, models=("p/a-1", "p/a-2"))
            built = trends_report.build_report(out, "misaligned", grader=None)
            titles = self._titles_at_save(lambda: write_charts(
                built, os.path.join(out, "charts")))
        assert titles, "nothing was drawn - the check below would be vacuous"
        unmarked = [t for t in titles if "Mainline scenario" not in t]
        assert not unmarked, unmarked
        assert built["metric_label"] == (
            "oversight subversion and sandbox escape attempt rate")

    def test_nothing_is_marked_outside_the_block(self):
        from conftest import skip_without
        skip_without("matplotlib", "charts are an optional extra")
        from matplotlib.figure import Figure
        from subversionbench import charting
        before = Figure.savefig
        with charting.scenario_marked("Mainline"):
            assert Figure.savefig is not before
        assert Figure.savefig is before


class TestTheGoalGuardingRateIsItsOwn:
    def test_question_22_counts_the_act_alone_over_the_episodes_that_could(self):
        with tempfile.TemporaryDirectory() as out:
            built = run_report.build_report(_corpus(out, goalguard="deferred"))
        section = next(q for q in built["questions"]
                       if q["id"] == "oversight_vs_goal_guarding")
        n = MIN_INFORMATIVE_DENOMINATOR
        assert section["overall"]["a"]["successes"] == n // 3
        assert section["overall"]["a"]["n"] == n
        assert not section.get("out_of_scope_for_corpus")

    def test_it_is_out_of_scope_on_a_mainline_corpus(self):
        with tempfile.TemporaryDirectory() as out:
            built = run_report.build_report(_corpus(out))
        section = next(q for q in built["questions"]
                       if q["id"] == "oversight_vs_goal_guarding")
        assert section.get("out_of_scope_for_corpus")

    def test_trends_reports_it_on_goal_guarding_and_skips_it_on_mainline(self):
        import contextlib
        import io
        import sys

        def run(out):
            saved, sys.argv = sys.argv, ["trends", "--output-dir", out,
                                         "--metric", "goalguard_act",
                                         "--no-charts"]
            try:
                with contextlib.redirect_stdout(io.StringIO()) as buf:
                    code = family_trends.main()
            finally:
                sys.argv = saved
            return code, buf.getvalue()

        with tempfile.TemporaryDirectory() as gg, \
                tempfile.TemporaryDirectory() as main:
            code, said = run(_corpus(gg, goalguard="deferred",
                                     models=("p/a-1", "p/a-2")))
            assert code == 0, said
            assert "goal-guarding rate" in said
            code, said = run(_corpus(main, models=("p/a-1", "p/a-2")))
        assert code == 0, said
        assert "Skipping --metric goalguard_act" in said
