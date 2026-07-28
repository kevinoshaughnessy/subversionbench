"""
Tests for subversionbench/redaction.py.

Covers rewriting the operator's paths and username out of anything
printed or saved.

Run: pytest test_redaction.py -v
"""

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
        text = ("I recommend Strategy B for Millbrook. I checked "
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
