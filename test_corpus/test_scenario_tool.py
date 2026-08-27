"""
scenario_tool.py: reading and editing the encoded scenario bundle.

WHY THIS FILE HAD NO TESTS, AND WHY THAT WAS NOT SAFE
-----------------------------------------------------
It was the only module in the project at 0% coverage - 50 statements, none of
them executed by anything. It is also the single supported way to edit the
scenario, and one of its four modes REWRITES scenario.b64 in place. A tool that
can corrupt the bundle every rollout is pinned against, with nothing exercising
it, is the wrong thing to leave uncovered.

The reason it stayed untested is real rather than an oversight: the obvious test
runs the tool, and the tool decodes the scenario. Two constraints follow, and
every test here observes both.

  - NO SCENARIO TEXT REACHES DISK OR AN ASSERTION. `load_scenario` is replaced
    with a synthetic bundle, so nothing in this file, and nothing it writes, has
    ever seen the real one. Entry NAMES are structural and appear in the tool's
    own help text; entry VALUES are the scenario and are never touched.
  - THE REAL BUNDLE IS NEVER WRITTEN. `WORKING_COPY` is redirected into a temp
    directory and `encode_scenario` is replaced with a recorder, so no test can
    reach scenario.b64 even if the tool's own guards were wrong.
"""

import contextlib
import io
import json
import sys
import tempfile
from pathlib import Path

import pytest

import scenario_tool

# Structural stand-in: the shapes the tool has to handle - a text entry, a list
# entry, and a name it has to match case-insensitively - with values that carry
# no scenario content.
#
# The invisible characters are written escaped rather than literally. A tracked
# file holding a real U+200B is a file whose diffs and greps quietly disagree
# with what a reader sees, and in a repository whose subject IS invisible
# characters that is a trap rather than a convenience.
ZERO_WIDTH = "\u200b"
CYRILLIC_ES = "\u0421"          # looks like a Latin C

SYNTHETIC = {
    "system_prompt": "placeholder text one",
    "questions": ["placeholder question", "another placeholder"],
    "MixedCaseEntry": f"placeholder with a zero-width {ZERO_WIDTH} in it",
}


class _Tool:
    """The tool wired to a synthetic bundle and a temp working copy.

    A context manager rather than a pytest fixture: run_tests.py is documented
    as a pytest-free way to run this suite and cannot interpret @pytest.fixture,
    so a fixture here would make that runner report a failure it could not
    explain. Same reason stdout is captured with redirect_stdout rather than
    capsys.
    """

    def __enter__(self):
        self.encoded = []
        self.working = Path(tempfile.mkdtemp()) / "scenario.json"
        self.out = ""
        self._saved = {
            "load_scenario": scenario_tool.load_scenario,
            "encode_scenario": scenario_tool.encode_scenario,
            "WORKING_COPY": scenario_tool.WORKING_COPY,
        }
        scenario_tool.load_scenario = lambda *a, **k: dict(SYNTHETIC)
        scenario_tool.encode_scenario = (
            lambda bundle, *a, **k: self.encoded.append(bundle))
        scenario_tool.WORKING_COPY = self.working
        self._argv = sys.argv
        return self

    def __exit__(self, *exc):
        for name, value in self._saved.items():
            setattr(scenario_tool, name, value)
        sys.argv = self._argv
        return False

    def run(self, *argv):
        """Run one invocation. Exit code returned, output kept in `self.out`."""
        sys.argv = ["scenario_tool.py", *argv]
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                return scenario_tool.main()
        finally:
            self.out = buf.getvalue()


class TestListing:
    def test_it_names_every_entry(self):
        with _Tool() as tool:
            assert tool.run("--list") == 0
            printed = tool.out
            for name in SYNTHETIC:
                assert name in printed

    def test_a_list_entry_is_reported_as_one(self):
        """A list entry and a text entry are different things to edit, so the
        listing distinguishes them rather than printing one length for both."""
        with _Tool() as tool:
            tool.run("--list")
            printed = tool.out
            assert "list[2]" in printed, printed
            assert "text" in printed

    def test_the_size_of_a_list_is_its_contents_not_its_length(self):
        """Summed characters, not the number of entries - the figure is there to
        say how much text is in there."""
        with _Tool() as tool:
            tool.run("--list")
            printed = tool.out
            total = sum(len(v) for v in SYNTHETIC["questions"])
            assert str(total) in printed, printed


class TestShow:
    def test_it_prints_a_matching_entry(self):
        with _Tool() as tool:
            assert tool.run("--show", "system") == 0
            printed = tool.out
            assert SYNTHETIC["system_prompt"] in printed

    def test_matching_is_case_insensitive(self):
        """The entry names are mixed case and a person typing one at a shell is
        not going to reproduce that."""
        with _Tool() as tool:
            assert tool.run("--show", "mixedcase") == 0
            assert "MixedCaseEntry" in tool.out

    def test_a_list_entry_prints_all_of_its_parts(self):
        with _Tool() as tool:
            assert tool.run("--show", "questions") == 0
            printed = tool.out
            for part in SYNTHETIC["questions"]:
                assert part in printed

    def test_no_match_is_an_error_that_says_what_to_try(self):
        """Exit 1, not 0. A silent success on a typo'd name reads as "that entry
        is empty" rather than "there is no such entry"."""
        with _Tool() as tool:
            assert tool.run("--show", "nosuchentry") == 1
            assert "--list" in tool.out


class TestDecode:
    def test_it_writes_a_working_copy_that_round_trips(self):
        with _Tool() as tool:
            assert tool.run("--decode") == 0
            assert json.loads(tool.working.read_text(encoding="utf-8")) == SYNTHETIC

    def test_it_says_what_to_do_next(self):
        with _Tool() as tool:
            tool.run("--decode")
            assert "--encode" in tool.out


class TestEncode:
    def _decoded(self, tool):
        tool.run("--decode")
        return json.loads(tool.working.read_text(encoding="utf-8"))

    def test_it_refuses_when_the_working_copy_is_absent(self):
        with _Tool() as tool:
            assert tool.run("--encode") == 1
            assert "--decode" in tool.out
            assert not tool.encoded, "it encoded something with no working copy"

    def test_an_unedited_round_trip_encodes_what_it_decoded(self):
        with _Tool() as tool:
            self._decoded(tool)
            assert tool.run("--encode") == 0
            assert tool.encoded == [SYNTHETIC]

    def test_an_edit_reaches_the_bundle(self):
        with _Tool() as tool:
            edited = self._decoded(tool)
            edited["system_prompt"] = "a different placeholder"
            tool.working.write_text(json.dumps(edited), encoding="utf-8")
            assert tool.run("--encode") == 0
            assert tool.encoded[0]["system_prompt"] == "a different placeholder"

    def test_a_missing_entry_is_refused_rather_than_encoded(self):
        """The guarantee that matters. An entry dropped by a bad edit would
        encode cleanly and then fail at rollout time, after the bundle on disk
        had already been overwritten."""
        with _Tool() as tool:
            edited = self._decoded(tool)
            del edited["questions"]
            tool.working.write_text(json.dumps(edited), encoding="utf-8")
            assert tool.run("--encode") == 1
            assert "questions" in tool.out
            assert not tool.encoded, "a truncated bundle was written anyway"

    def test_a_renamed_entry_is_caught_as_a_missing_one(self):
        """Renaming rather than deleting is the likelier slip, and it presents
        as the original name being absent."""
        with _Tool() as tool:
            edited = self._decoded(tool)
            edited["questiosn"] = edited.pop("questions")
            tool.working.write_text(json.dumps(edited), encoding="utf-8")
            assert tool.run("--encode") == 1
            assert not tool.encoded

    def test_a_working_copy_with_non_ascii_survives_the_round_trip(self):
        """Editing the scenario means adding invisible and confusable
        characters - they are the subject of the benchmark. Both sides of the
        round trip name utf-8; left to the locale this read raised
        UnicodeDecodeError on any non-UTF-8 machine, which is the defect class
        this project has already fixed once in the export path.
        """
        with _Tool() as tool:
            edited = self._decoded(tool)
            tricky = f"text with {ZERO_WIDTH} and {CYRILLIC_ES} in it"
            edited["system_prompt"] = tricky
            tool.working.write_text(json.dumps(edited, ensure_ascii=False),
                                    encoding="utf-8")
            assert tool.run("--encode") == 0
            assert tool.encoded[0]["system_prompt"] == tricky


class TestTheCliContract:
    def test_a_mode_is_required(self):
        """argparse exits 2 rather than falling through to --encode, which is
        the branch the function ends in."""
        with _Tool() as tool:
            with pytest.raises(SystemExit) as caught:
                tool.run()
            assert caught.value.code == 2

    def test_two_modes_at_once_are_refused(self):
        with _Tool() as tool:
            with pytest.raises(SystemExit) as caught:
                tool.run("--decode", "--list")
            assert caught.value.code == 2


class TestTheWorkingCopyCannotBeCommitted:
    def test_the_decoded_scenario_is_gitignored(self):
        """--decode writes the scenario in plaintext next to the module. The
        only thing standing between that and a commit is .gitignore, so the
        entry is checked here rather than assumed."""
        ignored = Path(".gitignore").read_text(encoding="utf-8").split()
        assert "scenario.json" in ignored

    def test_the_tool_writes_it_beside_the_module(self):
        """Where the gitignore entry expects it. A working copy written to the
        current directory instead would be untracked-but-not-ignored the moment
        the tool was run from anywhere else.

        Deliberately NOT wrapped in _Tool: that redirects WORKING_COPY into a
        temp directory, which is exactly the value this test must not see."""
        assert scenario_tool.WORKING_COPY.name == "scenario.json"
        assert (scenario_tool.WORKING_COPY.parent
                == Path(scenario_tool.__file__).parent)
