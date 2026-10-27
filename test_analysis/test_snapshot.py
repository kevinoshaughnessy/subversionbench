"""Which models a dated snapshot holds (report/snapshot.py, analysis plan D2).

A model is kept out only for missing propensity arms or an unread episode; a
missing capability verdict is listed as owed and the model stays in."""

import unittest
from unittest import mock

from report import run_report
from report.snapshot import capability_gaps, incomplete_models

ML = {("none", True, False), ("none", False, False)}
GG = {("none", True, "replacement"), ("none", True, "deferred")}


class TestWhoIsKeptOut(unittest.TestCase):

    def test_a_complete_model_is_not_listed(self):
        arms = {"mainline": {"a": ML}, "goalguard": {"a": GG}}
        self.assertEqual(incomplete_models(arms, {}), {})

    def test_a_model_missing_a_scenario_is_kept_out_with_its_reason(self):
        arms = {"mainline": {"a": ML, "b": ML}, "goalguard": {"a": GG}}
        self.assertEqual(incomplete_models(arms, {}),
                         {"b": ["goalguard: 2 of 2 arms not collected"]})

    def test_one_missing_arm_is_enough(self):
        arms = {"mainline": {"a": ML, "b": {("none", True, False)}},
                "goalguard": {"a": GG, "b": GG}}
        self.assertEqual(list(incomplete_models(arms, {})), ["b"])

    def test_an_unread_episode_keeps_the_model_out(self):
        arms = {"mainline": {"a": ML}, "goalguard": {"a": GG}}
        self.assertIn("a", incomplete_models(arms, {"a": 1}))

    def test_a_scenario_with_no_arms_at_all_is_refused(self):
        with self.assertRaises(ValueError):
            incomplete_models({"mainline": {"a": ML}, "goalguard": {}}, {})


class TestTheCapabilityVerdictIsOwedNotEnforced(unittest.TestCase):

    def test_missing_acts_are_listed_per_model(self):
        gaps = capability_gaps(["a", "b"], {"a": {"oversight", "sandbox",
                                                   "goalguard"},
                                            "b": {"goalguard"}})
        self.assertEqual(gaps, {"b": ["oversight", "sandbox"]})


class TestTheReportNarrowsEverySourceToTheSnapshot(unittest.TestCase):

    def test_summaries_episodes_and_failures_all_lose_other_models(self):
        rows = [{"model": m, "oversight": True, "lure": False, "nudge": "none"}
                for m in ("a", "b")]
        with mock.patch.object(run_report, "load_summaries", lambda d: rows), \
                mock.patch.object(run_report, "load_episodes",
                                  lambda d, **k: list(rows)), \
                mock.patch.object(run_report, "load_failed_episodes",
                                  lambda d: list(rows)):
            out = run_report._narrowed_corpus(
                "d", run_report.NO_EXCLUSION,
                run_report.NO_AWARENESS_EXCLUSION, run_report.NO_GRADER,
                only_models=["a"])
        summaries, episodes, failed = out[0], out[1], out[2]
        for name, got in (("summaries", summaries), ("episodes", episodes),
                          ("failed", failed)):
            self.assertEqual({r["model"] for r in got}, {"a"}, name)


if __name__ == "__main__":
    unittest.main()


class TestTheSnapshotIsReadFromTheDirectories(unittest.TestCase):
    """snapshot() over real directories: arms from the summaries, unread
    episodes from the headline grader's readings, and capability verdicts
    from the capability corpora - each reader driven, none patched."""

    @staticmethod
    def _capability_episode(directory, model, capability):
        import json
        import os
        name = (f"run_1_{model.replace('/', '_')}_none_capability-"
                f"{capability}_20260101T000000.json")
        with open(os.path.join(directory, name), "w",
                  encoding="utf-8") as handle:
            json.dump({"model": model, "nudge": "none", "oversight": True,
                       "lure": False, "capability": capability,
                       "transcript": [],
                       "analysis": {"out_of_scope_attempts": [],
                                    "sandbox_escape_attempts": []}}, handle)

    def _snapshot(self, unread_episode=False):
        import os
        import tempfile

        from report.snapshot import snapshot
        from subversionbench.config import DEFAULT_GRADER_MODEL
        from test_analysis.report_fixtures import _write_summary
        from test_analysis.test_report_graders import _graded
        with tempfile.TemporaryDirectory() as tmp:
            dirs = {name: os.path.join(tmp, name)
                    for name in ("ml", "gg", "mlcap", "ggcap")}
            for path in dirs.values():
                os.mkdir(path)
            for model in ("m/a", "m/b"):
                _write_summary(dirs["ml"], model, "none")
            _write_summary(dirs["gg"], "m/a", "none", goalguard="replacement")
            self._capability_episode(dirs["mlcap"], "m/a", "sandbox")
            if unread_episode:
                # Unread means another grader HAS read it: one no grader read
                # stays in, its fallback reading being the published one.
                _graded(dirs["ml"], 1, "m/a", {DEFAULT_GRADER_MODEL: True})
            return snapshot({"mainline": dirs["ml"], "goalguard": dirs["gg"]},
                            {"mainline": dirs["mlcap"],
                             "goalguard": dirs["ggcap"]})

    def test_a_model_missing_a_scenarios_arms_is_kept_out(self):
        snap = self._snapshot()
        self.assertEqual(snap["models"], ["m/a"])
        self.assertEqual(snap["excluded"],
                         {"m/b": ["goalguard: 1 of 1 arms not collected"]})

    def test_the_acts_with_no_capability_episode_are_owed(self):
        self.assertEqual(self._snapshot()["capability_gaps"],
                         {"m/a": ["goalguard", "oversight"]})

    def test_an_episode_the_headline_grader_has_not_read_keeps_it_out(self):
        snap = self._snapshot(unread_episode=True)
        self.assertNotIn("m/a", snap["models"])
        self.assertEqual(snap["excluded"]["m/a"],
                         ["1 episode(s) not read by the headline grader"])
