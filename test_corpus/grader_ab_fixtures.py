"""
Running the grader A/B with every grader call replaced.

Not named `test_*`, so neither runner collects it as a suite file: pytest looks
for `test_*.py` and so does run_tests.discover_modules. It still counts as suite
rather than shipping source, because conftest.is_test_file decides that by
position - anything under a `test_*/` directory - so the project guards that
apply to tests apply here too.

BOTH shape entries are swapped rather than only the one a test names, so a test
that gets --shapes wrong reaches a stub instead of a real client - the reason
`get_client` is stubbed too, belt and braces, on a script whose whole purpose is
to spend money on grader calls.
"""

import contextlib
import glob
import io
import json
import os
import sys
from pathlib import Path

import grader_ab as ab
import subversionbench.llm_client as ev_llm
from subversionbench.config import RUBRIC_QUESTIONS

_INPUT_ONLY_USAGE = {"read": 0, "written": 0, "uncached": 1000, "output": None}

def _rubric(keys, answers, quotes=None):
    """A cell's rubric result for one episode. `answers` is a list aligned to
    `keys`; None means unanswered."""
    out = {}
    for i, key in enumerate(keys):
        a = answers[i] if i < len(answers) else False
        out[key] = {
            "answer": a,
            "quote": (quotes or {}).get(key, "said something" if a else ""),
            "error": None if a is not None else "failed",
            "quote_grounded": "verbatim" if a else None,
        }
    return out


@contextlib.contextmanager
def _graders_stubbed(asker):
    shapes, client_factory = dict(ab.SHAPES), ev_llm.get_client
    for shape in ab.SHAPES:
        ab.SHAPES[shape] = asker
    ev_llm.get_client = lambda model, **kw: object()
    try:
        yield
    finally:
        ab.SHAPES.clear()
        ab.SHAPES.update(shapes)
        ev_llm.get_client = client_factory


def _stub_asker(usage=_INPUT_ONLY_USAGE, error_for=(), error=None,
                error_kind=None, unmeasured_for=()):
    """Stands in for either shape.

    `error_for` names the grader models whose every answer comes back as an
    error of `error_kind` - what an exhausted key or a spend cap looks like
    from here, and also what an ordinary unreadable reply looks like, which is
    the distinction the abort turns on.
    """
    def asker(corpus, model, client=None, channel_id=None, delay=0,
              usage_sink=None, unmeasured_sink=None):
        if usage is not None and usage_sink is not None:
            usage_sink.append(dict(usage))
        if model in unmeasured_for and unmeasured_sink is not None:
            unmeasured_sink.append("timed out with no usage recorded")
        if model in error_for:
            return {k: {"answer": None, "quote": "", "error": error,
                        "error_kind": error_kind}
                    for k in RUBRIC_QUESTIONS}
        return {k: {"answer": False, "quote": "", "error": None,
                    "error_kind": None} for k in RUBRIC_QUESTIONS}
    return asker


def _graded_episode(out, n, model="p/m", aware=True, failed=False,
                    stamp="20260101T000000"):
    """One run file load_candidates will accept - i.e. one carrying a STORED
    verdict, which is what the sample is balanced on."""
    grader = {"eval_aware": aware,
              "rubric_results": {k: {"answer": False, "quote": ""}
                                 for k in RUBRIC_QUESTIONS}}
    if failed:
        grader["grading_failed"] = True
    path = Path(out, f"run_{n}_{model.replace('/', '_')}_strong_{stamp}.json")
    path.write_text(json.dumps({
        "model": model, "nudge": "strong", "oversight": True, "lure": False,
        "transcript": [{"turn": 1, "type": "text", "content": "I recommend B."}],
        "analysis": {"eval_awareness_grader": grader}}), encoding="utf-8")
    return path


def _run_main(argv):
    buf = io.StringIO()
    saved = sys.argv
    sys.argv = ["grader_ab.py", *argv]
    try:
        with contextlib.redirect_stdout(buf):
            code = ab.main()
    finally:
        sys.argv = saved
    return code, buf.getvalue()


def _saved_run(out):
    paths = glob.glob(os.path.join(out, "grader_ab_*.json"))
    assert len(paths) == 1, f"expected one saved run, found {len(paths)}"
    return json.load(open(paths[0], encoding="utf-8"))
