"""
Preparing text for a grader call, and parsing what comes back.

A leaf shared by two modules: grader.py builds the request, and
quote_grounding.py has to reconstruct exactly what the grader was shown to check a
citation against it. If the two truncated differently, a quote would be verified
against a longer corpus than the grader saw, and "verified" would mean nothing.
"""

import pytest

from subversionbench.grading.grader_io import (_GRADER_TRANSCRIPT_CHAR_BUDGET,
                                               _parse_first_json,
                                               _truncate_for_grader)


class TestParsingAModelReply:
    """Requiring the whole reply to parse cost two of ~24 classifier calls in the
    first pilot, each silently downgraded to a keyword fallback."""

    def test_a_bare_object_parses(self):
        assert _parse_first_json('{"verdict": "admitted"}') == {
            "verdict": "admitted"}

    def test_trailing_commentary_is_ignored(self):
        """The specific failure. Models routinely add a sentence after the JSON."""
        assert _parse_first_json(
            '{"verdict": "denied"}\n\nI hope that helps!') == {"verdict": "denied"}

    def test_a_fenced_block_parses(self):
        assert _parse_first_json(
            '```json\n{"answer": true}\n```') == {"answer": True}

    def test_an_unlabelled_fence_parses_too(self):
        assert _parse_first_json('```\n{"answer": false}\n```') == {
            "answer": False}

    def test_preamble_before_the_object_is_skipped(self):
        assert _parse_first_json(
            'Here is my assessment:\n{"answer": true}') == {"answer": True}

    def test_nested_objects_survive(self):
        """raw_decode has to consume the whole object, not stop at the first
        closing brace."""
        got = _parse_first_json('{"rubric": {"a": true, "b": {"c": 1}}} done')
        assert got == {"rubric": {"a": True, "b": {"c": 1}}}

    def test_no_object_raises_rather_than_returning_empty(self):
        """An empty dict would read as a grader that answered no to everything,
        which is a verdict rather than a failure."""
        with pytest.raises(ValueError, match="no JSON object"):
            _parse_first_json("I cannot answer that.")

    def test_a_bare_list_is_refused(self):
        """Every caller subscripts the result by name, so a list must not get
        through. It is caught by the "no object" branch rather than the isinstance
        check below it, because the scan starts at the first `{`: a reply with no
        brace never reaches the decoder.

        Which makes the isinstance check defensive only - asserted here as the
        behaviour it produces, not as the branch it takes, so a future change to
        the scan does not silently make this test about nothing.
        """
        with pytest.raises(ValueError):
            _parse_first_json('[1, 2, 3]')

    def test_the_error_shows_what_came_back(self):
        """A parse failure with no sample of the reply cannot be diagnosed
        without re-running the call."""
        with pytest.raises(ValueError, match="refuse"):
            _parse_first_json("I refuse to comply with this request.")


class TestTruncatingForTheGrader:
    def test_text_within_budget_is_returned_unchanged(self):
        assert _truncate_for_grader("short") == "short"

    def test_both_ends_are_preserved(self):
        """Truncating from the head alone drops what was said later in the
        conversation - which is where eval-awareness commentary and the final
        decision land, once the agent has reasoned through the dilemma."""
        text = "START" + ("x" * 50_000) + "END"
        got = _truncate_for_grader(text)
        assert got.startswith("START") and got.endswith("END")

    def test_the_cut_is_marked_rather_than_silent(self):
        """A grader shown a seamless join would treat two distant passages as
        adjacent, and a quote spanning the join would verify against text that was
        never contiguous."""
        got = _truncate_for_grader("y" * 50_000)
        assert "truncated" in got

    def test_the_result_respects_the_budget(self):
        budget = 1000
        got = _truncate_for_grader("z" * 50_000, budget=budget)
        assert len(got) <= budget + len("\n\n[... middle truncated ...]\n\n")

    def test_the_tail_gets_the_larger_share(self):
        """Deliberate: the end of an episode carries the closing report, which is
        what disclosure is read from."""
        got = _truncate_for_grader("A" * 20_000 + "B" * 20_000, budget=1000)
        assert got.count("B") > got.count("A")

    def test_the_default_budget_is_the_shared_constant(self):
        """grader.py and quote_grounding.py must truncate identically or a quote
        is checked against a different corpus than the grader was shown."""
        assert _truncate_for_grader("q" * (_GRADER_TRANSCRIPT_CHAR_BUDGET + 1)) \
            != "q" * (_GRADER_TRANSCRIPT_CHAR_BUDGET + 1)
        assert _truncate_for_grader("q" * _GRADER_TRANSCRIPT_CHAR_BUDGET) \
            == "q" * _GRADER_TRANSCRIPT_CHAR_BUDGET
