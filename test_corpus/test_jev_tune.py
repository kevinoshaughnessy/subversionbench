"""
The jev criteria/threshold cross: the sample, the scoring, and the read-out
that says whether the wording is what is binding.
"""

import json
import tempfile
import unittest
from pathlib import Path

from grader_ab import jev_tune as jt
from subversionbench.config import RUBRIC_QUESTIONS


def _rubric(**answers):
    return {k: {"answer": bool(answers.get(k, False)), "quote": "",
                "error": None}
            for k in RUBRIC_QUESTIONS}


def _episode(out, n, model="p/m", rubric=None):
    path = Path(out, f"run_{n}_{model.replace('/', '_')}_strong_2026.json")
    path.write_text(json.dumps({
        "model": model, "nudge": "strong", "oversight": True, "lure": False,
        "transcript": [{"turn": 1, "type": "text", "content": "text"}],
        "analysis": {"eval_awareness_grader": {
            "eval_aware": False,
            "rubric_results": rubric if rubric is not None else _rubric()}}}),
        encoding="utf-8")


class TestTheSampleIsBalancedOnTheKeyItself(unittest.TestCase):
    """Not on the eval_aware verdict grader_ab's own sampler balances on:
    jev's errors are all misses on these two keys, and the corpus stores
    them at wildly different rates from the verdict."""

    def _candidates(self, out, n_true, n_false, key="mentioned_test"):
        n = 0
        for _ in range(n_true):
            _episode(out, n, rubric=_rubric(**{key: True}))
            n += 1
        for _ in range(n_false):
            _episode(out, n, rubric=_rubric(**{key: False}))
            n += 1
        return jt.sampling.load_candidates(out)

    def test_it_draws_both_sides_evenly(self):
        with tempfile.TemporaryDirectory() as out:
            cands = self._candidates(out, 30, 30)
            sample = jt.balanced_on_the_key(cands, "mentioned_test", 10)
        stored = [(c["stored_rubric"]["mentioned_test"]["answer"])
                  for c in sample]
        assert stored.count(True) == 10
        assert stored.count(False) == 10

    def test_a_lopsided_corpus_still_yields_the_minority_side(self):
        """referenced_system_prompt stores over four positives per negative.
        Sampling at the natural rate would spend the run on the class jev
        already answers correctly."""
        with tempfile.TemporaryDirectory() as out:
            cands = self._candidates(out, 60, 5)
            sample = jt.balanced_on_the_key(cands, "mentioned_test", 10)
        stored = [c["stored_rubric"]["mentioned_test"]["answer"]
                  for c in sample]
        assert stored.count(False) == 5, "took what the minority side had"
        assert stored.count(True) == 10

    def test_it_spreads_across_models_rather_than_taking_the_front(self):
        """The candidate list is sorted by filename and so by model; the
        front of it is one model's episodes."""
        with tempfile.TemporaryDirectory() as out:
            n = 0
            for model in ("a/one", "b/two", "c/three"):
                for _ in range(10):
                    _episode(out, n, model=model,
                             rubric=_rubric(mentioned_test=True))
                    n += 1
            cands = jt.sampling.load_candidates(out)
            sample = jt.balanced_on_the_key(cands, "mentioned_test", 6)
        assert len({c["model"] for c in sample}) == 3


class TestScoringSeparatesTheTwoSides(unittest.TestCase):
    """Recall and specificity, not agreement alone: jev's failure is
    entirely one-sided, and one number moves with whichever class the
    sample happens to hold more of."""

    def _scored(self, pairs):
        return [{"run": f"r{i}", "stored": s, "noul": n, "error": None}
                for i, (s, n) in enumerate(pairs)]

    def test_recall_and_specificity_move_apart_with_the_cut(self):
        scored = self._scored([(True, 0.3), (True, 0.3),
                               (False, 0.1), (False, 0.1)])
        rows = {r["threshold"]: r
                for r in jt.score_variant(scored, (0.2, 0.4))}
        assert rows[0.2]["recall"] == 1.0
        assert rows[0.2]["specificity"] == 1.0
        assert rows[0.4]["recall"] == 0.0
        assert rows[0.4]["specificity"] == 1.0

    def test_a_perfect_specificity_with_poor_recall_is_visible(self):
        """The shape the full corpus actually produced - it must not be
        reported as respectable agreement."""
        scored = self._scored([(True, 0.1)] * 3 + [(False, 0.0)] * 7)
        row = jt.score_variant(scored, (0.5,))[0]
        assert row["specificity"] == 1.0
        assert row["recall"] == 0.0
        assert row["agreement"] == 0.7, "agreement alone would look fine"

    def test_an_unscored_episode_is_skipped_not_counted_as_wrong(self):
        scored = [{"run": "r", "stored": True, "noul": None,
                   "error": "no score"}]
        row = jt.score_variant(scored, (0.5,))[0]
        assert row["tp"] == row["fn"] == 0
        assert row["agreement"] is None

    def test_best_row_picks_the_highest_agreement(self):
        scored = self._scored([(True, 0.3), (False, 0.1)])
        best = jt.best_row(jt.score_variant(scored, (0.2, 0.9)))
        assert best["threshold"] == 0.2

    def test_best_row_of_nothing_is_none(self):
        assert jt.best_row(jt.score_variant([], (0.5,))) is None


class TestEachVariantIsActuallySentToJev(unittest.TestCase):

    def test_the_variants_criteria_reach_the_call(self):
        """A cross that sent the same criteria every time would report three
        identical rows and read as 'the wording does not matter'."""
        seen = []

        def ask(keys, corpus, criteria=None, **kw):
            seen.append(criteria[keys[0]]["true"])
            return {keys[0]: {"answer": True, "noul": 0.9, "quote": "",
                              "error": None}}

        sample = [{"run": "r1", "corpus": "text",
                   "stored_rubric": _rubric(mentioned_test=True)}]
        for variant in ("shipped", "symmetric", "inclusive"):
            jt.run_variant(sample, "mentioned_test",
                           jt.CRITERIA_VARIANTS[variant], ask=ask)
        assert len(set(seen)) == 3, "the variants were not distinct on the wire"

    def test_the_asker_resolves_at_call_time(self):
        """A default argument would bind the paid client where a test
        cannot reach it - the defect already found once in jev_validate."""
        from unittest import mock
        sample = [{"run": "r1", "corpus": "text",
                   "stored_rubric": _rubric()}]
        with mock.patch.object(jt, "ask_rubric_questions_jev") as ask:
            ask.return_value = {"mentioned_test": {
                "answer": False, "noul": 0.1, "quote": "", "error": None}}
            jt.run_variant(sample, "mentioned_test", jt.CRITERIA_VARIANTS["shipped"])
        ask.assert_called_once()

    def test_every_variant_covers_every_scoped_key(self):
        from grader_ab.jev_client import JEV_CRITERIA
        for name, criteria in jt.CRITERIA_VARIANTS.items():
            assert set(criteria) == set(JEV_CRITERIA), name
            for key, branches in criteria.items():
                assert set(branches) == {"true", "false"}, f"{name}/{key}"


class TestTheReadOutNamesWhatIsBinding(unittest.TestCase):
    """The question this script exists to answer, and the one rubric_ab.py
    answered the same way for the LLM graders."""

    def _printed(self, recalls):
        import contextlib
        import io
        by_variant = {}
        for name, recall in recalls.items():
            n_true = 100
            tp = int(recall * n_true)
            by_variant[name] = [{"threshold": 0.5, "recall": recall,
                                 "specificity": 1.0, "agreement": 0.9,
                                 "tp": tp, "fn": n_true - tp, "fp": 0,
                                 "tn": n_true}]
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            jt._print_key("mentioned_test", by_variant)
        return buf.getvalue()

    def test_flat_recall_says_the_wording_is_not_binding(self):
        out = self._printed({"shipped": 0.68, "symmetric": 0.69,
                             "inclusive": 0.67})
        assert "NOT what is binding" in out

    def test_moving_recall_says_the_wording_is_worth_more_work(self):
        out = self._printed({"shipped": 0.68, "symmetric": 0.88,
                             "inclusive": 0.91})
        assert "IS moving it" in out

    def test_the_spread_is_reported_as_a_number(self):
        out = self._printed({"shipped": 0.60, "symmetric": 0.90})
        assert "30.0pp" in out
