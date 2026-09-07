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
import re
import subprocess
import tempfile
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


# Names defined identically in two or more source modules, with the reason each
# is still here. Checked in BOTH directions below: nothing outside this list may
# duplicate a definition, and everything in it must still be duplicated - so it
# can only shrink, and it tells you to delete the entry when you give the name
# an owner.
#
# The entry that started this was PRICES_PER_MTOK, defined in grader_ab/cost.py
# and grader_ab/prices.py, where the two copies were read by DIFFERENT callers:
# cli.py asked prices.py whether a grader was priced, and the arithmetic read
# cost.py's own copy, so the check and the thing checked could disagree. Beside
# it, a byte-identical `report_grader_failure` in turns.py that nothing imported
# - every caller resolved it from grading/. Both are fixed; these are what is
# left.
DUPLICATED_DEFINITIONS = {
    # A DPI and a text-wrapper shared by four chart modules in packages that
    # deliberately do not import each other - see the setuptools note in
    # pyproject.toml for why they are separate. A drift here is cosmetic.
    "CHART_DPI": "four chart modules in packages that cannot import each other",
    "_wrap": "same",
    # These two are the ones worth fixing next, and for the same reason: a
    # detector and the thing it detects reading separate copies of the rule.
    # sandbox.py BLOCKS wrapped commands and grading/command_patterns.py
    # DETECTS them, so a drift means the two disagree about what a wrapper is.
    "_COMMAND_WRAPPERS": "sandbox.py blocks them, command_patterns.py detects them",
    "AWARENESS_TIMING_LEVELS": "two modules in grading/ enumerating the same levels",
    # One-line probe root and channel map in two sibling detectors.
    "_PROBE_ROOT": "disguised_text.py and encoded_payload.py",
    "_WHERE": "same",
}


def _top_level_definitions(relative) -> dict:
    """Every top-level def/class/UPPER-or-underscore constant, to its source."""
    src = (PROJECT_ROOT / relative).read_text(encoding="utf-8")
    lines = src.split("\n")
    found = {}
    for node in ast.parse(src).body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names = [node.name]
        elif isinstance(node, ast.Assign):
            # `X = some_imported_name` is an ALIAS, not a definition, and the
            # owner is the name on the right. Six modules write
            # `_wilson_ci = wilson_ci` after importing it, which this scan
            # first reported as a six-way duplication - the exact opposite of
            # what it was looking for, since that line exists BECAUSE there is
            # one owner.
            if isinstance(node.value, ast.Name):
                continue
            names = [t.id for t in node.targets
                     if isinstance(t, ast.Name)
                     and (t.id.isupper() or t.id.startswith("_"))]
        else:
            continue
        for name in names:
            found[name] = "\n".join(lines[node.lineno - 1:node.end_lineno])
    return found


def _identical_across_modules() -> dict:
    """Name -> the modules defining it with byte-identical source."""
    by_name = {}
    for relative in source_python_files():
        for name, body in _top_level_definitions(relative).items():
            by_name.setdefault(name, []).append((str(relative), body))
    duplicated = {}
    for name, entries in by_name.items():
        bodies = {}
        for path, body in entries:
            bodies.setdefault(body, []).append(path)
        shared = sorted(p for paths in bodies.values() if len(paths) > 1
                        for p in paths)
        if shared:
            duplicated[name] = shared
    return duplicated


class TestNoTwoModulesDefineTheSameThing:
    """A second copy of a definition is a second thing to keep in step.

    Not a style rule. Both instances that prompted this were live: two price
    tables whose readers disagreed about which one was authoritative, and a
    33-line function duplicated byte for byte in a module nothing imported it
    from. The failure mode is never the duplication itself - it is the day one
    copy is corrected and the other is not, and every caller of the second one
    keeps the old answer without an error.

    Identical source only. Two modules defining the same NAME differently are
    doing different jobs and are not the target - `main`, `_run`, `_episode`
    and a dozen others legitimately recur.
    """

    def test_no_definition_outside_the_baseline_is_duplicated(self):
        offenders = [f"{name}: {', '.join(paths)}"
                     for name, paths in sorted(_identical_across_modules().items())
                     if name not in DUPLICATED_DEFINITIONS]
        assert not offenders, (
            "these are defined identically in more than one module. Give the "
            "name one owner and import it:\n  " + "\n  ".join(offenders))

    def test_the_baseline_holds_nothing_already_fixed(self):
        """The half that makes the list shrink."""
        duplicated = _identical_across_modules()
        fixed = [name for name in sorted(DUPLICATED_DEFINITIONS)
                 if name not in duplicated]
        assert not fixed, (
            "these now have one owner, so remove them from "
            "DUPLICATED_DEFINITIONS - a baseline that outlives the debt it "
            "records is an exemption:\n  " + "\n  ".join(fixed))

    def test_the_scan_can_still_answer_no(self):
        """A scan that found nothing would pass both tests above with every
        duplication in place. Prove it finds the ones the baseline names."""
        duplicated = _identical_across_modules()
        assert duplicated, "the scan found no duplication at all"
        for name in DUPLICATED_DEFINITIONS:
            assert len(duplicated.get(name, [])) > 1, (
                f"{name} is in the baseline but the scan does not see it "
                f"duplicated, so neither direction above is checking anything")


def _repeated_statement_runs(relative) -> list:
    """Lines where a run of statements is immediately followed by its own copy.

    A RUN, not a single statement: the shape this keeps appearing as is two
    unpacking lines pasted twice, which a scan for adjacent identical
    statements walks straight past because neither line equals its neighbour.
    """
    # Accepts a repo-relative path or an absolute one, so the tests below can
    # hand it a file in a temp directory to prove the scan can answer both ways.
    src = Path(PROJECT_ROOT / relative).read_text(encoding="utf-8")
    found = []
    for node in ast.walk(ast.parse(src)):
        body = getattr(node, "body", None)
        if not isinstance(body, list) or len(body) < 2:
            continue
        dumps = [ast.dump(st) for st in body]
        for k in range(1, len(dumps) // 2 + 1):
            for i in range(len(dumps) - 2 * k + 1):
                if dumps[i:i + k] == dumps[i + k:i + 2 * k]:
                    found.append(body[i + k].lineno)
    return sorted(set(found))


class TestNoStatementRunIsPastedTwice:
    """Copy-paste residue inside a body, which ruff cannot see.

    Every instance found was dead rather than wrong - a second `return 1` after
    the first, an assignment recomputing the value it just computed, two tally
    unpacking lines pasted twice - except one that printed a paragraph of
    operator advice twice. So the cost is a reader trusting that a line repeated
    on purpose means something.

    It recurs. Two separate instances were removed from grader_ab/cli.py in
    consecutive versions, and the guard added with the first one only compared
    top-level DEFINITIONS, so it could not see either. Whole-repo scope from
    conftest, and statements rather than definitions, is what covers both.

    Identical AST, so a run that differs by a single argument is not reported -
    two similar-looking blocks are usually two different jobs.
    """

    def test_no_body_repeats_a_run_of_statements(self):
        offenders = []
        for relative in project_python_files():
            lines = _repeated_statement_runs(relative)
            if lines:
                offenders.append(f"{relative}:{','.join(map(str, lines))}")
        assert not offenders, (
            "a run of statements is immediately followed by an identical copy "
            "of itself. Delete the second one:\n  " + "\n  ".join(offenders))

    def test_the_scan_finds_a_planted_repeat(self):
        """A scan that always returned nothing would pass the test above with
        every duplication in place.

        Both shapes, because the single-statement one is the easy case and the
        two-statement run is the one the first version of this scan missed.
        """
        with tempfile.TemporaryDirectory() as d:
            one = Path(d) / "one.py"
            one.write_text("def f():\n    x = 1\n    x = 1\n",
                           encoding="utf-8")
            assert _repeated_statement_runs(one) == [3]

            run = Path(d) / "run.py"
            run.write_text("def f(t):\n    a = t[0]\n    b = t[1]\n"
                           "    a = t[0]\n    b = t[1]\n", encoding="utf-8")
            assert _repeated_statement_runs(run) == [4]

    def test_the_scan_does_not_simply_say_yes(self):
        """Two statements that merely look alike are two different jobs."""
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "distinct.py"
            path.write_text("def f(t):\n    a = t[0]\n    b = t[1]\n",
                            encoding="utf-8")
            assert _repeated_statement_runs(path) == []


# The Agentic Benchmark Checklist is numbered TWICE by its own authors: the
# paper's prose uses T./O./R. and the standalone checklist they publish at
# github.com/uiuc-kang-lab/agentic-benchmarks uses II./I./III. for the same
# items. A citation giving only one form sends half its readers to a checklist
# that has no such item.
#
# The correspondence is an external fact and cannot be derived, so it is
# written here - but which FILES cite the checklist is derived, so a seventh
# citation added later inherits the rule instead of escaping it.
ABC_ITEM_NUMBERING = {
    "T.1": "II.1",    # tool versions are specified
    "T.9": "II.8",    # an oracle solver demonstrates the tasks are performable
    "R.3": "III.3",   # measures against data contamination
    "R.4": "III.4",   # measures or plans to keep challenges updated
    # R.5 and R.6 are word-for-word identical between the two documents, typo
    # included ("the evaluation subjective of the benchmark"), so this pair is
    # confirmed from both texts rather than inferred from position - which the
    # others in this map are, the paper grouping them as ranges in its prose.
    "R.5": "III.5",   # capabilities aimed at, against constructs measured
    "R.6": "III.6",   # the evaluation subject: a model or an agent framework
    "R.13": "III.13",  # results for a trivial agent
}

ABC_DOI = "2507.02825"

# CHANGELOG.md is a historical record: each entry describes what a past version
# said, and back-filling a numbering into an old entry would misrepresent it.
# Excluded by name because the category has exactly one member, and stated
# rather than silently skipped.
#
# It is worth reading for a different reason: the v131 entry claims hostenv.py
# was "named for items T.1 and R.6" and then explains only T.1. That half of the
# claim went unsubstantiated for twenty versions - the toolchain record is a
# COMPONENT of the evaluation subject and not a statement of it - and is now
# made good under "What is being evaluated" in docs/methodology.md, which says
# what the subject is and points at the fields that record each qualifier.
ABC_HISTORICAL_RECORD = "CHANGELOG.md"


def _abc_item_re(item: str) -> str:
    r"""`item` as a whole reference, not as the start of a longer one.

    "T.1" is a prefix of "T.10" and "III.1" of "III.13", so a plain `in` reads
    one as the other. The second lookahead is `(?!\.\d)` and NOT `(?![\d.])`,
    which is what this first was: a citation ending a sentence is followed by a
    full stop, so "II.8." failed to match and the guard reported a file that
    was in fact correct.
    """
    return rf"\b{re.escape(item)}(?!\d)(?!\.\d)"


def _abc_citing_files() -> list:
    """Every tracked file citing the checklist, EXCLUDING the one holding the map.

    Source AND prose, from `git ls-files`, because the citations are in both and
    the first version of this listed `README.md` by name - which would have gone
    on passing while a citation added anywhere else in docs/ escaped it. That is
    the hand-written-list defect the rest of this file exists to avoid.

    This module is excluded because it names every item number as data, in
    ABC_ITEM_NUMBERING and in the docstrings explaining it. Scanning it found
    citations that are not citations: it reported the "T.10" in its own comment
    as an unmapped item, which is a checker failing its own check by reading
    itself.
    """
    tracked = subprocess.run(
        ["git", "ls-files", "*.py", "*.md"], cwd=PROJECT_ROOT,
        capture_output=True, text=True, check=True).stdout.split()
    assert tracked, "git ls-files matched nothing, so the scope is empty"
    here = str(Path(__file__).resolve().relative_to(PROJECT_ROOT))
    return [Path(name) for name in tracked
            if name not in (here, ABC_HISTORICAL_RECORD)
            and ABC_DOI in (PROJECT_ROOT / name).read_text(encoding="utf-8")]


class TestEveryChecklistCitationGivesBothNumberings:
    """One item, two numbers, and a reader lands on one file.

    The repository cited the paper's prose numbering only - "item T.9" - which
    is correct against the paper and absent from the checklist the authors
    publish separately, where the same item is II.8. Anyone cross-referencing
    the published checklist finds nothing under T.9.

    Each citation carries both rather than pointing at one explanation of the
    mismatch, because a citation whose meaning depends on having read another
    file is not a citation.
    """

    def test_the_scan_reaches_both_source_and_prose(self):
        """Without this, every test below passes on a narrowed list.

        A count alone is not enough, and that is measured rather than assumed:
        narrowing the scan to `*.py` leaves exactly five citing modules, so a
        `len(citing) >= 5` assertion passed while every prose citation in
        docs/ went unchecked - which is the state that let one sit there.
        The citations live in source AND in prose, so the scope has to reach
        both kinds or it is not the scope this rule needs.
        """
        citing = _abc_citing_files()
        suffixes = {path.suffix for path in citing}
        assert ".py" in suffixes, citing
        assert ".md" in suffixes, (
            f"the scan reaches no prose, so a citation in docs/ or the README "
            f"is unchecked: {citing}")
        assert len(citing) >= 6, citing

    def test_every_paper_form_item_is_accompanied_by_its_other_number(self):
        offenders = []
        for relative in _abc_citing_files():
            body = (PROJECT_ROOT / relative).read_text(encoding="utf-8")
            for paper, repo in ABC_ITEM_NUMBERING.items():
                if not re.search(_abc_item_re(paper), body):
                    continue
                if not re.search(_abc_item_re(repo), body):
                    offenders.append(f"{relative} cites {paper} without {repo}")
        assert not offenders, (
            "these cite the checklist by the paper's numbering only, so a "
            "reader checking the authors' published checklist finds no such "
            "item:\n  " + "\n  ".join(offenders))

    def test_no_citation_uses_an_unmapped_item(self):
        """The half that keeps the map from falling behind. A file citing an
        item this map does not know is a file the test above skips silently."""
        cited = set()
        for relative in _abc_citing_files():
            body = (PROJECT_ROOT / relative).read_text(encoding="utf-8")
            cited |= set(re.findall(r"\b((?:T|R)\.\d{1,2})(?!\d)(?!\.\d)",
                                    body))
            cited |= set(re.findall(r"\b(O\.[a-i]\.\d)(?!\d)", body))
        unmapped = sorted(cited - set(ABC_ITEM_NUMBERING))
        assert not unmapped, (
            f"these checklist items are cited but not in ABC_ITEM_NUMBERING, "
            f"so nothing checks that their other number is given: {unmapped}")

    def test_the_two_numberings_are_never_confused_for_each_other(self):
        """T. and R. are the paper's, II. and III. the checklist's. A mapping
        row pointing a paper number at another paper number would satisfy the
        test above while citing nothing new."""
        for paper, repo in ABC_ITEM_NUMBERING.items():
            assert paper[0] in "TOR", paper
            assert repo.split(".")[0] in ("I", "II", "III"), repo
