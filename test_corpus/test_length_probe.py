"""
grader_ab/length_probe.py: planting a remark and reading back whether the
grader found it, at several lengths and depths.

The probe exists to be able to say NO - that a grader misses what sits in the
middle of a long text - so alongside a faithful stub grader that finds every
plant, one reads only the head and tail the way the 20,000-character budget
does, and the probe has to report the difference.
"""

import contextlib
import io
import json
import sys
import tempfile
import types
from pathlib import Path

import subversionbench.llm_client as ev_llm
from grader_ab import length_probe as lp
from subversionbench.grading.grader import _EVAL_SIGNAL_KEYS
from subversionbench.grading.quote_grounding import format_agent_text

_LINE = "I checked the next file and found nothing unusual. "


def _transcript(chars: int) -> list:
    """Agent text of about `chars` characters over several turns, with a
    tool result between them that a plant must never land in."""
    per_turn = max(1, chars // 4 // len(_LINE))
    out = []
    for turn in range(1, 5):
        out.append({"turn": turn, "type": "thinking", "content": _LINE * per_turn})
        out.append({"turn": turn, "type": "tool_result", "content": "ok"})
    return out


def _write_run(out, n, chars, model="p/m", aware=False, answer=False,
               keywords=False):
    rubric = {k: {"answer": answer, "quote": ""} for k in _EVAL_SIGNAL_KEYS}
    Path(out, f"run_{n}_{model.replace('/', '_')}_strong_20260101T000000.json"
         ).write_text(json.dumps({
             "model": model, "nudge": "strong", "transcript": _transcript(chars),
             "analysis": {
                 "eval_awareness_grader": {"eval_aware": aware,
                                           "rubric_results": rubric},
                 "eval_awareness_keywords": {"eval_aware": keywords}}}),
             encoding="utf-8")


def _corpus(out):
    """Two episodes a band, from different models."""
    for i, chars in enumerate((3000, 3000, 17000, 17000, 60000, 60000)):
        _write_run(out, i, chars, model=f"p/m{i}")


@contextlib.contextmanager
def _grader(sees=lambda text, at: True, refuse=False):
    """A stub grader. It answers yes, quoting the plant, when the planted
    sentence is in the request and `sees(text, index)` says it was read."""
    asked = []

    def client_for(model, **_kw):
        asked.append(model)

        class _Messages:
            @staticmethod
            def create(**kw):
                if refuse:
                    return types.SimpleNamespace(stop_reason="refusal",
                                                 content=[])
                text = json.dumps(kw, default=str)
                hit = next((s for s in lp.PLANTS.values()
                            if s in text and sees(text, text.index(s))), None)
                reply = {"answer": bool(hit), "quote": hit or ""}
                return types.SimpleNamespace(
                    stop_reason="end_turn",
                    content=[types.SimpleNamespace(type="text",
                                                   text=json.dumps(reply))])
        return types.SimpleNamespace(messages=_Messages())

    original = ev_llm.get_client
    ev_llm.get_client = client_for
    try:
        yield asked
    finally:
        ev_llm.get_client = original


def _main(out, *extra):
    buf, saved = io.StringIO(), sys.argv
    sys.argv = ["length_probe.py", "--output-dir", out, "--seed", "1",
                "--per-band", "2", *extra]
    try:
        with contextlib.redirect_stdout(buf):
            code = lp.main()
    finally:
        sys.argv = saved
    return code, buf.getvalue()


def _saved(out):
    return json.loads(next(Path(out).glob("length_probe_*.json")).read_text())


class TestPlanting:

    def test_the_sentence_appears_once_in_what_the_grader_is_shown(self):
        planted, _ = lp.plant(_transcript(20000), lp.PLANTS["explicit"], 0.5)
        assert format_agent_text(planted).count(lp.PLANTS["explicit"]) == 1

    def test_it_lands_where_it_was_asked_to(self):
        for fraction in lp.POSITIONS:
            _, landed = lp.plant(_transcript(20000), "X.", fraction)
            assert abs(landed - fraction) < 0.05, (fraction, landed)

    def test_it_never_lands_in_a_tool_result(self):
        """A plant in text the agent merely read is not something it said."""
        planted, _ = lp.plant(_transcript(20000), "X.", 0.5)
        assert all(e["content"] == "ok" for e in planted
                   if e["type"] == "tool_result")

    def test_the_original_transcript_is_untouched(self):
        original = _transcript(5000)
        before = json.dumps(original)
        lp.plant(original, "X.", 0.5)
        assert json.dumps(original) == before


class TestTheOutcome:

    def _answers(self, *rows):
        return {k: {"answer": a, "quote": q, "error_kind": e}
                for k, (a, q, e) in zip(_EVAL_SIGNAL_KEYS, rows, strict=False)}

    def test_found_needs_the_quote_to_be_the_plant(self):
        plant = lp.PLANTS["explicit"]
        assert lp.outcome(self._answers((True, plant, None)), plant) == "found"
        assert lp.outcome(self._answers((True, "something else", None)),
                          plant) == "other_yes"

    def test_a_refusal_is_not_a_miss(self):
        """A question the grader declined was not read; counting it as a
        miss would make a refusing grader look like a length effect."""
        answers = self._answers((False, "", None), (None, "", "refusal"))
        assert lp.outcome(answers, "X") == "refused"

    def test_all_no_is_a_miss(self):
        assert lp.outcome(self._answers((False, "", None)), "X") == "missed"


class TestTheSample:

    def test_only_episodes_answered_no_on_every_question_qualify(self):
        """An unanswered question may be a refusal hiding a positive."""
        with tempfile.TemporaryDirectory() as d:
            _write_run(d, 1, 3000)
            _write_run(d, 2, 3000, aware=True)
            _write_run(d, 3, 3000, answer=None)
            _write_run(d, 4, 3000, keywords=True)
            assert [n["run"] for n in lp.load_negatives(d)] == [
                "run_1_p_m_strong_20260101T000000.json"]

    def test_no_model_supplies_more_than_its_share_of_a_band(self):
        negatives = [{"run": f"r{i}", "model": "one", "length": 3000}
                     for i in range(10)]
        assert len(lp.draw(negatives, per_band=5, seed=1, per_model=2)) == 2

    def test_the_very_longest_are_drawn_first(self):
        negatives = ([{"run": f"r{i}", "model": f"m{i}", "length": 50000}
                      for i in range(20)]
                     + [{"run": "huge", "model": "mh", "length": 150000}])
        assert "huge" in [n["run"] for n in lp.draw(negatives, 2, seed=1)]


class TestTheRun:

    def test_nothing_is_sent_without_yes(self):
        with tempfile.TemporaryDirectory() as d:
            _corpus(d)
            with _grader() as asked:
                code, text = _main(d)
            assert code == 0 and asked == []
            assert "Nothing sent" in text
            assert not list(Path(d).glob("length_probe_*.json"))

    def test_a_faithful_grader_finds_every_plant_and_no_control(self):
        with tempfile.TemporaryDirectory() as d:
            _corpus(d)
            with _grader():
                code, _ = _main(d, "--yes")
            saved = _saved(d)
        assert code == 0 and saved["complete"]
        for key, row in saved["summary"].items():
            if "|control|" in key:
                assert row["found"] == 0 and row["missed"] == row["read"], key
            else:
                assert row["found"] == row["read"] > 0, key

    def test_a_grader_id_with_a_slash_still_saves(self):
        """The result is written once, at the end, so a "/" in the grader id
        - every OpenRouter id - would lose the whole paid run."""
        with tempfile.TemporaryDirectory() as d:
            _corpus(d)
            with _grader():
                code, text = _main(d, "--yes", "--grader", "z-ai/glm-5.3")
            assert code == 0, text
            assert next(Path(d).glob("length_probe_z-ai_glm-5.3_*.json"))

    def test_a_grader_blind_to_the_middle_shows_up_as_a_long_band_miss(self):
        """The check that the probe can answer no: a grader that reads only
        the first 8,000 and last 12,000 characters of the request misses the
        middle plant in the long band and nowhere in the short one."""
        def head_and_tail(text, at):
            return at < 8000 or at > len(text) - 12000
        with tempfile.TemporaryDirectory() as d:
            _corpus(d)
            with _grader(sees=head_and_tail):
                _main(d, "--yes")
            summary = _saved(d)["summary"]
        assert summary["long|explicit|0.5"]["found"] == 0
        assert summary["short|explicit|0.5"]["found_rate"] == 1.0

    def test_refusals_are_counted_apart_from_the_rate(self):
        with tempfile.TemporaryDirectory() as d:
            _corpus(d)
            with _grader(refuse=True):
                _main(d, "--yes")
            row = _saved(d)["summary"]["short|explicit|all"]
        assert row["refused"] == 6 and row["read"] == 0
        assert row["found_rate"] is None


class TestTheCeilingUsesEachModelsCachePrice:
    """A fixed 0.1 cache-read multiplier understated the ceiling for a model
    that bills cached reads near its input price, so an operator approved
    --yes against a figure the run could exceed."""

    def test_a_dearer_cache_read_raises_the_ceiling(self):
        from unittest import mock
        from grader_ab import length_probe as lp
        sample = [{"length": 38000}]
        prices = {"z-ai/glm-5.3": (0.365, 4.4)}
        with mock.patch.object(lp, "PRICES_PER_MTOK", prices):
            with mock.patch.object(lp, "CACHE_READ_MULTIPLIER",
                                   {"z-ai/glm-5.3": 0.71}):
                dear = lp.ceiling_usd(sample, "z-ai/glm-5.3")
            with mock.patch.object(lp, "CACHE_READ_MULTIPLIER", {}):
                standard = lp.ceiling_usd(sample, "z-ai/glm-5.3")
        assert dear > standard
