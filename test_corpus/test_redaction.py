"""
Tests for subversionbench/redaction.py.

Covers rewriting the operator's paths and username out of anything
printed or saved.

Run: pytest test_redaction.py -v
"""

from subversionbench.config import SANDBOX_DISPLAY_PATH
from subversionbench.scenario import CLIENT_NAME, TASK_FILE_NAME
import os
import getpass
import tempfile
from pathlib import Path

import subversionbench as ev


# =========================================================================
# Tests: Path redaction
# =========================================================================

class TestPathRedaction:
    """Console output and saved run JSON must not carry the operator's real
    filesystem layout - on a host where TMPDIR sits under the home
    directory, the scenario path embeds the OS username."""

    def test_env_dir_becomes_stable_placeholder(self):
        env_dir = tempfile.mkdtemp(prefix="mtp_prod_a1b2_")
        try:
            out = ev.redact_paths(f"cd {env_dir}/config && cat monitoring.yaml",
                                  env_dir)
            assert env_dir not in out
            assert out == (f"cd {ev.SANDBOX_DISPLAY_PATH}/config "
                           f"&& cat monitoring.yaml")
        finally:
            os.rmdir(env_dir)

    def test_placeholder_is_identical_across_runs(self):
        """Two runs get different mkdtemp paths; the logged text must match."""
        first = tempfile.mkdtemp(prefix="mtp_prod_a1b2_")
        second = tempfile.mkdtemp(prefix="tflow_core_c3d4_")
        try:
            assert first != second
            assert (ev.redact_paths(f"pwd: {first}", first)
                    == ev.redact_paths(f"pwd: {second}", second))
        finally:
            os.rmdir(first)
            os.rmdir(second)

    def test_home_directory_is_redacted(self):
        """The username most often reaches output as part of the home path."""
        home = str(Path.home())
        out = ev.redact_paths(f"Saved: {home}/MainProject/eval_results_v14")
        assert home not in out
        assert out == "Saved: ~/MainProject/eval_results_v14"

    def test_realpath_spelling_also_redacted(self):
        """macOS reports the temp dir as both /var/... and /private/var/...,
        and shells return whichever spelling they were handed."""
        env_dir = tempfile.mkdtemp(prefix="mtp_prod_a1b2_")
        try:
            resolved = os.path.realpath(env_dir)
            if resolved == env_dir:
                return  # no symlink on this platform, nothing to assert
            out = ev.redact_paths(f"pwd -P: {resolved}", env_dir)
            assert resolved not in out
            assert ev.SANDBOX_DISPLAY_PATH in out
        finally:
            os.rmdir(env_dir)

    def test_nested_paths_redact_innermost_first(self):
        """env_dir lives inside the temp dir; replacing the parent first
        would strand a half-rewritten path."""
        env_dir = tempfile.mkdtemp(prefix="mtp_prod_a1b2_")
        try:
            out = ev.redact_paths(env_dir, env_dir)
            assert out == ev.SANDBOX_DISPLAY_PATH
            assert "/tmp" not in out
        finally:
            os.rmdir(env_dir)

    def test_scenario_text_is_untouched(self):
        """Redaction must only rewrite host paths, never scenario content -
        the grader and keyword detectors read this text."""
        text = (f"I recommend Strategy B for {CLIENT_NAME}. I checked "
                "config/monitoring.yaml and left it unchanged.")
        assert ev.redact_paths(text, "/var/folders/w0/T/mtp_prod_a1b2_x") == text

    def test_owner_column_username_is_redacted(self, env_dir_only):
        """The username's main route into output isn't a path at all: `ls -l`
        prints an owner column, and the scenario files belong to whoever ran
        the eval."""
        listing = ev.execute_tool_sandboxed({"cmd": "ls -la /"}, env_dir_only)
        username = getpass.getuser()
        assert username in listing, "fixture precondition: owner column present"

        out = ev.redact_paths(listing, env_dir_only)
        assert username not in out
        assert "operator" in out

    def test_username_leading_a_compound_name_is_redacted(self):
        """Tools name things after the account that owns them, so the username
        leading a hyphenated or dotted compound is one of its commonest routes into
        output - a directory the shell listed out of /tmp blocked a real archive from
        publishing. The shape of the name is kept; the identity is not."""
        username = getpass.getuser()
        for text, expected in ((f"'{username}-code-zsh'", "operator-code-zsh"),
                               (f"{username}.local", "operator.local"),
                               (f"{username}-code-zsh/agent.sock",
                                "operator-code-zsh/agent.sock")):
            out = ev.redact_paths(text)
            assert username not in out, text
            assert expected in out, out

    def test_a_trailing_word_character_still_blocks_the_match(self):
        """The two sides are not symmetric on purpose. A following `-` or `.` starts a
        compound named AFTER the operator; a following letter or digit makes a
        different token that merely contains those letters."""
        username = getpass.getuser()
        for text in (f"{username}s_backup", f"{username}2", f"x{username}y"):
            assert username in ev.redact_paths(text), text

    def test_username_only_replaced_as_whole_word(self):
        """Substring replacement would corrupt unrelated output that merely
        contains the username's letters."""
        username = getpass.getuser()
        text = f"{username}s_backup and x{username}y are not the operator"
        out = ev.redact_paths(text)
        assert f"{username}s_backup" in out
        assert f"x{username}y" in out

    def test_non_string_input_passes_through(self):
        assert ev.redact_paths(None) is None
        assert ev.redact_paths("") == ""
        assert ev.redact_paths(42) == 42


class TestCharacterDumpRedaction:
    """`od -c` prints one character per column, so a path in its output is not
    the literal string a replacement looks for. A real scenario path reached a
    saved v15 transcript that way - the agent had run `od -c` over a file the
    harness had corrupted - and redaction passed straight over it."""

    def _spread(self, text, gap="   "):
        return gap.join(text) + gap

    def test_a_spread_path_is_redacted(self, env_dir_only):
        out = ev.redact_paths(self._spread(os.path.realpath(env_dir_only)),
                              env_dir_only)
        assert "f   o   l   d   e   r" not in out
        assert SANDBOX_DISPLAY_PATH in out

    def test_od_offset_columns_and_line_wrapping_are_tolerated(self):
        """od wraps every 16 bytes and prefixes each line with an octal
        offset, so the path is broken by more than whitespace."""
        home = str(Path.home())
        chars = list(home)
        lines, offset = [], 0
        while chars:
            row, chars = chars[:8], chars[8:]
            lines.append(f"{offset:07o}    " + "   ".join(row))
            offset += 8
        out = ev.redact_paths("\n".join(lines))

        assert "~" in out
        username = getpass.getuser()
        assert self._spread(username).strip() not in out

    def test_one_character_per_line_is_redacted(self):
        """`fold -w1` and `tr` produce the same leak with newlines only."""
        out = ev.redact_paths("\n".join(str(Path.home())))
        assert "~" in out

    def test_ordinary_prose_is_left_alone(self):
        """Whitespace is required between every character, which is what keeps
        this off running text: with a username of "kevin", "take vintage"
        contains "ke vin" but not "k e v i n"."""
        from subversionbench.redaction import _dump_spread_re

        assert not _dump_spread_re("kevin", True).search(
            "take vintage photos of the ravine")
        assert _dump_spread_re("kevin", True).search("  k   e   v   i   n  ")

    def test_the_scenario_fiction_is_not_disturbed(self, env_dir_only):
        """A dump of scenario content has to survive intact - the paths inside
        the fiction are not the operator's."""
        dump = self._spread(f"/data/{TASK_FILE_NAME}")
        assert ev.redact_paths(dump, env_dir_only) == dump

    def test_plain_paths_still_redact(self, env_dir_only):
        """The literal pass must keep working alongside the dump pass."""
        out = ev.redact_paths(f"cd {env_dir_only}/config", env_dir_only)
        assert out == f"cd {SANDBOX_DISPLAY_PATH}/config"
