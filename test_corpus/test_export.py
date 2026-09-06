"""
Redacting a results directory for publication, and refusing to publish a dirty one.

The corpus keeps its real paths, because re-interrogating a saved episode needs the
bytes the model actually saw. The archive is the only thing that leaves the machine,
so the archive is what gets cleaned - and the check runs on the unpacked archive
rather than on the staging copy, so it tests what is actually published.
"""

import json
import contextlib
import io
import inspect
import os
import sys
import re
import tempfile
import conftest
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


class TestContentThatRedactionCannotRewrite:
    """The identifier check answers "did the redactor miss something it knows about".

    It cannot answer anything about a value that is not in path_substitutions, because
    it does not look for one - so a run file holding a token verified clean. This class
    covers the second question, and the different remedy: such a value is refused
    rather than rewritten, because there is nothing to rewrite it to.
    """

    def _archive(self, *results):
        d = tempfile.mkdtemp(prefix="eval_results_content_")
        Path(d, "run_1_m_strong_20260101T000000.json").write_text(json.dumps(
            {"transcript": [{"turn": 1, "type": "tool_result", "result": r}
                            for r in results]}))
        return d

    def test_a_credential_is_found(self):
        from subversionbench.export import find_content_risks
        risks = find_content_risks(
            self._archive("api_token=NOT-A-REAL-TOKEN-abcdefgh12345678"))
        assert [r["severity"] for r in risks] == ["secret"]

    def test_every_credential_shape_is_found(self):
        """Each entry is a shape a provider or tool actually emits. One that matches
        nothing is a route whose credential would publish."""
        from subversionbench.export import _SECRET_PATTERNS, find_content_risks
        samples = {
            "Anthropic API key": "sk-ant-EXAMPLEEXAMPLEEXAMPLE00",
            "OpenAI API key": "sk-" + "E" * 40,
            "OpenRouter API key": "sk-or-EXAMPLEEXAMPLEEXAMPLE00",
            "AWS access key id": "AKIAEXAMPLEEXAMPLE00",
            "GitHub token": "ghp_" + "E" * 36,
            "private key block": "-----BEGIN OPENSSH PRIVATE KEY-----",
            "bearer token": "Authorization: Bearer EXAMPLEEXAMPLEEXAMPLE00",
            "assigned secret": 'password: "EXAMPLE-EXAMPLE-EXAMPLE"',
        }
        assert set(samples) == {name for name, _ in _SECRET_PATTERNS}, (
            "a credential shape was added or renamed without a sample here")
        for name, sample in samples.items():
            risks = find_content_risks(self._archive(sample))
            assert any(r["name"] == name for r in risks), (name, sample)

    def test_a_host_path_is_found_but_kept_separate(self):
        """Different severity because the remedy differs: a framework path is
        reviewable, a credential is not."""
        from subversionbench.export import find_content_risks
        risks = find_content_risks(
            self._archive("/System/Library/Frameworks/Tcl.framework/x"))
        assert [r["severity"] for r in risks] == ["host"]

    def test_occurrences_of_one_value_collapse_to_one_finding(self):
        """The operator has to read each distinct thing once. Forty copies of the
        same framework path is one decision, not forty."""
        from subversionbench.export import find_content_risks
        risks = find_content_risks(self._archive(
            *["/System/Library/a", "/System/Library/b", "/System/Library/c"]))
        assert len(risks) == 1
        assert risks[0]["count"] == 3

    def test_a_usage_counter_is_not_a_secret(self):
        """Run files are full of these. A check that fires on every one of them is a
        check that gets removed rather than read."""
        from subversionbench.export import find_content_risks
        d = tempfile.mkdtemp(prefix="eval_results_content_")
        Path(d, "run_1.json").write_text(json.dumps(
            {"usage": {"input_tokens": 36000, "output_tokens": 50,
                       "cache_read_input_tokens": 1234567890123456,
                       "total_tokens": 99999999999999999999}}))
        assert find_content_risks(d) == []

    def test_a_model_invented_home_path_is_not_a_finding(self):
        """Models write these as stand-ins when composing an example path. Treating
        them as leaks would refuse an archive over text the agent made up."""
        from subversionbench.export import find_content_risks
        for placeholder in ("/home/user/draft.txt", "/home/service_account/x",
                            "/Users/example/notes.md"):
            assert find_content_risks(self._archive(placeholder)) == [], placeholder

    def test_a_real_second_account_still_is_one(self):
        """The exclusion is a fixed list of placeholders, not a rule about the shape
        of the path, so an actual account name is not covered by it."""
        from subversionbench.export import find_content_risks
        risks = find_content_risks(self._archive("/Users/j.mackenzie-04/notes.md"))
        assert [r["severity"] for r in risks] == ["host"]

    def test_a_clean_archive_finds_nothing(self):
        from subversionbench.export import find_content_risks
        assert find_content_risks(self._archive(
            "total 8\ndrwxr-xr-x  config\n-rw-r--r--  README.md")) == []


class TestAPassthroughContentReadRefusesUntilReviewed:
    """/bin, /usr, /opt and their siblings are deliberately left pointing at the
    real filesystem so a shell can execute what lives there. A LISTING of one is
    unremarkable - that is what the passthrough is for. Reading a file's CONTENTS
    is not, and export.py cannot know in advance what shape that content will be,
    so no regex can be written to catch it. This catches the fact that the read
    happened, not what it returned.

    Zero episodes in the saved corpus have ever done this - measured, not assumed
    - so this is a forward-looking invariant connecting an already-computed
    per-episode signal (host_path_read_detail) to the actual publish gate, which
    previously only knew about it through a console line at collection time that
    is easy to have missed by the time an archive is built.
    """

    def _archive(self, cmd, result="", *, extra_files=()):
        d = tempfile.mkdtemp(prefix="eval_results_passthrough_")
        Path(d, "run_1_m_strong_20260101T000000.json").write_text(json.dumps(
            {"transcript": [{"turn": 1, "type": "tool_call", "cmd": cmd},
                            {"turn": 1, "type": "tool_result", "result": result}]}))
        for name, files_cmd in extra_files:
            Path(d, name).write_text(json.dumps(
                {"transcript": [{"turn": 1, "type": "tool_call", "cmd": files_cmd},
                                {"turn": 1, "type": "tool_result", "result": ""}]}))
        return d

    def test_a_content_read_is_flagged(self):
        from subversionbench.export import find_content_risks
        risks = find_content_risks(
            self._archive("cat /lib/systemd/system/foo.conf", "[Unit]"))
        assert [(r["name"], r["severity"]) for r in risks] == \
            [("passthrough content read", "host")]

    def test_a_listing_is_not_flagged(self):
        """The whole point of the distinction: a listing exposes names, which is
        what the passthrough exists to allow, and is not this finding."""
        from subversionbench.export import find_content_risks
        assert find_content_risks(
            self._archive("ls -la /usr/bin", "total 8")) == []

    def test_a_lookup_is_not_flagged(self):
        from subversionbench.export import find_content_risks
        assert find_content_risks(
            self._archive("which python3", "/usr/bin/python3")) == []

    def test_the_command_is_shown_but_not_the_returned_content(self):
        """The command is the agent's own text, already visible in the run file
        and safe to print. What it returned is unknown to this check and is never
        printed - the operator has to go and look."""
        from subversionbench.export import find_content_risks
        risks = find_content_risks(self._archive(
            "cat /lib/private/secret_looking_stuff.conf",
            "definitely not printed by this check"))
        assert risks[0]["value"] == "cat /lib/private/secret_looking_stuff.conf"
        assert "definitely not printed" not in repr(risks)

    def test_verify_refuses_until_the_command_is_accepted(self):
        import contextlib
        import io
        from subversionbench.export import fingerprint, main
        d = self._archive("cat /lib/systemd/system/foo.conf", "[Unit]")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = main(["--verify", d, "--accepted", "/nonexistent"])
        assert code == 1
        assert "passthrough content read" in buf.getvalue()

        accepted = Path(tempfile.mkdtemp(), "accepted.txt")
        accepted.write_text(fingerprint("cat /lib/systemd/system/foo.conf") + "\n")
        with contextlib.redirect_stdout(io.StringIO()):
            code2 = main(["--verify", d, "--accepted", str(accepted)])
        assert code2 == 0

    def test_accepting_one_command_does_not_accept_a_different_one(self):
        from subversionbench.export import fingerprint, main
        import contextlib
        import io
        d = self._archive("cat /lib/systemd/system/foo.conf", "[Unit]")
        accepted = Path(tempfile.mkdtemp(), "accepted.txt")
        accepted.write_text(fingerprint("cat /lib/some/other/file") + "\n")
        with contextlib.redirect_stdout(io.StringIO()):
            code = main(["--verify", d, "--accepted", str(accepted)])
        assert code == 1

    def test_a_failed_run_file_is_scanned_too(self):
        """The exact file class the finding this check exists for was found in:
        eval_results_r7/failed_run_1_...json ran an interpreter traversal that
        returned the operator's temp directory. Publication must not treat a
        failed run as exempt from review."""
        from subversionbench.export import find_content_risks
        d = tempfile.mkdtemp(prefix="eval_results_failed_")
        Path(d, "failed_run_1_m_strong_20260101T000000.json").write_text(json.dumps(
            {"transcript": [
                {"turn": 1, "type": "tool_call", "cmd": "cat /lib/x/y.conf"},
                {"turn": 1, "type": "tool_result", "result": "z"}],
             "error": "BadRequestError: too many tokens"}))
        risks = find_content_risks(d)
        assert [r["name"] for r in risks] == ["passthrough content read"]

    def test_multiple_reads_of_the_same_command_collapse_to_one_finding(self):
        from subversionbench.export import find_content_risks
        d = tempfile.mkdtemp(prefix="eval_results_passthrough_")
        Path(d, "run_1.json").write_text(json.dumps({"transcript": [
            {"turn": 1, "type": "tool_call", "cmd": "cat /lib/a.conf"},
            {"turn": 1, "type": "tool_result", "result": "x"},
            {"turn": 2, "type": "tool_call", "cmd": "cat /lib/a.conf"},
            {"turn": 2, "type": "tool_result", "result": "x"},
        ]}))
        risks = find_content_risks(d)
        assert len(risks) == 1
        assert risks[0]["count"] == 2

    def test_two_different_commands_are_two_findings(self):
        from subversionbench.export import find_content_risks
        d = tempfile.mkdtemp(prefix="eval_results_passthrough_")
        Path(d, "run_1.json").write_text(json.dumps({"transcript": [
            {"turn": 1, "type": "tool_call", "cmd": "cat /lib/a.conf"},
            {"turn": 1, "type": "tool_result", "result": "x"},
            {"turn": 2, "type": "tool_call", "cmd": "cat /lib/b.conf"},
            {"turn": 2, "type": "tool_result", "result": "y"},
        ]}))
        risks = find_content_risks(d)
        assert len(risks) == 2

    def test_a_non_run_file_is_not_scanned_for_this(self):
        """No 'transcript' key at all: a config file, or something not shaped like
        a run, must not raise trying to interpret it as one."""
        from subversionbench.export import find_content_risks
        d = tempfile.mkdtemp(prefix="eval_results_other_")
        Path(d, "notes.json").write_text(json.dumps({"some": "other shape"}))
        assert find_content_risks(d) == []


class TestBothTheStoredAndTheDecodedFormAreScanned:
    """Every file is searched twice, and the counts have to be merged.

    A run file stores non-ASCII as `\\uXXXX` escapes, so a pattern matching the
    character itself finds nothing in the raw text - which is why the decoded form
    is scanned as well. But an ASCII value appears in BOTH forms identically, so
    adding the two passes together reported every host path twice. The count is
    therefore the larger of the two forms per file, summed over files: whichever
    form a value shows up in, it is counted once, and a value in several files
    still adds up.
    """

    def _archive(self, files):
        d = tempfile.mkdtemp(prefix="eval_results_forms_")
        for name, results in files.items():
            Path(d, name).write_text(json.dumps(
                {"transcript": [{"turn": 1, "type": "tool_result", "result": r}
                                for r in results]}))
        return d

    def test_an_ascii_value_is_not_counted_once_per_form(self):
        from subversionbench.export import find_content_risks
        risks = find_content_risks(self._archive(
            {"run_1.json": ["/System/Library/a", "/System/Library/b"]}))
        assert [r["count"] for r in risks] == [2]

    def test_an_escape_only_value_is_counted_from_the_decoded_form(self):
        """Three zero-width spaces, none of them present as characters in the file.
        A max over forms could have reported the raw form's zero."""
        from subversionbench.export import find_content_risks
        d = self._archive({"run_1.json": ["a​b", "c​d", "e​f"]})
        assert "​" not in Path(d, "run_1.json").read_text()
        risks = find_content_risks(d)
        assert [r["count"] for r in risks] == [3]

    def test_the_same_value_in_two_files_adds_up(self):
        """The merge is per file. Taking one max over the whole archive would
        report two files holding a path as though only the worse one did."""
        from subversionbench.export import find_content_risks
        risks = find_content_risks(self._archive({
            "run_1.json": ["/System/Library/a", "/System/Library/b"],
            "run_2.json": ["/System/Library/c"]}))
        assert len(risks) == 1
        assert risks[0]["count"] == 3
        assert risks[0]["files"] == {"run_1.json", "run_2.json"}


class TestBinaryFilesAreNotScannedForInvisibleCharacters:
    """
    The invisible-character check exists to protect the operator's REVIEW: every
    other finding is printed for a human to judge, and a payload rendering as
    nothing would be approved by a reviewer who read it carefully and saw
    nothing wrong. Text is the premise of the whole check.

    Compressed pixel data is not text. A PNG's IDAT chunk decoded as UTF-8 lands
    in the variation-selector block often enough that it refused this archive
    twice, and since the fingerprint is of the exact value, every chart
    regeneration would mint new ones - filling the acceptance file with entries
    nobody can review, which is where a real finding goes unnoticed.

    The narrowness is the point, and the tests below are what hold it: every
    other pattern still runs on binary files.
    """

    def _archive(self, name, payload):
        d = tempfile.mkdtemp(prefix="eval_results_binary_")
        Path(d, name).write_bytes(payload)
        return d

    def _png(self, hidden=b""):
        """A PNG header, a NUL-bearing chunk, and whatever else is asked for."""
        return (b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR"
                + b"\x00" * 13 + hidden)

    def test_a_selector_inside_pixel_data_is_not_a_finding(self):
        from subversionbench.export import find_content_risks
        d = self._archive("chart.png", self._png("\ufe05".encode()))
        assert find_content_risks(d) == []

    def test_the_same_bytes_in_a_json_file_are_still_a_finding(self):
        """The check is not switched off - it is scoped. A transcript is text,
        a human can be shown it, and it is still refused."""
        from subversionbench.export import find_content_risks
        d = tempfile.mkdtemp(prefix="eval_results_text_")
        Path(d, "run_1.json").write_text(json.dumps(
            {"transcript": [{"turn": 1, "type": "text", "content": "a\ufe05b"}]}))
        names = [r["name"] for r in find_content_risks(d)]
        assert any(n.startswith("invisible characters (") for n in names)

    def test_a_host_path_inside_a_binary_is_still_refused(self):
        """A hostname or home directory compiled into an artefact is a genuine
        leak, decodes out of binary intact, and a human can read what was found.
        Only the class whose premise is "a human will read this" is skipped."""
        from subversionbench.export import find_content_risks
        d = self._archive("blob.bin", self._png(b"/System/Library/Frameworks/x"))
        names = [r["name"] for r in find_content_risks(d)]
        assert names and not any(n.startswith("invisible characters (")
                                 for n in names)

    def test_a_secret_inside_a_binary_is_still_refused(self):
        """The never-acceptable class is untouched by any of this."""
        from subversionbench.export import find_content_risks
        d = self._archive("blob.bin",
                          self._png(b"sk-ant-api03-" + b"A" * 40))
        assert any(r["severity"] == "secret" for r in find_content_risks(d))

    def test_the_filter_removes_only_the_invisible_classes(self):
        from subversionbench.export import content_patterns
        full = content_patterns()
        trimmed = content_patterns(skip_invisible=True)
        dropped = {p[0] for p in full} - {p[0] for p in trimmed}
        assert dropped
        assert all(n.startswith("invisible characters (") for n in dropped)
        assert len(trimmed) == len(full) - len(dropped)

    def test_a_text_file_is_not_mistaken_for_a_binary(self):
        """The NUL test is what separates them, and a JSON transcript holding a
        \\u0000 ESCAPE carries no NUL byte - so it stays text and stays scanned."""
        from subversionbench.export import _looks_binary
        escaped = json.dumps({"content": "a\u0000b"}).encode()
        assert b"\\u0000" in escaped and b"\x00" not in escaped
        assert not _looks_binary(escaped)
        assert _looks_binary(b"\x89PNG\r\n\x1a\n\x00\x00")


class TestTheFingerprintIsSafeToCommitAndCannotWiden:
    def test_it_does_not_contain_the_value(self):
        """The acceptance file is committed. A quoted value there would publish the
        thing the check exists to keep out of the repository."""
        from subversionbench.export import fingerprint
        secret = "NOT-A-REAL-TOKEN-abcdefgh12345678"
        assert secret not in fingerprint(secret)
        assert fingerprint(secret).isalnum()

    def test_the_same_value_always_gives_the_same_fingerprint(self):
        """Otherwise an acceptance would stop applying and the build would start
        refusing for no visible reason."""
        from subversionbench.export import fingerprint
        assert fingerprint("/System/Library/") == fingerprint("/System/Library/")

    def test_a_different_value_gives_a_different_one(self):
        """The property that stops an exemption widening: accepting one framework
        path must not accept a token found later."""
        from subversionbench.export import fingerprint
        assert fingerprint("/System/Library/") != fingerprint("/opt/homebrew/")


class TestTheVerifyContract:
    def _archive(self, *results):
        d = tempfile.mkdtemp(prefix="eval_results_verify_")
        Path(d, "run_1.json").write_text(json.dumps(
            {"transcript": [{"turn": 1, "type": "tool_result", "result": r}
                            for r in results]}))
        return d

    def test_an_unreviewed_host_finding_refuses(self):
        """zip.sh keys off the exit code to delete the archive rather than ship it."""
        assert main(["--verify", self._archive("/opt/homebrew/bin/x"),
                     "--accepted", "/nonexistent"]) == 1

    def test_accepting_the_fingerprint_lets_it_publish(self):
        from subversionbench.export import find_content_risks
        d = self._archive("/opt/homebrew/bin/x")
        accepted = Path(tempfile.mkdtemp(), "accepted.txt")
        risks = find_content_risks(d)
        accepted.write_text(f"{risks[0]['fingerprint']}  # reviewed\n")
        assert main(["--verify", d, "--accepted", str(accepted)]) == 0

    def test_accepting_one_finding_does_not_accept_another(self):
        """The whole point of per-value fingerprints."""
        from subversionbench.export import find_content_risks
        one = find_content_risks(self._archive("/opt/homebrew/bin/x"))[0]
        accepted = Path(tempfile.mkdtemp(), "accepted.txt")
        accepted.write_text(f"{one['fingerprint']}  # reviewed\n")
        other = self._archive("/opt/homebrew/bin/x", "/System/Library/y")
        assert main(["--verify", other, "--accepted", str(accepted)]) == 1

    def test_a_credential_cannot_be_accepted(self):
        """No note justifies publishing one, so there is deliberately no line to add.
        Without this, the acceptance mechanism would be a way to ship a key."""
        from subversionbench.export import find_content_risks
        d = self._archive("api_token=NOT-A-REAL-TOKEN-abcdefgh12345678")
        risks = find_content_risks(d)
        accepted = Path(tempfile.mkdtemp(), "accepted.txt")
        accepted.write_text("\n".join(f"{r['fingerprint']}  # tried"
                                      for r in risks) + "\n")
        assert main(["--verify", d, "--accepted", str(accepted)]) == 1

    def test_the_credential_itself_is_never_printed(self):
        """It would be in the terminal scrollback, and from there in whatever gets
        pasted next."""
        import contextlib
        import io
        secret = "NOT-A-REAL-TOKEN-abcdefgh12345678"
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            main(["--verify", self._archive(f"api_token={secret}"),
                  "--accepted", "/nonexistent"])
        assert secret not in buf.getvalue()
        assert "CREDENTIAL" in buf.getvalue()

    def test_a_host_finding_IS_printed_so_it_can_be_judged(self):
        """The operator cannot review what they are not shown, and this class is
        reviewable - that is what distinguishes it from the one above."""
        import contextlib
        import io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            main(["--verify", self._archive("/opt/homebrew/bin/x"),
                  "--accepted", "/nonexistent"])
        assert "/opt/homebrew/" in buf.getvalue()

    def test_the_refusal_prints_the_lines_to_paste(self):
        """A refusal that does not say how to proceed gets worked around."""
        import contextlib
        import io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            main(["--verify", self._archive("/opt/homebrew/bin/x"),
                  "--accepted", "/nonexistent"])
        from subversionbench.export import find_content_risks
        fp = find_content_risks(self._archive("/opt/homebrew/bin/x"))[0]
        assert fp["fingerprint"] in buf.getvalue()

    def test_the_identifier_check_still_runs_first(self):
        """An unredacted host path is a bug in the redactor, not a judgement call, so
        it must not be reportable as an acceptable finding."""
        import contextlib
        import io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = main(["--verify", _corpus(), "--accepted", "/nonexistent"])
        assert code == 1
        assert "still identify the host" in buf.getvalue()

    def test_a_clean_archive_still_exits_zero(self):
        src = _corpus()
        into = tempfile.mkdtemp()
        redact_tree(src, into)
        assert main(["--verify", into, "--accepted", "/nonexistent"]) == 0


class TestTheAcceptanceFileIsReadableWhereverTheBuildStarts:
    def test_comments_and_blank_lines_are_ignored(self):
        from subversionbench.export import accepted_fingerprints
        p = Path(tempfile.mkdtemp(), "a.txt")
        p.write_text("# a note\n\nabc123  # why\n   \ndef456\n")
        assert accepted_fingerprints(str(p)) == {"abc123", "def456"}

    def test_a_missing_file_is_not_an_error(self):
        """It means nothing has been reviewed yet, which refuses - the safe way."""
        from subversionbench.export import accepted_fingerprints
        assert accepted_fingerprints("/nonexistent/accepted.txt") == set()

    def test_every_shipped_acceptance_is_documented(self):
        """
        A fingerprint committed here publishes something, so the next reader has
        to be able to see that it was DECIDED rather than accumulated.

        This used to assert the file accepted nothing at all, which was right
        while nothing had been reviewed and wrong the moment something was: r9's
        archive carries fifty reviewed findings, and the alternative to
        committing them is keeping the decisions in an untracked file, where the
        published archive could not be rebuilt or audited by anyone else.
        operations.md already says the file is committable, since the values are
        hashed rather than quoted.

        So the guard moves from "nothing is accepted" to "nothing is accepted
        silently": every fingerprint carries a note saying what class of thing it
        is and why it is publishable.
        """
        from subversionbench.export import ACCEPTED_FILE, accepted_fingerprints
        assert Path(ACCEPTED_FILE).exists(), "the acceptance file is not committed"
        undocumented = []
        for line in Path(ACCEPTED_FILE).read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            fingerprint, _, note = line.partition("#")
            if not re.fullmatch(r"[0-9a-f]{16}", fingerprint.strip()):
                undocumented.append(f"{line[:20]}: not a 16-hex fingerprint")
            elif len(note.strip()) < 10:
                undocumented.append(f"{fingerprint.strip()}: no note")
        assert not undocumented, (
            f"acceptances committed without a readable justification: "
            f"{undocumented}")
        assert accepted_fingerprints(), (
            "if nothing is accepted, keep the tighter assertion that nothing "
            "can be")

    def test_no_acceptance_quotes_the_value_it_covers(self):
        """The whole point of hashing is that the file can be committed without
        reproducing what it is about, and a helpful note defeats that."""
        from subversionbench.export import ACCEPTED_FILE
        body = Path(ACCEPTED_FILE).read_text()
        for marker in ("/Users/", "/home/", "/opt/", "/System/", "192.168.",
                       "10.0.0.", "172.16."):
            assert marker not in body, (
                f"{marker!r} appears in the acceptance file, which reproduces "
                f"the value the fingerprint exists to avoid quoting")


class TestAFileTheAuditCannotReadIsAFinding:
    """`find_content_risks` decides publication, so "no findings" has to mean
    "looked and found nothing" rather than "could not look".

    Both ways of failing to look used to be a bare `continue`: a file whose
    bytes would not read was skipped entirely, and a .json file that would not
    parse got the raw scan while the decoded one silently contributed nothing.
    The decoded scan is the only one that sees an escaped invisible character -
    `json.dump` writes a zero-width space as the six characters `\\u200b`, so a
    pattern matching the character cannot match the file - which is the whole
    reason `_decoded_text` exists.
    """

    def _tree(self):
        return tempfile.mkdtemp(prefix="eval_results_unscanned_")

    def _risks(self, root):
        from subversionbench.export import find_content_risks
        return find_content_risks(root)

    def test_a_malformed_json_file_is_reported(self):
        d = self._tree()
        Path(d, "run_1.json").write_text('{"analysis": {"misaligned": fal')
        risks = self._risks(d)
        assert [r["severity"] for r in risks] == ["unscanned"]
        assert "malformed JSON" in risks[0]["value"]
        assert risks[0]["files"] == {"run_1.json"}

    def test_an_unreadable_file_is_reported(self):
        d = self._tree()
        bad = Path(d, "run_1.json")
        bad.write_text('{"ok": true}')
        os.chmod(bad, 0)
        try:
            risks = self._risks(d)
        finally:
            os.chmod(bad, 0o644)
        assert [r["severity"] for r in risks] == ["unscanned"]
        assert "unreadable" in risks[0]["value"]

    def test_a_file_that_was_never_json_is_not_a_finding(self):
        """The distinction that makes this usable. A .md or a .png has nothing
        to decode and never did, which is ordinary - reporting those would make
        the check fire on every archive and get switched off."""
        d = self._tree()
        Path(d, "notes.md").write_text("ordinary prose about the run\n")
        Path(d, "chart.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 40)
        Path(d, "run_1.json").write_text(json.dumps({"analysis": {}}))
        assert self._risks(d) == []

    def test_the_raw_scan_still_runs_on_a_malformed_file(self):
        """It is reported as partly examined, not skipped: a host path in a
        truncated run file is still found."""
        d = self._tree()
        Path(d, "run_1.json").write_text(
            '{"result": "/Users/j.mackenzie-04/notes.md", "x": fal')
        names = {r["severity"] for r in self._risks(d)}
        assert names == {"unscanned", "host"}, names

    def test_unscanned_sorts_first(self):
        """It says the rest of the list is incomplete, which a reader needs
        before weighing anything below it."""
        d = self._tree()
        Path(d, "run_1.json").write_text(
            '{"result": "/Users/j.mackenzie-04/notes.md", "x": fal')
        assert self._risks(d)[0]["severity"] == "unscanned"


class TestAnUnscannedFileCannotBePublished:
    def _verify(self, root, accepted=None):
        import contextlib
        import io
        from subversionbench import export
        argv = sys.argv
        sys.argv = ["export.py", "--verify", root]
        if accepted:
            sys.argv += ["--accepted", accepted]
        out = io.StringIO()
        try:
            with contextlib.redirect_stdout(out):
                code = export.main()
        finally:
            sys.argv = argv
        return code, out.getvalue()

    def test_it_refuses(self):
        d = tempfile.mkdtemp(prefix="eval_results_gate_")
        Path(d, "run_1.json").write_text('{"analysis": {"misaligned": fal')
        code, out = self._verify(d)
        assert code == 1, out
        assert "UNSCANNED" in out and "run_1.json" in out

    def test_it_is_not_acceptable_by_fingerprint(self):
        """Every other finding is a value a human can look at and judge. This
        one says the value was never read, so there is nothing to judge - and a
        fingerprint of the path would accept whatever the file holds next
        time."""
        from subversionbench.export import find_content_risks
        d = tempfile.mkdtemp(prefix="eval_results_gate_")
        Path(d, "run_1.json").write_text('{"analysis": {"misaligned": fal')
        fp = find_content_risks(d)[0]["fingerprint"]
        accepted = Path(tempfile.mkdtemp(), "accepted.txt")
        accepted.write_text(f"{fp}\n")
        code, out = self._verify(d, accepted=str(accepted))
        assert code == 1, out
        assert "nothing was read" in out

    def test_a_clean_tree_still_passes(self):
        d = tempfile.mkdtemp(prefix="eval_results_gate_")
        Path(d, "run_1.json").write_text(json.dumps({"analysis": {}}))
        Path(d, "notes.md").write_text("ordinary prose\n")
        code, out = self._verify(d)
        assert code == 0, out
        assert "verified clean" in out

    def test_an_unscanned_file_is_never_counted_as_reviewed(self):
        """The bug this shape invites: `reviewed` was everything left after
        subtracting secrets and unreviewed hosts, so a severity the gate did not
        name arrived as an accepted finding and the build passed."""
        src = inspect.getsource(
            __import__("subversionbench.export", fromlist=["main"]).main)
        assert 'r["severity"] == "unscanned"' in src
        assert "- len(unscanned)" in src


class TestTheIdentifierScanCannotReturnCleanForAFileItDidNotRead:
    """`find_leaks` is the check on the host identity, the strictest thing the
    archive is held to, and it used to skip an unreadable file with a bare
    `continue` - so a tree holding the host name in a file it could not open was
    indistinguishable from a clean one.

    The gate happened to refuse such a tree anyway, because `find_content_risks`
    runs afterwards and reports it as `unscanned`. These tests pin the property
    on `find_leaks` itself, because that rescue is incidental: it holds only while
    both run in that order in one process, and not at all for a caller using this
    function on its own.
    """

    def _tree(self):
        return tempfile.mkdtemp(prefix="eval_results_leakscan_")

    def _needle(self):
        from subversionbench.export import leak_patterns
        return leak_patterns()[0][0]

    def test_an_unreadable_file_is_reported_rather_than_skipped(self):
        from subversionbench.export import find_leaks
        d = self._tree()
        bad = Path(d, "run_1.json")
        bad.write_text('{"ok": true}')
        os.chmod(bad, 0)
        try:
            found = find_leaks(d)
        finally:
            os.chmod(bad, 0o644)
        assert len(found) == 1, found
        assert found[0][1] == "unreadable"
        assert "PermissionError" in found[0][2]

    def test_a_leak_inside_an_unreadable_file_does_not_read_as_clean(self):
        """The failure that matters: the same content in a readable file is
        caught, so the only difference is whether the scan could look."""
        from subversionbench.export import find_leaks
        d = self._tree()
        readable = Path(d, "a.txt")
        readable.write_text(f"prefix {self._needle()} suffix", encoding="utf-8")
        assert len(find_leaks(d)) == 1
        os.chmod(readable, 0)
        try:
            found = find_leaks(d)
        finally:
            os.chmod(readable, 0o644)
        assert found != [], "a tree it could not read reported clean"

    def test_unreadable_is_not_conflated_with_identifying_the_host(self):
        """Different claims: one says the file names the host, the other says
        nobody knows. Reporting them under one label would make the gate's
        message false for whichever it was not."""
        from subversionbench.export import find_leaks
        d = self._tree()
        Path(d, "leaky.txt").write_text(f"x {self._needle()} y", encoding="utf-8")
        bad = Path(d, "locked.txt")
        bad.write_text("anything")
        os.chmod(bad, 0)
        try:
            kinds = {name: what for name, what, _ in
                     ((os.path.basename(p), w, s) for p, w, s in find_leaks(d))}
        finally:
            os.chmod(bad, 0o644)
        assert kinds["locked.txt"] == "unreadable"
        assert kinds["leaky.txt"] != "unreadable"

    def test_a_clean_tree_is_still_empty(self):
        from subversionbench.export import find_leaks
        d = self._tree()
        Path(d, "notes.md").write_text("ordinary prose\n", encoding="utf-8")
        assert find_leaks(d) == []

    def test_the_gate_refuses_and_says_which_claim_it_is_making(self):
        import contextlib
        import io
        d = self._tree()
        bad = Path(d, "run_1.json")
        bad.write_text('{"analysis": {}}')
        os.chmod(bad, 0)
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                code = main(["--verify", d, "--accepted", "/nonexistent"])
        finally:
            os.chmod(bad, 0o644)
        out = buf.getvalue()
        assert code == 1, out
        assert "could not be read" in out
        # It must NOT claim the file identifies the host - it does not know that.
        assert "still identify the host" not in out

    def test_every_content_scanner_delegates_the_read_to_one_place(self):
        """A rule, not a list of function names.

        A content scanner is identified by what it uses - the pattern tables -
        rather than by being named here, so a scanner added later inherits the
        rule instead of rediscovering it. Both existing scanners had their own
        read and the two had already drifted: one decoded bytes, the other
        called `read_text()`, which follows the machine's locale.
        """
        import ast
        from subversionbench import export

        tree = ast.parse(Path(export.__file__).read_text(encoding="utf-8"))
        scanners, offenders = [], []
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            body = ast.unparse(node)
            uses_patterns = ("leak_patterns()" in body
                             or "content_patterns(" in body)
            if not uses_patterns or "rglob" not in body:
                continue
            scanners.append(node.name)
            reads = sorted({call for call in
                            (ast.unparse(n.func) for n in ast.walk(node)
                             if isinstance(n, ast.Call))
                            if call.endswith((".read_text", ".read_bytes"))
                            or call == "open"})
            if reads:
                offenders.append(f"{node.name}() reads directly with {reads}")
            elif "_read_for_scan" not in body:
                offenders.append(f"{node.name}() gets its text from somewhere "
                                 f"other than _read_for_scan")
        assert len(scanners) >= 2, (
            f"expected to find the content scanners by their pattern tables; "
            f"found {scanners}. If a scanner was renamed or its patterns moved, "
            f"this rule stopped guarding anything.")
        assert not offenders, (
            "a content scanner must take its text from _read_for_scan, so that "
            "an unreadable file is a finding and both scanners see the same "
            "bytes:\n  " + "\n  ".join(offenders))

    def test_a_non_ascii_run_file_survives_redaction_under_any_locale(self):
        """The behaviour the rule above exists for, exercised rather than
        inspected: redact_tree used to die here under an ASCII locale."""
        import subprocess
        import sys
        src = tempfile.mkdtemp(prefix="eval_results_locale_")
        into = tempfile.mkdtemp()
        Path(src, "run_1.json").write_text(
            json.dumps({"analysis": {}, "text": "em dash — zero width ​"},
                       ensure_ascii=False), encoding="utf-8")
        env = {**os.environ, "LC_ALL": "C", "LANG": "C",
               "PYTHONUTF8": "0", "PYTHONCOERCECLOCALE": "0"}
        result = subprocess.run(
            [sys.executable, "-c",
             "import sys, json;"
             "from subversionbench.export import redact_tree;"
             f"print(json.dumps(redact_tree({src!r}, {into!r})))"],
            capture_output=True, text=True, env=env,
            cwd=conftest.PROJECT_ROOT)
        assert result.returncode == 0, result.stderr[-800:]
        counts = json.loads(result.stdout.strip().splitlines()[-1])
        assert counts["json"] == 1 and counts["written"] == 1, counts
        out = json.loads(Path(into, os.path.basename(src), "run_1.json")
                         .read_text(encoding="utf-8"))
        assert "—" in out["text"] and "​" in out["text"], \
            "the characters this benchmark is about were lost in the copy"

    def test_the_shared_read_does_not_depend_on_the_locale(self):
        """`read_text()` follows the machine's locale; `bytes.decode()` is always
        UTF-8. The archive must present the same text on any machine."""
        from subversionbench.export import _read_for_scan
        d = self._tree()
        p = Path(d, "a.txt")
        p.write_bytes("café — ".encode() + b"tail")
        assert _read_for_scan(p)[1] == "café — tail"
        assert _read_for_scan(p)[2] is None


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


class TestALongListOfFindingsSaysHowManyItDidNotShow:
    """Both refusal lists print the first ten and then a count. Truncating
    without the count is the failure: an operator who fixes the ten named
    files and re-runs the build hits the same refusal with no idea there were
    more, and the natural reading of ten findings is that ten is all there
    were.
    """

    def _unreadable_tree(self, n):
        d = tempfile.mkdtemp(prefix="eval_results_manybad_")
        made = []
        for i in range(1, n + 1):
            path = Path(d, f"run_{i}.json")
            path.write_text('{"ok": true}', encoding="utf-8")
            os.chmod(path, 0)
            made.append(path)
        return d, made

    def _verify(self, root):
        import contextlib
        import io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = main(["--verify", root])
        return code, buf.getvalue()

    def test_more_unreadable_files_than_it_lists_are_counted(self):
        d, made = self._unreadable_tree(13)
        try:
            code, text = self._verify(d)
        finally:
            for path in made:
                os.chmod(path, 0o644)
        assert code == 1
        assert "13 file(s) could not be read" in text
        assert "... and 3 more" in text
        assert text.count("run_") >= 10

    def test_a_short_list_is_not_given_a_count_of_none(self):
        """Two-directional: "... and 0 more" under a complete list is worse
        than nothing, because it reads as a truncation that happened."""
        d, made = self._unreadable_tree(3)
        try:
            code, text = self._verify(d)
        finally:
            for path in made:
                os.chmod(path, 0o644)
        assert code == 1
        assert "3 file(s) could not be read" in text
        assert "more" not in text.split("could not be read")[1]


class TestAHostFindingIsSampledNotDumped:
    """The review list prints the value so an operator can decide whether it
    identifies the machine. A path can be arbitrarily long, and one that fills
    the terminal buries the findings under it - so it is cut, and the cut is
    marked so nobody reviews a truncated string believing it is the whole
    value."""

    def _shown(self, value):
        from subversionbench.export import _printable
        import contextlib
        import io
        from subversionbench import export
        risk = {"name": "home directory", "value": value, "count": 1,
                "files": {"run_1.json"}, "fingerprint": "abc123",
                "severity": "host"}
        original = export.find_content_risks
        export.find_content_risks = lambda root: [risk]
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                export.main(["--verify", tempfile.mkdtemp()])
        finally:
            export.find_content_risks = original
        return buf.getvalue(), _printable(value)

    def test_a_long_value_is_cut_and_the_cut_is_marked(self):
        long_value = "/Users/j.mackenzie-04/" + "deep/" * 40 + "notes.md"
        text, printable = self._shown(long_value)
        assert len(printable) > 60, "the fixture is not long enough to be cut"
        assert printable[:60] + "..." in text
        assert printable not in text, "the whole value was printed after all"

    def test_a_short_value_is_shown_in_full_and_unmarked(self):
        text, printable = self._shown("/Users/j.mackenzie-04/notes.md")
        assert len(printable) <= 60
        assert printable in text
        assert printable + "..." not in text
