"""
Episodes that were attempted and never produced an analysis.

The rule these guard is the one this codebase already applies one level down -
a failed grader leaves the DENOMINATOR rather than reading as "not aware". An
episode lost to an API error cannot join a denominator, because there is no
verdict to put in it; what it must not do is vanish, because attrition is not
always random with respect to the outcome being measured.
"""

import json
import os
import tempfile
import unittest

from report import (attrition_facts, data_quality_facts, load_episodes,
                    load_failed_episodes)
from report.console_data_quality import _print_attrition
from report.loading import ARM_FIELDS, arm_key
from test_analysis.report_fixtures import (_write_episode,
                                           _write_failed_episode)


class TestTheLoaderReadsOnlyTheAttemptedEpisodes(unittest.TestCase):
    """
    The two loaders partition the directory: every file goes to exactly one.

    Asserted in BOTH directions on one directory holding both kinds, because
    each failure is silent and they are different bugs. A failed episode
    reaching `load_episodes` is a run with no analysis in a rate's
    denominator; an analysed episode reaching `load_failed_episodes` is a
    completed run counted as a loss.
    """

    def test_the_two_loaders_partition_the_directory(self):
        with tempfile.TemporaryDirectory() as out:
            _write_episode(out, 1, "m/a", "strong")
            _write_episode(out, 2, "m/a", "strong", stamp="20260101T000001")
            _write_failed_episode(out, 3, "m/a", "strong",
                                  stamp="20260101T000002")

            analysed = load_episodes(out)
            failed = load_failed_episodes(out)

            self.assertEqual(len(analysed), 2)
            self.assertEqual(len(failed), 1)
            # And the whole directory is accounted for: every .json that is
            # not a summary went to one loader or the other. A third glob that
            # matched neither would be episodes nobody counts at all.
            written = [f for f in sorted(os.listdir(out))
                       if not f.startswith("summary")]
            self.assertEqual(len(written), len(analysed) + len(failed))

    def test_a_failed_episode_carries_no_transcript_into_the_report(self):
        """
        The saved partial holds the same scenario text a run file does, and
        nothing downstream reads it. Asserted on the loaded row rather than on
        the loader's source, because a guard that greps a function's body for
        a key it does not copy passes the moment the copying moves to a
        helper.
        """
        with tempfile.TemporaryDirectory() as out:
            path = _write_failed_episode(out, 1, "m/a", "strong")
            with open(path, encoding="utf-8") as handle:
                saved = json.load(handle)
            # The fixture wrote the field, so its absence below is the
            # loader's doing rather than the fixture's.
            saved["transcript"] = [{"role": "user", "content": "scenario"}]
            saved["system_prompt"] = "scenario"
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(saved, handle)

            row = load_failed_episodes(out)[0]

            for field in ("transcript", "system_prompt", "user_prompt"):
                self.assertNotIn(field, row)
            self.assertNotIn("scenario", json.dumps(row))

    def test_the_error_class_is_carried_and_the_message_is_not(self):
        """
        A provider's message carries its wording, sometimes an account
        identifier and sometimes a path. The class is what tells a routing
        mistake from a transient, and is the whole of what a reader needs.
        """
        with tempfile.TemporaryDirectory() as out:
            _write_failed_episode(
                out, 1, "m/a", "strong",
                error="NotFoundError: no endpoints for user acct_12345")

            row = load_failed_episodes(out)[0]

            self.assertEqual(row["error_class"], "NotFoundError")
            self.assertNotIn("acct_12345", json.dumps(row))

    def test_an_error_with_no_colon_still_classifies(self):
        with tempfile.TemporaryDirectory() as out:
            _write_failed_episode(out, 1, "m/a", "strong", error="")
            self.assertEqual(load_failed_episodes(out)[0]["error_class"],
                             "unknown")


class TestTheAttritionArmIsTheReportsArm(unittest.TestCase):
    """
    THE DEFECT THIS EXISTS FOR, planted and measured before it was written.

    The first version of `attrition_facts` built its own arm key and gave it a
    fifth field, `goalguard`, which failed episodes record and episode rows do
    not carry at all. Every arm it produced therefore matched no episode, and
    the table read "0/6 analysed" for arms holding nineteen analysed episodes.
    The table looked like a catastrophe and the corpus was fine.

    So the rule is not "use these four fields" - that is a second copy of the
    grouping, which is what went wrong - it is "use the same key the rates
    being qualified are grouped by", and it is checked by grouping both ways
    and comparing.
    """

    def test_the_key_is_the_one_the_report_groups_arms_by(self):
        from report.loading import act_arm_rows
        with tempfile.TemporaryDirectory() as out:
            for n in range(3):
                _write_episode(out, n, "m/a", "strong",
                               stamp=f"2026010100000{n}")

            episodes = load_episodes(out)
            rows = act_arm_rows(episodes)

            # The arms the report built, and the arms attrition would build,
            # derived from the same episodes rather than written out here.
            self.assertEqual(
                {arm_key(row) for row in rows},
                {arm_key(ep) for ep in episodes})

    def test_an_arm_that_lost_episodes_reports_the_ones_it_kept(self):
        with tempfile.TemporaryDirectory() as out:
            for n in range(4):
                _write_episode(out, n, "m/a", "strong",
                               stamp=f"2026010100000{n}")
            _write_failed_episode(out, 9, "m/a", "strong",
                                  stamp="20260101T000009")

            facts = attrition_facts(load_episodes(out),
                                    load_failed_episodes(out))

            self.assertEqual(len(facts["arms_with_losses"]), 1)
            arm = facts["arms_with_losses"][0]
            # The specific numbers, not merely that the arm appeared: the
            # planted defect produced an arm with exactly these keys and a
            # zero in n_analysed.
            self.assertEqual(arm["n_analysed"], 4)
            self.assertEqual(arm["n_lost"], 1)
            self.assertEqual(arm["n_attempted"], 5)
            self.assertEqual(arm["model"], "m/a")
            self.assertEqual(arm["nudge"], "strong")

    def test_a_field_outside_the_key_cannot_split_an_arm(self):
        """
        Two failures in one arm differing only on a field outside ARM_FIELDS
        are one arm's losses, not two arms'. `failed_on_turn` is such a field:
        when an episode died is a property of the loss, not of the arm.
        """
        with tempfile.TemporaryDirectory() as out:
            _write_episode(out, 1, "m/a", "strong")
            _write_failed_episode(out, 2, "m/a", "strong",
                                  stamp="20260101T000002", failed_on_turn=1)
            _write_failed_episode(out, 3, "m/a", "strong",
                                  stamp="20260101T000003", failed_on_turn=18)

            facts = attrition_facts(load_episodes(out),
                                    load_failed_episodes(out))

            self.assertEqual(len(facts["arms_with_losses"]), 1)
            self.assertEqual(facts["arms_with_losses"][0]["n_lost"], 2)
            self.assertEqual(facts["arms_with_losses"][0]["n_analysed"], 1)
            self.assertNotIn("failed_on_turn", facts["arms_with_losses"][0])

    def test_the_goal_guarding_arm_splits_an_arm(self):
        """
        The counterpart, and the reason `goalguard` is in ARM_FIELDS: the two
        goal-guarding arms are different scenarios, not two samples of one, so
        their losses belong to different arms and so do their rates.
        """
        with tempfile.TemporaryDirectory() as out:
            _write_failed_episode(out, 1, "m/a", "strong",
                                  stamp="20260101T000001",
                                  goalguard="replacement")
            _write_failed_episode(out, 2, "m/a", "strong",
                                  stamp="20260101T000002",
                                  goalguard="deferred")

            arms = attrition_facts([], load_failed_episodes(out))[
                "arms_with_losses"]

            self.assertEqual(len(arms), 2)
            self.assertEqual({a["goalguard"] for a in arms},
                             {"replacement", "deferred"})

    def test_every_arm_field_appears_in_the_reported_row(self):
        """Derived from ARM_FIELDS rather than listed, so a field added to the
        arm identity later is carried here without this test being edited."""
        with tempfile.TemporaryDirectory() as out:
            _write_failed_episode(out, 1, "m/a", "strong")
            arm = attrition_facts([], load_failed_episodes(out))[
                "arms_with_losses"][0]
            self.assertTrue(set(ARM_FIELDS) <= set(arm))


class TestTheTurnSeparatesTwoDifferentLosses(unittest.TestCase):
    """
    An episode that died on turn 1 made no tool call, so nothing it would have
    done is missing from a numerator - it cost an attempt. An episode that
    died mid-run was still working, and its outcome is unknown. Reporting only
    the total reads as the worse of the two, and on the goal-guarding pilot
    eleven of fourteen losses were turn-1 losses.
    """

    def test_a_turn_one_loss_is_counted_apart_from_a_mid_episode_one(self):
        with tempfile.TemporaryDirectory() as out:
            _write_failed_episode(out, 1, "m/a", "strong",
                                  stamp="20260101T000001", failed_on_turn=1)
            _write_failed_episode(out, 2, "m/a", "strong",
                                  stamp="20260101T000002", failed_on_turn=18)

            facts = attrition_facts([], load_failed_episodes(out))

            self.assertEqual(facts["n_lost_to_errors"], 2)
            self.assertEqual(facts["n_lost_before_any_turn_completed"], 1)
            self.assertEqual(facts["lost_on_turn"], {1: 1, 18: 1})

    def test_the_totals_add_up(self):
        with tempfile.TemporaryDirectory() as out:
            _write_episode(out, 1, "m/a", "strong")
            _write_failed_episode(out, 2, "m/a", "strong",
                                  stamp="20260101T000002")
            facts = attrition_facts(load_episodes(out),
                                    load_failed_episodes(out))
            self.assertEqual(facts["n_attempted"],
                             facts["n_analysed"] + facts["n_lost_to_errors"])


class TestTheReportSaysWhatItLost(unittest.TestCase):
    """The facts have to reach the document, not merely be computable."""

    def test_data_quality_facts_carries_attrition(self):
        with tempfile.TemporaryDirectory() as out:
            _write_episode(out, 1, "m/a", "strong")
            _write_failed_episode(out, 2, "m/a", "strong",
                                  stamp="20260101T000002")

            facts = data_quality_facts(load_episodes(out), [],
                                       load_failed_episodes(out))

            self.assertEqual(facts["attrition"]["n_lost_to_errors"], 1)
            self.assertEqual(facts["attrition"]["n_attempted"], 2)

    def test_a_corpus_with_no_failures_still_says_what_it_attempted(self):
        """
        Printed with its zero. A caveat that appears only when it has
        something to say cannot be read as having checked - the same terms the
        routing checks beside it are printed on.
        """
        with tempfile.TemporaryDirectory() as out:
            _write_episode(out, 1, "m/a", "strong")
            facts = data_quality_facts(load_episodes(out), [],
                                       load_failed_episodes(out))
            self.assertEqual(facts["attrition"]["n_lost_to_errors"], 0)
            printed = _printed(facts["attrition"])
            self.assertIn("attempted", printed)
            self.assertIn("1", printed)

    def test_the_printed_block_names_the_arm_and_the_error_class(self):
        with tempfile.TemporaryDirectory() as out:
            _write_episode(out, 1, "m/a", "strong")
            _write_failed_episode(out, 2, "m/a", "strong",
                                  stamp="20260101T000002",
                                  error="BadRequestError: upstream said no")

            printed = _printed(attrition_facts(load_episodes(out),
                                               load_failed_episodes(out)))

            self.assertIn("BadRequestError", printed)
            self.assertIn("m/a", printed)
            # The message stays out of the printed block too, not only out of
            # the JSON.
            self.assertNotIn("upstream said no", printed)

    def test_the_section_itself_prints_the_attrition_block(self):
        """
        THE WIRING, not the printer. Every other test here calls
        `_print_attrition` directly, so deleting its one call site from
        `_print_data_quality` would leave all of them green and the operator
        with a report that has lost the line. Renders the whole section and
        looks for the line in it.
        """
        with tempfile.TemporaryDirectory() as out:
            _write_episode(out, 1, "m/a", "strong")
            _write_failed_episode(out, 2, "m/a", "strong",
                                  stamp="20260101T000002")
            facts = data_quality_facts(load_episodes(out), [],
                                       load_failed_episodes(out))

            import contextlib
            import io
            from report.console_data_quality import _print_data_quality
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                _print_data_quality(facts)
            printed = buffer.getvalue()

        self.assertIn("episodes attempted: 2", printed)
        self.assertIn("1 lost to errors", printed)

    def test_the_block_is_silent_when_there_is_no_attrition_section(self):
        """A corpus analysed by an older report has no attrition key; the
        printer must skip rather than raise, because the rest of the section
        below it is what the operator called the tool for."""
        self.assertEqual(_printed({}), "")


def _printed(attrition: dict) -> str:
    import contextlib
    import io
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        _print_attrition(attrition)
    return buffer.getvalue()


if __name__ == "__main__":
    unittest.main()


class TestTheReportSaysWhichScenarioItPooled(unittest.TestCase):
    """
    `misaligned` and `scheming` are unions over the acts a scenario stages, so
    two scenarios do not produce the same composite. A corpus straddling both
    reports a number whose elements change between episodes - which is not a
    less precise estimate of anything, it is a quantity with no referent.

    The batch summary's provenance block already answers this per batch. The
    report pools across batches, and nothing in it said what it had pooled.
    """

    def _episode(self, out, n, scenario_id=None, **kw):
        path = _write_episode(out, n, "m/a", "strong",
                              stamp=f"2026010100000{n}", **kw)
        if scenario_id is not None:
            with open(path, encoding="utf-8") as handle:
                saved = json.load(handle)
            saved["scenario_id"] = scenario_id
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(saved, handle)
        return path

    def test_a_single_scenario_corpus_says_so_with_its_count(self):
        """Printed with its one value: a line that appears only when a corpus
        is mixed cannot be read as having checked that it is not."""
        with tempfile.TemporaryDirectory() as out:
            self._episode(out, 1, scenario_id="oversight-sandbox")
            self._episode(out, 2, scenario_id="oversight-sandbox")

            facts = data_quality_facts(load_episodes(out), [])

            self.assertEqual(facts["scenarios"], {"oversight-sandbox": 2})
            self.assertFalse(facts["scenarios_mixed"])

    def test_two_scenarios_in_one_corpus_are_flagged(self):
        with tempfile.TemporaryDirectory() as out:
            self._episode(out, 1, scenario_id="oversight-sandbox")
            self._episode(out, 2, scenario_id="goalguard-oversight-sandbox")

            facts = data_quality_facts(load_episodes(out), [])

            self.assertTrue(facts["scenarios_mixed"])
            self.assertEqual(len(facts["scenarios"]), 2)

    def test_an_episode_predating_the_field_is_the_shipped_act_set(self):
        """
        NOT "unrecorded". The field postdates r1 through r10 and those are one
        scenario, so reading its absence as unknown would put the entire
        published corpus in a second bucket and make every report claim it
        straddles two scenarios. The same reading the batch summary takes.
        """
        from subversionbench.rollout_pins import SCENARIO_ID

        with tempfile.TemporaryDirectory() as out:
            self._episode(out, 1)
            self._episode(out, 2, scenario_id=SCENARIO_ID)

            facts = data_quality_facts(load_episodes(out), [])

            self.assertEqual(facts["scenarios"], {SCENARIO_ID: 2})
            self.assertFalse(facts["scenarios_mixed"])

    def test_the_section_prints_the_scenario_line_and_the_warning(self):
        """The wiring as well as the fact - the same gap that let four
        defects through at the twin's pin seam."""
        import contextlib
        import io

        from report.console_data_quality import _print_data_quality

        with tempfile.TemporaryDirectory() as out:
            self._episode(out, 1, scenario_id="oversight-sandbox")
            self._episode(out, 2, scenario_id="goalguard-oversight-sandbox")
            facts = data_quality_facts(load_episodes(out), [])
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                _print_data_quality(facts)
            printed = buffer.getvalue()

        self.assertIn("scenario act sets in this corpus", printed)
        self.assertIn("goalguard-oversight-sandbox", printed)
        self.assertIn("straddles more than one SCENARIO", printed)
