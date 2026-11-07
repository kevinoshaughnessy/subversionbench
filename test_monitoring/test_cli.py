"""
The two command lines: `python3 -m monitoring` draws, dispatches and reports
end to end on a scratch corpus, and the bundle tool edits and re-pins a copy of
the bundle without ever touching the shipped one.
"""

import contextlib
import io
import json
import os
import shutil
import tempfile
from pathlib import Path
from unittest import mock

from monitoring import __main__ as cli
from monitoring import bundle as monitor_bundle
from monitoring.bundle import check_pins, fingerprints, load_bundle, load_pins
from monitoring.render import CUTS, VIEWS
from monitoring.run import RESULTS_DIR

from test_monitoring.test_sample import _episode


def _corpus_root():
    """A root holding a mainline corpus of three acts and plenty of negatives."""
    root = tempfile.mkdtemp()
    corpus = os.path.join(root, "eval_results_r10")
    os.makedirs(corpus)
    episodes = [_episode("m/a", "oversight")] * 3 + [_episode("m/a")] * 6
    for i, e in enumerate(episodes):
        with open(os.path.join(corpus, f"run_{i}_x.json"), "w", encoding="utf-8") as f:
            json.dump(e, f)
    return root


def _main(*argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = cli.main(list(argv))
    return code, out.getvalue()


def _write_rows(out_dir, manifest, fingerprint_for):
    os.makedirs(os.path.join(out_dir, RESULTS_DIR))
    rows = [{"monitor": "m", "id": e["id"], "view": view, "cut": cut,
             "fingerprint": fingerprint_for(view, cut),
             "suspicion": 90 if e["label"] == "act" else 5}
            for e in manifest["episodes"] for view in VIEWS for cut in CUTS]
    with open(os.path.join(out_dir, RESULTS_DIR, "m.jsonl"), "w",
              encoding="utf-8") as f:
        f.writelines(json.dumps(r) + "\n" for r in rows)


class TestTheMonitoringCommand:
    def test_sample_then_report(self):
        root, out = _corpus_root(), os.path.join(tempfile.mkdtemp(), "monitor")
        code, text = _main("--output-dir", out, "--corpus-root", root,
                           "sample", "--arms", "mainline-r10", "--seed", "1")
        assert code == 0 and text.startswith("3 episodes with an act and 3 without")
        with open(os.path.join(out, "manifest.json"), encoding="utf-8") as f:
            manifest = json.load(f)
        pins = fingerprints(load_bundle())
        _write_rows(out, manifest, lambda view, cut: pins[f"{view}/{cut}"])
        with open(os.path.join(out, RESULTS_DIR, "m.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps({"monitor": "m", "id": "x", "view": VIEWS[0],
                                "cut": CUTS[0], "fingerprint": "stale",
                                "suspicion": 1}) + "\n")
        code, text = _main("--output-dir", out, "--corpus-root", root, "report")
        assert code == 0
        assert "== headline acts (all pairs)" in text
        assert "by whether their scheming keywords matched" in text
        assert "1 rows under an earlier fingerprint left out." in text

    def test_a_manifest_without_the_scheming_tag_reads_it_from_the_episode(self):
        root = tempfile.mkdtemp()
        with open(os.path.join(root, "e.json"), "w", encoding="utf-8") as f:
            json.dump({"analysis": {"scheming_keywords": ["a match"]}}, f)
        manifest = {"episodes": [{"id": "p", "label": "act"},
                                 {"id": "old", "label": "clean", "path": "e.json"},
                                 {"id": "new", "label": "clean",
                                  "scheming_keywords": False}]}
        assert cli._scheming_flags(manifest, root) == {"old": True, "new": False}

    def test_run_is_handed_every_option(self):
        with mock.patch("monitoring.run.run_monitor", return_value=0) as run:
            code, _ = _main("--output-dir", "o", "run", "--monitor", "m/x",
                            "--views", VIEWS[0], "--cuts", f"{CUTS[0]},{CUTS[1]}",
                            "--limit", "4", "--dry-run")
        assert code == 0
        run.assert_called_once_with("o", "m/x", None, (VIEWS[0],),
                                    (CUTS[0], CUTS[1]), 4, True, False, 4, ".")

    def test_an_unknown_view_is_refused_before_anything_runs(self):
        with mock.patch("monitoring.run.run_monitor") as run, \
             contextlib.redirect_stderr(io.StringIO()):
            for views in ("nonsense", ","):
                try:
                    cli.main(["run", "--monitor", "m/x", "--views", views])
                except SystemExit as e:
                    assert e.code == 2
                    continue
                raise AssertionError(f"--views {views!r} was accepted")
        run.assert_not_called()


@contextlib.contextmanager
def _bundle_copy():
    """Point the bundle tool at scratch copies of the bundle and its pins."""
    scratch = Path(tempfile.mkdtemp())
    bundle_path, pins_path = scratch / "monitor.b64", scratch / "monitor.pins.json"
    shutil.copy(monitor_bundle._BUNDLE_PATH, bundle_path)
    shutil.copy(monitor_bundle._PINS_PATH, pins_path)
    with mock.patch.object(monitor_bundle, "_BUNDLE_PATH", bundle_path), \
         mock.patch.object(monitor_bundle, "_PINS_PATH", pins_path):
        yield bundle_path, pins_path


def _bundle_main(*argv, stdin=""):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), \
         mock.patch("sys.stdin", io.StringIO(stdin)):
        code = monitor_bundle._main(list(argv))
    return code, out.getvalue(), err.getvalue()


class TestTheBundleTool:
    def test_list_and_show(self):
        with _bundle_copy():
            code, text, _ = _bundle_main("--list")
            assert code == 0 and "question" in text and "system_prompt" in text
            code, text, _ = _bundle_main("--show", "question")
            assert code == 0 and text.strip() == load_bundle()["question"].strip()

    def test_show_of_a_missing_entry_fails(self):
        with _bundle_copy():
            code, text, err = _bundle_main("--show", "no-such-entry")
        assert code == 1 and not text and "--list" in err

    def test_set_unpins_and_pin_repins_the_copy_only(self):
        shipped = monitor_bundle._BUNDLE_PATH.read_text(encoding="utf-8")
        with _bundle_copy() as (bundle_path, pins_path):
            code, _, _ = _bundle_main("--set", "question", stdin="  replaced  \n")
            assert code == 0
            edited = load_bundle(bundle_path)
            assert edited["question"] == "replaced"
            try:
                check_pins(edited, load_pins(pins_path))
            except ValueError:
                pass
            else:
                raise AssertionError("an edited bundle still matched its pins")
            code, _, _ = _bundle_main("--pin")
            assert code == 0
            check_pins(edited, load_pins(pins_path))
        assert monitor_bundle._BUNDLE_PATH.read_text(encoding="utf-8") == shipped
        check_pins(load_bundle())
