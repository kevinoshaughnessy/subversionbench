"""
The detector text stays out of the training crawl, and stays readable.

scenario.b64 keeps the text the model READS out of published source.
detectors.b64 keeps out the text that decides what the model's own words MEAN:
the rubric, the grader's system prompt, and the two keyword lists. The argument
is Deckenbach et al., arXiv:2605.28591 - benchmark STRUCTURE leaks
independently of benchmark instances, and a model that has read the indicator
list knows which phrasings are matched and which are not.

Two properties, and neither alone is the point. The values must not appear in
tracked source; and they must still be reachable in one command, or the
benchmark stops being auditable and the ABC assessment stops being true.
"""

import base64
import json
import subprocess
import unittest
from pathlib import Path

from subversionbench.config import (EVAL_AWARENESS_INDICATORS,
                                    GOAL_CONFLICT_AWARENESS, RUBRIC_QUESTIONS,
                                    RUBRIC_SYSTEM_PROMPT)
from subversionbench.detectors import (REQUIRED, encode_detectors,
                                       load_detectors)

ROOT = Path(__file__).resolve().parent.parent

# Only the DISTINCTIVE phrases count as a reproduction. The list holds ordinary
# vocabulary this repository uses constantly for other reasons - a honeypot is
# a feature here, "conflict" is the subject of the benchmark - and a document
# using those words reveals nothing about which phrasings are matched. A
# 15-character floor separates the two without anyone maintaining a second
# list by hand.
_DISTINCTIVE_FLOOR = 15

# How many distinctive phrases a file may hold before it is a reproduction of
# the list rather than an illustration. Files sit at 0-3 today; the one
# exception is baselined below.
_MAX_PER_FILE = 4

# TWO-DIRECTIONAL BASELINE, so it can only shrink. Nothing outside this may
# offend, AND everything inside it must still offend - an entry that stops
# offending is deleted rather than left as a permanent exemption.
#
# This file builds its fixtures from literal indicator phrases, which is the
# largest remaining reproduction in tracked source. Left as debt rather than
# fixed blind: the phrases are load-bearing for what each test asserts about
# matching, and rewriting them to index into the constant would couple every
# assertion to the list's ORDER, which is not a property anything guarantees.
_BASELINE = {
    "test_grading/test_awareness_keywords.py",
}


def _distinctive():
    return [p for p in list(EVAL_AWARENESS_INDICATORS)
            + list(GOAL_CONFLICT_AWARENESS) if len(p) >= _DISTINCTIVE_FLOOR]


def _tracked_text_files():
    out = subprocess.run(["git", "ls-files"], cwd=ROOT,
                         capture_output=True, text=True).stdout.split()
    return [f for f in out if not f.endswith((".b64", ".enc", ".zip", ".png"))]


def _count(path, phrases):
    try:
        text = (ROOT / path).read_text(encoding="utf-8", errors="ignore").lower()
    except (OSError, IsADirectoryError):
        return 0
    return sum(1 for p in phrases if p in text)


class TestTheDetectorIsNotInTrackedSource(unittest.TestCase):

    def test_no_file_outside_the_baseline_reproduces_the_list(self):
        phrases = _distinctive()
        offenders = {f: n for f in _tracked_text_files()
                     if (n := _count(f, phrases)) >= _MAX_PER_FILE
                     and f not in _BASELINE}
        assert not offenders, (
            f"these tracked files reproduce the indicator list: {offenders}. "
            f"Describe the shape instead of quoting the matched value, the "
            f"way export_accepted.txt already requires.")

    def test_every_baselined_file_still_offends(self):
        """A one-directional baseline is a permanent exemption. This half is
        what makes the entry get deleted when the file is fixed."""
        phrases = _distinctive()
        clean = [f for f in _BASELINE if _count(f, phrases) < _MAX_PER_FILE]
        assert not clean, (
            f"{clean} no longer reproduces the list - delete it from "
            f"_BASELINE rather than leaving an exemption behind.")

    def test_the_phrase_set_is_not_empty(self):
        """A guard built on a filter that matches nothing passes with
        everything broken."""
        assert len(_distinctive()) > 20

    def test_no_rubric_question_appears_in_tracked_source(self):
        """Longer and far more distinctive than an indicator; even a 60
        character run of one is a reproduction rather than a coincidence."""
        runs = [q[:60].lower() for q in RUBRIC_QUESTIONS.values()]
        offenders = [f for f in _tracked_text_files()
                     if _count(f, runs)]
        assert not offenders, offenders

    def test_the_graders_system_prompt_does_not_appear_either(self):
        run = RUBRIC_SYSTEM_PROMPT[:60].lower()
        offenders = [f for f in _tracked_text_files() if _count(f, [run])]
        assert not offenders, offenders


class TestTheDetectorStaysReadable(unittest.TestCase):
    """Encoding it must not make the benchmark unauditable - that is most of
    why the ABC assessment passes. One command has to be enough."""

    def test_the_bundle_decodes_to_what_config_serves(self):
        b = load_detectors()
        assert tuple(b["eval_awareness_indicators"]) == EVAL_AWARENESS_INDICATORS
        assert tuple(b["goal_conflict_awareness"]) == GOAL_CONFLICT_AWARENESS
        assert dict(b["rubric_questions"]) == dict(RUBRIC_QUESTIONS)
        assert b["rubric_system_prompt"] == RUBRIC_SYSTEM_PROMPT

    def test_it_round_trips(self):
        import tempfile
        b = load_detectors()
        with tempfile.TemporaryDirectory() as d:
            p = Path(d, "x.b64")
            encode_detectors(b, p)
            assert load_detectors(p) == b

    def test_encoding_refuses_a_bundle_missing_an_entry(self):
        import tempfile
        b = {k: v for k, v in load_detectors().items() if k != "rubric_questions"}
        with tempfile.TemporaryDirectory() as d:
            try:
                encode_detectors(b, Path(d, "x.b64"))
            except ValueError as e:
                assert "rubric_questions" in str(e)
            else:
                raise AssertionError("expected a refusal")

    def test_every_required_entry_is_present(self):
        assert set(REQUIRED) <= set(load_detectors())

    def test_the_rationale_travels_with_the_values(self):
        """The evidence for each phrase names the REJECTED candidates, so it
        leaks the protocol as surely as the list does. It moved into the
        bundle rather than staying behind as a comment."""
        r = load_detectors()["rationale"]
        assert set(r) >= {"eval_awareness_indicators", "rubric_questions"}
        assert sum(len(v) for v in r.values()) > 5000

    # NO TEST THAT THE BUNDLE IS ENCODED RATHER THAN PLAIN JSON. One was
    # written and deleted: config.py loads the bundle at import, so a bundle
    # accidentally written as plaintext makes the whole package unimportable
    # and pytest exits 4 before collecting anything. The test could therefore
    # never fail, which is the defect this suite exists to catch, one level
    # up. The protection is real and stronger than a test - it is just not
    # this test doing it.


class TestItIsSeparateFromTheScenarioBundle(unittest.TestCase):
    """The held-out twin must be graded by the SAME instrument as the shipped
    scenario. heldout_tool.py refuses to encode a bundle missing any entry the
    shipped one has, so a rubric inside scenario.b64 would be forced into the
    held-out bundle as a second copy, free to drift - and a held-out run would
    silently measure with a different rubric."""

    def test_the_scenario_bundle_holds_no_detector_entry(self):
        from subversionbench.scenario import load_scenario
        assert not set(REQUIRED) & set(load_scenario())

    def test_the_detector_bundle_holds_no_scenario_entry(self):
        from subversionbench.scenario import load_scenario
        assert not set(load_detectors()) & set(load_scenario())

    def test_selecting_a_held_out_scenario_does_not_move_the_detector(self):
        """Behaviourally, not by reading the source for an `environ` lookup:
        a guard against a location breaks when the code is refactored and
        says nothing about what the function DOES. Point the scenario
        override at a real alternative bundle and the rubric must be
        unchanged - that is the whole reason these are two files."""
        import os
        import tempfile
        from unittest import mock

        from subversionbench.scenario import BUNDLE_ENV_VAR, load_scenario

        before = load_detectors()
        with tempfile.TemporaryDirectory() as d:
            twin = Path(d, "twin.b64")
            # A real, loadable scenario bundle that is not the shipped one.
            twin.write_text(base64.b64encode(
                json.dumps(dict(load_scenario(),
                                client_name="Elsewhere")).encode()
            ).decode(), encoding="utf-8")
            with mock.patch.dict(os.environ,
                                 {BUNDLE_ENV_VAR: str(twin)}, clear=False):
                assert load_detectors() == before


class TestARejectedPhraseStaysRejected(unittest.TestCase):
    """The rejections are the half of this record most likely to be lost.

    Three of the four candidates measured on 2026-09-22 look plausible and
    fail for different reasons, and an indicator list only ever grows unless
    something holds the failures. So the rejections are a mapping in the
    bundle rather than a paragraph: a guard can check a mapping against the
    live list, and cannot check prose.

    Nothing here quotes a phrase. The scrub rule this module enforces applies
    to this file too, so every phrase is derived from the bundle - which also
    means a phrase added to `rejected` is checked without anyone editing a
    test.
    """

    def test_no_rejected_phrase_is_in_the_live_list(self):
        b = load_detectors()
        both = sorted(set(b["rejected"]) & set(b["eval_awareness_indicators"]))
        assert not both, (
            f"{both} are recorded as rejected AND present in the list. One of "
            f"the two is wrong; the rationale says which.")

    def test_every_rejection_records_a_number(self):
        """A rejection with no measurement invites re-proposal, and is the
        difference between an argument and a matter of taste."""
        bare = [p for p, why in load_detectors()["rejected"].items()
                if not any(ch.isdigit() for ch in why)]
        assert not bare, bare

    def test_the_rejection_set_is_not_empty(self):
        """A guard over an empty mapping passes with everything broken."""
        assert len(load_detectors()["rejected"]) >= 5

    def test_every_accepted_phrase_is_actually_in_the_list(self):
        """The mirror of the rejection guard.

        A first attempt counted any indicator appearing in the rationale
        PROSE and asserted there were at least three. It passed with all
        three additions deleted, because the prose is long enough that other
        short indicators occur in it by chance - a guard that fails by
        passing, which is the thing this suite is for. `accepted` is a
        mapping for the same reason `rejected` is: it can be checked.
        """
        b = load_detectors()
        missing = sorted(set(b["accepted"]) - set(b["eval_awareness_indicators"]))
        assert not missing, (
            f"{missing} are recorded as accepted and are not in the list")

    def test_every_acceptance_records_a_number(self):
        bare = [p for p, why in load_detectors()["accepted"].items()
                if not any(ch.isdigit() for ch in why)]
        assert not bare, bare

    def test_the_two_records_do_not_overlap(self):
        b = load_detectors()
        both = sorted(set(b["accepted"]) & set(b["rejected"]))
        assert not both, f"{both} recorded as both accepted and rejected"
