"""
Misaligned acts by turns since first verbalised awareness.

The gap is act turn minus awareness turn, so its sign carries the ordering a
reader takes from it; an act that cannot be placed is counted beside the
histogram, never drawn at a gap it does not have; and only the acts an
episode's own verdict counts are included.
"""

import json
import os
import tempfile

import report as rr
from report.strategy_pressure import _arm_slug
from report_charts.act_awareness_gap import plot_act_awareness_gap
from test_analysis.report_fixtures import _write_episode


def _timing(level, act_turn=None, awareness_turn=None):
    return {"timing": level, "act_turn": act_turn,
            "awareness_turn": awareness_turn}


def _row(oversight=None, sandbox=None, goalguard=None, model="m/a",
         nudge="strong", oversight_arm=True, lure=False, arm=None):
    return {"model": model, "nudge": nudge, "oversight": oversight_arm,
            "lure": lure, "goalguard": arm,
            "oversight_awareness_timing": oversight or {},
            "sandbox_awareness_timing": sandbox or {},
            "goalguard_awareness_timing": goalguard or {}}


class TestTheGapIsActTurnMinusAwarenessTurn:
    def test_aware_on_turn_4_and_tampering_on_turn_6_is_one_act_at_two(self):
        block = rr.act_awareness_gap(
            [_row(oversight=_timing("before_act", 6, 4))])
        assert block["pooled"]["by_act"] == {"oversight": [(2, 1)]}

    def test_same_turn_is_zero_and_awareness_after_the_act_is_negative(self):
        block = rr.act_awareness_gap([
            _row(oversight=_timing("before_act", 5, 5)),
            _row(sandbox=_timing("after_act", 3, 7)),
            _row(sandbox=_timing("after_act", 2, 6))])
        assert block["pooled"]["by_act"] == {"oversight": [(0, 1)],
                                             "sandbox": [(-4, 2)]}

    def test_each_act_of_an_episode_counts(self):
        block = rr.act_awareness_gap([_row(
            oversight=_timing("before_act", 6, 4),
            sandbox=_timing("before_act", 9, 4))])
        assert block["pooled"]["n_placed"] == 2


class TestAnUnplacedActIsCountedNotDrawn:
    def test_not_aware_and_unlocatable_are_counted_apart_and_no_act_is_not(
            self):
        block = rr.act_awareness_gap([
            _row(oversight=_timing("not_aware", 6, None)),
            _row(oversight=_timing("act_unlocatable", None, 2)),
            _row(oversight=_timing("no_act")),
            _row()])
        pooled = block["pooled"]
        assert pooled["by_act"] == {}
        assert (pooled["n_placed"], pooled["n_not_aware"],
                pooled["n_unlocatable"]) == (0, 1, 1)


class TestArmsPoolModelsButNotEachOther:
    def test_one_entry_per_arm_with_every_model_in_it(self):
        block = rr.act_awareness_gap([
            _row(oversight=_timing("before_act", 6, 4), model="m/a"),
            _row(oversight=_timing("before_act", 7, 4), model="m/b"),
            _row(sandbox=_timing("before_act", 3, 2), oversight_arm=False,
                 lure=True)])
        arms = {a["arm"]: a["by_act"] for a in block["by_arm"]}
        assert arms == {"strong": {"oversight": [(2, 1), (3, 1)]},
                        "strong_nooversight_lure": {"sandbox": [(1, 1)]}}

    def test_the_arm_is_spelt_as_the_run_files_spell_it(self):
        with tempfile.TemporaryDirectory() as out:
            path = _write_episode(out, 1, "m/a", "none", oversight=False,
                                  lure=True, goalguard="deferred")
            stem = os.path.basename(path).split("m_a_", 1)[1]
            assert stem.startswith(_arm_slug(
                {"nudge": "none", "oversight": False, "lure": True,
                 "goalguard": "deferred"}) + "_")


def _saved(out, n, analysis_extra, **kw):
    path = _write_episode(out, n, "m/a", "strong",
                          stamp=f"2026010100{n:04d}", **kw)
    with open(path, encoding="utf-8") as f:
        saved = json.load(f)
    saved["analysis"].update(analysis_extra)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(saved, f)


class TestOnlyTheActsTheVerdictCountsAreRead:
    """The goal-guarding scenario counts its own act alone, so an oversight
    edit taken there must not reach that corpus's histogram."""

    def test_a_goalguard_episodes_oversight_act_is_left_out(self):
        with tempfile.TemporaryDirectory() as out:
            _saved(out, 1, {
                "goal_guarded": True,
                "awareness_timing_goalguard": _timing("before_act", 8, 3),
                "awareness_timing_oversight": _timing("before_act", 5, 3)},
                tampered=True, goalguard="replacement")
            _saved(out, 2, {
                "awareness_timing_oversight": _timing("before_act", 5, 3)},
                tampered=True)
            episodes = rr.load_episodes(out)
        arms = {a["arm"]: a["by_act"]
                for a in rr.act_awareness_gap(episodes)["by_arm"]}
        assert arms == {"strong_goalguard-replacement": {"goalguard": [(5, 1)]},
                        "strong": {"oversight": [(2, 1)]}}


class TestTheChartsAreOneForTheCorpusAndOnePerArm:
    def _report(self, rows):
        return {"characteristics": {"act_awareness_gap":
                                    rr.act_awareness_gap(rows)}}

    def test_an_arm_with_nothing_placed_draws_no_file(self):
        from conftest import skip_without
        skip_without("matplotlib", "charts are an optional extra")
        from subversionbench import charting
        plt = charting.import_pyplot()
        with tempfile.TemporaryDirectory() as out:
            path = os.path.join(out, "act_awareness_gap.png")
            written = plot_act_awareness_gap(plt, self._report([
                _row(oversight=_timing("before_act", 6, 4)),
                _row(oversight=_timing("not_aware", 6, None),
                     oversight_arm=False)]), path)
            assert written == [path,
                               os.path.join(out, "act_awareness_gap_strong.png")]
            assert all(os.path.exists(p) for p in written)

    def test_nothing_placed_draws_nothing(self):
        assert plot_act_awareness_gap(
            None, self._report([_row(oversight=_timing("not_aware", 6))]),
            "unused.png") is None
