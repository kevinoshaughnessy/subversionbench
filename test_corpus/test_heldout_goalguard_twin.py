"""
The goal-guarding held-out twin: a bundle of its own, so that the two held-out
scenarios share no name a reader could match one against the other on.

Three ways that could quietly stop being true: the tool acting on the mainline
twin when asked for the goal-guarding one, the mainline twin pinning (and so
allowing) a goal-guarding arm under its shared names, and run_heldout.sh
starting a goal-guarding batch under the wrong twin.
"""

import os
import re
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path

import heldout_tool as ht

from test_corpus.heldout_fixtures import BUNDLE_PATH, PROJECT_ROOT, _heldout_bundle

_SELECTED = ("BUNDLE_PATH", "WORKING_COPY", "PINS_PATH", "ROLLOUT_VERSION",
             "_twin")


class _twin_selected:
    """heldout_tool pointed at the goal-guarding twin for the block, and put
    back after, since the selection rebinds module globals."""

    def __enter__(self):
        self.saved = {name: getattr(ht, name) for name in _SELECTED}
        ht.use_goalguard_twin()
        return self

    def __exit__(self, *exc):
        for name, value in self.saved.items():
            setattr(ht, name, value)
        return False


class TestTheToolActsOnTheTwinItWasAskedFor:
    def test_every_path_and_the_rollout_name_move_together(self):
        before = {name: getattr(ht, name) for name in _SELECTED}
        with _twin_selected():
            after = {name: getattr(ht, name) for name in _SELECTED}
        for name in _SELECTED:
            assert after[name] != before[name], name
        assert {name: getattr(ht, name) for name in _SELECTED} == before
        for name in ("BUNDLE_PATH", "WORKING_COPY", "PINS_PATH"):
            assert after[name].parent == ht.HELDOUT_DIR, name
        # zip.sh recognises a held-out corpus by this word in its rollout name.
        assert "heldout" in after["ROLLOUT_VERSION"]

    def test_only_the_goalguard_twin_pins_goal_guarding_cells(self):
        computed = []
        saved = ht.load_heldout, ht._under_the_override
        ht.load_heldout = lambda path=None: {"goalguard": {}}
        ht._under_the_override = lambda *a: computed.append(a) or {"cell": 1}
        try:
            assert ht._goalguard_fingerprints(Path("x")) == {}
            assert not computed, "the mainline twin computed goal-guarding pins"
            with _twin_selected():
                assert ht._goalguard_fingerprints(Path("x")) == {"cell": 1}
        finally:
            ht.load_heldout, ht._under_the_override = saved


def _stubbed_run_heldout(tmp):
    """run_heldout.sh in a copy whose heldout_tool.py records its arguments
    and exports nothing, and whose run_all_arms.sh does nothing."""
    shutil.copy(PROJECT_ROOT / "run_heldout.sh", tmp)
    Path(tmp, "heldout_tool.py").write_text(
        "import sys\n"
        "open('tool_args', 'w').write(' '.join(sys.argv[1:]))\n"
        "print('')\n", encoding="utf-8")
    arms = Path(tmp, "run_all_arms.sh")
    arms.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    arms.chmod(arms.stat().st_mode | stat.S_IXUSR)


def _exported_with(*args):
    with tempfile.TemporaryDirectory() as tmp:
        _stubbed_run_heldout(tmp)
        env = {**os.environ, "PYTHONPATH": str(PROJECT_ROOT)}
        env.pop("SUBVERSIONBENCH_SCENARIO_BUNDLE", None)
        result = subprocess.run(["bash", "run_heldout.sh", *args], cwd=tmp,
                                env=env, capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        return Path(tmp, "tool_args").read_text(encoding="utf-8").split()


class TestRunHeldoutChoosesTheTwinFromTheArms:
    def test_a_goal_guarding_batch_exports_the_goal_guarding_twin(self):
        assert _exported_with("--model", "m", "--goalguards",
                              "replacement,deferred") == ["--export",
                                                          "--goalguard"]

    def test_a_goal_guarding_capability_run_does_too(self):
        assert "--goalguard" in _exported_with("--capability", "goalguard")

    def test_a_mainline_batch_exports_the_mainline_twin(self):
        assert _exported_with("--model", "m", "--runs", "10") == ["--export"]


def _names(bundle):
    """The proper names the bundle declares: its client and the words of its
    contamination list. The list also holds two technical strings, which are
    not words and are left out."""
    terms = [bundle["client_name"], *bundle["contaminating_terms"]]
    return {t for t in terms if t.isalpha()}


def _text(value):
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return "\n".join(_text(v) for v in value.values())
    if isinstance(value, list):
        return "\n".join(_text(v) for v in value)
    return ""


def test_the_two_held_out_twins_share_no_declared_name():
    """Read from the bundles, so no name is written here. ponytail: covers
    the names each bundle declares; a surname that is never declared is
    checked by hand when a twin is renamed."""
    mainline = _heldout_bundle()
    goalguard = _heldout_bundle(BUNDLE_PATH.with_name(
        ht.GOALGUARD_BUNDLE_PATH.name))
    for names, other in ((_names(mainline), goalguard),
                         (_names(goalguard), mainline)):
        assert names, "a bundle declared no names, so nothing was checked"
        text = _text(other)
        shared = [n for n in names
                  if re.search(rf"\b{re.escape(n)}\b", text, re.IGNORECASE)]
        assert not shared, f"{len(shared)} name(s) appear in both twins"
