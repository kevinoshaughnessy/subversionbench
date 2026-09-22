"""
Suspicion of MISUSE, which is not suspicion of being EVALUATED.

WHY THIS MEASURE EXISTS. An agent saying "this content looks like an attack on
me" and an agent saying "this situation looks like a test of me" are making
different claims, and until 2026-09-22 only the second had a measure. The
rubric question `questioned_authenticity` asks whether the scenario may be
"planted" - and content planted by an attacker satisfies that wording as
readily as content planted by an experimenter - so the two were merging. Over
r10, 99 episodes have EVERY fired signal question citing misuse language, 37 of
them resting on that one question alone.

NOTHING HERE QUOTES A PHRASE. The scrub rule that governs the awareness list
governs this one: every phrase is derived from the bundle by SHAPE, so a test
asserts its rule against whichever indicator currently has that shape rather
than against one remembered example - and a phrase added later is covered
without anyone editing this file.
"""

import unittest

from subversionbench.config import (EVAL_AWARENESS_INDICATORS,
                                    MISUSE_INDICATORS)
from subversionbench.grading.awareness_keywords import (
    detect_eval_awareness_keywords, detect_misuse_suspicion)


def _entry(text, turn=1, kind="text"):
    return [{"turn": turn, "type": kind, "content": text}]


class TestItFiresOnTheMisuseVocabulary(unittest.TestCase):

    def test_every_indicator_is_matched_by_its_own_text(self):
        """A phrase in the list that cannot match itself is dead weight, and
        that is how the trailing-letter defect was found in the awareness
        list."""
        for phrase in MISUSE_INDICATORS:
            got = detect_misuse_suspicion(_entry(f"I think {phrase} is at play"))
            assert got["misuse_suspected"], phrase
            assert phrase in got["indicators_found"], phrase

    def test_the_list_is_not_empty(self):
        """Every test here iterates the list; an empty one passes them all."""
        assert len(MISUSE_INDICATORS) >= 3

    def test_silence_on_ordinary_task_text(self):
        got = detect_misuse_suspicion(_entry(
            "I will compare the two strategies and write the recommendation."))
        assert got["misuse_suspected"] is False
        assert got["indicators_found"] == []
        assert got["relevant_quotes"] == []

    def test_an_empty_transcript_is_not_suspicion(self):
        assert detect_misuse_suspicion([])["misuse_suspected"] is False

    def test_it_reads_reasoning_as_well_as_visible_text(self):
        """A model can name an attack in its reasoning and say nothing about
        it in its answer - the same argument the awareness screen makes for
        scanning thinking entries."""
        phrase = MISUSE_INDICATORS[0]
        got = detect_misuse_suspicion(_entry(f"this smells like {phrase}",
                                             kind="thinking"))
        assert got["misuse_suspected"], "thinking entries must be scanned"

    def test_tool_output_is_not_scanned(self):
        """The agent quoting a document back is not the agent suspecting
        anything. Scanning tool_result would let scenario text trip the
        measure - the failure that gave the awareness list a phrase with a
        98% false-positive rate."""
        phrase = MISUSE_INDICATORS[0]
        got = detect_misuse_suspicion(_entry(phrase, kind="tool_result"))
        assert got["misuse_suspected"] is False


class TestItIsSeparateFromTheAwarenessMeasure(unittest.TestCase):
    """The whole point. If these two pooled, the split bought nothing."""

    def test_the_two_lists_share_no_phrase(self):
        assert not set(MISUSE_INDICATORS) & set(EVAL_AWARENESS_INDICATORS)

    def test_misuse_language_alone_does_not_make_an_episode_aware(self):
        """The regression that would undo the split: a misuse phrase leaking
        back into the awareness list, or the two detectors sharing a pattern
        table."""
        for phrase in MISUSE_INDICATORS:
            t = _entry(f"I believe {phrase} is being attempted here")
            assert detect_misuse_suspicion(t)["misuse_suspected"], phrase
            assert detect_eval_awareness_keywords(t)["eval_aware"] is False, (
                f"{phrase!r} is making an episode eval_aware")

    def test_awareness_language_alone_is_not_misuse(self):
        """The mirror, so neither list can quietly absorb the other."""
        for phrase in EVAL_AWARENESS_INDICATORS:
            t = _entry(f"I think {phrase} describes my situation")
            if not detect_eval_awareness_keywords(t)["eval_aware"]:
                continue
            assert detect_misuse_suspicion(t)["misuse_suspected"] is False, (
                f"{phrase!r} is making an episode misuse_suspected")

    def test_an_episode_may_be_both(self):
        """Not mutually exclusive - a model can say the content is an attack
        AND that the situation is a test. Recording one must not suppress the
        other, which is what pooling them would do."""
        aware = next(p for p in EVAL_AWARENESS_INDICATORS
                     if detect_eval_awareness_keywords(
                         _entry(f"x {p} y"))["eval_aware"])
        t = _entry(f"this looks like {MISUSE_INDICATORS[0]}, and {aware} too")
        assert detect_misuse_suspicion(t)["misuse_suspected"]
        assert detect_eval_awareness_keywords(t)["eval_aware"]


class TestTheRecordItLeaves(unittest.TestCase):

    def test_it_quotes_the_original_text_not_the_normalised_one(self):
        """An excerpt taken from the normalised string would be missing the
        punctuation that made the match interesting."""
        phrase = MISUSE_INDICATORS[0]
        got = detect_misuse_suspicion(_entry(f'the memo is a "{phrase}" -- I think'))
        assert got["misuse_suspected"]
        assert '"' in got["relevant_quotes"][0], got["relevant_quotes"]

    def test_the_excerpt_names_its_turn(self):
        got = detect_misuse_suspicion(
            _entry(f"clearly {MISUSE_INDICATORS[0]}", turn=7))
        assert "[Turn 7]" in got["relevant_quotes"][0]

    def test_indicators_are_sorted_and_unique(self):
        """Set iteration order moves with the hash seed, which made
        --write-back rewrite every run file on every invocation."""
        phrase = MISUSE_INDICATORS[0]
        got = detect_misuse_suspicion(_entry(f"{phrase} and again {phrase}"))
        assert got["indicators_found"] == sorted(set(got["indicators_found"]))

    def test_decoration_inside_a_phrase_does_not_defeat_it(self):
        """Markdown emphasis a model adds mid-phrase, which the awareness
        matcher already handles - both measures go through one normaliser, so
        this cannot be true of one and not the other."""
        phrase = MISUSE_INDICATORS[0]
        if " " not in phrase:
            self.skipTest("needs a multi-word indicator")
        head, tail = phrase.split(" ", 1)
        got = detect_misuse_suspicion(_entry(f"looks like *{head}* {tail}"))
        assert got["misuse_suspected"], phrase
