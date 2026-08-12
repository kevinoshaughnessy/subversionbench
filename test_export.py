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

    def test_the_shipped_file_parses_and_accepts_nothing_by_default(self):
        """A fingerprint committed here would publish something without the next
        reader knowing it had been decided."""
        from subversionbench.export import ACCEPTED_FILE, accepted_fingerprints
        assert Path(ACCEPTED_FILE).exists(), "the acceptance file is not committed"
        assert accepted_fingerprints() == set()
