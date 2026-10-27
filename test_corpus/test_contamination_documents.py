"""
The contamination probes pointed at another benchmark's documents.

`contamination_check.py --documents DIR` runs the same probes over every text
file under a directory, with that benchmark's own canary string and an opt-in
recognition probe. What matters is that the directory replaces the scenario
rather than joining it, that a canary of several GUIDs is probed as one string
with a control of the same shape, that a benchmark with no canary can still
earn a verdict, and that nothing identifying the benchmark is saved.
"""

import contextlib
import io
import tempfile
import uuid
from pathlib import Path

import contamination_check as cc
from subversionbench import contamination as c

LINE_A = "Threshold for batch 4471 was raised to 0.93 on the night shift"
LINE_B = "Escalation window shortened from 45 to 30 minutes after review 12"
TWO_GUIDS = f"{uuid.UUID(int=1, version=4)} {uuid.UUID(int=2, version=4)}"


def _benchmark(files: dict) -> str:
    root = tempfile.mkdtemp()
    for name, content in files.items():
        path = Path(root, name)
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_text(content, encoding="utf-8")
    return root


class TestADirectoryReplacesTheScenario:
    def test_text_files_are_read_and_the_rest_left_out(self):
        root = _benchmark({"a/email.txt": LINE_A, "b/notes.md": LINE_B,
                           ".hidden/x.txt": LINE_A, "a/.DS_Store": "x",
                           "a/blob.bin": b"\xff\xfe\x00\x81"})
        assert list(c.directory_documents(root)) == ["a/email.txt",
                                                     "b/notes.md"]

    def test_the_pattern_leaves_out_a_harness_s_metadata(self):
        root = _benchmark({"c1/email.txt": LINE_A,
                           "c1/metadata.json": '{"id": 4471}'})
        assert list(c.directory_documents(root, "*.txt")) == ["c1/email.txt"]

    def test_every_scenario_item_comes_from_the_directory(self):
        docs = {"one.txt": LINE_A, "two.txt": LINE_B}
        items = c.build_forced_choice(documents=docs)
        originals = {i["options"][i["answer_index"]]
                     for i in items if i["source"] == "scenario"}
        assert originals == {LINE_A, LINE_B}

    def test_a_line_repeated_across_conditions_is_one_item(self):
        docs = {"cond1/email.txt": LINE_A, "cond2/email.txt": LINE_A}
        assert len(c.scenario_lines(documents=docs)) == 1

    def test_a_document_repeated_across_conditions_is_cut_once(self):
        text = " ".join(f"word{i}" for i in range(60))
        docs = {"cond1/email.txt": text, "cond2/email.txt": text}
        scenario = [x for x in c.build_continuations(documents=docs)
                    if x["source"] == "scenario"]
        assert len(scenario) == 1


class TestAnotherBenchmarksCanary:
    LEAD = "We include the following canary string: "

    def test_every_guid_but_the_last_is_given_and_the_last_is_asked_for(self):
        real, _ = c.canary_prompts(TWO_GUIDS, lead=self.LEAD)
        first, last = TWO_GUIDS.split()
        prompt = c.canary_prompt(real)
        assert self.LEAD + first + " " + last[:9] in prompt
        assert last[9:] not in prompt
        assert c.score_canary(real, last[9:])["hit"]

    def test_the_control_has_as_many_guids_and_none_of_the_real_ones(self):
        real, control = c.canary_prompts(TWO_GUIDS, lead=self.LEAD)
        shown = c._GUID_RE.findall(control["prefix"])
        assert len(shown) == 1 and shown[0] not in TWO_GUIDS
        assert control["guid"] not in TWO_GUIDS
        assert not c.score_canary(real, control["guid"])["hit"]

    def test_this_benchmarks_canary_is_still_asked_as_before(self):
        real, _ = c.canary_prompts()
        assert c.canary_prompt(real).endswith(
            "subversionbench canary GUID " + c.CANARY_GUID[:9])

    def test_a_canary_with_no_guid_is_refused(self):
        try:
            c.canary_prompts("not a guid")
        except ValueError:
            return
        raise AssertionError("a canary string with no GUID was accepted")


class TestRecognition:
    def test_a_term_counts_as_a_whole_word_in_any_case(self):
        assert c.score_recognition("From Lynch et al.", ["lynch"])["named"]
        assert not c.score_recognition("a lynching", ["lynch"])["named"]

    def test_a_decline_is_told_apart_from_a_wrong_name(self):
        assert c.score_recognition("UNKNOWN", ["lynch"])["declined"]
        assert not c.score_recognition("Some paper", ["lynch"])["declined"]

    def test_excerpts_are_spread_and_the_control_comes_last(self):
        words = " ".join(f"w{i}" for i in range(40))
        docs = {f"d{i}.txt": f"doc{i} {words}" for i in range(10)}
        items = c.build_recognition(documents=docs, limit=3)
        assert [i["source"] for i in items] == ["scenario"] * 3 + ["control"]
        assert len({i["document"] for i in items}) == 4

    def test_naming_only_the_real_source_is_a_signal(self):
        named = [{"source": "scenario", "named": True},
                 {"source": "control", "named": False}]
        summary = c.summarise_contamination([], [], [], recognition=named)
        assert any("named the source" in s for s in summary["signals"])
        both = [{"source": "scenario", "named": True},
                {"source": "control", "named": True}]
        assert not any("named the source" in s for s in
                       c.summarise_contamination([], [], [],
                                                 recognition=both)["signals"])

    def test_without_the_probe_the_summary_is_as_before(self):
        assert "recognition" not in c.summarise_contamination([], [], [])

    def test_the_terms_are_counted_and_never_saved(self):
        items = c.build_recognition(documents={"d.txt": " ".join(
            f"w{i}" for i in range(40))})
        original = cc.ask
        cc.ask = lambda *a, **k: ("This is from the Zephyrine study.", None)
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                results = cc._probe_recognition(None, "m", items,
                                                ["Zephyrine"], 0, False)
        finally:
            cc.ask = original
        assert results[0]["named"] and results[0]["terms_named"] == 1
        assert "Zephyrine" not in repr(results)


class TestAVerdictWithoutACanary:
    @staticmethod
    def _items(n=12):
        return [{"source": s, "correct": False} for s in ("scenario", "control")
                for _ in range(n)]

    def test_enough_items_and_no_canary_to_ask_is_no_evidence(self):
        summary = c.summarise_contamination(self._items(), [], [],
                                            canary_expected=False)
        assert summary["verdict"] == "no evidence"

    def test_a_canary_that_was_expected_and_never_answered_still_counts(self):
        assert c.summarise_contamination(self._items(), [], [])[
            "verdict"] == "inconclusive"


class TestTheFlagsAreRefusedBeforeAnyCall:
    @staticmethod
    def _refused(argv):
        parser = cc._parser()
        args = parser.parse_args(["--models", "m", *argv])
        try:
            with contextlib.redirect_stderr(io.StringIO()):
                cc._probe_inputs(args, parser)
        except SystemExit:
            return True
        return False

    def test_a_canary_without_documents(self):
        assert self._refused(["--canary", TWO_GUIDS])

    def test_a_directory_that_does_not_exist(self):
        assert self._refused(["--documents", "/no/such/benchmark"])

    def test_a_pattern_that_matches_nothing(self):
        root = _benchmark({"a.txt": LINE_A})
        assert self._refused(["--documents", root, "--documents-glob", "*.md"])

    def test_a_canary_with_no_guid(self):
        root = _benchmark({"a.txt": LINE_A})
        assert self._refused(["--documents", root, "--canary", "none here"])

    def test_a_good_directory_is_accepted(self):
        root = _benchmark({"a.txt": LINE_A})
        assert not self._refused(["--documents", root, "--canary", TWO_GUIDS,
                                  "--recognition-terms", "x"])
