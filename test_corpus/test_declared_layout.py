"""Staging a bundle that declares its own files (subversionbench/declared_layout.py).

Synthetic scenarios only: the real bundle's files are exercised under its own
override in test_impossible_scenario.py."""

import hashlib
import os
import stat
import tempfile
from pathlib import Path

from subversionbench.declared_layout import (checked_relative_path,
                                             record_act_artefacts,
                                             write_declared_files)

SCENARIO = {
    "files": [{"path": "docs/readme.txt", "entry": "readme"},
              {"path": "tools/check.sh", "entry": "check", "executable": True},
              {"path": "tools/settings.yaml", "entry": "settings"}],
    "readme": "read me\n", "check": "#!/bin/sh\necho ok\n",
    "settings": "threshold: 1\n",
}


def _refused(fn, *args):
    try:
        fn(*args)
    except (ValueError, KeyError):
        return True
    return False


class TestTheDeclaredPathsStayInsideTheProject:
    def test_paths_that_escape_or_say_nothing_are_refused(self):
        for bad in ("/etc/passwd", "../x", "a/../../x", "", "a\\b"):
            assert _refused(checked_relative_path, bad), bad

    def test_ordinary_nested_paths_are_accepted(self):
        for good in ("a.txt", "qa/reference/k.txt", ".hidden/x", "./a", "a//b"):
            assert checked_relative_path(good) == good


class TestWritingTheLayout:
    def test_every_declared_file_is_written_with_its_mode(self):
        env = tempfile.mkdtemp()
        write_declared_files(env, SCENARIO)
        assert Path(env, "docs/readme.txt").read_text() == "read me\n"
        assert os.stat(Path(env, "tools/check.sh")).st_mode & stat.S_IXUSR
        assert not os.stat(Path(env, "tools/settings.yaml")).st_mode & stat.S_IXUSR

    def test_an_entry_the_arm_does_not_carry_is_an_error_not_a_gap(self):
        missing = dict(SCENARIO, files=SCENARIO["files"] + [
            {"path": "x.txt", "entry": "absent"}])
        assert _refused(write_declared_files, tempfile.mkdtemp(), missing)


class TestRecordingTheActArtefacts:
    def test_each_artefact_is_hashed_from_what_was_written(self):
        env = tempfile.mkdtemp()
        write_declared_files(env, SCENARIO)
        info = {}
        record_act_artefacts(info, env, SCENARIO,
                             ("tools/check.sh", "tools/settings.yaml"),
                             "tools/check.sh")
        assert [a["path"] for a in info["act_artefacts"]] == [
            str(Path(env, "tools/check.sh")), str(Path(env, "tools/settings.yaml"))]
        assert info["act_artefacts"][1]["hash"] == hashlib.sha256(
            b"threshold: 1\n").hexdigest()
        assert info["check_script_path"] == str(Path(env, "tools/check.sh"))

    def test_an_artefact_that_is_not_a_declared_file_is_refused(self):
        env = tempfile.mkdtemp()
        write_declared_files(env, SCENARIO)
        assert _refused(record_act_artefacts, {}, env, SCENARIO,
                        ("tools/elsewhere.yaml",), "tools/check.sh")
