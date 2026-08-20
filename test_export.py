"""
Redacting a results directory for publication, and refusing to publish a dirty one.

The corpus keeps its real paths, because re-interrogating a saved episode needs the
bytes the model actually saw. The archive is the only thing that leaves the machine,
so the archive is what gets cleaned - and the check runs on the unpacked archive
rather than on the staging copy, so it tests what is actually published.
"""

import json
import os
import re
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
