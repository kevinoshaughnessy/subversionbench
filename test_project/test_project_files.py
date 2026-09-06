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
        probe = probe_dir / "sneaky.py"
        probe.write_text("y = 2\n", encoding="utf-8")
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


# Source files that still read or write text at the machine's locale's mercy.
#
# A BASELINE, NOT AN EXEMPTION. The rule below applies to every project source
# file; these are the ones that predate it, and the guard checks in BOTH
# directions - no file outside this set may offend, and every file inside it
# must still offend. So the list can only shrink: fix a file and the guard tells
# you to remove it from here, which is what stops a baseline from quietly
# becoming a permanent carve-out.
#
# Left standing rather than fixed in one pass because the fix edits source, and
# these were measured while a batch was collecting - see AGENTS.md on why source
# edits are unsafe then.
LOCALE_DEPENDENT_IO = frozenset({
    "contamination_check.py",
    "report/loading.py",
    "report/run_report.py",
    "rubric_ab.py",
    "sad_oversight.py",
    "subversionbench/arms_summary.py",
    "subversionbench/batch.py",
    "subversionbench/compare.py",
    "subversionbench/environment.py",
    "subversionbench/isolation.py",
    "subversionbench/readmodes/grade.py",
    "subversionbench/readmodes/reclassify.py",
    "subversionbench/readmodes/reinterrogate.py",
    "subversionbench/readmodes/resummarise.py",
    "subversionbench/reporting/summary.py",
    "subversionbench/runner.py",
    "trends/family_trends.py",
})


def _locale_dependent_io(path: Path) -> list:
    """Lines in `path` where text IO is left to the machine's locale."""
    found = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if not isinstance(node, ast.Call):
            continue
        name = ast.unparse(node.func)
        if not (name.endswith((".read_text", ".write_text")) or name == "open"):
            continue
        mode = ""
        if len(node.args) > 1 and isinstance(node.args[1], ast.Constant):
            mode = str(node.args[1].value)
        if "b" in mode:
            continue          # bytes carry no encoding question
        if any(kw.arg == "encoding" for kw in node.keywords):
            continue
        found.append(node.lineno)
    return found


class TestNoFileIsReadOrWrittenAtTheLocalesMercy:
    """`read_text()`/`write_text()`/`open()` without `encoding=` follow the
    machine's locale rather than the file's actual encoding.

    This corpus holds non-ASCII by design - the invisible and confusable
    characters are the subject - so under a non-UTF-8 locale these raise
    UnicodeDecodeError on real data. It has happened twice: `redact_tree` raised
    on any run file holding a non-ASCII character, and `scenario_tool --encode`
    raised on a working copy someone had edited.

    ONE GUARD, DERIVING ITS OWN SCOPE. Both of those fixes came with a rule
    checked over a single module, which is how the second one was able to happen
    after the first was fixed: two guards for one rule, neither covering the
    other's file, and 49 sites covered by neither. Scope comes from conftest so
    a module added later inherits the rule instead of escaping it.
    """

    def test_no_file_outside_the_baseline_leaves_it_to_the_locale(self):
        offenders = []
        for relative in source_python_files():
            # str(): conftest yields Path objects and the baseline is written as
            # strings, and `Path("x.py") in {"x.py"}` is quietly False - which
            # made every baselined file read as a new offender.
            if str(relative) in LOCALE_DEPENDENT_IO:
                continue
            lines = _locale_dependent_io(PROJECT_ROOT / relative)
            if lines:
                offenders.append(f"{relative}:{','.join(map(str, lines))}")
        assert not offenders, (
            "these read or write text at the machine's locale's mercy. Name "
            "encoding=\"utf-8\":\n  " + "\n  ".join(offenders))

    def test_the_baseline_holds_nothing_already_fixed(self):
        """The half that makes the list shrink. A file that has been fixed but
        left in the baseline is a file the rule has stopped covering, and nothing
        would say so."""
        fixed = [relative for relative in sorted(LOCALE_DEPENDENT_IO)
                 if not _locale_dependent_io(PROJECT_ROOT / relative)]
        assert not fixed, (
            "these no longer leave text IO to the locale, so remove them from "
            "LOCALE_DEPENDENT_IO - a baseline that outlives the debt it records "
            "is an exemption:\n  " + "\n  ".join(fixed))

    def test_every_file_in_the_baseline_still_exists(self):
        """A renamed or deleted file left in the list would silently stop being
        checked by either direction above."""
        missing = [relative for relative in sorted(LOCALE_DEPENDENT_IO)
                   if not (PROJECT_ROOT / relative).exists()]
        assert not missing, missing

    def test_the_baseline_is_not_growing(self):
        """The ratchet, stated as a number so that adding a file to the list is a
        visible change to this line rather than one entry among eighteen."""
        assert len(LOCALE_DEPENDENT_IO) <= 18, (
            f"the baseline has grown to {len(LOCALE_DEPENDENT_IO)}. New code must "
            f"name its encoding; only existing entries may be removed.")


class TestTheVersionIsNotCopiedIntoSource:
    """VERSION lives in version.py and nowhere else.

    Two module docstrings said "SubversionBench v17" through a hundred and
    twenty-two releases. A docstring is not executed, so nothing failed and
    nothing said it had stopped being true - the same shape as a pinned value
    kept in two places, which this repository has been bitten by before and
    which test_config.py already guards for pyproject.

    Scoped to every shipping file rather than the two that were wrong, so a
    module added later inherits the rule instead of escaping it.
    """

    def test_no_source_file_hardcodes_a_release_number(self):
        import re
        from conftest import PROJECT_ROOT, source_python_files

        files = source_python_files()
        assert files, "no source files - the guard would pass vacuously"
        stale = re.compile(r"SubversionBench\s+v\d+", re.IGNORECASE)
        offenders = [f"{rel}:{i}"
                     for rel in files
                     for i, line in enumerate(
                         (PROJECT_ROOT / rel).read_text(
                             encoding="utf-8").splitlines(), 1)
                     if stale.search(line)]
        assert not offenders, (
            f"a release number is written into source at {offenders}. "
            f"VERSION in version.py is the one copy; anything else rots "
            f"silently because nothing executes a docstring.")


# ---------------------------------------------------------------------------
# The file-length ratchet
# ---------------------------------------------------------------------------
#
# AGENTS.md sets 1,000 lines per file and 100 per function, and says to treat
# them as a ratchet rather than a fact: nothing new may exceed them, and
# anything already over may only get smaller. For the file limit there is now
# nothing over, so the ratchet is a plain rule with no exemptions - which is the
# strongest form it can take and the reason it is written as one here.
#
# The FUNCTION limit is a separate matter and deliberately not asserted below.
# Forty-five functions exceed it, the largest being summary_document at 336
# lines and run_batch at 324, and both are on the deferred list in AGENTS.md.
# A rule declared as absolute while forty-five things violate it is one that
# gets switched off the first time it is inconvenient.

MAX_FILE_LINES = 1000


def _too_long(paths) -> list:
    """`path:lines` for every file over the limit, longest first."""
    counts = [(len((PROJECT_ROOT / rel).read_text(encoding="utf-8").splitlines()),
               str(rel)) for rel in paths]
    return [f"{name}: {n} lines" for n, name in sorted(counts, reverse=True)
            if n > MAX_FILE_LINES]


class TestNoFileIsOverTheLimit:
    """1,000 lines, source and suite alike.

    WHY THIS IS CHECKED RATHER THAN REMEMBERED. Twenty files were over when
    this was written, six of them source, and nothing said so: the limit lived
    in AGENTS.md, which is read by whoever thinks to read it. Two of the twenty
    were files created ALREADY over - a rule with no check is a rule a new file
    can be born violating.

    Scope comes from conftest, so a file added later inherits the rule instead
    of escaping it, and there is no baseline to add an entry to. The suite is
    held to the same number as the source: a three-thousand-line test file costs
    a reader the same thing, and thirteen of the twenty were tests.
    """

    def test_no_source_file_is_over_the_limit(self):
        files = source_python_files()
        assert files, "no source files - the guard would pass vacuously"
        assert not _too_long(files), (
            f"over {MAX_FILE_LINES} lines. AGENTS.md's limit is a ratchet: "
            f"split on a division the file already has - a section banner, or "
            f"a group of functions with one relationship to the rest:\n  "
            + "\n  ".join(_too_long(files)))

    def test_no_suite_file_is_over_the_limit(self):
        files = suite_python_files()
        assert files, "no suite files - the guard would pass vacuously"
        assert not _too_long(files), (
            f"over {MAX_FILE_LINES} lines:\n  " + "\n  ".join(_too_long(files)))

    def test_the_check_fires_on_a_file_that_is_over(self):
        """The half that stops an empty result reading as a clean repository.

        Every file satisfies the rule today, so both checks above find nothing -
        which is the same answer a broken scan gives. Measured against a real
        file of a known length rather than a synthetic string, because what the
        check reads is a path.
        """
        import tempfile
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT) as tmp:
            long_file = Path(tmp) / "far_too_long.py"
            long_file.write_text("x = 1\n" * (MAX_FILE_LINES + 1),
                                 encoding="utf-8")
            found = _too_long([long_file.relative_to(PROJECT_ROOT)])
        assert len(found) == 1, found
        assert f"{MAX_FILE_LINES + 1} lines" in found[0]

    def test_the_check_passes_a_file_exactly_at_the_limit(self):
        """Two-directional on the boundary: the limit is what a file may BE,
        not what it must stay under."""
        import tempfile
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT) as tmp:
            at_limit = Path(tmp) / "exactly_at_the_limit.py"
            at_limit.write_text("x = 1\n" * MAX_FILE_LINES, encoding="utf-8")
            assert _too_long([at_limit.relative_to(PROJECT_ROOT)]) == []
