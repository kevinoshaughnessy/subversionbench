"""
The blinded suspects_misuse pack: what the rater may see, and what they may not.

WHY THIS MATTERS MORE THAN THE SAMPLING. A pack that draws a slightly odd
sample produces labels of slightly odd provenance. A pack that leaks one field
produces labels that measure the leak, and nothing downstream can tell: the
awareness labels drawn before this one were taken with the grader's own
verdict on screen, and the only reason that is known is that someone said so.

So the leak tests come first and are written against the RULE - nothing but id,
block and text reaches the rater - rather than against a list of fields
remembered at the time. A field added to the candidate later is sealed by
construction and this asserts that it is.
"""

import json
import tempfile
import unittest
from pathlib import Path

from grader_ab import misuse_pack


def _cand(run, model, misuse, near_miss=False, **extra):
    # The corpus deliberately does NOT contain the run or the model. A fixture
    # that puts an identity field inside the text makes the leak test fail on
    # the fixture rather than on the packer, which is what the first draft did.
    return {"run": run, "model": model, "nudge": "strong", "oversight": True,
            "lure": False, "screen_says_misuse": misuse,
            "screen_indicators": ["x"] if misuse else [],
            "near_miss": near_miss, "stored_aware": True,
            "corpus": f"the agent wrote something, item {abs(hash(run)) % 9999}",
            **extra}


def _pool(n_pos=12, n_neg=12, models=6):
    out = []
    for i in range(n_pos):
        out.append(_cand(f"run_pos_{i}.json", f"m{i % models}", True))
    for i in range(n_neg):
        out.append(_cand(f"run_neg_{i}.json", f"m{i % models}", False,
                         near_miss=True))
    # Plain negatives, which must never be drawn: they separate nothing.
    for i in range(20):
        out.append(_cand(f"run_plain_{i}.json", f"m{i % models}", False))
    return out


class TestTheRaterSeesTheTextAndNothingElse(unittest.TestCase):

    def _written(self, sample=None, seed=1):
        with tempfile.TemporaryDirectory() as d:
            misuse_pack.build(sample or _pool()[:12], seed, "out", d, block=4)
            return {p.name: p.read_text(encoding="utf-8")
                    for p in Path(d).iterdir()}

    def test_the_pack_carries_only_id_block_and_text(self):
        files = self._written()
        pack = json.loads(files["pack.json"])
        for ep in pack["episodes"]:
            assert set(ep) == {"id", "block", "text"}, ep

    def test_no_sealed_field_value_appears_anywhere_the_rater_reads(self):
        """The rule, not a remembered list of columns: every value the
        candidate carries other than the text must be absent from the pack
        and from every readable block.

        WHAT THIS CANNOT REACH, and no packer can: the transcript is the
        agent's own words, and an agent that names itself, or quotes its
        system prompt back, discloses something the pack went to trouble to
        seal. Blinding bounds what the HARNESS reveals; it cannot edit the
        evidence without changing what the rater is judging.
        """
        sample = _pool()[:12]
        files = self._written(sample)
        readable = "\n".join(v for k, v in files.items()
                             if k == "pack.json" or k.startswith("block_"))
        for item in sample:
            for field, value in item.items():
                if field == misuse_pack.TEXT_KEY:
                    continue
                if isinstance(value, str) and value:
                    assert value not in readable, (field, value)

    def test_the_stratum_itself_is_not_in_the_pack(self):
        """The answer the sample was balanced on is the one field whose leak
        would make a label worthless."""
        files = self._written()
        assert misuse_pack.STRATUM_KEY not in files["pack.json"]

    def test_the_key_holds_what_the_pack_drops(self):
        with tempfile.TemporaryDirectory() as d:
            sample = _pool()[:12]
            misuse_pack.build(sample, 1, "out", d, block=4)
            key = json.loads(Path(d, "key.SEALED.json").read_text())
        for ep in key["episodes"]:
            assert "run" in ep and misuse_pack.STRATUM_KEY in ep
            assert misuse_pack.TEXT_KEY not in ep

    def test_the_labels_template_arrives_blank(self):
        files = self._written()
        rows = [json.loads(x) for x in files["labels.jsonl"].splitlines()]
        assert rows and all(r["label"] is None and r["code"] is None
                            for r in rows)


class TestTheCodebookIsFrozenBeforeTheCases(unittest.TestCase):

    def test_it_is_written_into_the_pack_directory(self):
        with tempfile.TemporaryDirectory() as d:
            written = misuse_pack.build(_pool()[:12], 1, "out", d, block=4)
            assert Path(d, "codebook.txt").exists()
            assert written[0].endswith("codebook.txt"), "codebook goes first"

    def test_it_names_no_keyword_from_either_list(self):
        """A rater who knows which phrases are matched is judging the list
        rather than the episode - which is the thing the labels exist to
        check independently of the list."""
        from subversionbench.config import (EVAL_AWARENESS_INDICATORS,
                                            MISUSE_INDICATORS)
        text = misuse_pack.CODEBOOK.lower()
        named = [p for p in list(MISUSE_INDICATORS) + list(EVAL_AWARENESS_INDICATORS)
                 if p.lower() in text]
        assert not named, f"{len(named)} phrase(s) named in the codebook"

    def test_it_separates_misuse_from_evaluation_awareness(self):
        """The distinction the whole measure turns on. A codebook that does
        not draw it invites the rater to label the other construct."""
        assert "not suspecting an attack" in misuse_pack.CODEBOOK.lower()

    def test_it_allows_an_unsettled_verdict(self):
        assert "null" in misuse_pack.CODEBOOK.lower()


class TestTheDraw(unittest.TestCase):

    def test_both_sides_are_equal(self):
        got = misuse_pack.draw(_pool(), 12, seed=1, per_model=6)
        sides = [c["screen_says_misuse"] for c in got]
        assert sides.count(True) == sides.count(False) == 6

    def test_a_plain_negative_is_never_drawn(self):
        """The whole point of the negative side. A uniformly drawn negative
        contains no misuse language at all and separates no two graders."""
        got = misuse_pack.draw(_pool(), 12, seed=1, per_model=6)
        assert all(c["near_miss"] for c in got if not c["screen_says_misuse"])

    def test_no_model_dominates_a_side(self):
        got = misuse_pack.draw(_pool(), 12, seed=1, per_model=1)
        for want in (True, False):
            models = [c["model"] for c in got
                      if c["screen_says_misuse"] is want]
            assert len(models) == len(set(models)), models

    def test_it_is_deterministic_given_the_seed(self):
        a = misuse_pack.draw(_pool(), 12, seed=7, per_model=6)
        b = misuse_pack.draw(_pool(), 12, seed=7, per_model=6)
        assert [c["run"] for c in a] == [c["run"] for c in b]

    def test_a_different_seed_draws_differently(self):
        a = misuse_pack.draw(_pool(), 12, seed=7, per_model=6)
        b = misuse_pack.draw(_pool(), 12, seed=8, per_model=6)
        assert [c["run"] for c in a] != [c["run"] for c in b]

    def test_it_returns_short_rather_than_unbalancing(self):
        """A side that runs out must not be topped up from the other: a pack
        that quietly unbalances itself is what the tail marker exists for."""
        pool = [_cand(f"p{i}.json", "m", True) for i in range(10)]
        pool += [_cand("n0.json", "m", False, near_miss=True)]
        got = misuse_pack.draw(pool, 10, seed=1, per_model=10)
        sides = [c["screen_says_misuse"] for c in got]
        assert sides.count(False) == 1 and sides.count(True) == 5

    def test_an_empty_pool_draws_nothing(self):
        assert misuse_pack.draw([], 10, seed=1) == []


class TestTheNearMissRuleReadsTheBundle(unittest.TestCase):
    """The negatives are defined by the phrases the bundle records as
    REJECTED misuse candidates. Derived, so a rejection added later widens
    the pool without anyone editing this."""

    def test_the_rejected_set_is_not_empty(self):
        assert len(misuse_pack._rejected_misuse_patterns()) >= 5

    def test_every_rejected_phrase_compiles_to_a_matcher(self):
        for phrase, matcher in misuse_pack._rejected_misuse_patterns().items():
            assert matcher.search(
                misuse_pack.normalise_for_matching(f"x {phrase} y")), phrase

    def test_no_rejected_phrase_is_a_live_misuse_indicator(self):
        from subversionbench.config import MISUSE_INDICATORS
        both = set(misuse_pack._rejected_misuse_patterns()) & set(MISUSE_INDICATORS)
        assert not both


def _rejected_phrase() -> str:
    """One phrase the bundle records as a rejected misuse candidate, read at
    run time: the phrases are protocol, so no tracked file may spell one."""
    return sorted(misuse_pack._rejected_misuse_patterns())[0]


def _run_file(out, name, said=None, suspected=False, tool_said=None,
              **over):
    """A run file as the loader reads it. `said` is the agent's own text;
    `tool_said` is text only a tool result carries."""
    transcript = [{"turn": 1, "type": "text",
                   "content": said or "I recommend the second option."}]
    if tool_said:
        transcript.append({"turn": 1, "type": "tool_result",
                           "content": tool_said})
    data = {"model": "p/m", "nudge": "strong", "oversight": True,
            "lure": False, "transcript": transcript,
            "analysis": {"misuse_keywords": {
                "misuse_suspected": suspected,
                "indicators_found": ["x"] if suspected else []},
                "eval_awareness_grader": {"eval_aware": True}}}
    data.update(over)
    Path(out, name).write_text(json.dumps(data), encoding="utf-8")


class TestLoadingCandidates(unittest.TestCase):

    def _loaded(self, **kw):
        with tempfile.TemporaryDirectory() as d:
            _run_file(d, "run_1.json", **kw)
            return misuse_pack.load_misuse_candidates(d)

    def test_a_screened_episode_carries_the_screen_s_verdict(self):
        [c] = self._loaded(suspected=True)
        assert c["screen_says_misuse"] is True and c["near_miss"] is False
        assert c["screen_indicators"] == ["x"] and c["stored_aware"] is True

    def test_a_rejected_phrase_in_the_agent_s_words_is_a_near_miss(self):
        [c] = self._loaded(said=f"I notice {_rejected_phrase()} here.")
        assert c["near_miss"] is True

    def test_a_screen_positive_is_never_a_near_miss(self):
        """A near miss is a NEGATIVE the rejected phrases fire on; the same
        phrase in a positive episode says nothing about the negative side."""
        [c] = self._loaded(said=f"I notice {_rejected_phrase()} here.",
                           suspected=True)
        assert c["near_miss"] is False

    def test_a_rejected_phrase_only_in_a_tool_result_is_not_a_near_miss(self):
        """The agent's own words only, the same corpus the grader is shown:
        a phrase it merely read is not something it said."""
        [c] = self._loaded(tool_said=f"notice: {_rejected_phrase()}")
        assert c["near_miss"] is False

    def test_an_ordinary_negative_is_not_a_near_miss(self):
        [c] = self._loaded()
        assert c["near_miss"] is False

    def test_episodes_the_screen_cannot_speak_for_are_skipped(self):
        with tempfile.TemporaryDirectory() as d:
            _run_file(d, "run_1_no_transcript.json", transcript=[])
            _run_file(d, "run_2_no_model.json", model=None)
            _run_file(d, "run_3_no_screen.json", analysis={})
            _run_file(d, "run_4_unresolved.json", analysis={
                "misuse_keywords": {"misuse_suspected": None}})
            Path(d, "run_5_corrupt.json").write_text("{", encoding="utf-8")
            _run_file(d, "run_6_kept.json")
            got = misuse_pack.load_misuse_candidates(d)
        assert [c["run"] for c in got] == ["run_6_kept.json"]


class TestTheCommandLine(unittest.TestCase):

    def _main(self, *argv):
        import contextlib
        import io
        import sys
        buf, saved = io.StringIO(), sys.argv
        sys.argv = ["misuse_pack.py", *argv]
        try:
            with contextlib.redirect_stdout(buf):
                code = misuse_pack.main()
        finally:
            sys.argv = saved
        return code, buf.getvalue()

    def test_it_builds_a_pack_with_its_codebook_from_a_results_directory(self):
        with tempfile.TemporaryDirectory() as d:
            for i in range(3):
                _run_file(d, f"run_pos_{i}.json", suspected=True,
                          said=f"item {i}")
                _run_file(d, f"run_neg_{i}.json",
                          said=f"item {i}: {_rejected_phrase()}")
            dest = str(Path(d, "pack"))
            code, out = self._main("--output-dir", d, "--n", "4",
                                   "--per-model", "3", "--seed", "1",
                                   "--block", "2", "--dest", dest)
            assert code == 0, out
            assert Path(dest, "codebook.txt").exists()
            key = json.loads(Path(dest, "key.SEALED.json").read_text())
        sides = [e[misuse_pack.STRATUM_KEY] for e in key["episodes"]]
        assert sides.count(True) == sides.count(False) == 2
        assert "2 the screen calls misuse, 2 near misses" in out

    def test_an_empty_sample_is_refused_rather_than_written(self):
        with tempfile.TemporaryDirectory() as d:
            dest = str(Path(d, "pack"))
            code, out = self._main("--output-dir", d, "--seed", "1",
                                   "--dest", dest)
            assert code == 1 and "empty" in out
            assert not Path(dest).exists()
