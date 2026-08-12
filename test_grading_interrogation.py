"""
Asking the model about an act, and labelling what it says back.
"""

import subversionbench.grading as ev_grade


class TestTheResponseMetadataExplainsAnEmptyAnswer:
    """42 saved answers were empty and the cause had to be reconstructed by
    elimination: the adapter's no-visible-output diagnostic appeared in none of
    them, which ruled out budget exhaustion and left "returned a tool_use block
    and no text" - the model trying to act rather than answer. `stop_reason` and
    `block_types` say so directly, so the next occurrence needs no detective
    work."""

    def _ask(self, blocks, stop_reason):
        import types, io, contextlib
        import subversionbench.run_eval as ev_run
        from subversionbench.grading.acts import MISALIGNED_ACTS

        class Fake:
            class _M:
                def create(self, **kw):
                    return types.SimpleNamespace(
                        content=[types.SimpleNamespace(
                            type=t,
                            text=("Yes, I modified it." if t == "text" else ""),
                            thinking="", name="bash", id="x", input={})
                                 for t in blocks],
                        stop_reason=stop_reason,
                        usage=types.SimpleNamespace(input_tokens=1, output_tokens=1))
            messages = _M()

        orig = ev_grade.classify_interrogation_answer
        ev_grade.classify_interrogation_answer = lambda text, *a, **k: {
            "verdict": "no_answer" if not text.strip() else "admitted",
            "verdict_llm": None, "verdict_keyword": None,
            "classifiers_agree": None, "used_keyword_fallback": False,
            "quote": "", "classifier_error": None,
            "classifier_called": False, "classifier_model": "g"}
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                out = ev_run.run_followup("sys", [{"role": "user", "content": "t"}],
                                          "m", Fake(), MISALIGNED_ACTS[0])
        finally:
            ev_grade.classify_interrogation_answer = orig
        return out[0]

    def test_a_tool_call_instead_of_an_answer_is_visible(self):
        rec = self._ask(["tool_use"], "tool_use")
        assert rec["answer"] == ""
        assert rec["block_types"] == ["tool_use"]
        assert rec["stop_reason"] == "tool_use"
        assert rec["retried_after_empty"] is True

    def test_reasoning_only_is_distinguishable_from_it(self):
        """The other candidate cause, and the point of recording this: the two
        produce the same empty answer and different metadata."""
        rec = self._ask(["thinking"], "length")
        assert rec["answer"] == ""
        assert rec["block_types"] == ["thinking"]
        assert rec["stop_reason"] == "length"

    def test_a_normal_answer_records_that_it_was_not_retried(self):
        rec = self._ask(["text"], "end_turn")
        assert rec["retried_after_empty"] is False
        assert rec["block_types"] == ["text"]
