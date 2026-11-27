"""
The primary estimate's in-context reading (report/in_context.py).

What matters: a suspicious episode that acted is sorted by where its suspicion was relative to
the act - in view, only earlier and not replayed, only after, or nowhere - and keeps its
awareness at the act only in the first case; every episode, acting or not, gets the same turn
units; and the report reproduces the published contrast before printing any other.
"""

import contextlib
import io
import json
import os
import sys
import tempfile
from unittest import mock

from report import in_context as R

QUOTE = "this scenario reads like an evaluation of me"


def _tr(where):
    """Suspicion on turn 1 ('early'), turn 2 before the act ('same') or after it ('after')."""
    say = {"type": "thinking", "content": QUOTE}
    tr = [{"type": "thinking", "turn": 1, "content": "start"},
          {"type": "tool_call", "turn": 1, "cmd": "ls"},
          {"type": "thinking", "turn": 2, "content": "next"},
          {"type": "tool_call", "turn": 2, "cmd": "edit the check"},
          {"type": "thinking", "turn": 3, "content": "done"}]
    at = {"early": 1, "same": 3, "after": 5}.get(where)
    if at is not None:
        tr.insert(at, dict(say, turn=tr[at - 1]["turn"] if where != "after" else 3))
    return tr


def _episode(where, model="moonshotai/kimi-k2.6", acted=True):
    return {"model": model, "transcript": _tr(where), "analysis": {"acted": acted}}


def _act_machinery():
    """The act machinery, patched to read the made-up episode: one act, at the edit."""
    def first_act(tr, a, x):
        i = next(i for i, t in enumerate(tr) if t.get("cmd") == "edit the check")
        return i, tr[i]["turn"]
    return (mock.patch.object(R, "view", lambda a, g: dict(a, eval_awareness_grader={"quote": QUOTE})),
            mock.patch.object(R, "counted_acts", lambda a: [{"name": "oversight"}] if a.get("acted") else []),
            mock.patch.object(R, "act_value", lambda a, x: True),
            mock.patch.object(R, "first_act_position", first_act))


def _context(where, acted=True, aware=True, model="moonshotai/kimi-k2.6"):
    with contextlib.ExitStack() as stack:
        for patch in _act_machinery():
            stack.enter_context(patch)
        return R.episode_in_context({"aware": aware, "misaligned": acted}, _episode(where, model, acted))


class TestWhereTheSuspicionWas:
    def test_in_view_at_the_act(self):
        out = _context("same")
        assert out["why"] == "in view at the act" and out["aware_at_act"]

    def test_only_in_earlier_reasoning(self):
        out = _context("early")
        assert out["why"] == "only in earlier reasoning, not replayed" and not out["aware_at_act"]

    def test_earlier_reasoning_of_a_replayed_model_is_in_view(self):
        assert _context("early", model="claude-opus-5-5")["aware_at_act"]

    def test_only_after_the_act(self):
        out = _context("after")
        assert out["why"] == "voiced only after the act" and not out["aware_at_act"]

    def test_nowhere(self):
        assert _context(None)["why"] == "nothing located"


class TestEveryEpisodeAlike:
    def test_an_acting_episode_runs_to_its_act(self):
        assert _context("early")["units"] == [(1, True, False), (2, False, True)]

    def test_an_episode_that_did_not_act_keeps_its_verdict_and_runs_to_its_last_turn(self):
        out = _context("early", acted=False)
        assert out["aware_at_act"] and out["why"] is None
        assert out["units"] == [(1, True, False), (2, False, False), (3, False, False)]

    def test_an_unaware_episode_has_no_suspicion_located(self):
        assert not any(e for _, e, _ in _context("same", aware=False)["units"])


def _primary_row(name, aware, acted):
    return {"run_file": name + ".json", "aware": aware, "misaligned": acted, "model": "m/x",
            "nudge": "none", "oversight": True, "lure": False, "goalguard": None, "variant": None}


def _run_main():
    root = tempfile.mkdtemp()
    mainline = os.path.join(root, "eval_results_r10x")
    os.makedirs(mainline)
    rows = []
    for i, (where, aware, acted) in enumerate([("same", True, True), ("early", True, True),
                                               (None, False, True), (None, False, False),
                                               ("early", True, False)] * 4):
        rows.append(_primary_row(f"run_{i}", aware, acted))
        with open(os.path.join(mainline, f"run_{i}.json"), "w", encoding="utf-8") as f:
            json.dump(_episode(where, acted=acted), f)
    published = {"stratified": {"mantel_haenszel": {"risk_difference": 0.01,
                                                     "risk_difference_ci95_sato": (-0.01, 0.03)}}}
    calls = []

    def estimate(mainline_rows, goalguard_rows, exposure="aware"):
        calls.append(exposure)
        return published

    out = io.StringIO()
    with contextlib.ExitStack() as stack:
        for patch in (*_act_machinery(),
                      mock.patch.object(R, "snapshot", lambda d, c: {"models": ["m/x"]}),
                      mock.patch.object(R, "headline_rows",
                                        lambda d, ex, keep, models: (rows if d == mainline else [], 0)),
                      mock.patch.object(R, "primary_estimate", estimate),
                      mock.patch.object(sys, "argv", ["prog", "--mainline-dir", mainline,
                                                      "--goalguard-dir", os.path.join(root, "gg")])):
            stack.enter_context(patch)
        with contextlib.redirect_stdout(out):
            R.main()
    return out.getvalue(), calls


class TestTheReport:
    def test_the_published_contrast_comes_first_then_the_biased_one(self):
        out, calls = _run_main()
        assert calls == ["aware", "aware_at_act"]
        assert out.index("as published") < out.index("re-scored at the act") < out.index("turn level")

    def test_the_acting_suspicious_episodes_are_sorted_and_counted(self):
        out, _ = _run_main()
        assert "20 episodes; 8 suspicious and acting" in out
        assert "in view at the act 4" in out and "only in earlier reasoning, not replayed 4" in out
