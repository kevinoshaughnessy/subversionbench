"""
Every grading call is noted to the corpus it graded, so a pass can be costed.

No grader token was stored anywhere before this: on the impossible-task corpus
grading very likely cost more than collection, and no total could be given.
"""

import ast
import contextlib
import io
import json
import os
import tempfile
import types
from pathlib import Path
from unittest import mock

import conftest
import subversionbench.llm_client as llm
from subversionbench import run_eval, usage_ledger
from test_readmodes import test_grade_escalation as escalation


def _response(read=10, uncached=90, output=5):
    return types.SimpleNamespace(
        content=[types.SimpleNamespace(type="text", text=json.dumps(
            {"answer": True, "quote": "q"}))],
        usage={"prompt_tokens": read + uncached, "cached_tokens": read,
               "completion_tokens": output})


def _client(calls):
    class Messages:
        @staticmethod
        def create(**kw):
            calls.append(kw)
            return _response()
    return types.SimpleNamespace(messages=Messages())


def _lines(out):
    path = Path(out) / usage_ledger.LEDGER_NAME
    return ([json.loads(x) for x in path.read_text().splitlines()]
            if path.exists() else [])


class TestTheLedger:
    def test_each_call_is_one_line_with_its_counters_and_pass(self):
        with tempfile.TemporaryDirectory() as out:
            with usage_ledger.recording(out, "grade-escalation"):
                for _ in range(2):
                    usage_ledger.create(_client([]), model="m", max_tokens=5)
            lines = _lines(out)
        assert len(lines) == 2
        assert lines[0]["mode"] == "grade-escalation" and lines[0]["model"] == "m"
        assert (lines[0]["read"], lines[0]["uncached"], lines[0]["output"]) == (
            10, 90, 5)

    def test_outside_a_recording_nothing_is_written(self):
        with tempfile.TemporaryDirectory() as out:
            with usage_ledger.recording(out, "x"):
                pass
            usage_ledger.create(_client([]), model="m")
            assert _lines(out) == []

    def test_a_grading_pass_notes_every_call_it_makes(self):
        mode = escalation.TestTheReadMode()
        out = mode._corpus()
        calls = []
        with usage_ledger.recording(out, "grade-escalation"), \
                mock.patch.object(llm, "get_client",
                                  lambda model, **_kw: _client(calls)), \
                contextlib.redirect_stdout(io.StringIO()):
            from conftest import FakeArgs
            from subversionbench.batch import BatchSelection
            from subversionbench.readmodes.grade_escalation import (
                grade_escalation_runs)
            args = FakeArgs(output_dir=out, model="x-ai/grok-4.5", nudge="none",
                            grader_model="g", write_back=True)
            grade_escalation_runs(args, BatchSelection.typed(args))
        assert calls and len(_lines(out)) == len(calls)


class TestMainOpensIt:
    def test_named_for_the_read_mode(self):
        opened = []

        @contextlib.contextmanager
        def recording(output_dir, mode):
            opened.append((output_dir, mode))
            yield

        with tempfile.TemporaryDirectory() as out, \
                mock.patch.object(usage_ledger, "recording", recording), \
                mock.patch("sys.argv", ["run_eval", "--model", "m/x",
                                        "--output-dir", out, "--resummarise"]), \
                contextlib.redirect_stdout(io.StringIO()):
            run_eval.main()
        assert opened == [(out, "resummarise")]


def _direct_calls(path) -> int:
    """Calls of the form X.messages.create(...) in one source file."""
    tree = ast.parse((conftest.PROJECT_ROOT / path).read_text(encoding="utf-8"))
    return sum(1 for node in ast.walk(tree)
               if isinstance(node, ast.Call)
               and isinstance(node.func, ast.Attribute)
               and node.func.attr == "create"
               and isinstance(node.func.value, ast.Attribute)
               and node.func.value.attr == "messages")


class TestNoCallEscapesIt:
    # Collection's own turns are recorded on each episode (episode.py), and
    # the ledger is the one place that makes the call for everything else.
    ALLOWED = {"subversionbench/episode.py", "subversionbench/usage_ledger.py"}

    def test_only_collection_and_the_ledger_call_the_client(self):
        calling = {str(p) for p in conftest.source_python_files()
                   if str(p).startswith("subversionbench") and _direct_calls(p)}
        assert calling == self.ALLOWED, (
            f"{sorted(calling - self.ALLOWED)} call messages.create directly: "
            f"use usage_ledger.create so the call is noted")

    def test_the_walk_can_still_find_a_call(self):
        assert _direct_calls(Path("subversionbench/episode.py"))
        assert not _direct_calls(Path("subversionbench/batch.py"))
        assert os.path.exists(conftest.PROJECT_ROOT / "subversionbench/episode.py")
