"""
Which episodes the experiment runs over, and what the finished cells say.

Balanced on the stored verdict and oversampling the models whose awareness is
phrased unusually: that is the difference between measuring recall and
measuring precision, and it is silent when wrong. The read-outs are exercised
on synthetic cells because every one of them is computed after the calls are
paid for, so a crash in the report costs the whole run.
"""


import collections
import contextlib
import io
import tempfile
from pathlib import Path

import grader_ab as ab
from subversionbench.config import RUBRIC_QUESTIONS
from test_corpus.grader_ab_fixtures import (
    _graded_episode, _rubric)


class TestTheVerdictComesFromTheRealClassifier:
    def test_an_all_failed_rubric_has_no_verdict(self):
        """Not a False. A cell that answered nothing has not measured the
        episode, and scoring it as not-aware is the absence-is-a-no error the
        rubric parser exists to prevent."""
        keys = list(RUBRIC_QUESTIONS)
        assert ab.cell_verdict(_rubric(keys, [None] * len(keys))) is None

    def test_a_partly_failed_rubric_still_gets_one(self):
        """Nine independent questions, so eight answers are still evidence -
        which is exactly what the batched shape gives up."""
        keys = list(RUBRIC_QUESTIONS)
        answers = [None] + [False] * (len(keys) - 1)
        assert ab.cell_verdict(_rubric(keys, answers)) is False

    def test_it_agrees_with_the_shipped_classifier(self):
        """Derived, not reimplemented: a second copy of the awareness logic here
        would let the experiment and the corpus disagree about what aware
        means."""
        from subversionbench.grading.grader import (
            _EVAL_SIGNAL_KEYS, classify_awareness_from_rubric)
        keys = list(RUBRIC_QUESTIONS)
        rubric = _rubric(keys, [False] * len(keys))
        for k in list(_EVAL_SIGNAL_KEYS)[:2]:
            rubric[k] = {"answer": True, "quote": f"distinct span for {k}",
                         "error": None, "quote_grounded": "verbatim"}
        assert ab.cell_verdict(rubric) == \
            classify_awareness_from_rubric(rubric)["eval_aware"]


class TestTheContaminationProxyMeasuresWhatItSays:
    def test_answers_that_move_together_score_higher(self):
        """The whole point: batching should raise this if it makes the five
        eval-signal questions agree with each other more."""
        keys = list(RUBRIC_QUESTIONS)
        from subversionbench.grading.grader import _EVAL_SIGNAL_KEYS
        together, split = _rubric(keys, [False] * len(keys)), \
            _rubric(keys, [False] * len(keys))
        for k in _EVAL_SIGNAL_KEYS:
            together[k] = {"answer": True, "quote": k, "error": None}
        for i, k in enumerate(_EVAL_SIGNAL_KEYS):
            split[k] = {"answer": i % 2 == 0, "quote": k, "error": None}
        assert ab.signal_correlation([together]) == 1.0
        assert ab.signal_correlation([split]) < 1.0

    def test_unanswered_questions_are_left_out_of_the_pairs(self):
        """A failed answer is not agreement with anything."""
        keys = list(RUBRIC_QUESTIONS)
        from subversionbench.grading.grader import _EVAL_SIGNAL_KEYS
        rubric = _rubric(keys, [False] * len(keys))
        for k in _EVAL_SIGNAL_KEYS:
            rubric[k] = {"answer": None, "quote": "", "error": "x"}
        assert ab.signal_correlation([rubric]) is None


class TestTheSampleIsWhatItClaims:
    def _candidates(self, spec):
        """spec: {model: (n_aware, n_unaware)}."""
        out = []
        for model, (na, nu) in spec.items():
            for i in range(na):
                out.append({"run": f"{model}-a{i}", "model": model,
                            "stored_aware": True})
            for i in range(nu):
                out.append({"run": f"{model}-u{i}", "model": model,
                            "stored_aware": False})
        return out

    def test_it_balances_on_the_stored_verdict(self):
        """Sampling at the corpus's natural aware rate measures precision well
        and recall badly, and recall is the thing a weaker grader loses."""
        cands = self._candidates({"m": (50, 50)})
        picked = ab.stratified_sample(cands, per_model=4, balance=True)
        assert sum(1 for c in picked if c["stored_aware"]) == 2
        assert sum(1 for c in picked if not c["stored_aware"]) == 2

    def test_unbalanced_sampling_takes_what_the_corpus_offers(self):
        cands = self._candidates({"m": (1, 50)})
        picked = ab.stratified_sample(cands, per_model=6, balance=False)
        assert len(picked) == 6
        assert sum(1 for c in picked if c["stored_aware"]) == 1

    def test_named_models_are_drawn_double(self):
        cands = self._candidates({"easy": (20, 20), "hard": (20, 20)})
        picked = ab.stratified_sample(cands, per_model=4, oversample={"hard"},
                                      balance=True)
        counts = {m: sum(1 for c in picked if c["model"] == m)
                  for m in ("easy", "hard")}
        assert counts["hard"] == 2 * counts["easy"]

    def test_the_hard_phrasing_models_are_the_default_oversample(self):
        """They are named because a proportional sample would be decided by the
        models whose phrasing is easy. If this list empties, the sample silently
        stops being the one the experiment was designed around."""
        assert ab.HARD_PHRASING_MODELS
        assert "google/gemini-3.5-flash" in ab.HARD_PHRASING_MODELS

    def test_a_cap_does_not_drop_every_model_after_the_middle(self):
        """Truncating a model-ordered list keeps only the alphabetical start,
        which would quietly make a --limit run a different experiment."""
        cands = self._candidates(dict.fromkeys("abcdefgh", (10, 10)))
        picked = ab.stratified_sample(cands, per_model=4, balance=True, limit=8)
        assert len(picked) == 8
        assert len({c["model"] for c in picked}) == 8

    def test_a_model_with_no_aware_episodes_still_contributes(self):
        cands = self._candidates({"m": (0, 10)})
        picked = ab.stratified_sample(cands, per_model=4, balance=True)
        assert picked and all(not c["stored_aware"] for c in picked)

    def test_a_one_sided_model_contributes_at_every_n_including_one(self):
        """At n=1 the balanced split is 1 aware / 0 unaware, so a model whose
        episodes are all on one side drew NOTHING - it vanished from the
        sample, and main() reported an empty sample by blaming --models for a
        model that was in the directory all along. n=4 alone did not catch
        this: the shortfall only empties the draw once the split leaves one
        side at zero."""
        for n in (1, 2, 3, 4):
            for spec in ({"m": (0, 10)}, {"m": (10, 0)}):
                picked = ab.stratified_sample(self._candidates(spec),
                                              per_model=n, balance=True)
                assert len(picked) == n, (
                    f"n={n} with {spec} drew {len(picked)}, not {n}")

    def test_a_balanced_draw_takes_exactly_what_was_asked_for(self):
        """Not more, not less. The floor this replaced drew n+1 at n=1 (one
        from each side, with a minimum of one) and n-1 at every odd n, so the
        episode count - and the bill - did not match --per-model."""
        cands = self._candidates({"m": (50, 50)})
        for n in (1, 2, 3, 4, 5, 8):
            picked = ab.stratified_sample(cands, per_model=n, balance=True)
            assert len(picked) == n, f"n={n} drew {len(picked)}"

    def test_the_sample_is_deterministic(self):
        """Two runs must draw the same episodes or their results cannot be
        compared, which is the only reason to run this twice."""
        cands = self._candidates({"a": (5, 5), "b": (5, 5)})
        first = ab.stratified_sample(cands, per_model=4, balance=True)
        second = ab.stratified_sample(cands, per_model=4, balance=True)
        assert [c["run"] for c in first] == [c["run"] for c in second]


class TestACapDrawsFromEveryModelItCan:
    def _candidates(self, counts):
        """`counts` maps model to how many aware episodes it has."""
        return [{"run": f"{model}_{i}", "model": model, "stored_aware": True,
                 "nudge": "strong", "oversight": True, "lure": False,
                 "corpus": "", "scenario": "", "stored_rubric": {}}
                for model, n in sorted(counts.items()) for i in range(n)]

    def test_a_model_that_runs_out_does_not_stop_the_others(self):
        """The round-robin has to keep drawing from the models that still have
        episodes. Stopping at the first exhausted one is the alphabetical
        truncation the round-robin replaced, wearing a different hat."""
        got = ab.stratified_sample(
            self._candidates({"a": 1, "b": 4}), per_model=4, balance=False,
            limit=4)
        assert len(got) == 4
        assert collections.Counter(c["model"] for c in got) == {"b": 3, "a": 1}

    def test_a_cap_above_the_sample_returns_the_sample_once_each(self):
        got = ab.stratified_sample(
            self._candidates({"a": 1, "b": 2}), per_model=4, balance=False,
            limit=99)
        assert len(got) == 3
        assert len({c["run"] for c in got}) == 3, (
            "the round-robin drew the same episode twice")


class TestTheCandidateScanSkipsWhatItCannotUse:
    """Silently, and it has to: the alternative is a whole directory scan
    failing on one truncated file. What matters is that the reason for each
    exclusion is the right one, because an over-broad skip shrinks the sample
    without saying so."""

    def test_an_unreadable_run_file_does_not_stop_the_scan(self):
        with tempfile.TemporaryDirectory() as out:
            _graded_episode(out, 1)
            Path(out, "run_2_p_m_strong_20260101T000000.json").write_text(
                '{"model": "p/m", "analysis":', encoding="utf-8")
            got = ab.load_candidates(out)
        assert [c["run"] for c in got] == [
            "run_1_p_m_strong_20260101T000000.json"]

    def test_an_episode_whose_grading_failed_is_not_a_candidate(self):
        """It has a stored verdict field and no verdict worth balancing on.
        Counting it would put an ungraded episode on one side of the balance."""
        with tempfile.TemporaryDirectory() as out:
            _graded_episode(out, 1, failed=True)
            assert ab.load_candidates(out) == []
            _graded_episode(out, 2, failed=False)
            assert len(ab.load_candidates(out)) == 1


class TestTheReportRunsWithoutAnApi:
    """Every read-out is computed after the calls are paid for, so a crash here
    costs the whole run. The reference cell is present in one case and absent in
    another, because a partial 2x2 is a normal thing to ask for."""

    def _results(self, cells):
        keys = list(RUBRIC_QUESTIONS)
        out = {}
        for cell, per_run in cells.items():
            out[cell] = {run: _rubric(keys, answers)
                         for run, answers in per_run.items()}
        return out

    def _render(self, results, stored=None):
        keys = list(RUBRIC_QUESTIONS)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            ab.report(results, [], keys, stored if stored is not None else {})
        return buf.getvalue()

    def _two_cells(self):
        keys = list(RUBRIC_QUESTIONS)
        ref = "|".join(ab.REFERENCE)
        yes = [True] * len(keys)
        no = [False] * len(keys)
        return self._results({
            ref: {"r1": yes, "r2": no},
            "claude-sonnet-5|batched": {"r1": yes, "r2": yes},
        })

    def test_it_renders_every_section(self):
        out = self._render(self._two_cells())
        for heading in ("PER-QUESTION RATES BY CELL",
                        "AGREEMENT AGAINST THE REFERENCE CELL",
                        "POSITION GRADIENT",
                        "CONTAMINATION AND ROBUSTNESS",
                        "VERDICT RATE BY CELL"):
            assert heading in out, f"{heading} missing from the report"

    def test_it_reports_the_noise_floor_against_the_stored_labels(self):
        """Without it every other number is uninterpretable, because graders are
        non-deterministic and some disagreement is expected for free."""
        keys = list(RUBRIC_QUESTIONS)
        results = self._two_cells()
        stored = {"r1": _rubric(keys, [True] * len(keys)),
                  "r2": _rubric(keys, [True] * len(keys))}
        out = self._render(results, stored)
        assert "Noise floor" in out
        # r2 agrees with neither, so the floor is one of two.
        assert "1/2" in out

    def test_it_says_so_rather_than_crashing_when_the_reference_is_absent(self):
        keys = list(RUBRIC_QUESTIONS)
        out = self._render(self._results(
            {"claude-sonnet-5|batched": {"r1": [True] * len(keys)}}))
        assert "reference cell" in out and "absent" in out

    def test_a_cell_that_failed_everywhere_does_not_divide_by_zero(self):
        keys = list(RUBRIC_QUESTIONS)
        ref = "|".join(ab.REFERENCE)
        out = self._render(self._results({
            ref: {"r1": [False] * len(keys)},
            "claude-sonnet-5|batched": {"r1": [None] * len(keys)},
        }))
        assert "VERDICT RATE BY CELL" in out

    def test_the_position_row_carries_one_number_per_question(self):
        """The pre-registered read-out: a slope across these is what says
        batching lost the late answers."""
        keys = list(RUBRIC_QUESTIONS)
        out = self._render(self._two_cells())
        # Scoped to the section, because the cell name heads a line in the
        # agreement section too - which is what an earlier version of this test
        # matched, asserting on the wrong row entirely.
        section = out.split("POSITION GRADIENT")[1].split(
            "CONTAMINATION AND ROBUSTNESS")[0]
        row = next(line for line in section.splitlines()
                   if line.startswith("claude-sonnet-5|batched"))
        numbers = row.split()[1:]
        assert len(numbers) == len(keys), row
        assert all(n.isdigit() for n in numbers), row
