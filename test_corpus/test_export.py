"""
Redacting a results directory for publication.

The transcripts hold the full scenario and every host path the model was shown,
so the question is not whether the redactor rewrote something: it is whether
anything it did not rewrite can still name the machine. The source directory is
never touched, and nothing is silently left out of the copy.
"""


import contextlib
import io
import json
import os
import tempfile
from pathlib import Path

import pytest

from subversionbench.config import OPERATOR_DISPLAY_NAME
from subversionbench.export import (ExportRefused, find_leaks, leak_patterns,
                                    main, redact_tree)
from subversionbench.redaction import _operator_username, path_substitutions

HOST_PATH = path_substitutions()[0][0]
USERNAME = _operator_username()


def _corpus(**extra):
    """A results directory holding one run file with host identifiers in it."""
    d = tempfile.mkdtemp(prefix="eval_results_test_")
    run = {
        "model": "m", "nudge": "strong",
        "transcript": [{"turn": 1, "type": "tool_result",
                        "result": f"drwxr-xr-x 8 {USERNAME} staff {HOST_PATH}/x"}],
        # the API conversation, which is what leaks today: it holds the RAW tool
        # result because replay needs the paths the shell really reported
        "messages": [{"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t1",
             "content": f"-rw-r--r-- 1 {USERNAME} staff 671 {HOST_PATH}/env"}]}],
        "analysis": {"nested": {"deep": [f"{HOST_PATH}/deeper"]}},
    }
    run.update(extra)
    Path(d, "run_1_m_strong_20260101T000000.json").write_text(json.dumps(run))
    Path(d, "summary_m_strong_20260101T000000.json").write_text(
        json.dumps({"model": "m", "note": f"built in {HOST_PATH}"}))
    return d


class TestTheSourceIsNeverTouched:
    def test_redacting_leaves_the_corpus_alone(self):
        """The corpus is where replay reads from. Cleaning it would make every
        re-interrogation a different conversation from the one it reproduces."""
        src = _corpus()
        before = Path(src, "run_1_m_strong_20260101T000000.json").read_text()
        redact_tree(src, tempfile.mkdtemp())
        assert Path(src, "run_1_m_strong_20260101T000000.json").read_text() == before
        assert USERNAME in before

    def test_the_copy_lands_under_the_original_name(self):
        """zip runs from inside the staging dir, so the entry names have to be
        `eval_results_x/...` for unzip to recreate the directory."""
        src = _corpus()
        into = tempfile.mkdtemp()
        redact_tree(src, into)
        assert os.path.isdir(os.path.join(into, os.path.basename(src)))


class TestEveryPlaceAHostIdentifierHides:
    def _redacted(self):
        src = _corpus()
        into = tempfile.mkdtemp()
        redact_tree(src, into)
        return Path(into, os.path.basename(src))

    def test_the_transcript_is_clean(self):
        run = json.loads((self._redacted() /
                          "run_1_m_strong_20260101T000000.json").read_text())
        text = json.dumps(run["transcript"])
        assert USERNAME not in text and HOST_PATH not in text
        assert OPERATOR_DISPLAY_NAME in text

    def test_the_saved_conversation_is_clean(self):
        """The one that actually leaks today. `messages` was added for phrasing
        replay and holds the raw tool result by design."""
        run = json.loads((self._redacted() /
                          "run_1_m_strong_20260101T000000.json").read_text())
        text = json.dumps(run["messages"])
        assert USERNAME not in text and HOST_PATH not in text

    def test_nesting_does_not_hide_one(self):
        """Redaction walks values rather than substituting over the encoded text, so
        depth is irrelevant - which is what stops a field nobody thought about from
        keeping its path."""
        run = json.loads((self._redacted() /
                          "run_1_m_strong_20260101T000000.json").read_text())
        assert HOST_PATH not in json.dumps(run["analysis"])

    def test_summaries_are_redacted_too(self):
        assert HOST_PATH not in (self._redacted() /
                                 "summary_m_strong_20260101T000000.json").read_text()

    def test_an_unparseable_file_is_redacted_as_text_not_dropped(self):
        """A truncated run file is still data. Dropping it would quietly shrink the
        archive; shipping it raw would leak."""
        src = _corpus()
        Path(src, "run_2_broken.json").write_text(f"{{oops {USERNAME} {HOST_PATH}")
        into = tempfile.mkdtemp()
        counts = redact_tree(src, into)
        assert counts["unreadable"] == 1
        out = Path(into, os.path.basename(src), "run_2_broken.json").read_text()
        assert USERNAME not in out and HOST_PATH not in out


class TestTheVerifierAgreesWithTheRedactorByConstruction:
    def test_the_patterns_are_derived_not_restated(self):
        """A substitution added to path_substitutions is checked for automatically.
        Two hand-maintained lists would drift, and the drift would ship.

        Every real path except one the redactor would produce anyway; see
        test_a_placeholder_is_never_itself_a_needle for why that exception is not
        a hole.
        """
        derived = {needle for needle, _ in leak_patterns()}
        produced = {placeholder for _, placeholder in path_substitutions()}
        for real, _ in path_substitutions():
            if real in produced:
                continue
            assert real in derived
        if USERNAME:
            assert USERNAME in derived

    def test_a_placeholder_is_never_itself_a_needle(self, monkeypatch):
        """The placeholders are what successful redaction writes, so a needle
        equal to one fires on correct output and can never indicate a leak.

        The collision is forced rather than waited for. tempfile.gettempdir() is
        "/tmp" on Linux and the temp placeholder is "/tmp" too, so the real pair
        substitutes a string for itself and every correctly redacted export was
        reported as leaking there. On macOS gettempdir() sits under /var/folders
        and the collision cannot arise at all, so the substitutions are supplied
        here instead of taken from the host, and the rule is checked on both.
        """
        import subversionbench.export as export
        monkeypatch.setattr(export, "path_substitutions",
                            lambda *a, **k: [("/host/private", "~"),
                                             ("/tmp", "/tmp")])
        needles = {needle for needle, _ in export.leak_patterns()}
        assert "/host/private" in needles, (
            "a real host path must still be checked for")
        assert "/tmp" not in needles, (
            "the redactor's own placeholder was treated as a host path, so "
            "correctly redacted output reads as a leak")

    def test_it_finds_a_leak_in_any_file_type(self):
        d = tempfile.mkdtemp()
        Path(d, "anything.txt").write_text(f"owner {USERNAME}")
        assert find_leaks(d)

    def test_a_redacted_tree_verifies_clean(self):
        src = _corpus()
        into = tempfile.mkdtemp()
        redact_tree(src, into)
        assert find_leaks(into) == []

    def test_an_unredacted_tree_does_not(self):
        assert find_leaks(_corpus())


class TestTheCliContract:
    def test_verify_exits_nonzero_on_a_leak(self):
        """zip.sh keys off the exit code to delete the archive rather than ship it."""
        assert main(["--verify", _corpus()]) == 1

    def test_verify_exits_zero_when_clean(self):
        src = _corpus()
        into = tempfile.mkdtemp()
        redact_tree(src, into)
        assert main(["--verify", into]) == 0

    def test_redacting_requires_both_paths(self):
        import pytest
        with pytest.raises(SystemExit):
            main(["--dir", "somewhere"])


class TestNothingIsSilentlyLeftOut:
    """An incomplete archive that reports success is worse than a failed build.

    The first version skipped directories while zip.sh counted files with a recursive
    `find`, so a nested file could vanish from the archive behind a reassuring
    message.
    """

    def test_a_nested_file_reaches_the_archive(self):
        src = _corpus()
        os.makedirs(os.path.join(src, "nested"))
        Path(src, "nested", "run_2.json").write_text(
            json.dumps({"result": f"{HOST_PATH}/deep"}))
        into = tempfile.mkdtemp()
        redact_tree(src, into)
        nested = Path(into, os.path.basename(src), "nested", "run_2.json")
        assert nested.exists(), "a nested file was dropped from the staged copy"
        assert HOST_PATH not in nested.read_text(), "and it was not redacted"

    def test_what_landed_is_checked_against_what_was_walked(self):
        """Counted off disk, not off the loop's own bookkeeping. A counter beside each
        write only proves the code meant to write."""
        src = _corpus()
        into = tempfile.mkdtemp()
        counts = redact_tree(src, into)
        staged = [p for p in Path(into).rglob("*") if p.is_file()]
        assert counts["seen"] == len(staged) > 0

    def test_an_incomplete_copy_refuses_rather_than_returning(self):
        """If a future branch stops writing a file it walked, the staged copy must not
        be archived. Simulated by making the walk see one more file than it writes."""
        import subversionbench.export as export
        src = _corpus()
        original = export.shutil.copy2

        def skip_one(s, d):
            if s.endswith(".keep"):
                return None          # walked, deliberately not written
            return original(s, d)

        Path(src, "notes.keep").write_text("x")
        export.shutil.copy2 = skip_one
        try:
            with pytest.raises(ExportRefused, match="incomplete"):
                redact_tree(src, tempfile.mkdtemp())
        finally:
            export.shutil.copy2 = original


class TestALinkOutOfTheTreeIsRefused:
    """This module decides what leaves the machine, so it does not resolve links."""

    def _with_link(self):
        src = _corpus()
        outside = tempfile.mkdtemp()
        Path(outside, "private.txt").write_text("SENSITIVE-OUTSIDE-DATA")
        os.symlink(os.path.join(outside, "private.txt"),
                   os.path.join(src, "leaked.json"))
        return src

    def test_it_refuses_rather_than_following(self):
        with pytest.raises(ExportRefused, match="symbolic link"):
            redact_tree(self._with_link(), tempfile.mkdtemp())

    def test_the_target_content_never_reaches_the_staging_copy(self):
        src, into = self._with_link(), tempfile.mkdtemp()
        try:
            redact_tree(src, into)
        except ExportRefused:
            pass
        staged = " ".join(p.read_text(errors="replace")
                          for p in Path(into).rglob("*") if p.is_file())
        assert "SENSITIVE-OUTSIDE-DATA" not in staged

    def test_it_refuses_rather_than_skipping(self):
        """Silently dropping the link would repeat the subdirectory mistake: the
        archive would build, and nobody would know something was omitted."""
        assert main(["--dir", self._with_link(), "--into", tempfile.mkdtemp()]) == 1

    def test_a_symlinked_directory_is_refused_too(self):
        src = _corpus()
        outside = tempfile.mkdtemp()
        Path(outside, "x.json").write_text("{}")
        os.symlink(outside, os.path.join(src, "linked_dir"))
        with pytest.raises(ExportRefused, match="symbolic link"):
            redact_tree(src, tempfile.mkdtemp())


class TestTheStagingRunReportsWhatItDid:
    """--dir/--into is the half of the CLI that WRITES the archive, and its
    success path had never run: nothing had asserted the counts it prints or
    that it exits zero, which is what zip.sh reads."""

    def test_a_successful_staging_exits_zero_and_counts_the_files(self):
        src = _corpus()
        into = tempfile.mkdtemp()
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = main(["--dir", src, "--into", into])
        text = buf.getvalue()
        assert code == 0, text
        assert "redacted" in text and "JSON file(s)" in text
        assert os.listdir(into), "nothing reached the staging directory"

    def test_other_files_are_reported_separately_from_json(self):
        """A copied file was not redacted, so the two counts answer different
        questions: how much was rewritten, and how much went through
        untouched."""
        src = _corpus()
        Path(src, "notes.txt").write_text("nothing host-specific here\n")
        into = tempfile.mkdtemp()
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            main(["--dir", src, "--into", into])
        assert "other file(s) copied" in buf.getvalue()

    def test_a_refusal_while_staging_exits_non_zero(self):
        """zip.sh keys off the exit code to delete the archive rather than
        ship it, so a refusal that exited zero would publish the thing the
        refusal exists to stop."""
        import subversionbench.export as export
        src = _corpus()
        into = tempfile.mkdtemp()
        real = export.redact_tree
        try:
            def _refuse(*a, **k):
                raise export.ExportRefused("a field was not walked")
            export.redact_tree = _refuse
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = export.main(["--dir", src, "--into", into])
        finally:
            export.redact_tree = real
        assert code == 1
        assert "REFUSING TO STAGE" in buf.getvalue()
        assert "a field was not walked" in buf.getvalue()

    def test_a_long_list_of_leaks_is_truncated_and_counted(self):
        """Ten are shown and the rest are counted. Cutting the tail silently
        would let an operator fix what is on screen and rebuild into the
        same refusal, with no idea how much was left."""
        src = _corpus()
        for i in range(14):
            Path(src, f"run_leak_{i}.json").write_text(
                json.dumps({"result": f"{HOST_PATH}/leak{i}"}))
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = main(["--verify", src])
        text = buf.getvalue()
        assert code == 1
        assert "REFUSING TO PUBLISH" in text
        assert "... and " in text and "more" in text
        shown = [ln for ln in text.splitlines() if ln.strip().startswith("run_")]
        assert len(shown) <= 10, f"{len(shown)} files listed, expected at most 10"
