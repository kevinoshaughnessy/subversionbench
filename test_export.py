"""
Redacting a results directory for publication, and refusing to publish a dirty one.

The corpus keeps its real paths, because re-interrogating a saved episode needs the
bytes the model actually saw. The archive is the only thing that leaves the machine,
so the archive is what gets cleaned - and the check runs on the unpacked archive
rather than on the staging copy, so it tests what is actually published.
"""

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
        Two hand-maintained lists would drift, and the drift would ship."""
        derived = {needle for needle, _ in leak_patterns()}
        for real, _ in path_substitutions():
            assert real in derived
        if USERNAME:
            assert USERNAME in derived

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
