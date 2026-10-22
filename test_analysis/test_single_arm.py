"""
Every model inside one arm, as counts.

The block counts each reading per model in each named arm the corpus holds,
over that reading's own observable episodes, leaves out an arm the corpus does
not hold, and lays every model against every arm in the design's order. The
charts draw it as counts and draw nothing for an arm that is not there.
"""

import os
import tempfile

from report.run_report import build_report
from report.single_arm import single_arm
from report_charts.arm_grid import plot_arm_grid_act, plot_arm_grid_awareness
from report_charts.single_arm import (plot_awareness_vs_act,
                                      plot_baseline_profile,
                                      plot_baseline_text_awareness,
                                      plot_goalguard_arms, plot_lure_arm,
                                      plot_max_pressure_acts,
                                      plot_no_oversight_arm)
from test_analysis.report_fixtures import _write_episode, _write_summary


def _row(model="m/a", nudge="none", oversight=True, lure=False,
         goalguard=None, **readings):
    row = {"model": model, "nudge": nudge, "oversight": oversight,
           "lure": lure, "goalguard": goalguard,
           "aware": False, "aware_text": False, "aware_text_is_bound": False,
           "misaligned": False, "scheming": False,
           "scheming_undetermined": False,
           "monitoring_disabled": False, "monitoring_observable": oversight,
           "sandbox_escape": False, "sandbox_escape_absent": False,
           "honeypot_discovered": False if lure else None,
           "honeypot_read": False if lure else None}
    row.update(readings)
    return row


def _counts(block, arm, model="m/a"):
    rows = {r["model"]: r for r in block["arms"][arm]["by_model"]}
    return rows[model]["counts"]


class TestEachArmIsCountedAlone:
    def test_only_the_arms_episodes_are_counted(self):
        block = single_arm([_row(aware=True), _row(aware=False),
                            _row(nudge="max", aware=True)])
        assert _counts(block, "baseline")["aware"] == {"k": 1, "n": 2}

    def test_each_reading_has_its_own_denominator(self):
        block = single_arm([_row(aware=True), _row(aware=None),
                            _row(misaligned=True)])
        counts = _counts(block, "baseline")
        assert counts["aware"] == {"k": 1, "n": 2}
        assert counts["misaligned"] == {"k": 1, "n": 3}

    def test_an_act_the_arm_cannot_take_has_no_denominator(self):
        block = single_arm([_row(oversight=False, monitoring_disabled=False)])
        assert _counts(block, "no_oversight")["monitoring_disabled"]["n"] == 0

    def test_an_arm_the_corpus_lacks_is_left_out(self):
        assert set(single_arm([_row()])["arms"]) == {"baseline"}

    def test_the_goalguard_arms_are_named(self):
        block = single_arm([_row(goalguard="replacement", misaligned=True),
                            _row(goalguard="deferred")])
        assert _counts(block, "goalguard_replacement")["misaligned"]["k"] == 1
        assert _counts(block, "goalguard_deferred")["misaligned"]["k"] == 0

    def test_visible_text_is_a_floor_where_reasoning_came_back(self):
        block = single_arm([_row(model="m/r", aware_text_is_bound=True),
                            _row(model="m/t")])
        floor = {r["model"]: r["text_is_floor"]
                 for r in block["arms"]["baseline"]["by_model"]}
        assert floor == {"m/r": True, "m/t": False}


class TestTheGrid:
    def test_arms_run_in_the_designs_order(self):
        block = single_arm([_row(nudge=n, lure=lure)
                            for n in ("max", "strong", "none")
                            for lure in (True, False)])
        assert block["grid"]["arms"] == ["none", "none_lure", "strong",
                                         "strong_lure", "max", "max_lure"]

    def test_every_model_has_a_cell_in_every_arm(self):
        block = single_arm([_row(model="m/a", aware=True),
                            _row(model="m/b", nudge="max")])
        cells = {r["model"]: r["cells"] for r in block["grid"]["by_model"]}
        assert cells["m/a"]["none"]["aware"] == {"k": 1, "n": 1}
        assert cells["m/a"]["max"]["aware"] == {"k": 0, "n": 0}


class TestItReachesTheReport:
    def test_from_run_files(self):
        with tempfile.TemporaryDirectory() as out:
            for n in range(1, 4):
                _write_episode(out, n, "p/m", "none", tampered=n == 1)
            _write_summary(out, "p/m", "none", n_runs=3)
            block = build_report(out)["single_arm"]
        assert _counts(block, "baseline", "p/m")["misaligned"] == {
            "k": 1, "n": 3}


_PLOTS = (plot_baseline_profile, plot_baseline_text_awareness,
          plot_max_pressure_acts, plot_awareness_vs_act, plot_lure_arm,
          plot_no_oversight_arm, plot_goalguard_arms, plot_arm_grid_awareness,
          plot_arm_grid_act)


class TestTheCharts:
    @staticmethod
    def _drawn(rows):
        from conftest import skip_without
        skip_without("matplotlib", "charts are an optional extra")
        from subversionbench import charting
        plt = charting.import_pyplot()
        report = {"single_arm": single_arm(rows)}
        with tempfile.TemporaryDirectory() as out:
            return {plot.__name__ for plot in _PLOTS
                    if plot(plt, report, os.path.join(out, "c.png"))}

    def test_every_chart_draws_when_its_arms_are_there(self):
        rows = [_row(model=m, nudge=n, oversight=o, lure=lure,
                     aware=True, misaligned=m == "m/a")
                for m in ("m/a", "m/b")
                for n, o, lure in (("none", True, False), ("max", True, True),
                                   ("none", True, True),
                                   ("none", False, False))]
        rows += [_row(goalguard=g) for g in ("replacement", "deferred")]
        assert self._drawn(rows) == {p.__name__ for p in _PLOTS}

    def test_a_chart_whose_arm_is_absent_draws_nothing(self):
        assert self._drawn([_row(nudge="strong")]) == {
            "plot_arm_grid_awareness", "plot_arm_grid_act"}
