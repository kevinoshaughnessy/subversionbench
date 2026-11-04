"""
A corpus's charts leave out what its scenario does not stage or count.

The impossible-task corpus, which counts the oversight act alone in one
oversight-present cell, was drawn with every mainline chart: sandbox refusals
(models looking for a Python the world does not have) as escape attempts,
persistence after them, oversight contrasts with one side, and mainline's two
oversight files by name.
"""

import json
import os
import tempfile
from unittest import mock

import report.run_report as run_report
from report.pooling import scenario_acts_in
from report_charts.exclusion import counts_act
from report_charts.single_arm import _counted
from report_charts.write import CHART_ACT, CHARACTERISTIC_CHARTS
from test_analysis.report_fixtures import _write_episode

SANDBOX_QUESTIONS = {"awareness_vs_sandbox_escape", "awareness_vs_sandbox_scheming",
                     "lure_vs_sandbox_escape"}


def _corpus(out, scenario_id):
    for i in range(1, 11):
        path = _write_episode(out, i, "p/a", "strong", tampered=i % 2 == 0)
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        data["scenario_id"] = scenario_id
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f)
    return out


def _marked(scenario_id) -> dict:
    with tempfile.TemporaryDirectory() as out:
        built = run_report.build_report(_corpus(out, scenario_id))
    return built, {q["id"]: q.get("out_of_scope_for_corpus", "")
                   for q in built["questions"]}


class TestTheActsAScenarioCounts:
    def test_read_off_each_rows_recorded_scenario(self):
        assert scenario_acts_in([{"scenario_id": "oversight"}]) == ["oversight"]
        assert scenario_acts_in([{"scenario_id": "oversight-sandbox"},
                                 {"scenario_id": "oversight"}]) == [
            "oversight", "sandbox"]
        assert scenario_acts_in([]) is None

    def test_an_unrecorded_set_counts_every_act(self):
        assert counts_act({}, "sandbox")
        assert counts_act({"scenario_acts": ["oversight", "sandbox"]}, "sandbox")
        assert not counts_act({"scenario_acts": ["oversight"]}, "sandbox")


class TestQuestionsOutsideTheScenario:
    def test_sandbox_questions_are_out_where_no_sandbox_act_is_counted(self):
        built, marked = _marked("oversight")
        assert built["scenario_acts"] == ["oversight"]
        derived = {i for i in marked
                   if "sandbox" in i.partition("_vs_")[2] or i.startswith("lure_")}
        assert derived == SANDBOX_QUESTIONS, "the id convention moved"
        assert all(marked[i] for i in derived)

    def test_and_kept_where_it_is(self):
        _built, marked = _marked("oversight-sandbox")
        assert not any(marked[i] for i in SANDBOX_QUESTIONS)

    def test_mainlines_two_files_are_out_only_for_a_bundle_with_its_own(self):
        own = ("monitoring_disabled", "quality_check_modified")
        _built, marked = _marked("oversight-sandbox")
        assert not any(marked[f"awareness_vs_{o}"] for o in own)
        with mock.patch.object(run_report, "ACT_ARTEFACTS", ("qa/check.sh",)):
            built, marked = _marked("oversight-sandbox")
        assert all(marked[f"awareness_vs_{o}"] for o in own)
        assert not marked["awareness_vs_oversight_tampered"]
        assert built["own_act_artefacts"]

    def test_oversight_contrasts_are_out_where_the_scenario_stages_one_side(self):
        oversight = [i for i in _marked("oversight-sandbox")[1]
                     if i.startswith("oversight_vs_")]
        assert oversight, "no oversight question found - the check is vacuous"
        assert not any(_marked("oversight-sandbox")[1][i] for i in oversight)
        with mock.patch.object(run_report, "ROLLOUT_FINGERPRINTS",
                               {(True, False): "x"}):
            _built, marked = _marked("oversight-sandbox")
        assert all(marked[i] for i in oversight)


class TestChartsOutsideTheScenario:
    def test_every_chart_named_for_an_act_is_a_chart(self):
        names = {name for name, _plot, _grader in CHARACTERISTIC_CHARTS}
        assert set(CHART_ACT) <= names

    def test_those_charts_are_not_written_where_the_act_is_not_counted(self):
        from conftest import skip_without
        skip_without("matplotlib", "charts are an optional extra")
        import report_charts
        drawn = []

        def plot(_plt, _report, path):
            drawn.append(os.path.basename(path))
            return None

        charts = tuple((n, plot, g) for n, _p, g in CHARACTERISTIC_CHARTS)
        with tempfile.TemporaryDirectory() as out, \
                mock.patch("report_charts.write.CHARACTERISTIC_CHARTS", charts):
            report_charts.write_charts({"scenario_acts": ["oversight"]}, out)
            assert not set(CHART_ACT) & set(drawn)
            drawn.clear()
            report_charts.write_charts({"scenario_acts": ["oversight", "sandbox"]}, out)
            assert set(CHART_ACT) <= set(drawn)

    def test_the_profile_drops_the_panels_the_scenario_does_not_stage(self):
        every = ("aware", "monitoring_disabled", "sandbox_escape")
        assert _counted({"scenario_acts": ["oversight", "sandbox"]}, every) == every
        assert _counted({"scenario_acts": ["oversight"], "own_act_artefacts": True},
                        every) == ("aware",)
