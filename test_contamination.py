"""
Tests for contamination detection.

A contamination probe is a measuring instrument pointed at the benchmark's own
validity, so the failure that matters is not "it crashed" but "it returned a
clean verdict it had not earned". These tests are weighted accordingly: most of
them try to make a probe report cleanliness when it should not, or report
contamination when a control explains it.
"""

import json
import tempfile
from pathlib import Path

import subversionbench.contamination as cont
from subversionbench.scenario import SCENARIO


def _clean_summary(**kw):
    return cont.summarise_contamination(kw.get("fc", []), kw.get("canary", []),
                                        kw.get("cont", []), k=kw.get("k", 4))


class TestLeakAudit:
    """The only probe that finds exposure while it can still be fixed. It runs
    against the repository, so what it must never do is miss a quotation
    because of how the file happens to be wrapped."""

    def test_a_pasted_sentence_is_found(self):
        stolen = " ".join(SCENARIO["internal_memo"].split()[:20])
        found = cont.audit_text(f"Some prose. {stolen} More prose.")
        assert found.get("internal_memo", 0) > 0

    def test_unrelated_text_is_not_flagged(self):
        assert cont.audit_text(
            "The quick brown fox jumps over the lazy dog, repeatedly and "
            "with some enthusiasm, for eight or more words.") == {}

    def test_a_quotation_wrapped_across_lines_is_found(self):
        """The bug this replaced scanned line by line, so a comment reflowed
        across two lines read as clean - which is the commonest shape of leak
        in a source file."""
        words = SCENARIO["internal_memo"].split()[:24]
        wrapped = "# " + " ".join(words[:8]) + "\n# " + " ".join(words[8:16]) \
                  + "\n# " + " ".join(words[16:])
        out = tempfile.mkdtemp()
        path = Path(out) / "leaky.py"
        path.write_text(wrapped)
        found = cont.audit_file(path)
        assert found, "a wrapped quotation must still be found"
        assert found["lines"], "must report where it is"

    def test_the_bundle_itself_is_skipped(self):
        """scenario.b64 holds the scenario by design; flagging it would bury
        the findings that matter under the one that does not."""
        report = cont.audit_paths(["subversionbench/scenario.b64"])
        assert report["findings"] == []
        assert report["files_audited"] == 0

    def test_the_report_contains_no_scenario_text(self):
        """The audit runs in terminals and CI logs. Printing the leak in order
        to report the leak would put it somewhere new."""
        stolen = " ".join(SCENARIO["internal_memo"].split()[:20])
        out = tempfile.mkdtemp()
        path = Path(out) / "leaky.md"
        path.write_text(stolen)
        serialised = json.dumps(cont.audit_file(path))
        for word in SCENARIO["internal_memo"].split()[:20]:
            if len(word) > 6:
                assert word.lower() not in serialised.lower(), (
                    f"{word!r} leaked into the audit report")

    def test_an_unreadable_file_is_skipped_not_fatal(self):
        out = tempfile.mkdtemp()
        binary = Path(out) / "blob.bin"
        binary.write_bytes(b"\x00\xff\xfe" * 100)
        assert cont.audit_file(binary) == {}
        assert cont.audit_file(Path(out) / "does_not_exist") == {}

    def test_this_repository_reproduces_no_scenario_text(self):
        """
        The audit, pointed at the thing it exists to protect.

        Every other test here checks that the audit COULD find a leak. None
        checked whether there was one, so the audit only ran when somebody
        remembered to run it - and it had not been run since v40. When it was,
        it found four shingles of the internal memo quoted in config.py, in a
        comment explaining a clause-boundary repair. Tracked, and therefore in
        the next crawl.

        The scenario ships base64-encoded so its text stays out of plain source;
        a comment reproducing it defeats that as completely as committing the
        plaintext would. This is the guard that makes the encoding worth having.

        Skipped rather than failed outside a git checkout: the file list comes
        from `git ls-files`, and an installed copy has no index to read.
        """
        import subprocess

        try:
            out = subprocess.run(["git", "ls-files"], capture_output=True,
                                 text=True, timeout=30)
        except (OSError, subprocess.SubprocessError):
            import pytest
            pytest.skip("git is not available")
        if out.returncode != 0 or not out.stdout.strip():
            import pytest
            pytest.skip("not a git checkout")

        paths = [p for p in out.stdout.splitlines() if p]
        report = cont.audit_paths(paths)
        # Paths only. Naming the shingles would print the leak in order to
        # report it, which is the mistake test_the_report_contains_no_scenario
        # _text exists to prevent.
        leaks = [(f["path"], f["shingles"]) for f in report["findings"]]
        assert not leaks, (
            f"these tracked files reproduce scenario text: {leaks}. "
            f"Paraphrase the quotation or move it into the bundle.")

    def test_findings_are_worst_first(self):
        out = tempfile.mkdtemp()
        words = SCENARIO["internal_memo"].split()
        small = Path(out) / "small.md"
        small.write_text(" ".join(words[:10]))
        large = Path(out) / "large.md"
        large.write_text(" ".join(words[:60]))
        report = cont.audit_paths([small, large])
        assert [f["path"] for f in report["findings"]] == [str(large), str(small)]


class TestControlDocument:
    """The control is what makes a positive forced-choice result mean anything.
    If it shared text with the scenario, contamination would show up in both
    arms and cancel in the gap - the probe would report cleanliness precisely
    when the model was dirtiest."""

    def test_the_control_shares_no_text_with_the_scenario(self):
        for seed in range(5):
            assert cont.audit_text(cont.control_document(seed)) == {}

    def test_the_control_is_deterministic(self):
        assert cont.control_document(3) == cont.control_document(3)

    def test_different_seeds_give_different_controls(self):
        assert cont.control_document(0) != cont.control_document(1)

    def test_the_control_supplies_forced_choice_material(self):
        """Same shape as the scenario, or the two arms are different puzzles
        and the comparison is not like-for-like."""
        assert len(cont.distinctive_lines(cont.control_document(0))) >= 5

    def test_the_control_grows_to_the_size_asked_for(self):
        for wanted in (5, 20, 40):
            assert len(cont.distinctive_lines(
                cont.control_document(0, lines_wanted=wanted))) >= wanted


class TestForcedChoice:
    """The quantitative core: a known null, and no requirement that the model
    emit scenario text."""

    def _items(self, **kw):
        return cont.build_forced_choice(k=kw.get("k", 4), seed=kw.get("seed", 0),
                                        limit=kw.get("limit", 4))

    def test_items_are_deterministic_for_a_seed(self):
        assert self._items() == self._items()

    def test_a_different_seed_gives_different_items(self):
        assert self._items(seed=1) != self._items(seed=2)

    def test_exactly_one_option_is_the_original(self):
        for item in self._items():
            assert len(set(item["options"])) == len(item["options"])
            assert 0 <= item["answer_index"] < len(item["options"])

    def test_decoys_differ_from_the_original_only_in_digits(self):
        """A decoy that differed in a word would let a model win on register
        rather than recall, which is not what is being measured."""
        for item in self._items():
            answer = item["options"][item["answer_index"]]
            for i, option in enumerate(item["options"]):
                if i == item["answer_index"]:
                    continue
                assert option != answer
                strip = lambda s: "".join(c for c in s if not c.isdigit())
                assert strip(option) == strip(answer), (
                    "decoys must be format-identical to the original")

    def test_both_arms_are_present_and_balanced(self):
        items = self._items(limit=4)
        by_source = {}
        for item in items:
            by_source[item["source"]] = by_source.get(item["source"], 0) + 1
        assert by_source["scenario"] == by_source["control"]

    def test_no_limit_uses_every_scenario_line(self):
        """The arms are zipped, so a control smaller than the scenario silently
        truncates the scenario arm. That shipped once: the probe reported
        building 35 items and measured 4."""
        available = sum(len(cont.distinctive_lines(SCENARIO[key]))
                        for key in cont.SCENARIO_DOCUMENTS if key in SCENARIO)
        items = cont.build_forced_choice(k=4, seed=0)
        scenario_items = [i for i in items if i["source"] == "scenario"]
        assert len(scenario_items) == available, (
            f"{len(scenario_items)} of {available} scenario lines used")

    def test_k_controls_the_number_of_options(self):
        for k in (2, 3, 5):
            for item in cont.build_forced_choice(k=k, seed=0, limit=2):
                assert len(item["options"]) == k

    def test_the_prompt_shows_every_option_once(self):
        item = self._items()[0]
        prompt = cont.forced_choice_prompt(item)
        for option in item["options"]:
            assert prompt.count(option) == 1

    def test_scoring(self):
        item = self._items()[0]
        assert cont.score_forced_choice(item, item["answer_index"] + 1) is True
        wrong = (item["answer_index"] + 1) % len(item["options"]) + 1
        assert cont.score_forced_choice(item, wrong) is False
        # Unparseable is None, never False: a refusal is not a wrong answer,
        # and counting it as one would drag the arm towards chance.
        for bad in (None, "", "banana", 0, 99, [1]):
            assert cont.score_forced_choice(item, bad) is None


class TestCanary:
    """Near-zero false positive rate is the whole value of this probe, and it
    depends entirely on the control."""

    def test_the_real_and_control_probes_differ(self):
        real, control = cont.canary_prompts()
        assert real["guid"] != control["guid"]
        assert real["prefix"] != control["prefix"]
        assert real["prefix"] + real["suffix"] == real["guid"]

    def test_the_prompt_withholds_the_answer(self):
        real, _ = cont.canary_prompts()
        assert real["suffix"] not in cont.canary_prompt(real)

    def test_a_completed_suffix_is_a_hit(self):
        real, _ = cont.canary_prompts()
        assert cont.score_canary(real, real["suffix"])["hit"] is True

    def test_a_restated_guid_is_a_hit(self):
        """Models often answer with the whole identifier rather than continuing
        the string; that is recall too."""
        real, _ = cont.canary_prompts()
        scored = cont.score_canary(real, f"That looks like {real['guid']}.")
        assert scored["guid_match"] is True and scored["hit"] is True

    def test_a_refusal_is_not_a_hit(self):
        real, _ = cont.canary_prompts()
        scored = cont.score_canary(real, "UNKNOWN")
        assert scored["hit"] is False and scored["declined"] is True

    def test_a_wrong_guid_is_not_a_hit(self):
        real, _ = cont.canary_prompts()
        scored = cont.score_canary(real, "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
        assert scored["hit"] is False


class TestContinuation:
    def test_overlap_is_one_for_an_exact_reproduction(self):
        text = "alpha beta gamma delta epsilon zeta eta theta iota"
        assert cont.continuation_overlap(text, text) == 1.0

    def test_overlap_is_zero_for_unrelated_text(self):
        assert cont.continuation_overlap(
            "alpha beta gamma delta epsilon zeta",
            "nothing here matches at all whatsoever") == 0.0

    def test_padding_does_not_reduce_overlap(self):
        """Recall, not precision: a correct reproduction wrapped in commentary
        has still reproduced it."""
        text = "alpha beta gamma delta epsilon zeta"
        assert cont.continuation_overlap(
            text, f"Certainly! Here it is: {text} Let me know if...") == 1.0

    def test_the_prompt_withholds_the_continuation(self):
        for item in cont.build_continuations():
            prompt = cont.continuation_prompt(item)
            assert item["given"] in prompt
            assert item["expected"] not in prompt

    def test_both_arms_are_built(self):
        sources = {c["source"] for c in cont.build_continuations()}
        assert sources == {"scenario", "control"}


class TestVerdict:
    """Where a wrong answer does the most damage: this is the line a reader
    will quote."""

    def _fc(self, scenario_hits, scenario_n, control_hits, control_n):
        out = []
        for source, hits, n in (("scenario", scenario_hits, scenario_n),
                                ("control", control_hits, control_n)):
            out += [{"source": source, "correct": i < hits} for i in range(n)]
        return out

    def _canary(self, real_hit, control_hit=False):
        return [{"source": "real", "hit": real_hit, "declined": False},
                {"source": "control", "hit": control_hit, "declined": False}]

    def test_a_completed_canary_is_decisive(self):
        s = _clean_summary(canary=self._canary(True))
        assert s["verdict"] == "contaminated"
        assert any("canary completed" == sig for sig in s["signals"])

    def test_a_canary_hit_with_a_control_hit_is_not_contamination(self):
        """A model that completes a GUID nobody has ever published is
        generating hex. Reading that as contamination would condemn a clean
        model on the strength of its own confabulation."""
        s = _clean_summary(canary=self._canary(True, control_hit=True))
        assert s["verdict"] != "contaminated"
        assert any("generating GUIDs" in sig for sig in s["signals"])

    def test_beating_the_control_is_suspected_not_confirmed(self):
        s = _clean_summary(fc=self._fc(80, 100, 25, 100),
                           canary=self._canary(False))
        assert s["verdict"] == "suspected"
        assert s["forced_choice"]["p_vs_control"] < 0.05

    def test_matching_the_control_is_no_evidence(self):
        """Both arms above chance is a plausibility bias, not memorisation.
        This is the case the control exists for."""
        s = _clean_summary(fc=self._fc(45, 100, 43, 100),
                           canary=self._canary(False))
        assert s["verdict"] == "no evidence"

    def test_chance_performance_is_no_evidence(self):
        s = _clean_summary(fc=self._fc(25, 100, 24, 100),
                           canary=self._canary(False))
        assert s["verdict"] == "no evidence"

    def test_a_significant_but_tiny_gap_is_not_a_signal(self):
        """At large n a 2-point gap reaches significance while meaning nothing
        about memorisation; the effect-size floor is what stops that being
        reported as contamination."""
        s = _clean_summary(fc=self._fc(2700, 10000, 2500, 10000),
                           canary=self._canary(False))
        assert s["verdict"] == "no evidence"

    def test_unscored_items_stay_out_of_the_denominator(self):
        fc = self._fc(10, 20, 5, 20) + [
            {"source": "scenario", "correct": None} for _ in range(30)]
        s = _clean_summary(fc=fc, canary=self._canary(False))
        assert s["forced_choice"]["scenario"]["n"] == 20

    def test_an_empty_run_is_inconclusive_not_clean(self):
        """The worst output this module could produce is a clean bill of health
        issued on no data, because it is indistinguishable from the good news it
        is not. A run whose every call failed once reported 'no evidence'."""
        s = _clean_summary()
        assert s["verdict"] == "inconclusive"
        assert s["forced_choice"]["scenario"]["n"] == 0
        assert s["caveats"], "a negative must ship with what it cannot rule out"

    def test_a_run_where_every_call_failed_is_inconclusive(self):
        fc = [{"source": s, "correct": None, "error": "401 unauthorized"}
              for s in ("scenario", "control") for _ in range(20)]
        canary = [{"source": s, "hit": False, "declined": False,
                   "error": "401 unauthorized"} for s in ("real", "control")]
        s = cont.summarise_contamination(fc, canary, [], k=4)
        assert s["verdict"] == "inconclusive"
        assert s["n_errors"] == 42
        assert any("too little evidence" in sig for sig in s["signals"])

    def test_too_few_items_is_inconclusive_even_without_errors(self):
        s = _clean_summary(fc=self._fc(2, 4, 1, 4), canary=self._canary(False))
        assert s["verdict"] == "inconclusive"

    def test_a_canary_hit_still_decides_when_the_rest_failed(self):
        """A completed canary needs no corroboration; refusing to report it
        because the forced-choice arm errored would discard the strongest
        evidence the module can obtain."""
        s = _clean_summary(canary=self._canary(True))
        assert s["verdict"] == "contaminated"

    def test_the_verdict_carries_no_scenario_text(self):
        s = _clean_summary(fc=self._fc(80, 100, 25, 100),
                           canary=self._canary(True))
        assert cont.audit_text(json.dumps(s)) == {}
