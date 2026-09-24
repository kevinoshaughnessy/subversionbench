"""
What identifies an arm, and that every row shape agrees about it.

An arm is the unit a rate is published for. Four different loaders build
arm-shaped rows - a summary row, an episode row, a failed-episode row and a
rebuilt arm row - and each one has to agree about which fields name the arm,
or two different conditions end up averaged under one label.

These guard the rule rather than a field list: the scope is derived from
ARM_FIELDS, so a coordinate added to the arm later is covered here without
this file being edited. That is the failure this file exists for - `goalguard`
was a real coordinate that only one of the four row shapes carried.
"""

import tempfile
import unittest

from report import duplicate_arms, load_episodes, load_summaries
from report.loading import ARM_FIELDS, act_arm_rows, awareness_arm_rows
from test_analysis.report_fixtures import _write_episode, _write_summary


class TestEveryRowShapeCarriesTheWholeArm(unittest.TestCase):
    """
    Derived from ARM_FIELDS rather than listed. A field in the key that some
    row shape does not carry groups every row of that shape under None, which
    is how the attrition table came to match no episode - and, in the other
    direction, how two goal-guarding arms came to pool into one rate.
    """

    def _corpus(self, out):
        _write_summary(out, "m/a", "strong", goalguard="replacement")
        _write_episode(out, 1, "m/a", "strong", goalguard="replacement")
        return out

    def test_a_summary_row_carries_every_arm_field(self):
        with tempfile.TemporaryDirectory() as out:
            row = load_summaries(self._corpus(out))[0]
            self.assertTrue(set(ARM_FIELDS) <= set(row),
                            f"missing: {set(ARM_FIELDS) - set(row)}")
            self.assertEqual(row["goalguard"], "replacement")

    def test_an_episode_row_carries_every_arm_field(self):
        with tempfile.TemporaryDirectory() as out:
            row = load_episodes(self._corpus(out))[0]
            self.assertTrue(set(ARM_FIELDS) <= set(row),
                            f"missing: {set(ARM_FIELDS) - set(row)}")
            self.assertEqual(row["goalguard"], "replacement")

    def test_both_rebuilt_arm_row_shapes_carry_every_arm_field(self):
        """
        The rows questions 1-4 pool from under the awareness reading. Both
        builders are checked, derived from a list of them, because they are
        two copies of the same rollup and a field added to one and not the
        other is a report whose halves disagree about what an arm is.
        """
        with tempfile.TemporaryDirectory() as out:
            episodes = load_episodes(self._corpus(out))
            for builder in (act_arm_rows, awareness_arm_rows):
                with self.subTest(builder=builder.__name__):
                    row = builder(episodes)[0]
                    self.assertTrue(
                        set(ARM_FIELDS) <= set(row),
                        f"{builder.__name__} missing: "
                        f"{set(ARM_FIELDS) - set(row)}")
                    self.assertEqual(row["goalguard"], "replacement")


class TestTheGoalGuardingArmsDoNotPool(unittest.TestCase):
    """
    THE DEFECT THIS FILE WAS WRITTEN FOR, measured before it was fixed.

    `deferred` and `replacement` stage different scenarios - the same file and
    the same means, differing in the motive the model is given for editing it.
    They are two conditions, not two samples of one, so a rate over both is an
    average of two populations rather than a less precise estimate of either.

    On the pilot corpus the report read gemini/none as 9/19 misaligned, which
    is a 9/10 arm and a 0/9 arm averaged into a number neither of them is.
    """

    def _two_arms(self, out):
        for n in range(3):
            _write_episode(out, n, "m/a", "strong", goalguard="replacement",
                           stamp=f"2026010100000{n}", tampered=True)
        for n in range(3, 5):
            _write_episode(out, n, "m/a", "strong", goalguard="deferred",
                           stamp=f"2026010100000{n}")
        return load_episodes(out)

    def test_the_two_arms_are_two_rows_not_one(self):
        with tempfile.TemporaryDirectory() as out:
            rows = act_arm_rows(self._two_arms(out))

            self.assertEqual(len(rows), 2)
            by_arm = {r["goalguard"]: r for r in rows}
            self.assertEqual(by_arm["replacement"]["n_runs"], 3)
            self.assertEqual(by_arm["deferred"]["n_runs"], 2)

    def test_a_rate_is_not_averaged_across_the_two_arms(self):
        """
        The numbers, not merely the row count. Pooled, these five episodes
        report 3/5; split, they report 3/3 and 0/2 - and no arm reports the
        pooled figure, which is the assertion that fails when they pool.
        """
        with tempfile.TemporaryDirectory() as out:
            rows = act_arm_rows(self._two_arms(out))
            by_arm = {r["goalguard"]: r for r in rows}

            self.assertEqual(by_arm["replacement"]["n_misaligned"], 3)
            self.assertEqual(by_arm["deferred"]["n_misaligned"], 0)


class TestTwoArmsAreNotReportedAsOneCollectedTwice(unittest.TestCase):
    """
    Checked in BOTH directions, because a one-directional check here is worse
    than none: `duplicate_arms` tells the operator to "delete or move the
    superseded batch", and it was firing on the two goal-guarding arms. Acting
    on that advice throws away half an experiment.
    """

    def test_two_different_goal_guarding_arms_are_not_duplicates(self):
        with tempfile.TemporaryDirectory() as out:
            _write_summary(out, "m/a", "strong", goalguard="replacement",
                           stamp="20260101T000001")
            _write_summary(out, "m/a", "strong", goalguard="deferred",
                           stamp="20260101T000002")

            self.assertEqual(duplicate_arms(load_summaries(out)), [])

    def test_one_arm_collected_twice_is_still_a_duplicate(self):
        """The other direction. Without this, the check above passes with
        duplicate_arms returning [] unconditionally."""
        with tempfile.TemporaryDirectory() as out:
            _write_summary(out, "m/a", "strong", goalguard="replacement",
                           stamp="20260101T000001")
            _write_summary(out, "m/a", "strong", goalguard="replacement",
                           stamp="20260101T000002")

            dupes = duplicate_arms(load_summaries(out))

            self.assertEqual(len(dupes), 1)
            self.assertEqual(dupes[0]["n_batches"], 2)
            self.assertEqual(dupes[0]["goalguard"], "replacement")

    def test_a_propensity_corpus_is_unaffected(self):
        """
        Every episode ever collected without the goal-guarding bundle records
        None here, so the new coordinate must partition such a corpus exactly
        as before - which is why the published corpus does not move.
        """
        with tempfile.TemporaryDirectory() as out:
            _write_summary(out, "m/a", "strong", stamp="20260101T000001")
            _write_summary(out, "m/a", "strong", stamp="20260101T000002")

            dupes = duplicate_arms(load_summaries(out))

            self.assertEqual(len(dupes), 1)
            self.assertIsNone(dupes[0]["goalguard"])


if __name__ == "__main__":
    unittest.main()
