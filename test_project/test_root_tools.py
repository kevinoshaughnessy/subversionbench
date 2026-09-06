"""
Every root script an operator invokes: does it start, and does it refuse before
it spends?

A script that raises on import is a script nobody can run, and one that starts
a paid run before checking its arguments is worse. What is exercised here is
the boundary each one has to get right before any money is at stake.
"""


import contextlib
import pathlib
import string
import subprocess
import sys
import tempfile

import conftest
from test_project.tool_fixtures import _ProbeSpy


def _root_scripts() -> list:
    """Every root script with a __main__ guard, as repo-relative paths."""
    found = []
    for path in sorted(conftest.PROJECT_ROOT.glob("*.py")):
        if path.name.startswith("test_") or path.name in ("conftest.py",
                                                          "run_tests.py"):
            continue
        source = path.read_text(encoding="utf-8")
        if 'if __name__ == "__main__"' in source and "argparse" in source:
            found.append(path)
    return found


class TestEveryRootScriptStillStarts:
    """The cheapest check that a tool is not broken, run over all of them."""

    def test_the_script_list_is_not_empty(self):
        """A glob that matches nothing empties the scope and every check built
        on it passes. This suite has been bitten by exactly that."""
        assert len(_root_scripts()) >= 8, [p.name for p in _root_scripts()]

    def test_each_one_answers_help_without_a_traceback(self):
        """--help imports the module and builds its parser, which is where a
        broken tool breaks. It spends nothing and reaches no model."""
        failures = []
        for path in _root_scripts():
            done = subprocess.run(
                [sys.executable, str(path), "--help"],
                cwd=str(conftest.PROJECT_ROOT), capture_output=True,
                text=True, timeout=120)
            if done.returncode != 0 or "Traceback" in done.stderr:
                failures.append(
                    f"{path.name}: exit={done.returncode} "
                    f"{done.stderr.strip().splitlines()[-1] if done.stderr else ''}")
        assert not failures, "\n".join(failures)

    def test_each_one_describes_itself(self):
        """A --help with no description is a tool whose purpose lives only in
        whoever wrote it. Checked because these scripts have no README entry
        beyond a one-line table row in docs/Layout.md."""
        thin = []
        for path in _root_scripts():
            done = subprocess.run(
                [sys.executable, str(path), "--help"],
                cwd=str(conftest.PROJECT_ROOT), capture_output=True,
                text=True, timeout=120)
            body = done.stdout.split("options:")[0]
            if len(body.split()) < 12:
                thin.append(path.name)
        assert not thin, f"these print a --help that explains nothing: {thin}"


class TestRubricABRefusesBeforeItSpends:
    """Both of main()'s guard paths return 1 without making a call.

    Each is reached before the grid runs, which matters because the grid is
    one call per episode per cell - a 20-episode pilot over a 2x2 is 80.
    """

    def test_a_directory_with_no_matching_runs_is_a_refusal(self):
        import rubric_ab
        with tempfile.TemporaryDirectory() as d:
            code, text = conftest.run_tool_main(rubric_ab, [
                "--model", "x-ai/grok-4.5", "--output-dir", d])
        assert code == 1
        assert "No run files" in text

    def test_a_question_with_no_superseded_wording_is_a_refusal(self):
        """Comparing the shipped wording against itself would report a
        Fisher p of 1 and prove nothing, having paid for every call."""
        import rubric_ab
        from subversionbench.config import RUBRIC_QUESTIONS
        unrecorded = sorted(set(RUBRIC_QUESTIONS) - set(rubric_ab.PREVIOUS_WORDINGS))
        assert unrecorded, "every question has a previous wording - pick another guard"
        with tempfile.TemporaryDirectory() as d:
            conftest.write_run_file(d, 1, "x-ai/grok-4.5", "strong")
            code, text = conftest.run_tool_main(rubric_ab, [
                "--model", "x-ai/grok-4.5", "--output-dir", d,
                "--question", unrecorded[0]])
        assert code == 1
        assert "PREVIOUS_WORDINGS" in text


class TestHeldoutToolFingerprints:
    """Computing a held-out bundle's four arm fingerprints.

    The awkward shape here is load-bearing and the docstring on the function
    says why: pinning has to run UNDER the bundle override, and rollout_pins
    refuses to import under the override without the very sidecar the pin is
    about to write. A provisional sidecar breaks that cycle, and the whole
    risk of the arrangement is that one is left behind - which would leave
    the bundle pinned to a value nothing produced, and the drift guard would
    then refuse every arm of the next batch.
    """

    def _tool(self, tmpdir):
        import heldout_tool
        heldout_tool.PINS_PATH = pathlib.Path(tmpdir) / "heldout.pins.json"
        return heldout_tool

    def _restoring(self, tmpdir):
        """heldout_tool with PINS_PATH redirected, put back afterwards."""
        import heldout_tool
        real = heldout_tool.PINS_PATH

        @contextlib.contextmanager
        def _ctx():
            try:
                yield self._tool(tmpdir)
            finally:
                heldout_tool.PINS_PATH = real
        return _ctx()

    def test_the_probe_runs_under_the_bundle_it_was_asked_about(self):
        """Not the shipped one. Fingerprinting an un-overridden process was
        the original defect: the fingerprint covers the sandbox display path
        and the task file's name as well as the text, so all four came back
        disagreeing with what any run reproduces."""
        with tempfile.TemporaryDirectory() as d:
            with self._restoring(d) as tool:
                bundle = pathlib.Path(d) / "twin.json"
                bundle.write_text("{}", encoding="utf-8")
                with _ProbeSpy(tool) as spy:
                    tool._fingerprints(bundle)
        assert spy.env_at_probe_time["SUBVERSIONBENCH_SCENARIO_BUNDLE"] == str(bundle)

    def test_the_probe_sees_a_sidecar_so_the_harness_will_import(self):
        with tempfile.TemporaryDirectory() as d:
            with self._restoring(d) as tool:
                with _ProbeSpy(tool) as spy:
                    tool._fingerprints(pathlib.Path(d) / "twin.json")
        assert spy.sidecar_at_probe_time is not None, \
            "without a sidecar rollout_pins refuses to import under the override"
        assert len(spy.sidecar_at_probe_time["fingerprints"]) == 4

    def test_the_provisional_value_can_never_be_read_as_a_real_fingerprint(self):
        """If a --pin is interrupted and one survives, the drift guard must
        refuse to start rather than accept it. Real fingerprints are hex."""
        with tempfile.TemporaryDirectory() as d:
            with self._restoring(d) as tool:
                with _ProbeSpy(tool) as spy:
                    tool._fingerprints(pathlib.Path(d) / "twin.json")
        provisional = {e["fingerprint"]
                       for e in spy.sidecar_at_probe_time["fingerprints"]}
        assert len(provisional) == 1
        value = provisional.pop()
        assert not all(c in string.hexdigits for c in value), \
            f"{value!r} could be mistaken for a fingerprint"

    def test_a_sidecar_that_was_not_there_is_not_there_afterwards(self):
        """Restores on EVERY exit, not only on failure. Leaving the
        provisional behind on success made the accept step implicit."""
        with tempfile.TemporaryDirectory() as d:
            with self._restoring(d) as tool:
                with _ProbeSpy(tool):
                    tool._fingerprints(pathlib.Path(d) / "twin.json")
                assert not tool.PINS_PATH.exists()

    def test_an_existing_sidecar_comes_back_byte_for_byte(self):
        with tempfile.TemporaryDirectory() as d:
            with self._restoring(d) as tool:
                before = b'{"rollout_version": "heldout1", "fingerprints": []}'
                tool.PINS_PATH.write_bytes(before)
                with _ProbeSpy(tool):
                    tool._fingerprints(pathlib.Path(d) / "twin.json")
                assert tool.PINS_PATH.read_bytes() == before

    def test_a_failed_probe_restores_the_sidecar_and_says_what_broke(self):
        with tempfile.TemporaryDirectory() as d:
            with self._restoring(d) as tool:
                before = b'{"rollout_version": "heldout1", "fingerprints": []}'
                tool.PINS_PATH.write_bytes(before)
                with _ProbeSpy(tool, returncode=1):
                    try:
                        tool._fingerprints(pathlib.Path(d) / "twin.json")
                    except RuntimeError as failure:
                        assert "probe failed" in str(failure)
                    else:
                        raise AssertionError("a failed probe must not return pins")
                assert tool.PINS_PATH.read_bytes() == before

    def test_each_arm_keeps_the_fingerprint_the_probe_reported_for_it(self):
        """JSON has no tuple key, so the probe reports a list of triples and
        this rebuilds the mapping. A pair rebuilt the wrong way round pins
        each arm to its neighbour's identity - four plausible-looking
        fingerprints, none of which that arm reproduces, and the drift guard
        then refuses every arm of the next batch."""
        with tempfile.TemporaryDirectory() as d:
            with self._restoring(d) as tool:
                with _ProbeSpy(tool):
                    pins = tool._fingerprints(pathlib.Path(d) / "twin.json")
        assert pins == {(o, lure): f"fp-o{o}-l{lure}"
                        for o in (True, False) for lure in (True, False)}


class TestHeldoutToolRefusesWithoutItsBundle:
    """The bundle is gitignored and exists only where it was authored, so
    every mode has to say that rather than traceback on a missing file."""

    def test_a_missing_bundle_is_a_refusal_that_explains_itself(self):
        import heldout_tool
        real = heldout_tool.BUNDLE_PATH
        try:
            # Under ROOT, because the message reports the path relative to it.
            # A temp directory is not, and asking for that relation raises.
            heldout_tool.BUNDLE_PATH = heldout_tool.HELDOUT_DIR / "absent.enc"
            assert not heldout_tool.BUNDLE_PATH.exists()
            code, text = conftest.run_tool_main(heldout_tool, ["--list"])
        finally:
            heldout_tool.BUNDLE_PATH = real
        assert code == 1
        assert "not found" in text and "gitignored" in text
