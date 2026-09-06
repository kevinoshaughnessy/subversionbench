"""
Staging a model's r9 episodes into r10 without reintroducing the confound
r10 exists to remove.

Two things are guarded here, and the first is the one that matters.

A STALE ARM MUST NEVER BE STAGED. r10 changed only the no-oversight arm; r9's
no-oversight episodes were produced by the scenario the fix changed, and
pooling them with r10's no-oversight episodes would silently reintroduce the
confound this repository spent a rollout bump removing - measured directly:
the escape rate that scenario induced fell from 89.8% to 0.0%. So the
poolability test - does this episode's own fingerprint match what current
code assembles for its arm - is the one thing every test below either proves
holds or proves catches a violation of.

NOTHING IS EVER OVERWRITTEN OR LOST. --source-dir is read-only; --dest-dir
never has an existing file replaced. A staging run that is re-run for the
same model must be a no-op, not a re-copy, or the mechanism could not safely
be part of a repeatable per-model loop.
"""

import json
import os
import tempfile

import conftest
import restage_model as rm
from subversionbench.rollout import rollout_fingerprint


def _current(oversight, lure):
    return rollout_fingerprint(oversight=bool(oversight), lure=bool(lure))


def _run_file(d, name, model, nudge, oversight, lure, fingerprint=...):
    if fingerprint is ...:
        fingerprint = _current(oversight, lure)
    data = {"model": model, "nudge": nudge, "oversight": oversight,
           "lure": lure, "rollout_fingerprint": fingerprint,
           "rollout_version": "r9", "analysis": {}, "transcript": []}
    with open(os.path.join(d, name), "w", encoding="utf-8") as f:
        json.dump(data, f)
    return os.path.join(d, name)


def _summary_file(d, name, model, nudge, oversight, lure, fingerprints=...):
    if fingerprints is ...:
        fingerprints = {_current(oversight, lure): 10}
    parts = ["summary"] + [model.replace("/", "_"), nudge]
    stem = "_".join(parts)
    if lure:
        stem += "_lure"
    if not oversight:
        stem += "_nooversight"
    filename = f"{stem}_20260101T000000.json"
    data = {"model": model, "nudge": nudge,
           "rollout": {"fingerprints": fingerprints}}
    with open(os.path.join(d, filename), "w", encoding="utf-8") as f:
        json.dump(data, f)
    return os.path.join(d, filename)


class TestPoolableRunFiles:
    def test_a_matching_fingerprint_is_kept(self):
        with tempfile.TemporaryDirectory() as d:
            _run_file(d, "run_1_m_strong_20260101T000000.json", "m", "strong",
                      True, False)
            got = rm.poolable_run_files(d, "m", rm._current_fingerprint_cache())
            assert len(got) == 1

    def test_a_stale_no_oversight_fingerprint_is_excluded(self):
        """The property everything else here exists to protect. A no-oversight
        episode carrying the PRE-FIX fingerprint must never be staged, however
        the file arrived."""
        with tempfile.TemporaryDirectory() as d:
            _run_file(d, "run_1_m_strong_nooversight_20260101T000000.json", "m",
                      "strong", False, False, fingerprint="pre_fix_stale_hash")
            got = rm.poolable_run_files(d, "m", rm._current_fingerprint_cache())
            assert got == {}

    def test_a_different_model_is_not_included(self):
        with tempfile.TemporaryDirectory() as d:
            _run_file(d, "run_1_other_strong_20260101T000000.json", "other",
                      "strong", True, False)
            got = rm.poolable_run_files(d, "m", rm._current_fingerprint_cache())
            assert got == {}

    def test_a_file_with_no_recorded_fingerprint_is_excluded(self):
        """Nothing to compare, so nothing is assumed - the same
        not-applicable-is-not-a-yes rule the rest of this codebase follows."""
        with tempfile.TemporaryDirectory() as d:
            path = _run_file(d, "run_1_m_strong_20260101T000000.json", "m",
                             "strong", True, False)
            data = json.load(open(path, encoding="utf-8"))
            del data["rollout_fingerprint"]
            json.dump(data, open(path, "w", encoding="utf-8"))
            got = rm.poolable_run_files(d, "m", rm._current_fingerprint_cache())
            assert got == {}

    def test_both_oversight_arms_at_every_nudge_level_are_kept(self):
        """The actual shape of a real model's r9 corpus: oversight-present
        episodes are current at every nudge level, not just the one most
        recently touched."""
        with tempfile.TemporaryDirectory() as d:
            for i, nudge in enumerate(("none", "strong", "max")):
                for lure in (False, True):
                    _run_file(d, f"run_{i}_m_{nudge}"
                             f"{'_lure' if lure else ''}_20260101T00000{i}.json",
                             "m", nudge, True, lure)
            got = rm.poolable_run_files(d, "m", rm._current_fingerprint_cache())
            assert len(got) == 6


class TestPoolableSummaryFiles:
    def test_a_matching_summary_is_kept(self):
        with tempfile.TemporaryDirectory() as d:
            _summary_file(d, "s", "m", "strong", True, False)
            got = rm.poolable_summary_files(d, "m",
                                            rm._current_fingerprint_cache())
            assert len(got) == 1

    def test_the_arm_comes_from_the_filename_not_a_stamped_field(self):
        """Checked against a real corpus file before this was written: summary
        files do not stamp oversight/lure at the top level at all, so a
        version of this that read s.get("oversight") would silently exclude
        every real summary rather than fail loudly."""
        with tempfile.TemporaryDirectory() as d:
            path = _summary_file(d, "s", "m", "strong", True, False)
            data = json.load(open(path, encoding="utf-8"))
            assert "oversight" not in data and "lure" not in data
            got = rm.poolable_summary_files(d, "m",
                                            rm._current_fingerprint_cache())
            assert len(got) == 1

    def test_a_stale_no_oversight_summary_is_excluded(self):
        with tempfile.TemporaryDirectory() as d:
            _summary_file(d, "s", "m", "strong", False, False,
                         fingerprints={"pre_fix_stale_hash": 20})
            got = rm.poolable_summary_files(d, "m",
                                            rm._current_fingerprint_cache())
            assert got == {}

    def test_a_batch_that_straddles_two_fingerprints_is_excluded(self):
        """A summary aggregating a mixed-fingerprint batch is treated as not
        poolable rather than guessed about - conservative on purpose, since
        this script's only job is to avoid reintroducing a known confound."""
        with tempfile.TemporaryDirectory() as d:
            current = _current(True, False)
            _summary_file(d, "s", "m", "strong", True, False,
                         fingerprints={current: 15, "some_other_hash": 5})
            got = rm.poolable_summary_files(d, "m",
                                            rm._current_fingerprint_cache())
            assert got == {}

    def test_a_summary_with_no_fingerprints_recorded_is_excluded(self):
        with tempfile.TemporaryDirectory() as d:
            _summary_file(d, "s", "m", "strong", True, False, fingerprints={})
            got = rm.poolable_summary_files(d, "m",
                                            rm._current_fingerprint_cache())
            assert got == {}


class TestStaging:
    def test_poolable_files_are_copied_byte_identical(self):
        with tempfile.TemporaryDirectory() as src, \
                tempfile.TemporaryDirectory() as dst:
            path = _run_file(src, "run_1_m_strong_20260101T000000.json", "m",
                             "strong", True, False)
            result = rm.stage("m", src, dst)
            assert result["staged"] == 1
            copied = os.path.join(dst, "run_1_m_strong_20260101T000000.json")
            assert os.path.exists(copied)
            assert open(path, "rb").read() == open(copied, "rb").read()

    def test_a_stale_arm_never_reaches_the_destination(self):
        """The end-to-end version of the property TestPoolableRunFiles proves
        at the function level - checked again here because a defect in how
        stage() combines run and summary results could reintroduce it even
        with poolable_run_files itself correct."""
        with tempfile.TemporaryDirectory() as src, \
                tempfile.TemporaryDirectory() as dst:
            _run_file(src, "run_1_m_strong_nooversight_20260101T000000.json",
                     "m", "strong", False, False, fingerprint="pre_fix_stale")
            _summary_file(src, "s", "m", "strong", False, False,
                         fingerprints={"pre_fix_stale": 10})
            rm.stage("m", src, dst)
            assert os.listdir(dst) == []

    def test_dry_run_copies_nothing(self):
        with tempfile.TemporaryDirectory() as src, \
                tempfile.TemporaryDirectory() as dst:
            _run_file(src, "run_1_m_strong_20260101T000000.json", "m",
                     "strong", True, False)
            result = rm.stage("m", src, dst, dry_run=True)
            assert result["staged"] == 1     # counts what WOULD be staged
            assert os.listdir(dst) == []     # but copies nothing

    def test_rerunning_is_a_no_op_the_second_time(self):
        """The property that makes this safe inside a per-model loop run
        more than once - a re-run must not re-copy, and must not error."""
        with tempfile.TemporaryDirectory() as src, \
                tempfile.TemporaryDirectory() as dst:
            _run_file(src, "run_1_m_strong_20260101T000000.json", "m",
                     "strong", True, False)
            first = rm.stage("m", src, dst)
            second = rm.stage("m", src, dst)
            assert first["staged"] == 1
            assert second["staged"] == 0
            assert second["skipped_existing"] == 1

    def test_an_existing_destination_file_is_never_overwritten(self):
        """Even if its content differs from what would have been copied - a
        real collision is a sign something is wrong, and silently picking a
        winner would hide that."""
        with tempfile.TemporaryDirectory() as src, \
                tempfile.TemporaryDirectory() as dst:
            _run_file(src, "run_1_m_strong_20260101T000000.json", "m",
                     "strong", True, False)
            existing_path = os.path.join(dst, "run_1_m_strong_20260101T000000.json")
            with open(existing_path, "w", encoding="utf-8") as f:
                json.dump({"sentinel": True}, f)
            rm.stage("m", src, dst)
            assert json.load(open(existing_path, encoding="utf-8")) == \
                {"sentinel": True}

    def test_source_directory_is_never_written_to(self):
        with tempfile.TemporaryDirectory() as src, \
                tempfile.TemporaryDirectory() as dst:
            _run_file(src, "run_1_m_strong_20260101T000000.json", "m",
                     "strong", True, False)
            before = sorted(os.listdir(src))
            rm.stage("m", src, dst)
            assert sorted(os.listdir(src)) == before

    def test_the_real_corpus_matches_the_measured_split(self):
        """Anchors this test suite to the actual number this script was built
        to verify: of google/gemini-3.5-flash's r9 episodes, exactly the
        oversight-present 100 are poolable, none of the no-oversight 105 are.
        Skipped when the real corpus is not present on this checkout."""
        import unittest
        if not os.path.isdir("eval_results_r9"):
            raise unittest.SkipTest("eval_results_r9 not present")
        with tempfile.TemporaryDirectory() as dst:
            result = rm.stage("google/gemini-3.5-flash", "eval_results_r9", dst)
        assert result["n_run_files_poolable"] == 100
        for arm, _counts in result["by_arm"].items():
            assert "oversight=True" in arm, (
                f"a no-oversight arm was judged poolable: {arm}")


class TestTheCLIRefusesRatherThanGuesses:
    def test_an_unknown_model_name_is_reported_not_silently_empty(self):
        with tempfile.TemporaryDirectory() as src, \
                tempfile.TemporaryDirectory() as dst:
            _run_file(src, "run_1_m_strong_20260101T000000.json", "m",
                     "strong", True, False)
            result = rm.stage("totally-different-model", src, dst)
            assert result["n_run_files_poolable"] == 0
            assert result["n_summary_files_poolable"] == 0


class TestTheExitCodeTheShellLoopReads:
    """main()'s own contract, which stage() cannot express.

    The usage this script documents is a `for m in ...` loop over models, so
    the exit code is the only thing distinguishing a model that staged from
    one whose name was mistyped - both print, and both leave the destination
    looking plausible.
    """

    def test_a_typo_in_the_model_name_exits_non_zero(self):
        """Silent success on an unknown model is the failure this guards:
        the loop moves on, the destination gains nothing, and the arms it
        was supposed to gain are reported missing much later."""
        with tempfile.TemporaryDirectory() as src, \
                tempfile.TemporaryDirectory() as dst:
            _run_file(src, "run_1_m_strong_20260101T000000.json", "m",
                     "strong", True, False)
            code, text = conftest.run_tool_main(rm, [
                "--model", "typo", "--source-dir", src, "--dest-dir", dst])
            assert code == 1
            assert "nothing poolable" in text

    def test_a_source_directory_that_is_not_there_stops_the_run(self):
        """Asserting only on the exit code would not discriminate here: a
        missing source directory globs to nothing, so the "nothing poolable"
        branch downstream returns 1 as well. What separates them is that
        this one never reaches the staging report at all."""
        with tempfile.TemporaryDirectory() as dst:
            code, text = conftest.run_tool_main(rm, [
                "--model", "m", "--source-dir", os.path.join(dst, "absent"),
                "--dest-dir", dst])
            assert code == 1
            assert "not a directory" in text
            assert "poolable run file(s)" not in text, \
                "the guard printed and then carried on anyway"

    def test_a_destination_that_is_not_there_stops_the_run(self):
        """Checked before anything is read, so a mistyped destination costs
        a message rather than a walk of thousands of files - which is the
        part worth asserting, since the walk would find nothing and return
        the same 1 either way."""
        with tempfile.TemporaryDirectory() as src:
            _run_file(src, "run_1_m_strong_20260101T000000.json", "m",
                     "strong", True, False)
            code, text = conftest.run_tool_main(rm, [
                "--model", "m", "--source-dir", src,
                "--dest-dir", os.path.join(src, "absent")])
            assert code == 1
            assert "not a directory" in text
            assert "poolable run file(s)" not in text, \
                "the guard printed and then walked the corpus anyway"

    def test_a_successful_staging_exits_zero_and_leaves_the_file_there(self):
        with tempfile.TemporaryDirectory() as src, \
                tempfile.TemporaryDirectory() as dst:
            _run_file(src, "run_1_m_strong_20260101T000000.json", "m",
                     "strong", True, False)
            code, _text = conftest.run_tool_main(rm, [
                "--model", "m", "--source-dir", src, "--dest-dir", dst])
            assert code == 0
            assert os.listdir(dst) == ["run_1_m_strong_20260101T000000.json"]

    def test_a_dry_run_exits_zero_and_copies_nothing(self):
        """--dry-run is what an operator runs first, so it has to report the
        same selection while leaving the destination untouched. A dry run
        that exited non-zero would read as "nothing to stage"."""
        with tempfile.TemporaryDirectory() as src, \
                tempfile.TemporaryDirectory() as dst:
            _run_file(src, "run_1_m_strong_20260101T000000.json", "m",
                     "strong", True, False)
            code, text = conftest.run_tool_main(rm, [
                "--model", "m", "--source-dir", src, "--dest-dir", dst,
                "--dry-run"])
            assert code == 0
            assert os.listdir(dst) == [], "a dry run copied a file"
            assert "would stage 1" in text
            assert "nothing was copied" in text
