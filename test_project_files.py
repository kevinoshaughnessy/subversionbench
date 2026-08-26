"""
The guards' idea of "the project" must match the project.

Every static check in this suite - undefined names, unused imports, the README
layout, the declared-dependency check - starts by deciding which files to look
at, and each of them used to decide separately. They disagreed: the
undefined-name guard globbed three named directories non-recursively and so
never examined `grading/`, `readmodes/`, `reporting/` or `reporting/facts/`,
which is 41 of 95 source files and includes every grader and every module that
computes a published figure.

A guard that silently examines less than it claims is worse than no guard,
because the passing result is read as evidence. So the file set is derived in
one place (`conftest.py`) and checked here against an independent source -
`git ls-files` - which is maintained by a different mechanism entirely and
therefore cannot drift in step with a mistake in the derivation.
"""

import ast
import subprocess
from pathlib import Path

from conftest import (PROJECT_ROOT, is_test_file, project_packages,
                      project_python_files, source_python_files,
                      suite_python_files)

# pytest is imported where it is used, not here: run_tests.py exists so the suite
# is runnable in a bare environment, and it loads each module by path - a
# top-level `import pytest` would make this file unloadable there.


def _git_tracked_python_files():
    """Tracked .py paths, or None where git cannot answer."""
    try:
        result = subprocess.run(["git", "ls-files", "*.py"],
                                capture_output=True, text=True,
                                cwd=PROJECT_ROOT)
    except OSError:
        return None
    if result.returncode != 0:
        return None
    return {Path(line) for line in result.stdout.splitlines() if line.strip()}


class TestTheDerivedFileSetMatchesTheRepository:
    def test_every_tracked_python_file_is_discovered(self):
        """The direction that matters. A tracked file the derivation misses is a
        file every static guard silently skips."""
        tracked = _git_tracked_python_files()
        if tracked is None:
            return                    # not a git checkout; nothing to compare to
        missed = sorted(tracked - set(project_python_files()))
        assert not missed, (
            "these files are in the repository but no static guard examines "
            "them:\n  " + "\n  ".join(str(p) for p in missed))

    def test_discovery_finds_nothing_outside_the_repository(self):
        """The other direction, allowing for files not yet committed: anything
        discovered must at least be a real path inside the project."""
        for p in project_python_files():
            assert (PROJECT_ROOT / p).is_file(), p
            assert not p.is_absolute(), p

    def test_untracked_files_are_still_examined(self):
        """A guard that only looked at tracked files would not see a module until
        it was committed, which is exactly when a mistake in it is cheapest to
        find."""
        new = PROJECT_ROOT / "_untracked_probe_.py"
        new.write_text("x = 1\n", encoding="utf-8")
        try:
            assert Path("_untracked_probe_.py") in project_python_files()
        finally:
            new.unlink()


class TestTheExclusionsAreByRuleNotByAccident:
    def test_no_discovered_file_lives_somewhere_excluded(self):
        excluded = {".git", ".venv", "build", "dist", "__pycache__",
                    "scratchpad", "report_snapshots"}
        for p in project_python_files():
            assert not (set(p.parts) & excluded), p
            assert not any(x.startswith("eval_results") for x in p.parts), p
            assert not any(x.endswith(".egg-info") for x in p.parts), p

    def test_a_file_in_an_excluded_directory_is_not_discovered(self):
        probe_dir = PROJECT_ROOT / "eval_results_probe_"
        probe_dir.mkdir(exist_ok=True)
        probe = probe_dir / "sneaky.py";  probe.write_text("y = 2\n", encoding="utf-8")
        try:
            found = project_python_files()
            assert Path("eval_results_probe_/sneaky.py") not in found
        finally:
            probe.unlink()
            probe_dir.rmdir()


class TestSourceAndTestsPartitionTheProject:
    def test_the_two_halves_are_disjoint_and_complete(self):
        source, tests = set(source_python_files()), set(suite_python_files())
        assert not (source & tests)
        assert source | tests == set(project_python_files())

    def test_both_halves_are_non_empty(self):
        """Either half coming back empty would make its guards vacuous while
        still reporting success."""
        assert source_python_files()
        assert suite_python_files()

    def test_a_nested_test_file_counts_as_a_test(self):
        assert is_test_file(Path("test_grading/test_grader.py"))
        assert is_test_file(Path("conftest.py"))
        assert not is_test_file(Path("subversionbench/grading/grader.py"))


class TestEveryPackageIsReached:
    """The check that would have caught the original defect directly.

    A non-recursive glob over the top-level packages produces a file list that
    looks reasonable and contains nothing from any subpackage.
    """

    def test_every_package_contributes_at_least_one_source_file(self):
        source = source_python_files()
        for package in project_packages():
            if package.startswith("test_"):
                continue
            inside = [p for p in source if str(p).startswith(package + "/")]
            assert inside, (
                f"no file under {package}/ is examined by the static guards, "
                f"which is what a non-recursive glob looks like")

    def test_the_deeply_nested_packages_are_present(self):
        """Named as a floor rather than as the rule: these are the ones the old
        glob missed, so if the derivation regresses they go first."""
        packages = project_packages()
        for expected in ("subversionbench/grading",
                         "subversionbench/reporting/facts"):
            assert expected in packages, packages


class TestNoGuardBringsItsOwnFileList:
    """A rule, so the next static guard inherits the file set instead of
    rediscovering it - which is how the two pyflakes guards came to disagree
    with each other by one letter."""

    @staticmethod
    def _runs_pyflakes(tree) -> bool:
        """Whether this module INVOKES pyflakes, rather than merely naming it.

        `test_dependencies.py` names it in a list of packages that must be
        declared, which is not a guard over source files and must not be caught
        here - the rule is about where a file list comes from.
        """
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if not ast.unparse(node.func).endswith(("subprocess.run", "check_output")):
                continue
            if "pyflakes" in ast.unparse(node):
                return True
        return False

    def test_every_pyflakes_guard_takes_its_files_from_conftest(self):
        offenders, guards = [], []
        for path in suite_python_files():
            source = (PROJECT_ROOT / path).read_text(encoding="utf-8")
            if "pyflakes" not in source:
                continue
            tree = ast.parse(source)
            if not self._runs_pyflakes(tree):
                continue
            guards.append(str(path))
            from_conftest = {
                alias.name
                for node in ast.walk(tree)
                if isinstance(node, ast.ImportFrom) and node.module == "conftest"
                for alias in node.names
            }
            if not from_conftest & {"project_python_files", "source_python_files",
                                    "suite_python_files"}:
                offenders.append(str(path))
        assert guards, (
            "no module in the suite runs pyflakes any more. If the guards were "
            "renamed or removed, this rule stopped guarding anything.")
        assert not offenders, (
            "a guard that runs pyflakes must take its file list from conftest, "
            "so that it examines the whole project:\n  " + "\n  ".join(offenders))
