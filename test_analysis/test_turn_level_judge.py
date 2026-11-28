"""
The judge runner (turn_level/judge.py), with the category call stubbed.

What matters: without --run nothing is called; a unit shared by several sets or views is judged
once; an empty earlier view costs no call; a judged unit is never paid for again, a failed one
is asked once more and then left; a refusal is recorded as one; an error every remaining call
would repeat stops the pass; and the judge never sees tool output.
"""

import json
import os
import tempfile
from unittest import mock

from subversionbench.grading import category
from turn_level import store
from turn_level.judge import judge

TOOL_OUTPUT = "TOOL OUTPUT THE JUDGE MUST NOT SEE"


def _episode(earlier_text: bool) -> dict:
    tr = []
    for turn in (1, 2):
        if earlier_text:
            tr.append({"type": "text", "turn": turn, "content": f"visible {turn}"})
        tr += [{"type": "tool_call", "turn": turn, "cmd": "ls"},
               {"type": "tool_result", "turn": turn, "result": TOOL_OUTPUT}]
    return {"model": "x/m", "transcript": tr + [{"type": "thinking", "turn": 3, "content": "own reasoning"}]}


def _member(ep: str) -> dict:
    return {"episode": f"src/{ep}", "turn": 3, "o": 1}


def _work(root: str) -> str:
    """A working directory with one B set (so episode-level units too) whose control's earlier
    view is empty, and a second set sharing the case unit."""
    episodes = {}
    for name, earlier in (("ep1", True), ("ep2", False)):
        path = os.path.join(root, f"{name}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(_episode(earlier), f)
        episodes[f"src/{name}"] = {"path": path, "model": "m", "source": "src",
                                   "scenario": "blackmail", "stratum": ["m", "a"], "acted": name == "ep1"}
    sets = [{"id": f"B-{i}", "kind": "blackmail", "model": "m", "stratum": ["m", "a"],
             "scenario": "blackmail", "k": 2, "case": _member("ep1"), "controls": [_member("ep2")]}
            for i in (1, 2)]
    work = os.path.join(root, "work")
    store.write_json(store.sets_path(work, "B"), {"sets": sets, "episodes": episodes})
    return work


def _block(aware=True, error=None, kind=None):
    return {"eval_aware": None if error else aware, "grading_failed": bool(error),
            "category": None if error else "true", "quote": "", "quote_grounded": None,
            "error": error, "error_kind": kind}


class _Stub:
    def __init__(self, reply=lambda text: _block()):
        self.texts, self.reply = [], reply

    def __call__(self, text, model, instrument, scenario=""):
        self.texts.append(text)
        return self.reply(text)


def _judge(work, stub, run=True):
    with mock.patch.object(category, "awareness_block", stub):
        return judge(work, run=run, delay=0)


class TestJudge:
    def test_plan_only_calls_nothing(self):
        with tempfile.TemporaryDirectory() as root:
            stub = _Stub()
            assert _judge(_work(root), stub, run=False) == 0 and stub.texts == []

    def test_each_unit_once_no_call_for_an_empty_view_and_never_twice(self):
        with tempfile.TemporaryDirectory() as root:
            work, stub = _work(root), _Stub()
            assert _judge(work, stub) == 0
            # in_view x2, earlier for ep1 only, whole x2: the shared case unit once.
            assert len(stub.texts) == 5
            assert not any(TOOL_OUTPUT in t for t in stub.texts)
            empty = store.read_verdicts(work)["src/ep2#3#earlier"]["record"]
            assert empty["no_call"] and empty["eval_aware"] is False
            _judge(work, stub)
            assert len(stub.texts) == 5

    def test_a_failed_unit_is_asked_once_more_then_left(self):
        with tempfile.TemporaryDirectory() as root:
            work = _work(root)
            stub = _Stub(lambda text: _block(error="Error code: 403 - flagged") if "visible" in text
                         else _block())
            for _ in range(3):
                _judge(work, stub)
            slot = store.read_verdicts(work)["src/ep1#3#in_view"]
            assert slot["attempts"] == 2 and slot["record"] is None and slot["refused"]

    def test_a_fatal_error_stops_the_pass(self):
        with tempfile.TemporaryDirectory() as root:
            stub = _Stub(lambda text: _block(error="bad key", kind="auth"))
            assert _judge(_work(root), stub) == 1 and len(stub.texts) == 1

    def test_a_fatal_error_uses_up_no_attempt(self):
        """Credit runs out twice, then is topped up: every unit is still owed its call, and a unit
        that then fails on its own still gets the one retry the plan gives it."""
        with tempfile.TemporaryDirectory() as root:
            work = _work(root)
            for _ in range(2):
                _judge(work, _Stub(lambda text: _block(error="credit", kind="usage_limit")))
            assert all(slot["attempts"] == 0 for slot in store.read_verdicts(work).values())
            fails_once = _Stub(lambda text: _block(error="malformed reply", kind="reply"))
            _judge(work, fails_once)
            _judge(work, _Stub())
            assert all(slot["record"] is not None for slot in store.read_verdicts(work).values())
