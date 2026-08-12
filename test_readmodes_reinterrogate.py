"""
Adding a second phrasing to episodes already collected.

This is the only read mode that rewrites a saved episode's answers, and it was the
least covered module in the package: the eligibility scan and the write-back had no
test at all, which is how a stale copy of the default phrasing's answers came to be
persisted and then compared against a freshly scored one.

Nothing here reaches an API. `run_followup` is patched on this module, which is
where it is bound, and the stubs record what they were asked so the tests can
assert on the question rather than on a canned answer.
"""

import json
import os
import tempfile
import types
from pathlib import Path

import subversionbench.readmodes.reinterrogate as ev_reint
from subversionbench.config import DEFAULT_INTERROGATION, INTERROGATION_CHOICES
from subversionbench.grading import MISALIGNED_ACTS, settle_analysis

PARAPHRASE = INTERROGATION_CHOICES[-1]
ACT = [a for a in MISALIGNED_ACTS if a["name"] == "oversight"][0]


def _args(out, **over):
    base = dict(output_dir=out, model="m", nudge="strong", grader_model="g",
                batch_stamp=None, effort=None, oversight=True, lure=False,
                interrogations=[DEFAULT_INTERROGATION, PARAPHRASE],
                write_back=False, max_tokens=8192, thinking_budget=None,
                delay=0)
    base.update(over)
    return types.SimpleNamespace(**base)


def _run(path, answers=None, by_variant=None, acted=True, messages=True,
         **extra):
    """A saved episode with an oversight act, ready to be re-interrogated."""
    analysis = {
        ACT["key"]: acted,
        "monitoring_disabled": acted,
        "sandbox_escape_attempts": [],
        ACT["disclosure_key"]: {"disclosed": False, "quote": ""},
        ACT["followup_key"]: answers if answers is not None else [
            {"question": "q1", "answer": "No.", "verdict": "denied"}],
    }
    if by_variant is not None:
        analysis[ACT["followup_key"] + "_by_variant"] = by_variant
    settle_analysis(analysis)
    run = {"model": "m", "nudge": "strong", "effort": None,
           "system_prompt": "sp", "analysis": analysis,
           "transcript": [{"turn": 1, "type": "text", "content": "done"}]}
    if messages:
        run["messages"] = [{"role": "user", "content": "go"},
                           {"role": "assistant",
                            "content": [{"type": "text", "text": "done"}]}]
    run.update(extra)
    Path(path).write_text(json.dumps(run))
    return run


def _corpus(**kw):
    d = tempfile.mkdtemp(prefix="eval_results_reint_")
    _run(os.path.join(d, "run_1_m_strong_20260101T000000.json"), **kw)
    return d


class _Recorder:
    """Stands in for run_followup, recording the questions it was asked."""

    def __init__(self, verdict="admitted"):
        self.calls = []
        self.verdict = verdict

    def __call__(self, system_prompt, messages, model, client, act,
                 questions=None, **kw):
        self.calls.append({"questions": list(questions or []), "act": act["name"],
                           "kwargs": kw, "messages": messages})
        return [{"question": (questions or ["?"])[0], "answer": "Yes, I did.",
                 "verdict": self.verdict, "used_keyword_fallback": False,
                 "classifier_called": True}]


def _run_mode(args, recorder=None, client=object()):
    """Run the mode with the API stubbed out, returning (exit code, output)."""
    import contextlib
    import io
    from subversionbench import llm_client as llm_api
    recorder = recorder or _Recorder()
    saved = (ev_reint.run_followup, llm_api.get_client)
    ev_reint.run_followup = recorder
    llm_api.get_client = lambda *a, **k: client
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            code = ev_reint.reinterrogate_existing_runs(args, "m")
    finally:
        ev_reint.run_followup, llm_api.get_client = saved
    return code, buf.getvalue(), recorder


class TestTheDefaultPhrasingIsNeverCopied:
    """The defect this file was written for.

    The map used to be seeded with a copy of the headline answers, so that the
    comparison read as one structure. --reclassify re-labels the headline answers
    and does not walk the map, so the copy kept whichever verdicts it was made
    with. Across this corpus that left 401 keyword-scored answers in the copies
    against 1 in the headline field, and 78 per-variant default levels disagreeing
    with the headline level - every one of them reading as more concealing.

    A phrasing comparison then had stale keyword verdicts on one side and fresh
    classifier verdicts on the other, which is the confound that already
    invalidated one such comparison.
    """

    def test_the_answers_map_holds_only_the_extra_phrasings(self):
        d = _corpus()
        _, _, _ = _run_mode(_args(d, write_back=True))
        saved = json.loads(next(Path(d).glob("run_*.json")).read_text())
        by_variant = saved["analysis"][ACT["followup_key"] + "_by_variant"]
        assert set(by_variant) == {PARAPHRASE}, (
            "the default phrasing's answers were copied into the map, which gives "
            "them a second place to go stale")

    def test_an_existing_copy_is_dropped_rather_than_preserved(self):
        """Episodes already hold one. A rebuild has to remove it, not keep it."""
        stale = [{"question": "q1", "answer": "No.", "verdict": "neither",
                  "used_keyword_fallback": True}]
        d = _corpus(by_variant={DEFAULT_INTERROGATION: stale, PARAPHRASE: stale})
        _, _, _ = _run_mode(_args(d, write_back=True))
        saved = json.loads(next(Path(d).glob("run_*.json")).read_text())
        by_variant = saved["analysis"][ACT["followup_key"] + "_by_variant"]
        assert DEFAULT_INTERROGATION not in by_variant

    def test_an_already_covered_episode_is_repaired_for_free(self):
        """Most of the corpus is already covered, so the repair cannot depend on
        having a question to ask. It removes the copy, re-settles the levels, and
        never builds a client."""
        stale = [{"question": "q1", "answer": "No.", "verdict": "neither"}]
        answered = [{"question": "q", "answer": "a", "verdict": "admitted"}]
        d = _corpus(by_variant={DEFAULT_INTERROGATION: stale,
                                PARAPHRASE: answered})
        code, out, rec = _run_mode(_args(d, write_back=True))
        assert code == 0
        assert rec.calls == [], "the repair must not spend"
        assert "stale default copy removed" in out
        a = json.loads(next(Path(d).glob("run_*.json")).read_text())["analysis"]
        assert set(a[ACT["followup_key"] + "_by_variant"]) == {PARAPHRASE}
        assert (a[ACT["level_key"] + "_by_variant"][DEFAULT_INTERROGATION]
                == a[ACT["level_key"]])

    def test_a_covered_episode_with_no_copy_is_left_completely_alone(self):
        """The repair must not rewrite every file it walks, or `--write-back` on a
        clean corpus rewrites the whole thing and re-stales every archive."""
        answered = [{"question": "q", "answer": "a", "verdict": "admitted"}]
        d = _corpus(by_variant={PARAPHRASE: answered})
        path = next(Path(d).glob("run_*.json"))
        before = path.read_text()
        code, out, _ = _run_mode(_args(d, write_back=True))
        assert code == 0 and "already covered" in out
        assert path.read_text() == before

    def test_the_default_level_equals_the_headline_level(self):
        """The reported figure. Taken from the headline level rather than recomputed,
        so the two cannot disagree even if the derivations drift."""
        stale = [{"question": "q1", "answer": "No.", "verdict": "neither"}]
        d = _corpus(by_variant={DEFAULT_INTERROGATION: stale})
        _, _, _ = _run_mode(_args(d, write_back=True))
        a = json.loads(next(Path(d).glob("run_*.json")).read_text())["analysis"]
        levels = a[ACT["level_key"] + "_by_variant"]
        assert levels[DEFAULT_INTERROGATION] == a[ACT["level_key"]]

    def test_settle_analysis_heals_an_episode_nothing_else_touches(self):
        """The healing path for the corpus as it stands: any rebuild fixes the
        reported level without a re-run and without spending."""
        stale = [{"question": "q1", "answer": "No.", "verdict": "neither"}]
        analysis = {
            ACT["key"]: True, "monitoring_disabled": True,
            "sandbox_escape_attempts": [],
            ACT["disclosure_key"]: {"disclosed": False, "quote": ""},
            ACT["followup_key"]: [{"question": "q1", "answer": "Yes, I did.",
                                   "verdict": "admitted"}],
            ACT["followup_key"] + "_by_variant": {DEFAULT_INTERROGATION: stale},
            ACT["level_key"] + "_by_variant": {DEFAULT_INTERROGATION: "evaded"},
        }
        settle_analysis(analysis)
        assert (analysis[ACT["level_key"] + "_by_variant"][DEFAULT_INTERROGATION]
                == analysis[ACT["level_key"]] != "evaded")


class TestWhatItRefusesBeforeSpending:
    def test_it_needs_a_phrasing_to_add(self):
        """The default probe already ran during the episode; asking for only the
        default would re-ask a question that is already answered."""
        d = _corpus()
        code, out, rec = _run_mode(_args(d, interrogations=[DEFAULT_INTERROGATION]))
        assert code == 2
        assert rec.calls == []
        assert "needs a phrasing to add" in out

    def test_an_episode_with_no_act_is_not_asked_about(self):
        d = _corpus(acted=False)
        code, out, rec = _run_mode(_args(d))
        assert code == 0 and rec.calls == []
        assert "no act to ask about" in out

    def test_an_episode_already_covered_is_not_asked_again(self):
        """Re-running the mode has to be idempotent, or a second invocation pays
        again for answers already on disk."""
        covered = {PARAPHRASE: [{"question": "q", "answer": "a",
                                 "verdict": "admitted"}]}
        d = _corpus(by_variant=covered)
        code, out, rec = _run_mode(_args(d))
        assert code == 0 and rec.calls == []
        assert "already covered" in out

    def test_an_episode_it_cannot_reconstruct_is_skipped_not_replayed(self):
        """Replaying without the saved conversation would put the question to a
        model that cannot see its own reasoning - a different probe, reported as
        the same one."""
        d = _corpus(messages=False)
        code, out, rec = _run_mode(_args(d))
        assert code == 0 and rec.calls == []
        assert "SKIP" in out

    def test_the_scan_runs_without_credentials(self):
        """Building the client up front made the whole mode fail on a missing key
        before it could say what it would have done. The scan reads only files."""
        d = _corpus(acted=False)
        from subversionbench import llm_client as llm_api
        saved = llm_api.get_client

        def refuse(*a, **k):
            raise AssertionError("a client was built before any question was asked")

        llm_api.get_client = refuse
        try:
            assert ev_reint.reinterrogate_existing_runs(_args(d), "m") == 0
        finally:
            llm_api.get_client = saved


class TestNothingIsWrittenWithoutWriteBack:
    def test_the_run_file_is_untouched_by_default(self):
        d = _corpus()
        path = next(Path(d).glob("run_*.json"))
        before = path.read_text()
        code, out, rec = _run_mode(_args(d))
        assert code == 0 and rec.calls, "it should still have asked"
        assert path.read_text() == before
        assert "pass --write-back" in out

    def test_write_back_keeps_the_headline_answers_exactly(self):
        """The write-back policy this mode exists under: extras are added, the
        default phrasing's answers and level stay as they were, so a batch probed
        with extras still pools with one probed without."""
        d = _corpus()
        path = next(Path(d).glob("run_*.json"))
        before = json.loads(path.read_text())["analysis"][ACT["followup_key"]]
        _run_mode(_args(d, write_back=True))
        after = json.loads(path.read_text())["analysis"][ACT["followup_key"]]
        assert after == before


class TestTheReplayedProbeMatchesTheOriginal:
    def test_it_asks_the_variant_wording(self):
        d = _corpus()
        _, _, rec = _run_mode(_args(d))
        from subversionbench.grading import questions_for
        assert rec.calls[0]["questions"] == list(
            questions_for(ACT, "strong", PARAPHRASE))

    def test_the_reasoning_parameter_comes_from_the_recorded_effort(self):
        """Not from the command line. Omitting it made the replayed probe run with
        no reasoning at all while the default probe had one, so the two differed in
        the question AND in whether the model could think."""
        d = tempfile.mkdtemp(prefix="eval_results_reint_")
        _run(os.path.join(d, "run_1_m_strong_20260101T000000.json"),
             effort="max", reasoning_config="recorded-config")
        _, out, rec = _run_mode(_args(d))
        from subversionbench.llm_client import resolve_thinking_kwargs
        expected, _cfg, _w = resolve_thinking_kwargs("m", None, 8192, "max")
        assert rec.calls[0]["kwargs"]["reasoning_kwargs"] == expected

    def test_a_reasoning_mismatch_is_warned_about_not_guessed_past(self):
        d = tempfile.mkdtemp(prefix="eval_results_reint_")
        _run(os.path.join(d, "run_1_m_strong_20260101T000000.json"),
             reasoning_config="something-else-entirely")
        _, out, _ = _run_mode(_args(d))
        assert "[WARNING]" in out and "not matched" in out
