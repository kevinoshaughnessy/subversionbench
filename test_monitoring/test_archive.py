"""
Archiving the monitoring benchmark's results.

zip.sh withholds every file of this corpus, because its allowlist is made of run-file
names, so the archive has its own: a manifest, a token ledger and results/*.jsonl.
"""

import json
import os
import re
import shutil
import tempfile
from pathlib import Path

import pytest

from monitoring import archive
from monitoring.archive import ArchiveRefused, is_published, stage
from subversionbench.redaction import path_substitutions

HOST_PATH = path_substitutions()[0][0]
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _corpus(**extra_files) -> str:
    """A monitoring results directory holding one host path in a monitor's reason."""
    root = tempfile.mkdtemp(prefix="eval_results_monitor_test_")
    Path(root, "manifest.json").write_text(json.dumps({"meta": {}, "episodes": []}))
    Path(root, "api_usage.jsonl").write_text(json.dumps({"model": "m"}) + "\n")
    results = Path(root, "results")
    results.mkdir()
    row = {"id": "e1", "monitor": "m", "reason": f"it read {HOST_PATH}/x"}
    (results / "m.jsonl").write_text(json.dumps(row) + "\n")
    for name, text in extra_files.items():
        Path(root, name).parent.mkdir(parents=True, exist_ok=True)
        Path(root, name).write_text(text)
    return root


class TestWhatShips:
    PUBLISHED = ("manifest.json", "api_usage.jsonl", "results/claude-haiku-5-5.jsonl",
                 "results/z-ai_glm-5.3-flash.jsonl")
    WITHHELD = (".DS_Store", "notes.md", "results/.DS_Store", "results/m.json",
                "results/sub/m.jsonl", "other/manifest.json", "run_1.json")

    def test_every_corpus_shape_ships(self):
        assert [n for n in self.PUBLISHED if not is_published(n)] == []

    def test_no_stray_file_ships(self):
        assert [n for n in self.WITHHELD if is_published(n)] == []

    def test_both_sets_are_non_empty(self):
        assert self.PUBLISHED and self.WITHHELD


class TestStaging:
    def test_the_published_files_are_staged_and_the_rest_named(self):
        src = _corpus(**{".DS_Store": "x", "scratch.txt": "notes"})
        counts = stage(src, tempfile.mkdtemp())
        assert counts["written"] == 3
        assert counts["withheld"] == [".DS_Store", "scratch.txt"]

    def test_a_host_path_is_redacted_in_a_jsonl_row(self):
        src = _corpus()
        into = tempfile.mkdtemp()
        stage(src, into)
        staged = Path(into, os.path.basename(src), "results", "m.jsonl").read_text()
        assert HOST_PATH not in staged
        assert json.loads(staged)["id"] == "e1"

    def test_the_source_is_never_touched(self):
        src = _corpus()
        before = Path(src, "results", "m.jsonl").read_text()
        stage(src, tempfile.mkdtemp())
        assert Path(src, "results", "m.jsonl").read_text() == before
        assert HOST_PATH in before

    def test_a_link_out_of_the_tree_is_refused(self):
        src = _corpus()
        outside = tempfile.mkdtemp()
        Path(outside, "secret.jsonl").write_text("{}")
        os.symlink(Path(outside, "secret.jsonl"), Path(src, "results", "link.jsonl"))
        with pytest.raises(ArchiveRefused):
            stage(src, tempfile.mkdtemp())

    def test_a_directory_with_nothing_to_ship_is_refused(self):
        src = tempfile.mkdtemp(prefix="eval_results_monitor_test_")
        Path(src, "notes.md").write_text("x")
        with pytest.raises(ArchiveRefused):
            stage(src, tempfile.mkdtemp())


class TestThePasswordIsThePublishedOne:
    def test_it_appears_in_the_operations_doc(self):
        text = (PROJECT_ROOT / "docs" / "operations.md").read_text(encoding="utf-8")
        assert archive.ARCHIVE_PASSWORD in text


@pytest.mark.skipif(shutil.which("zip") is None or shutil.which("unzip") is None,
                    reason="zip and unzip are needed to build an archive")
class TestTheArchiveRoundTrips:
    def test_it_encrypts_and_unpacks_redacted(self):
        src = _corpus()
        out = Path(tempfile.mkdtemp(), "eval_results_monitor_test.zip")
        archive.build(src, str(out))
        assert out.exists()
        unpacked = tempfile.mkdtemp()
        import subprocess
        subprocess.run(["unzip", "-q", "-P", archive.ARCHIVE_PASSWORD, str(out),
                        "-d", unpacked], check=True)
        names = sorted(p.relative_to(unpacked).as_posix()
                       for p in Path(unpacked).rglob("*") if p.is_file())
        stem = os.path.basename(src)
        assert names == sorted(f"{stem}/{n}" for n in
                               ("manifest.json", "api_usage.jsonl", "results/m.jsonl"))
        for p in Path(unpacked).rglob("*.jsonl"):
            assert HOST_PATH not in p.read_text()

    def test_it_needs_the_password(self):
        src = _corpus()
        out = Path(tempfile.mkdtemp(), "eval_results_monitor_test.zip")
        archive.build(src, str(out))
        import subprocess
        bad = subprocess.run(["unzip", "-q", "-P", "wrong", str(out), "-d",
                              tempfile.mkdtemp()], capture_output=True)
        assert bad.returncode != 0

    def test_a_leak_that_survives_redaction_is_refused(self, monkeypatch):
        """The host check must be able to say no: with redaction disabled the
        staged copy still names the host and no archive is written."""
        monkeypatch.setattr(archive, "redact_paths", lambda text: text)
        src = _corpus()
        out = Path(tempfile.mkdtemp(), "eval_results_monitor_test.zip")
        with pytest.raises(ArchiveRefused):
            archive.build(src, str(out))
        assert not out.exists()


def test_the_cli_names_a_missing_directory():
    with pytest.raises(SystemExit):
        archive.main(["--dir", "/nonexistent-" + re.sub(r"\W", "", os.urandom(4).hex())])
