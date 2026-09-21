"""
Fixtures shared by the two jev_validate suites.

Extracted when test_jev_validate.py crossed the 1000-line limit and was
split along the division it already carried: the run mechanics on one
side, what actually reached the client on the other. Both need the same
stored-rubric and stub-jev builders, and a second copy of a fixture is
how two suites come to disagree about what they are testing.

Deliberately NOT folded into grader_ab_fixtures.py, which has its own
_rubric with a different signature. One name meaning two things inside
one package is worse than two modules.
"""

import json
from pathlib import Path

from subversionbench.config import RUBRIC_QUESTIONS


def _rubric(**answers):
    """A stored nine-key rubric, every key false unless named."""
    return {k: {"answer": bool(answers.get(k, False)),
                "quote": "said something" if answers.get(k) else "",
                "error": None}
            for k in RUBRIC_QUESTIONS}


def _episode(out, n, model="p/m", rubric=None, aware=False,
             stamp="20260101T000000"):
    """One run file load_candidates accepts: a transcript and a stored
    verdict, which is what every comparison here is against."""
    path = Path(out, f"run_{n}_{model.replace('/', '_')}_strong_{stamp}.json")
    path.write_text(json.dumps({
        "model": model, "nudge": "strong", "oversight": True, "lure": False,
        "transcript": [{"turn": 1, "type": "text",
                        "content": "I recommend B."}],
        "analysis": {"eval_awareness_grader": {
            "eval_aware": aware,
            "rubric_results": rubric if rubric is not None else _rubric()}}}),
        encoding="utf-8")
    return path


def _jev_saying(**answers):
    """A stand-in for jev that answers the same way every episode."""
    def ask(keys, corpus, threshold=0.5, instructions=None,
            batched=True, **kw):
        return {k: {"answer": answers.get(k), "quote": "",
                    "error": None if k in answers else "no score"}
                for k in keys}
    return ask


def _jev_scoring(**scores):
    """A stand-in for jev that returns a fixed noul score per key.

    A score of None is the unanswered case - no verdict and an error, the
    same shape the real client returns when a question comes back without a
    numeric score.
    """
    def ask(keys, corpus, threshold=0.5, instructions=None,
            batched=True, **kw):
        out = {}
        for k in keys:
            score = scores.get(k)
            out[k] = {"answer": None if score is None else score >= threshold,
                      "noul": score, "quote": "",
                      "error": None if score is not None else "no score"}
        return out
    return ask
