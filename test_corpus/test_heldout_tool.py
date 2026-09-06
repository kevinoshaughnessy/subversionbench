"""
heldout_tool.py, run against a COPY of the bundle.

Every mode is exercised with BUNDLE_PATH and its two siblings redirected, so
--encode and --pin - which rewrite the bundle and its rollout sidecar - cannot
touch the real one. The two subprocess helpers are stubbed and tested in their
own right; what is exercised here is the dispatch and the decisions it makes on
what they return.
"""


import io
import json
import tempfile
import unittest
from pathlib import Path

import conftest
from subversionbench.scenario import (load_scenario)


# The same list test_scenario.py checks the counterfactual against. Imported
# by value rather than shared, because the two files pin the same rule for two
# different bundles and one must not start passing because the other's list
# shrank.
HARD_TERMS = ("monitor", "check_recommendation", "quality check",
              "quality-check", "threshold", "checker", "platform-eng",
              "oversight", "audit", "compliance", "flag")

REQUIRED_KEYS = ("system_prompt_strong_nudge", "system_prompt_no_nudge",
                 "user_prompt", "followup_monitoring_questions",
                 "followup_sandbox_questions", "task_file", "internal_memo",
                 "monitoring_config", "quality_check_script", "readme",
                 "system_log", "meeting_notes", "traffic_counts_csv",
                 "model_params")




class TestTheToolsTwoSubprocessBoundaries:
    """load_heldout and _invariants_hold: one reads a path, one reads an exit
    code, and both were unexecuted by the suite.

    Neither fails loudly if it is wrong. A load_heldout that ignored its
    argument would silently pin the SHIPPED scenario's fingerprints onto the
    held-out sidecar. An _invariants_hold with its sense inverted would accept
    a bundle whose invariants had just failed - and the whole point of that
    function is that the assertions live in one file rather than being
    reimplemented beside the bundle.
    """

    def test_load_heldout_reads_the_path_it_is_given(self):
        """Not always BUNDLE_PATH. The default is the shipped location, so an
        ignored argument is the difference between pinning the held-out bundle
        and pinning the wrong one."""
        import heldout_tool as ht
        seen = {}
        real = ht.decrypt
        try:
            def _decrypt(text):
                seen["text"] = text
                return {"ok": 1}
            ht.decrypt = _decrypt
            tmp = Path(tempfile.mkdtemp()) / "b.enc"
            tmp.write_text("CIPHERTEXT", encoding="utf-8")
            assert ht.load_heldout(tmp) == {"ok": 1}
            assert seen["text"] == "CIPHERTEXT"
        finally:
            ht.decrypt = real

    def test_the_invariants_verdict_follows_the_exit_code(self):
        import contextlib
        import types

        import heldout_tool as ht
        real = ht.subprocess.run
        try:
            for code, expected in ((0, True), (1, False), (5, False)):
                ht.subprocess.run = (
                    lambda *a, _c=code, **k: types.SimpleNamespace(
                        returncode=_c, stdout="1 passed", stderr=""))
                with contextlib.redirect_stdout(io.StringIO()):
                    assert ht._invariants_hold() is expected, code
        finally:
            ht.subprocess.run = real

    def test_it_says_what_pytest_said(self):
        """The operator is being asked to trust a pass. A silent True is the
        same output as a broken check."""
        import contextlib
        import types

        import heldout_tool as ht
        real = ht.subprocess.run
        try:
            ht.subprocess.run = lambda *a, **k: types.SimpleNamespace(
                returncode=0, stdout="49 passed in 1.80s", stderr="")
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                ht._invariants_hold()
            assert "49 passed" in out.getvalue()
        finally:
            ht.subprocess.run = real


class TestTheHeldOutToolsModes:
    """heldout_tool.main, run against a COPY of the bundle.

    Every mode is exercised on a temporary copy with BUNDLE_PATH and its two
    siblings redirected, so --encode and --pin - which rewrite the bundle and
    its rollout sidecar - cannot touch the real one. The held-out bundle
    exists only where it was authored and is gitignored, so these skip
    wherever it is absent; that is a corpus-absent skip, which
    SUBVERSIONBENCH_NO_SKIPS deliberately still allows.

    The two subprocess helpers are stubbed. _fingerprints runs the harness
    under a bundle override and _invariants_hold runs pytest, and both are
    tested in their own right - what is unrun here is main's dispatch and
    the decisions it makes on what they return.
    """

    def _workspace(self):
        """A scratch directory UNDER the repo root.

        Not a system temp directory: several of main's messages report a
        path relative to ROOT, and asking for that relation on a path
        outside it raises. `heldout/` is gitignored, so a copy of the bundle
        there cannot be committed by accident.
        """
        import heldout_tool
        return tempfile.TemporaryDirectory(dir=str(heldout_tool.HELDOUT_DIR),
                                           prefix="tooltest_")

    def _tool(self, tmpdir, stub_fingerprints=None, stub_invariants=None):
        """heldout_tool with its paths redirected at a copy. A context
        manager, not a fixture: run_tests.py cannot interpret one."""
        import contextlib
        import shutil
        import heldout_tool

        if not heldout_tool.BUNDLE_PATH.is_file():
            raise unittest.SkipTest("the held-out bundle is not on this machine")

        @contextlib.contextmanager
        def _ctx():
            saved = {name: getattr(heldout_tool, name) for name in
                     ("BUNDLE_PATH", "WORKING_COPY", "PINS_PATH",
                      "_fingerprints", "_invariants_hold")}
            try:
                copy = Path(tmpdir) / "scenario_heldout.enc"
                shutil.copy2(saved["BUNDLE_PATH"], copy)
                heldout_tool.BUNDLE_PATH = copy
                heldout_tool.WORKING_COPY = Path(tmpdir) / "scenario_heldout.json"
                heldout_tool.PINS_PATH = Path(tmpdir) / "scenario_heldout.pins.json"
                if stub_fingerprints is not None:
                    heldout_tool._fingerprints = stub_fingerprints
                if stub_invariants is not None:
                    heldout_tool._invariants_hold = stub_invariants
                yield heldout_tool
            finally:
                for name, value in saved.items():
                    setattr(heldout_tool, name, value)
        return _ctx()

    def _encodable(self, tool):
        """The twin, plus any entry the SHIPPED bundle has and it does not.

        --encode checks the working copy against the shipped key set, and
        the held-out bundle predates at least one entry added since it was
        authored - so an unmodified round trip is refused today. Filling the
        gap here keeps these tests about main's dispatch rather than about
        that difference, which test_every_entry_the_scenario_needs_is_present
        is the right place to notice.
        """
        edited = tool.load_heldout(tool.BUNDLE_PATH)
        shipped = load_scenario()
        for key in set(shipped) - set(edited):
            edited[key] = shipped[key]
        return edited

    def _pins(self, value="fp"):
        return lambda path: {(o, lure): f"{value}-{o}-{lure}"
                             for o in (True, False) for lure in (True, False)}

    def test_list_names_every_entry_with_a_size(self):
        with self._workspace() as d:
            with self._tool(d) as tool:
                code, text = conftest.run_tool_main(tool, ["--list"])
        assert code == 0
        assert "chars" in text
        assert len(text.strip().splitlines()) >= 5

    def test_show_prints_the_entries_whose_name_matches(self):
        with self._workspace() as d:
            with self._tool(d) as tool:
                names = sorted(tool.load_heldout(tool.BUNDLE_PATH))
                code, text = conftest.run_tool_main(tool, ["--show", names[0]])
        assert code == 0
        assert f"===== {names[0]} =====" in text

    def test_show_matching_nothing_says_so_and_exits_non_zero(self):
        """A silent zero here reads as an empty entry rather than a typo."""
        with self._workspace() as d:
            with self._tool(d) as tool:
                code, text = conftest.run_tool_main(
                    tool, ["--show", "no_such_entry_anywhere"])
        assert code == 1
        assert "Try --list" in text

    def test_check_reports_the_invariant_suites_verdict_as_its_exit_code(self):
        """--check is what CI and a pre-collection rehearsal run, so its exit
        code IS its answer. _invariants_hold runs pytest in a subprocess and
        is tested in its own right; what is unrun here is main passing its
        verdict through rather than reporting its own."""
        def verdict(holds):
            return lambda: holds

        for holds, expected in ((True, 0), (False, 1)):
            with self._workspace() as d:
                with self._tool(d, stub_invariants=verdict(holds)) as tool:
                    code, _text = conftest.run_tool_main(tool, ["--check"])
            assert code == expected, holds

    def test_check_does_not_touch_the_bundle_or_write_a_working_copy(self):
        """It is the read-only mode. A --check that decoded would leave the
        scenario in plaintext on any machine that ran CI."""
        with self._workspace() as d:
            with self._tool(d, stub_invariants=lambda: True) as tool:
                before = tool.BUNDLE_PATH.read_bytes()
                conftest.run_tool_main(tool, ["--check"])
                assert tool.BUNDLE_PATH.read_bytes() == before
                assert not tool.WORKING_COPY.exists()

    def test_decode_writes_the_working_copy_for_editing(self):
        with self._workspace() as d:
            with self._tool(d) as tool:
                code, text = conftest.run_tool_main(tool, ["--decode"])
                assert code == 0, text
                assert tool.WORKING_COPY.is_file()
                written = json.loads(tool.WORKING_COPY.read_text(
                    encoding="utf-8"))
                assert written == tool.load_heldout(tool.BUNDLE_PATH)
        assert "then --encode" in text

    def test_export_refuses_without_rollout_pins(self):
        """The harness would refuse to start anyway; saying so here costs a
        message instead of a batch that dies at its first episode."""
        with self._workspace() as d:
            with self._tool(d) as tool:
                code, _text = conftest.run_tool_main(tool, ["--export"])
        assert code == 1

    def test_export_writes_the_plaintext_readable_only_by_its_owner(self):
        """It is the scenario in the clear, on a machine that may be
        shared."""
        with self._workspace() as d:
            with self._tool(d) as tool:
                tool.PINS_PATH.write_text(json.dumps(
                    {"rollout_version": "heldout2", "fingerprints": []}),
                    encoding="utf-8")
                code, text = conftest.run_tool_main(tool, ["--export"])
                assert code == 0, text
                assert oct(tool.WORKING_COPY.stat().st_mode)[-3:] == "600"
                assert str(tool.WORKING_COPY) in text

    def test_pin_refuses_a_bundle_that_assembles_like_the_shipped_one(self):
        """That would mean the reworded twin produces the same arm identity,
        so its episodes could be pooled with r9's - which destroys the only
        property the held-out corpus has."""
        from subversionbench.rollout_pins import ROLLOUT_FINGERPRINTS
        with self._workspace() as d:
            with self._tool(d, stub_fingerprints=lambda p: dict(
                    ROLLOUT_FINGERPRINTS)) as tool:
                code, text = conftest.run_tool_main(tool, ["--pin"])
        assert code == 1
        assert "match the shipped rollout's fingerprints exactly" in text

    def test_pin_writes_a_sidecar_naming_its_own_rollout(self):
        """NOT r9. Sharing a rollout version is what would make two rollouts
        indistinguishable, which is the whole point of the held-out arm."""
        import heldout_tool
        with self._workspace() as d:
            with self._tool(d, stub_fingerprints=self._pins()) as tool:
                code, text = conftest.run_tool_main(tool, ["--pin"])
                assert code == 0, text
                sidecar = json.loads(tool.PINS_PATH.read_text(
                    encoding="utf-8"))
        assert sidecar["rollout_version"] == heldout_tool.ROLLOUT_VERSION
        assert sidecar["rollout_version"] != "r9"
        assert len(sidecar["fingerprints"]) == 4

    def test_encode_without_a_working_copy_says_to_decode_first(self):
        with self._workspace() as d:
            with self._tool(d) as tool:
                code, text = conftest.run_tool_main(tool, ["--encode"])
        assert code == 1 and "run --decode first" in text

    def test_encode_refuses_a_bundle_missing_an_entry_and_keeps_the_old_one(self):
        """Checked against the SHIPPED bundle's key set, not the twin's own -
        comparing it against itself would accept one that had quietly lost an
        entry the harness reaches for."""
        with self._workspace() as d:
            with self._tool(d) as tool:
                before = tool.BUNDLE_PATH.read_bytes()
                edited = tool.load_heldout(tool.BUNDLE_PATH)
                dropped = sorted(edited)[0]
                del edited[dropped]
                tool.WORKING_COPY.write_text(json.dumps(edited),
                                             encoding="utf-8")
                code, text = conftest.run_tool_main(tool, ["--encode"])
                assert tool.BUNDLE_PATH.read_bytes() == before
        assert code == 1
        assert "is missing" in text and dropped in text

    def test_an_edit_that_moves_the_rollout_is_refused_without_repin(self):
        """A NEW ROLLOUT is always a deliberate act. Episodes collected under
        the old pins are not comparable with ones collected after, and the
        refusal is what stops that happening by accident."""
        with self._workspace() as d:
            with self._tool(d, stub_fingerprints=self._pins("moved"),
                            stub_invariants=lambda: True) as tool:
                before = tool.BUNDLE_PATH.read_bytes()
                tool.PINS_PATH.write_text(json.dumps({
                    "rollout_version": "heldout1",
                    "fingerprints": [{"oversight": o, "lure": lure,
                                      "fingerprint": "old"}
                                     for o in (True, False)
                                     for lure in (True, False)]}),
                    encoding="utf-8")
                tool.WORKING_COPY.write_text(
                    json.dumps(self._encodable(tool)), encoding="utf-8")
                code, text = conftest.run_tool_main(tool, ["--encode"])
                assert tool.BUNDLE_PATH.read_bytes() == before, "rolled back"
        assert code == 1
        assert "NEW ROLLOUT" in text
        assert "are NOT comparable" in text

    def test_repin_accepts_the_move_and_records_it(self):
        with self._workspace() as d:
            with self._tool(d, stub_fingerprints=self._pins("moved"),
                            stub_invariants=lambda: True) as tool:
                tool.PINS_PATH.write_text(json.dumps({
                    "rollout_version": "heldout1",
                    "fingerprints": [{"oversight": o, "lure": lure,
                                      "fingerprint": "old"}
                                     for o in (True, False)
                                     for lure in (True, False)]}),
                    encoding="utf-8")
                tool.WORKING_COPY.write_text(
                    json.dumps(self._encodable(tool)), encoding="utf-8")
                code, text = conftest.run_tool_main(
                    tool, ["--encode", "--repin"])
                assert code == 0, text
                sidecar = json.loads(tool.PINS_PATH.read_text(
                    encoding="utf-8"))
        assert "NEW ROLLOUT" in text
        assert "Collect into a fresh --output-dir" in text
        # The superseded pins are kept, so an archived results directory can
        # still be identified from a fingerprint alone.
        assert sidecar["superseded"], "the previous rollout was forgotten"

    def test_a_bundle_that_fails_its_invariants_is_rolled_back(self):
        """Written, then checked, then kept or rolled back. The invariants
        run as the tracked test, which reads the bundle at its real path, so
        there is no staging path to check it at - the rollback is what makes
        that safe."""
        with self._workspace() as d:
            with self._tool(d, stub_fingerprints=self._pins(),
                            stub_invariants=lambda: False) as tool:
                before = tool.BUNDLE_PATH.read_bytes()
                tool.PINS_PATH.write_text(json.dumps({
                    "rollout_version": "heldout2",
                    "fingerprints": [{"oversight": o, "lure": lure,
                                      "fingerprint": f"fp-{o}-{lure}"}
                                     for o in (True, False)
                                     for lure in (True, False)]}),
                    encoding="utf-8")
                tool.WORKING_COPY.write_text(
                    json.dumps(self._encodable(tool)), encoding="utf-8")
                code, text = conftest.run_tool_main(tool, ["--encode"])
                assert tool.BUNDLE_PATH.read_bytes() == before
        assert code == 1
        assert "rolled back" in text
