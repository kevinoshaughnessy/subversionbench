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
