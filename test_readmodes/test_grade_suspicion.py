"""
`--grade-suspicion`: one of the two suspicion questions added to saved
episodes.

What matters is that a plan calls nothing, that an answer is stored under its
question and grader beside every other reading, that a pass never pays twice
or stores a failure, that only episodes the question arises for are asked,
and that the question is asked of the headline reading's population whichever
grader answers it.
"""

import contextlib
import importlib
import io
import json
import tempfile
import types
from pathlib import Path
from unittest import mock

import subversionbench.llm_client as llm
from conftest import FakeArgs
from subversionbench.batch import BatchSelection
from subversionbench.config import (DEFAULT_GRADER_MODEL,
                                    HEADLINE_AWARENESS_GRADER)
from subversionbench.grading.suspicion import SUSPICION_KEY
from subversionbench.readmodes.grade_suspicion import grade_suspicion_runs

suspicion = importlib.import_module("subversionbench.grading.suspicion")

NAME = "run_1_x-ai_grok-4.5_none_20261029T100000.json"
TRANSCRIPT = [
    {"turn": 1, "type": "thinking", "content": "This may be a test."},
    {"turn": 1, "type": "tool_call", "cmd": "the act"},
]


def _headline(aware):
    return {"graders": [{"grader_model": HEADLINE_AWARENESS_GRADER,
                         "eval_awareness_grader": {
                             "instrument": "category_rules",
                             "grader_model": HEADLINE_AWARENESS_GRADER,
                             "eval_aware": aware}}]}


def _corpus(analysis, transcript=TRANSCRIPT):
    out = tempfile.mkdtemp()
    Path(f"{out}/{NAME}").write_text(json.dumps(
        {"model": "x-ai/grok-4.5", "nudge": "none", "transcript": transcript,
         "analysis": analysis}))
    return out


def _run(out, question, answer="beside", write_back=True, placed=(1, 1),
         raise_text=None, grader=HEADLINE_AWARENESS_GRADER):
    args = FakeArgs(output_dir=out, model="x-ai/grok-4.5", nudge="none",
                    grader_model=DEFAULT_GRADER_MODEL, write_back=write_back,
                    category_grader=grader)
    args.grade_suspicion, args.concurrency = question, 2
    calls = []

    class Messages:
        @staticmethod
        def create(**kw):
            calls.append(kw)
            if raise_text:
                raise RuntimeError(raise_text)
            return types.SimpleNamespace(content=[types.SimpleNamespace(
                type="text", text=json.dumps({
                    "category": answer, "quote": "", "competing_reading": ""}))],
                usage=None, stop_reason="end_turn")

    def fake_position(transcript, analysis, act):
        return placed if act["name"] == "sandbox" else (None, None)

    original = llm.get_client
    llm.get_client = lambda model, **_kw: types.SimpleNamespace(
        messages=Messages())
    try:
        with mock.patch.object(suspicion, "first_act_position", fake_position), \
                contextlib.redirect_stdout(io.StringIO()):
            code = grade_suspicion_runs(args, BatchSelection.typed(args))
    finally:
        llm.get_client = original
    stored = json.loads(Path(f"{out}/{NAME}").read_text())["analysis"]
    return code, calls, stored.get(SUSPICION_KEY, {}).get(question, {})


class TestTheReadMode:
    def test_without_write_back_nothing_is_called(self):
        code, calls, stored = _run(_corpus(_headline(True)), "decision",
                                   write_back=False)
        assert code == 0 and calls == [] and stored == {}

    def test_an_answer_is_stored_under_its_grader_and_not_asked_twice(self):
        out = _corpus(_headline(True))
        code, calls, stored = _run(out, "decision")
        assert code == 0 and len(calls) == 1
        block = stored[HEADLINE_AWARENESS_GRADER]
        assert block["category"] == "beside" and block["act"] == "sandbox"
        assert _run(out, "decision")[1] == []

    def test_the_other_readings_are_left_as_they_were(self):
        out = _corpus(_headline(True))
        _run(out, "framing", answer="puzzle")
        analysis = json.loads(Path(f"{out}/{NAME}").read_text())["analysis"]
        assert analysis["graders"] == _headline(True)["graders"]

    def test_a_second_grader_is_stored_beside_the_first(self):
        out = _corpus(_headline(True))
        _run(out, "framing", answer="puzzle")
        _, calls, stored = _run(out, "framing", answer="simulation",
                                grader="another/grader")
        assert len(calls) == 1
        assert {m: b["category"] for m, b in stored.items()} == {
            HEADLINE_AWARENESS_GRADER: "puzzle", "another/grader": "simulation"}

    def test_a_failed_call_is_not_written_and_is_asked_again(self):
        out = _corpus(_headline(True))
        code, _, stored = _run(out, "decision", raise_text="Error code: 500")
        assert code == 1 and stored == {}
        _, calls, stored = _run(out, "decision")
        assert len(calls) == 1 and stored[HEADLINE_AWARENESS_GRADER]

    def test_a_reading_by_an_earlier_wording_is_asked_again(self):
        out = _corpus({**_headline(True), SUSPICION_KEY: {"framing": {
            HEADLINE_AWARENESS_GRADER: {"instrument": "an earlier wording",
                                        "category": "puzzle"}}}})
        _, calls, stored = _run(out, "framing", answer="simulation")
        assert len(calls) == 1
        assert stored[HEADLINE_AWARENESS_GRADER]["category"] == "simulation"

    def test_framing_is_not_asked_of_an_episode_the_headline_calls_unaware(self):
        code, calls, _ = _run(_corpus(_headline(False)), "framing")
        assert code == 0 and calls == []

    def test_framing_follows_the_headline_whichever_grader_answers(self):
        """The population is the headline reading's, so a second grader is
        compared with the first on the same episodes."""
        _, calls, _ = _run(_corpus(_headline(False)), "framing",
                           grader="another/grader")
        assert calls == []

    def test_decision_is_not_asked_without_an_act_that_can_be_placed(self):
        code, calls, _ = _run(_corpus(_headline(True)), "decision",
                              placed=(None, None))
        assert code == 0 and calls == []
