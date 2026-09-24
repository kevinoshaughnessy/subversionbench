"""
Wiring the grader A/B sample into the blinding engine.

`subversionbench.blinding` holds the rules and `test_analysis/test_blinding.py`
guards them. What is left here is the part only this experiment can get wrong:
which of a candidate's fields is the text, which is the stratum, and which are
identity that must stay sealed. Those three are named in one place, so a guard
that derives the forbidden set from a REAL candidate is what proves the naming
right.
"""

import contextlib
import io
import json
import os
import sys
import tempfile

from grader_ab import blind_pack
from subversionbench import blinding
from test_corpus.grader_ab_fixtures import _graded_episode


# A value shorter than this cannot be distinguished from the same word
# occurring in the agent's own text, so the check below skips it. Measured
# against the real pack, not chosen: see the docstring there.
_DISTINCTIVE_ENOUGH = 8
_SKIPPED_AS_TOO_SHORT = {"nudge"}


def _run_blind_pack(argv):
    buf = io.StringIO()
    saved = sys.argv
    sys.argv = ["blind_pack.py", *argv]
    try:
        with contextlib.redirect_stdout(buf):
            code = blind_pack.main()
    finally:
        sys.argv = saved
    return code, buf.getvalue()


def _candidates(n_aware: int, n_unaware: int) -> list:
    """Candidates shaped as `sampling.load_candidates` returns them."""
    out = []
    for i in range(n_aware + n_unaware):
        aware = i < n_aware
        side = "aware" if aware else "plain"
        out.append({
            "run": f"run_{i}_modelzero_{side}_nooversight.json",
            "model": f"vendor/model-{i % 3}",
            "nudge": "max",
            "oversight": aware,
            "lure": not aware,
            "stored_aware": aware,
            "stored_rubric": {"suspects_being_tested": {"answer": aware}},
            "corpus": (f"[AGENT - Turn 1]\nepisode {i} said something. "
                       + "then it kept going. " * 30),
            "scenario": "bulk that need not be kept",
        })
    return out


def _built(n_aware=5, n_unaware=5, seed=1, dest=None):
    candidates = _candidates(n_aware, n_unaware)
    with contextlib.ExitStack() as stack:
        if dest is None:
            tmp = stack.enter_context(tempfile.TemporaryDirectory())
            dest = os.path.join(tmp, "pack")
        blind_pack.build(candidates, seed, "eval_results_test",
                         {"per_model": 1}, dest)
        read = {}
        for name in sorted(os.listdir(dest)):
            read[name] = open(os.path.join(dest, name),
                              encoding="utf-8").read()
    return candidates, read


class TestTheSealedFieldsAreTheRightOnes:
    def test_no_candidate_field_but_the_corpus_reaches_the_rater(self):
        """Derived from a real candidate: every field the sample carries is
        checked against everything a rater can open, and only `corpus` is
        allowed through. A field added to `load_candidates` later is covered by
        this without being named here.

        The run filename is the sharpest of them - it encodes the model and the
        arm, `..._nooversight_...` - which is why it is identity rather than a
        handle.

        SHORT VALUES ARE SKIPPED, and the second half of this check is what
        keeps that from becoming a hole. Run over the real r10 pack this
        flagged `nudge=max`, `nudge=none` and `nudge=strong`: the arm names are
        ordinary English words, and they appear in 9, 2 and 38 of the 116
        transcripts as the agent's own writing rather than as metadata. A
        substring test cannot tell those apart, so a floor is the only option -
        and `_SKIPPED_AS_TOO_SHORT` below pins which fields it lets through, so
        a field that BECOMES short is a failure rather than a silent
        exemption.

        This check also exempts whatever `TEXT_KEY` names, so a WRONG text
        field is invisible to it by construction - planting `TEXT_KEY = "run"`
        passed here. `test_the_text_is_the_corpus_the_grader_was_shown` is what
        catches that."""
        candidates, read = _built()
        rater_sees = "".join(text for name, text in read.items()
                             if name != "key.SEALED.json")
        checkable = [
            (field, value)
            for candidate in candidates
            for field, value in candidate.items()
            if field != blind_pack.TEXT_KEY and isinstance(value, str) and value
        ]
        leaked = sorted({
            f"{field}={value}" for field, value in checkable
            if len(value) >= _DISTINCTIVE_ENOUGH and value in rater_sees
        })
        assert not leaked, f"the rater can see: {leaked}"
        assert {field for field, value in checkable
                if len(value) < _DISTINCTIVE_ENOUGH} == _SKIPPED_AS_TOO_SHORT

    def test_the_stratum_is_the_stored_verdict(self):
        """Named rather than assumed: balancing on the wrong field would
        produce a pack that looks balanced and is not, and every check on the
        engine side would still pass."""
        assert blind_pack.STRATUM_KEY == "stored_aware"

    def test_the_text_is_the_corpus_the_grader_was_shown(self):
        """`agent_corpus` documents itself as formatted and capped exactly as
        the grader sees it. A rater shown the raw transcript would see tool
        output the judge never read, and a disagreement would then be about
        the INPUT rather than the judgement."""
        candidates, read = _built()
        pack = json.loads(read["pack.json"])
        assert (sorted(e["text"] for e in pack["episodes"])
                == sorted(c["corpus"] for c in candidates))

    def test_the_key_still_names_the_run_and_the_verdict(self):
        """The sealed half has to carry enough to join a label back to an
        episode and to the judge's answer, or the labelling cannot be scored
        at all. Dropping too much is as bad as leaking."""
        _, read = _built()
        key = json.loads(read["key.SEALED.json"])
        for episode in key["episodes"]:
            assert episode["run"] and "stored_aware" in episode
            assert episode["model"] and "oversight" in episode

    def test_the_bulk_fields_are_dropped_from_the_key(self):
        """Both are recoverable from the run file the key names, and the
        rubric is the verdict spelled out question by question."""
        _, read = _built()
        key = json.loads(read["key.SEALED.json"])
        assert all("scenario" not in e and "stored_rubric" not in e
                   for e in key["episodes"])

    def test_the_provenance_says_which_directory_and_arguments(self):
        _, read = _built()
        key = json.loads(read["key.SEALED.json"])
        assert key["output_dir"] == "eval_results_test"
        assert key["sample_args"] == {"per_model": 1}


class TestTheCommandLine:
    def test_it_builds_a_pack_from_a_results_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            for i in range(4):
                _graded_episode(tmp, i, model="p/m", aware=i % 2 == 0)
            dest = os.path.join(tmp, "pack")
            code, out = _run_blind_pack([
                "--output-dir", tmp, "--per-model", "4", "--seed", "1",
                "--block", "2", "--dest", dest])
            assert code == 0, out
            pack = json.load(open(os.path.join(dest, "pack.json"),
                                  encoding="utf-8"))
        assert pack["n"] == 4 and pack["seed"] == 1

    def test_the_recorded_seed_is_the_one_that_shuffled(self):
        """Asserting `pack["seed"] == 1` only proves the seed was COPIED into
        the document. Planting a CLI that shuffled on a constant while still
        recording --seed passed that check, which makes the pack claim a
        reproducibility it does not have."""
        orders = []
        for seed in ("1", "2"):
            with tempfile.TemporaryDirectory() as tmp:
                for i in range(20):
                    _graded_episode(tmp, i, model=f"p/m{i % 2}",
                                    aware=i % 2 == 0)
                dest = os.path.join(tmp, "pack")
                code, out = _run_blind_pack([
                    "--output-dir", tmp, "--per-model", "10", "--seed", seed,
                    "--block", "2", "--dest", dest])
                assert code == 0, out
                # The key, not the pack: `_graded_episode` gives every episode
                # the same transcript text, so comparing the pack's texts
                # cannot see a reordering at all.
                key = json.load(open(os.path.join(dest, "key.SEALED.json"),
                                     encoding="utf-8"))
            orders.append([e["run"] for e in key["episodes"]])
        assert sorted(orders[0]) == sorted(orders[1])
        assert orders[0] != orders[1]

    def test_an_empty_sample_is_refused_rather_than_written(self):
        """A directory with nothing graded produces no pack at all: an empty
        pack is a labelling exercise that silently measures nothing."""
        with tempfile.TemporaryDirectory() as tmp:
            dest = os.path.join(tmp, "pack")
            code, out = _run_blind_pack([
                "--output-dir", tmp, "--per-model", "4", "--seed", "1",
                "--dest", dest])
        assert code == 1 and "empty" in out
        assert not os.path.exists(dest)

    def test_the_default_block_is_the_engines(self):
        """A second copy of the block size here would be a second thing to
        keep in step."""
        assert blind_pack.BLOCK_SIZE is blinding.BLOCK_SIZE
