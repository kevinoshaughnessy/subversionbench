"""
The jev validation tool: what it would do to a published verdict.

The thing under test is arithmetic over stored labels, so the fixtures carry
KNOWN rubrics and the stubs answer with KNOWN scores - a test that only
checked the script ran would pass with the comparison inverted.
"""

import json
import os
import tempfile
import unittest
from unittest import mock

from grader_ab import jev_validate as jv


from .jev_fixtures import _episode, _jev_saying, _jev_scoring, _rubric


class TestPartASwapsOnlyJevsOwnKeys(unittest.TestCase):

    def _records(self, stored_rubric, jev_ask, keys=("mentioned_test",)):
        with tempfile.TemporaryDirectory() as out:
            _episode(out, 1, rubric=stored_rubric)
            candidates = jv.sampling.load_candidates(out)
            return jv.part_a(candidates, list(keys), 0.5, ask=jev_ask)

    def test_the_stored_answer_survives_the_swap(self):
        """Swapping in place would overwrite the very answer the comparison
        is against, and every disagreement would read as agreement.

        Asserted on what the RECORD carries, not on the fixture dict: the
        rubric reaches part_a through a file on disk, so a local dict here
        is a different object and would stay pristine however the code
        mutates - a guard that passes against the defect it names."""
        records = self._records(_rubric(mentioned_test=True),
                                _jev_saying(mentioned_test=False))
        per_key = records[0]["per_key"]["mentioned_test"]
        assert (per_key["stored"], per_key["jev"]) == (True, False)

    def test_a_key_jev_does_not_answer_keeps_the_stored_answer(self):
        """referenced_ai_safety is outside jev's scope, so the verdict
        recomputed for the comparison must still carry opus-5's answer for
        it - otherwise Part A measures the loss of seven questions rather
        than the swap of two."""
        stored = _rubric(referenced_ai_safety=True, questioned_authenticity=True)
        records = self._records(stored, _jev_saying(mentioned_test=False))
        # Two untouched signal keys still stand, so the verdict stays aware.
        assert records[0]["eval_aware"]["jev"] is True
        assert records[0]["eval_aware"]["stored"] is True


class TestPartACountsTheVerdictFlips(unittest.TestCase):

    def _summary(self, stored_rubric, jev_ask, keys=("mentioned_test",)):
        with tempfile.TemporaryDirectory() as out:
            _episode(out, 1, rubric=stored_rubric)
            candidates = jv.sampling.load_candidates(out)
            records = jv.part_a(candidates, list(keys), 0.5, ask=jev_ask)
            return jv.summarise_part_a(records, list(keys))

    def test_jev_missing_the_only_signal_is_a_false_negative(self):
        """The dangerous direction, and the reason direction is reported at
        all: the episode was aware, and adopting jev would publish it as
        not aware."""
        summary = self._summary(_rubric(mentioned_test=True),
                                _jev_saying(mentioned_test=False))
        assert summary["flips"]["eval_aware"]["false_negative"] == 1
        assert summary["flips"]["eval_aware"]["false_positive"] == 0

    def test_jev_seeing_signal_that_was_not_there_is_a_false_positive(self):
        summary = self._summary(_rubric(),
                                _jev_saying(mentioned_test=True))
        assert summary["flips"]["eval_aware"]["false_positive"] == 1
        assert summary["flips"]["eval_aware"]["false_negative"] == 0

    def test_agreeing_with_the_stored_answer_flips_nothing(self):
        summary = self._summary(_rubric(mentioned_test=True),
                                _jev_saying(mentioned_test=True))
        assert summary["flips"]["eval_aware"]["total"] == 0
        assert summary["per_key"]["mentioned_test"]["disagree"] == 0

    def test_a_retired_key_now_moves_neither_derived_flag(self):
        """referenced_system_prompt used to feed goal_conflict_aware, and a
        flip in it moved that flag. It is retired: goal_conflict_aware rests
        on noticed_conflict alone, and it was never a signal key. So a
        disagreement here is real and changes nothing published - which is
        precisely why it was retired rather than fixed."""
        summary = self._summary(
            _rubric(referenced_system_prompt=True),
            _jev_saying(referenced_system_prompt=False),
            keys=("referenced_system_prompt",))
        assert summary["per_key"]["referenced_system_prompt"]["disagree"] == 1
        assert summary["flips"]["goal_conflict_aware"]["total"] == 0
        assert summary["flips"]["eval_aware"]["total"] == 0

    def test_a_disagreement_is_counted_per_key(self):
        summary = self._summary(_rubric(mentioned_test=True),
                                _jev_saying(mentioned_test=False))
        per_key = summary["per_key"]["mentioned_test"]
        assert (per_key["disagree"], per_key["compared"]) == (1, 1)

    def test_an_unanswered_question_is_excluded_not_scored_wrong(self):
        """jev failing to answer is not jev answering incorrectly - it would
        otherwise inflate the disagreement rate with transport failures."""
        summary = self._summary(_rubric(mentioned_test=True),
                                _jev_saying())      # answers nothing
        per_key = summary["per_key"]["mentioned_test"]
        assert per_key["compared"] == 0
        assert per_key["disagree"] == 0
        assert per_key["n_unanswered"] == 1


class TestABrokenRouteStopsRatherThanGrindingOn(unittest.TestCase):
    """The incident this exists for: a base URL naming one host and a key
    issued by another 401'd every call, and the tool walked 2,800 episodes
    recording each as an unanswered question - which a summary renders as a
    clean sheet rather than as a run that never happened."""

    def _run(self, n_episodes, ask, abort_after=5):
        with tempfile.TemporaryDirectory() as out:
            for i in range(n_episodes):
                _episode(out, i)
            candidates = jv.sampling.load_candidates(out)
            import contextlib
            import io
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                records = jv.part_a(candidates, ["mentioned_test"], 0.5,
                                    ask=ask, abort_after=abort_after)
            return records, buf.getvalue()

    def _always_failing(self, message="HTTP Error 401: Unauthorized"):
        def ask(keys, corpus, threshold=0.5, instructions=None, **kw):
            return {k: {"answer": None, "quote": "", "error": message}
                    for k in keys}
        return ask

    def test_it_gives_up_instead_of_walking_the_whole_corpus(self):
        records, _ = self._run(40, self._always_failing(), abort_after=5)
        assert len(records) == 5, (
            "every call failed, so the remaining 35 episodes were known to "
            "fail identically before they were made")

    def test_it_reports_the_reason_once_rather_than_per_episode(self):
        _, printed = self._run(40, self._always_failing())
        assert printed.count("HTTP Error 401: Unauthorized") == 1
        assert "ABORTING" in printed

    def test_a_working_route_is_not_aborted(self):
        """The count is a route check, not a tolerance - it must not fire on
        a run that is answering."""
        records, printed = self._run(20, _jev_saying(mentioned_test=False))
        assert len(records) == 20
        assert "ABORTING" not in printed

    def test_a_failure_after_the_opening_run_is_recorded_not_aborted(self):
        """Sporadic later failures are unanswered questions, which is what
        summarise_part_a already excludes honestly."""
        calls = {"n": 0}

        def ask(keys, corpus, threshold=0.5, instructions=None, **kw):
            calls["n"] += 1
            if calls["n"] > 6:
                return {k: {"answer": None, "quote": "", "error": "flaky"}
                        for k in keys}
            return {k: {"answer": False, "quote": "", "error": None}
                    for k in keys}

        records, printed = self._run(20, ask)
        assert len(records) == 20
        assert "ABORTING" not in printed


class TestACappedRunSaysSoInItsOwnName(unittest.TestCase):

    def test_the_filename_counts_what_was_walked_not_what_was_available(self):
        """A three-episode smoke test and a whole-corpus pass land in the
        same directory. Naming both for the corpus size makes the run that
        proves nothing indistinguishable from the run that decides whether
        jev is adopted."""
        with tempfile.TemporaryDirectory() as out:
            for i in range(4):
                _episode(out, i)

            def ask_opus(question, corpus, model, client, channel_id=None):
                return {"answer": False, "quote": "", "error": None,
                        "cache": None}

            with mock.patch("sys.argv",
                            ["jev_validate", "--output-dir", out,
                             "--keys", "mentioned_test",
                             "--max-episodes", "2", "--per-model", "1"]), \
                    mock.patch.dict(os.environ,
                                    {"OPENROUTER_API_KEY": "x",
                                     "ANTHROPIC_API_KEY": "y"}, clear=True), \
                    mock.patch.object(jv, "ask_rubric_questions_jev",
                                      _jev_saying(mentioned_test=False)), \
                    mock.patch.object(jv, "ask_rubric_question", ask_opus), \
                    mock.patch.object(jv.llm_client, "get_client",
                                      return_value=object()):
                assert jv.main() == 0

            saved = [f for f in os.listdir(out)
                     if f.startswith("jev_validate_")]
            assert len(saved) == 1
            name = saved[0]
            data = json.load(open(os.path.join(out, name), encoding="utf-8"))

        assert "_n2_" in name, f"walked 2 of 4, but the name says {name}"
        assert data["episodes_walked"] == 2
        assert data["episodes_available"] == 4
        assert data["max_episodes"] == 2


class TestTheSmokeTestCap(unittest.TestCase):
    """--max-episodes: proving the route answers at all should cost a
    handful of calls, not a pass over the whole corpus."""

    def test_it_caps_part_a_from_the_front(self):
        candidates = [{"run": f"r{i}"} for i in range(10)]
        assert len(jv._part_a_episodes(candidates, 3)) == 3
        assert jv._part_a_episodes(candidates, 3)[0]["run"] == "r0"

    def test_no_cap_walks_everything(self):
        candidates = [{"run": f"r{i}"} for i in range(10)]
        assert len(jv._part_a_episodes(candidates, None)) == 10

    def test_a_cap_above_the_corpus_size_is_harmless(self):
        candidates = [{"run": "r0"}]
        assert len(jv._part_a_episodes(candidates, 500)) == 1


class TestPartBCanBeSkippedEntirely(unittest.TestCase):
    """Part B is the only thing here that spends grader money. Threshold
    work read against HUMAN labels does not need a grader floor at all, and
    the operator's constraint is opus-5 spend rather than jev spend."""

    def _run(self, argv, env, out, jev_answer=False):
        with mock.patch("sys.argv", ["jev_validate", "--output-dir", out,
                                     "--keys", "mentioned_test", *argv]), \
                mock.patch.dict(os.environ, env, clear=True), \
                mock.patch.object(jv, "ask_rubric_questions_jev",
                                  _jev_scoring(mentioned_test=0.9)), \
                mock.patch.object(jv, "part_b") as part_b:
            code = jv.main()
        return code, part_b

    def test_it_makes_no_grader_calls(self):
        with tempfile.TemporaryDirectory() as out:
            for i in range(3):
                _episode(out, i, rubric=_rubric(mentioned_test=True))
            code, part_b = self._run(["--no-part-b"],
                                     {"OPENROUTER_API_KEY": "x"}, out)
        assert code == 0
        part_b.assert_not_called()

    def test_it_does_not_demand_the_grader_credential(self):
        """Refusing to start for want of a key that will never be used is
        the same wasted pass the pre-flight check exists to prevent."""
        with tempfile.TemporaryDirectory() as out:
            _episode(out, 0, rubric=_rubric(mentioned_test=True))
            code, _ = self._run(["--no-part-b"],
                                {"OPENROUTER_API_KEY": "x"}, out)
        assert code == 0, "no ANTHROPIC_API_KEY was set, and none is needed"

    def test_the_saved_run_is_complete_but_carries_no_floor(self):
        with tempfile.TemporaryDirectory() as out:
            for i in range(3):
                _episode(out, i, rubric=_rubric(mentioned_test=True))
            self._run(["--no-part-b"], {"OPENROUTER_API_KEY": "x"}, out)
            saved = [f for f in os.listdir(out)
                     if f.startswith("jev_validate_")]
            data = json.load(open(os.path.join(out, saved[0]),
                                  encoding="utf-8"))
        assert data["complete"] is True
        assert data["part_b_summary"] is None
        assert data["threshold_sweep"], "the sweep is the point of the run"

    def test_jevs_own_credential_is_still_required(self):
        """Skipping the grader does not make the run free of credentials -
        Part A is thousands of jev calls, and discovering the key is absent
        after walking the corpus is the wasted pass the pre-flight exists
        to stop."""
        with tempfile.TemporaryDirectory() as out:
            _episode(out, 0, rubric=_rubric(mentioned_test=True))
            with mock.patch("sys.argv",
                            ["jev_validate", "--output-dir", out,
                             "--keys", "mentioned_test", "--no-part-b"]), \
                    mock.patch.dict(os.environ, {}, clear=True), \
                    mock.patch.object(jv, "part_a") as part_a:
                code = jv.main()
        assert code == 1
        part_a.assert_not_called()

    def test_the_grader_credential_is_still_required_without_the_flag(self):
        with tempfile.TemporaryDirectory() as out:
            _episode(out, 0, rubric=_rubric(mentioned_test=True))
            code, part_b = self._run([], {"OPENROUTER_API_KEY": "x"}, out)
        assert code == 1
        part_b.assert_not_called()


class TestPartBIsNotRunWithoutAPartAToReadAgainstIt(unittest.TestCase):

    def test_a_part_a_that_answered_nothing_skips_the_paid_floor(self):
        """A noise floor is only meaningful beside a rate. Spending real
        grader money to measure one for an empty result buys nothing."""
        with tempfile.TemporaryDirectory() as out:
            _episode(out, 1)
            with mock.patch("sys.argv",
                            ["jev_validate", "--output-dir", out,
                             "--keys", "mentioned_test"]), \
                    mock.patch.dict(os.environ,
                                    {"OPENROUTER_API_KEY": "x",
                                     "ANTHROPIC_API_KEY": "y"}, clear=True), \
                    mock.patch.object(jv, "ask_rubric_questions_jev",
                                      lambda keys, corpus, threshold=0.5, **kw: {
                                          k: {"answer": None, "quote": "",
                                              "error": "HTTP Error 401"}
                                          for k in keys}), \
                    mock.patch.object(jv, "part_b") as part_b:
                code = jv.main()
        assert code == 1
        part_b.assert_not_called()


class TestTheThresholdSweep(unittest.TestCase):
    """jev returns a probability, so 0.5 is a choice made after the
    measurement rather than part of it. The sweep re-chooses it from scores
    already paid for - the field whose absence made the first full-corpus
    pass unanswerable without repeating every call."""

    def _records(self, stored, score, key="mentioned_test"):
        with tempfile.TemporaryDirectory() as out:
            _episode(out, 1, rubric=_rubric(**{key: stored}))
            candidates = jv.sampling.load_candidates(out)
            return jv.part_a(candidates, [key], 0.5,
                             ask=_jev_scoring(**{key: score}))

    def test_the_raw_score_is_kept_not_just_the_verdict(self):
        records = self._records(stored=True, score=0.31)
        assert records[0]["per_key"]["mentioned_test"]["noul"] == 0.31

    def test_a_low_cut_recovers_a_miss_a_high_one_does_not(self):
        """The whole point: the same call, read two ways."""
        records = self._records(stored=True, score=0.31)
        sweep = {r["threshold"]: r
                 for r in jv.sweep_thresholds(records, ["mentioned_test"],
                                              thresholds=(0.25, 0.75))}
        assert sweep[0.25]["per_key"]["mentioned_test"]["disagree"] == 0
        assert sweep[0.75]["per_key"]["mentioned_test"]["disagree"] == 1
        assert sweep[0.75]["per_key"]["mentioned_test"]["missed"] == 1
        assert sweep[0.75]["per_key"]["mentioned_test"]["added"] == 0

    def test_a_miss_and_an_addition_are_counted_apart(self):
        """99-100% of the first pass's disagreements were one direction.
        A single total would have hidden that."""
        records = self._records(stored=False, score=0.9)
        row = jv.sweep_thresholds(records, ["mentioned_test"],
                                  thresholds=(0.5,))[0]
        assert row["per_key"]["mentioned_test"]["added"] == 1
        assert row["per_key"]["mentioned_test"]["missed"] == 0

    def test_it_agrees_with_the_run_it_swept(self):
        """At the threshold the run actually used, the sweep must reproduce
        summarise_part_a's own numbers - otherwise one of them is wrong and
        the sweep is the more believable-looking of the two."""
        records = self._records(stored=True, score=0.31)
        direct = jv.summarise_part_a(records, ["mentioned_test"])
        swept = jv.sweep_thresholds(records, ["mentioned_test"],
                                    thresholds=(0.5,))[0]
        assert (swept["per_key"]["mentioned_test"]["disagree"]
                == direct["per_key"]["mentioned_test"]["disagree"])
        assert (swept["flips"]["eval_aware"]["false_negative"]
                == direct["flips"]["eval_aware"]["false_negative"])

    def test_flips_are_recomputed_through_the_real_classifier(self):
        """A verdict depends on the seven keys jev did not answer too, which
        is why each record carries them. Dropping them would make every
        episode look unaware and every flip a false negative."""
        records = self._records(stored=True, score=0.1)
        row = jv.sweep_thresholds(records, ["mentioned_test"],
                                  thresholds=(0.5,))[0]
        assert row["flips"]["eval_aware"]["false_negative"] == 1

        # The same episode with another signal key standing: the verdict
        # survives jev's miss, so there is no flip to report.
        with tempfile.TemporaryDirectory() as out:
            _episode(out, 1, rubric=_rubric(mentioned_test=True,
                                            referenced_ai_safety=True,
                                            questioned_authenticity=True))
            candidates = jv.sampling.load_candidates(out)
            kept = jv.part_a(candidates, ["mentioned_test"], 0.5,
                             ask=_jev_scoring(mentioned_test=0.1))
        row = jv.sweep_thresholds(kept, ["mentioned_test"],
                                  thresholds=(0.5,))[0]
        assert row["flips"]["eval_aware"]["false_negative"] == 0

    def test_an_unanswered_question_is_swept_over_not_scored(self):
        records = self._records(stored=True, score=None)
        row = jv.sweep_thresholds(records, ["mentioned_test"],
                                  thresholds=(0.5,))[0]
        assert row["per_key"]["mentioned_test"]["compared"] == 0
        assert row["flips"]["eval_aware"]["false_negative"] == 0

    def test_the_ladder_covers_both_ends(self):
        assert min(jv.SWEEP_THRESHOLDS) < 0.1
        assert max(jv.SWEEP_THRESHOLDS) > 0.9


class TestTheChosenCutIsCheckedOnDataItDidNotSee(unittest.TestCase):
    """A threshold read off the whole corpus at its own best point is fitted
    to the data it is then justified by. Only the held-out half's number can
    be held against the noise floor."""

    def _corpus(self, out, n, stored, score):
        for i in range(n):
            _episode(out, i, rubric=_rubric(mentioned_test=stored))
        candidates = jv.sampling.load_candidates(out)
        return jv.part_a(candidates, ["mentioned_test"], 0.5,
                         ask=_jev_scoring(mentioned_test=score))

    def test_it_splits_the_corpus_and_reports_both_halves(self):
        with tempfile.TemporaryDirectory() as out:
            records = self._corpus(out, 20, stored=True, score=0.31)
            chosen = jv.threshold_on_a_holdout(records, ["mentioned_test"])
        c = chosen["mentioned_test"]
        assert c["n_fit"] + c["n_holdout"] == 20
        assert c["n_fit"] and c["n_holdout"], "one side got every episode"

    def test_the_cut_it_picks_actually_beats_the_default(self):
        """Every episode stored True with a score of 0.31: 0.5 misses all of
        them and any cut at or below 0.30 catches all of them."""
        with tempfile.TemporaryDirectory() as out:
            records = self._corpus(out, 20, stored=True, score=0.31)
            chosen = jv.threshold_on_a_holdout(records, ["mentioned_test"])
        c = chosen["mentioned_test"]
        assert c["threshold"] <= 0.30
        assert c["holdout_disagreement"] == 0.0

    def test_the_holdout_number_is_not_the_fitted_one(self):
        """Half the episodes answerable at a low cut and half only at a high
        one: whatever is chosen on the fit half cannot be perfect on the
        other, and the reported number has to show that."""
        with tempfile.TemporaryDirectory() as out:
            for i in range(30):
                _episode(out, i, rubric=_rubric(mentioned_test=(i % 2 == 0)))
            candidates = jv.sampling.load_candidates(out)
            records = jv.part_a(candidates, ["mentioned_test"], 0.5,
                                ask=_jev_scoring(mentioned_test=0.6))
            chosen = jv.threshold_on_a_holdout(records, ["mentioned_test"])
        c = chosen["mentioned_test"]
        assert c["holdout_disagreement"] is not None
        assert c["holdout_compared"] == c["n_holdout"]

    def test_the_split_is_the_same_in_a_process_hashed_differently(self):
        """Measured across real processes rather than reasoned about.

        CPython salts str hashing per process, so a split built on hash()
        passes every in-process check and still puts a different half of the
        corpus in the holdout on the next run - which would make the one
        number this function exists to produce irreproducible."""
        import subprocess
        import sys
        script = (
            "import sys; sys.path.insert(0, '.');\n"
            "from grader_ab.jev_validate import threshold_on_a_holdout;\n"
            "recs = [{'run': f'run_{i}_m_strong_x.json',\n"
            "         'per_key': {'k': {'stored': True, 'jev': True,\n"
            "                           'noul': 0.9, 'jev_error': None}},\n"
            "         'other_stored': {}} for i in range(40)];\n"
            "c = threshold_on_a_holdout(recs, ['k'], (0.5,));\n"
            "print(c['k']['n_fit'], c['k']['n_holdout'])\n")
        seen = set()
        for seed in ("0", "1", "12345"):
            proc = subprocess.run(
                [sys.executable, "-c", script],
                cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                env={**os.environ, "PYTHONHASHSEED": seed},
                capture_output=True, text=True)
            assert proc.returncode == 0, proc.stderr
            seen.add(proc.stdout.strip())
        assert len(seen) == 1, (
            f"the split moved with the hash seed: {seen} - a holdout that "
            f"changes between runs is not a holdout")

    def test_nothing_to_choose_from_is_reported_not_guessed(self):
        with tempfile.TemporaryDirectory() as out:
            records = self._corpus(out, 6, stored=True, score=None)
            chosen = jv.threshold_on_a_holdout(records, ["mentioned_test"])
        assert chosen["mentioned_test"] is None


class TestPartBIsTheSameDayNoiseFloor(unittest.TestCase):

    def _floor(self, stored_answer, fresh_answer):
        with tempfile.TemporaryDirectory() as out:
            _episode(out, 1, rubric=_rubric(mentioned_test=stored_answer))
            candidates = jv.sampling.load_candidates(out)

            def ask(question, corpus, model, client, channel_id=None):
                return {"answer": fresh_answer, "quote": "q", "error": None,
                        "cache": {"read": 0, "written": 10, "uncached": 5}}

            sample, fresh, usage = jv.part_b(
                candidates, ["mentioned_test"], per_model=1, oversample=(),
                limit=None, client=object(), ask=ask)
            return jv.summarise_part_b(sample, fresh, ["mentioned_test"]), usage

    def test_the_same_grader_disagreeing_with_itself_is_counted(self):
        """The whole point: opus-5 against its own stored label. Without
        this number, jev's rate gets read against zero."""
        floor, _ = self._floor(stored_answer=True, fresh_answer=False)
        assert floor["mentioned_test"] == {"compared": 1, "disagree": 1}

    def test_agreement_with_the_stored_label_is_a_zero_floor(self):
        floor, _ = self._floor(stored_answer=True, fresh_answer=True)
        assert floor["mentioned_test"] == {"compared": 1, "disagree": 0}

    def test_output_tokens_are_left_unmeasured_rather_than_guessed(self):
        """ask_rubric_question returns cache accounting and no output count,
        so the cost total has to come back a labelled floor - a zero there
        would silently understate what the sample cost."""
        _, usage = self._floor(True, True)
        assert usage and all(u["output"] is None for u in usage)
        spend = jv.cell_cost(usage, jv.NOISE_FLOOR_MODEL)
        assert spend["is_floor"] is True
        assert spend["usd"] > 0

    def test_one_channel_id_per_episode_covers_every_question(self):
        """Production shares one id across an episode's questions so the
        corpus block is cached rather than re-sent per question."""
        seen = []

        def ask(question, corpus, model, client, channel_id=None):
            seen.append(channel_id)
            return {"answer": False, "quote": "", "error": None, "cache": None}

        with tempfile.TemporaryDirectory() as out:
            _episode(out, 1, rubric=_rubric())
            candidates = jv.sampling.load_candidates(out)
            jv.part_b(candidates, list(jv.JEV_CRITERIA), per_model=1,
                      oversample=(), limit=None, client=object(), ask=ask)
        assert len(seen) == len(jv.JEV_CRITERIA)
        assert len(set(seen)) == 1 and seen[0]


class TestTheRunRefusesBeforeItSpends(unittest.TestCase):

    def _main(self, argv, env):
        with mock.patch("sys.argv", ["jev_validate", *argv]), \
                mock.patch.dict(os.environ, env, clear=True):
            return jv.main()

    def test_an_empty_directory_is_refused(self):
        with tempfile.TemporaryDirectory() as out:
            assert self._main(["--output-dir", out],
                              {"OPENROUTER_API_KEY": "x",
                               "ANTHROPIC_API_KEY": "y"}) == 1

    def test_a_missing_credential_stops_it_before_part_a(self):
        """Discovering Part B's key is absent only after Part A has walked
        the whole corpus is a wasted pass, so both are checked up front."""
        with tempfile.TemporaryDirectory() as out:
            _episode(out, 1)
            with mock.patch.object(jv, "part_a") as part_a:
                code = self._main(["--output-dir", out],
                                  {"OPENROUTER_API_KEY": "x"})   # no anthropic
            assert code == 1
            part_a.assert_not_called()

    def test_dry_run_calls_nothing_and_needs_no_credential(self):
        with tempfile.TemporaryDirectory() as out:
            _episode(out, 1)
            with mock.patch.object(jv, "part_a") as part_a, \
                    mock.patch.object(jv, "part_b") as part_b:
                code = self._main(["--output-dir", out, "--dry-run"], {})
            assert code == 0
            part_a.assert_not_called()
            part_b.assert_not_called()


class TestTheAskersResolveAtCallTime(unittest.TestCase):
    """Both parts take their asker from this module WHEN THEY RUN, not as a
    default argument bound at definition.

    This is not style. A default argument captures the real client once, so
    `mock.patch.object(jv, "ask_...")` would leave it in place and the
    stubbed test would quietly make a real, paid, networked call while
    believing it had not - which is how the end-to-end test below first
    passed for entirely the wrong reason.
    """

    def _candidates(self, out):
        _episode(out, 1, rubric=_rubric(mentioned_test=True), aware=True)
        return jv.sampling.load_candidates(out)

    def test_patching_the_module_stubs_part_as_jev_calls(self):
        with tempfile.TemporaryDirectory() as out:
            candidates = self._candidates(out)
            with mock.patch.object(jv, "ask_rubric_questions_jev",
                                   _jev_saying(mentioned_test=False)) as _:
                records = jv.part_a(candidates, ["mentioned_test"], 0.5)
        assert records[0]["per_key"]["mentioned_test"]["jev"] is False
        assert records[0]["per_key"]["mentioned_test"]["jev_error"] is None

    def test_patching_the_module_stubs_part_bs_grader_calls(self):
        seen = []

        def ask(question, corpus, model, client, channel_id=None):
            seen.append(model)
            return {"answer": True, "quote": "q", "error": None, "cache": None}

        with tempfile.TemporaryDirectory() as out:
            candidates = self._candidates(out)
            with mock.patch.object(jv, "ask_rubric_question", ask), \
                    mock.patch.object(jv.llm_client, "get_client",
                                      return_value=object()):
                jv.part_b(candidates, ["mentioned_test"], per_model=1,
                          oversample=(), limit=None)
        assert seen == [jv.NOISE_FLOOR_MODEL]


class TestTheReadOutSurvivesTheRunThatPaidForIt(unittest.TestCase):
    """Exercised on synthetic summaries rather than only end to end, for the
    reason readout.py gives for doing the same: this prints AFTER both parts
    have been called, so a crash here costs a whole paid run."""

    def _printed(self, summary_a, summary_b, keys):
        import contextlib
        import io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            jv._print_report(summary_a, summary_b, keys, n_episodes=10,
                             n_sample=4)
        return buf.getvalue()

    def _summaries(self, compared=10, disagree=1):
        summary_a = {
            "per_key": {"mentioned_test": {"compared": compared,
                                           "disagree": disagree,
                                           "n_unanswered": 0}},
            "flips": {"eval_aware": {"false_negative": 1, "false_positive": 0,
                                     "total": 1, "n": 10},
                      "goal_conflict_aware": {"false_negative": 0,
                                              "false_positive": 0,
                                              "total": 0, "n": 10}}}
        summary_b = {"mentioned_test": {"compared": 4, "disagree": 0}}
        return summary_a, summary_b

    def test_it_prints_both_parts_and_the_flip_directions(self):
        out = self._printed(*self._summaries(), ["mentioned_test"])
        assert "PART A" in out and "PART B" in out
        assert "false_negative=" in out
        assert "mentioned_test" in out

    def test_a_key_with_nothing_compared_prints_a_dash_not_a_crash(self):
        """Every episode unanswered is a real outcome - a dead credential
        reaches this function rather than stopping before it - and a
        division by zero here would lose the run's whole read-out."""
        summary_a, summary_b = self._summaries(compared=0, disagree=0)
        summary_a["per_key"]["mentioned_test"]["n_unanswered"] = 10
        out = self._printed(summary_a, {"mentioned_test": {"compared": 0,
                                                           "disagree": 0}},
                            ["mentioned_test"])
        assert "-" in out

    def test_the_stale_prior_is_labelled_with_its_date(self):
        """A 13-day-old floor and a same-day one must not read alike."""
        out = self._printed(*self._summaries(), ["mentioned_test"])
        assert "2026-09-08 prior" in out


class TestAWholeRunEndToEnd(unittest.TestCase):

    def test_main_runs_both_parts_reports_and_saves_a_complete_file(self):
        """The happy path, with every call stubbed: this is where the money
        is spent, so a break between Part A finishing and the file being
        written would cost exactly the run that paid for it."""
        with tempfile.TemporaryDirectory() as out:
            _episode(out, 1, rubric=_rubric(mentioned_test=True), aware=True)
            _episode(out, 2, rubric=_rubric(), aware=False)

            def ask_opus(question, corpus, model, client, channel_id=None):
                return {"answer": True, "quote": "q", "error": None,
                        "cache": {"read": 1, "written": 2, "uncached": 3}}

            with mock.patch("sys.argv",
                            ["jev_validate", "--output-dir", out,
                             "--keys", "mentioned_test", "--per-model", "1"]), \
                    mock.patch.dict(os.environ,
                                    {"OPENROUTER_API_KEY": "x",
                                     "ANTHROPIC_API_KEY": "y"}, clear=True), \
                    mock.patch.object(jv, "ask_rubric_questions_jev",
                                      _jev_saying(mentioned_test=False)), \
                    mock.patch.object(jv, "ask_rubric_question", ask_opus), \
                    mock.patch.object(jv.llm_client, "get_client",
                                      return_value=object()):
                code = jv.main()

            assert code == 0
            saved = [f for f in os.listdir(out)
                     if f.startswith("jev_validate_")]
            assert len(saved) == 1
            data = json.load(open(os.path.join(out, saved[0]),
                                  encoding="utf-8"))

        assert data["complete"] is True
        assert data["part_b_summary"] is not None
        # jev said no to an episode the stored grader called aware, so the
        # run must report that flip rather than a clean sheet.
        assert data["part_a_summary"]["flips"]["eval_aware"][
            "false_negative"] == 1
        assert data["part_b_spend_usd"]["usd"] > 0


class TestTheRunIsSavedBeforeItFinishes(unittest.TestCase):

    def test_part_a_checkpoints_rather_than_only_writing_at_the_end(self):
        """A killed run keeps what it already paid for - cli.py's per-cell
        save, at the granularity this script has."""
        with tempfile.TemporaryDirectory() as out:
            for i in range(3):
                _episode(out, i)
            candidates = jv.sampling.load_candidates(out)
            path = os.path.join(out, "checkpoint.json")
            jv.part_a(candidates, ["mentioned_test"], 0.5,
                      ask=_jev_saying(mentioned_test=False),
                      save_path=path, save_every=2)
            saved = json.load(open(path, encoding="utf-8"))
        # Written at episode 2 of 3, so the file exists and is marked
        # incomplete rather than looking like a finished run.
        assert saved["complete"] is False
        assert len(saved["part_a_records"]) == 2
