"""
The root scripts an operator runs, and the helpers inside them nothing called.

Eighteen functions in this repository were never executed by the suite, found
by reading coverage rather than by grepping for call sites - a name can appear
in a comment, and an indirect call appears nowhere. Most of them were in these
scripts: the tools are the part of the codebase that ships without a test file
of its own, because each is "just a CLI" until it stops working.

WHAT A SMOKE TEST OVER --help IS ACTUALLY WORTH HERE. It runs the module's
imports, builds its parser, and exits. That catches the failures these scripts
really have - an import removed in a refactor, an argparse call with a bad
default, a helper renamed at one of two call sites - none of which the rest of
the suite can see, and all of which surface as a traceback in front of an
operator who is part-way through something expensive.

Derived from the directory rather than from a list, so a script added later
inherits the check instead of escaping it.
"""

import io
import subprocess
import sys

import conftest


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


class TestContaminationCheckHelpers:
    """contamination_check.py's two pure helpers, neither previously run."""

    def test_tracked_files_lists_what_git_would_ship(self):
        import contamination_check as cc
        files = cc.tracked_files()
        assert files, "no tracked files - the crawler's view cannot be empty"
        assert "AGENTS.md" in files and "pyproject.toml" in files
        assert all(not p.startswith("/") for p in files), "expected repo-relative"

    def test_tracked_files_is_empty_rather_than_fatal_without_git(self):
        """It answers "what would a crawler see". Outside a checkout the honest
        answer is nothing, and a traceback there would stop the whole check
        over a question that has a sensible answer."""
        import contamination_check as cc
        real = cc.subprocess.run
        try:
            def _missing(*a, **k):
                raise FileNotFoundError("git")
            cc.subprocess.run = _missing
            assert cc.tracked_files() == []
        finally:
            cc.subprocess.run = real

    def _summary(self, **over):
        base = {
            "verdict": "clean",
            "signals": [],
            "forced_choice": {
                "scenario": {"hits": 1, "n": 4, "rate": 0.25},
                "control": {"hits": 1, "n": 4, "rate": 0.25},
                "chance_rate": 0.25, "p_vs_control": 0.5,
            },
            "continuation": {"scenario_overlap": None, "control_overlap": None},
        }
        base.update(over)
        return base

    def test_print_verdict_names_the_model_and_the_verdict(self):
        import contextlib

        import contamination_check as cc
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            cc.print_verdict("some/model", self._summary())
        text = out.getvalue()
        assert "some/model" in text and "CLEAN" in text

    def test_print_verdict_shows_every_signal_it_was_given(self):
        """The signals are the finding. One dropped in formatting is a
        contamination indicator that was computed and never seen."""
        import contextlib

        import contamination_check as cc
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            cc.print_verdict("m", self._summary(
                verdict="suspect", signals=["recalled the memo", "named it"]))
        text = out.getvalue()
        assert "recalled the memo" in text and "named it" in text

    def test_print_verdict_survives_a_run_with_no_forced_choice(self):
        """n=0 is the shape a --quick run produces, and dividing by it or
        formatting None would end the report part-way through."""
        import contextlib

        import contamination_check as cc
        summary = self._summary()
        summary["forced_choice"]["scenario"]["n"] = 0
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            cc.print_verdict("m", summary)
        assert "m" in out.getvalue()


class TestRubricABCells:
    """The grid rubric_ab fans out over."""

    def test_every_grader_is_paired_with_every_wording(self):
        import rubric_ab
        graders = ("a", "b")
        wordings = (("w1", "q1"), ("w2", "q2"))
        got = list(rubric_ab.cells("k", graders, wordings))
        assert got == [("a", "w1", "q1"), ("a", "w2", "q2"),
                       ("b", "w1", "q1"), ("b", "w2", "q2")]

    def test_an_empty_axis_yields_no_work(self):
        """A missing wording list must produce no cells rather than one cell
        with a missing question - the A/B is meaningless without both axes."""
        import rubric_ab
        assert list(rubric_ab.cells("k", ("a",), ())) == []
        assert list(rubric_ab.cells("k", (), (("w", "q"),))) == []
