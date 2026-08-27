"""
The grading package's surface: eleven modules behind one import site.

grading.py was 1,482 lines with nine reasons to change. The split is only worth
anything if callers keep importing from one place - otherwise the module boundaries
become a dependency graph every caller has to know - so what this file pins is the
surface, and that the submodules stay leaves.
"""

import ast
import glob
import importlib
import inspect
from pathlib import Path

import subversionbench.grading as grading

def _submodules() -> tuple:
    """Every module in the package, taken from disk.

    DERIVED, NOT LISTED, and the difference was live. The hardcoded tuple this
    replaces held 14 names against 16 modules on disk: `disguised_text` and
    `transcript_pairs` were added afterwards and every guard in this file
    silently stopped covering them - including the one that catches a caller
    reaching past the single import site, which is the whole point of the file.

    A guard that names its own scope stops guarding when code moves, and it
    fails by passing. That is the failure this file exists to prevent for the
    package's callers, so it should not be the way the file is written.
    """
    package = Path(grading.__file__).parent
    return tuple(sorted(p.stem for p in package.glob("*.py")
                        if p.stem != "__init__"))


SUBMODULES = _submodules()

# Modules that exist to be shared BETWEEN submodules rather than called from
# outside, so their public names are not expected on the package surface.
#
# Named here but not TRUSTED here: test_every_shared_leaf_really_is_internal
# checks that nothing outside the package imports either of them, so this cannot
# become somewhere to park a module that merely forgot to export something.
SHARED_LEAVES = ("grader_io", "transcript_pairs")


class TestTheSurfaceIsWhatItSaysItIs:
    def test_every_exported_name_exists(self):
        missing = [n for n in grading.__all__ if not hasattr(grading, n)]
        assert not missing, missing

    def test_no_duplicates(self):
        """The list is grouped by concern rather than sorted, so a name added to
        two groups is easy to miss by eye."""
        duplicated = [n for n in set(grading.__all__)
                      if grading.__all__.count(n) > 1]
        assert not duplicated, duplicated

    def test_the_verdict_functions_are_all_reachable(self):
        """settle_analysis is the one place verdicts are derived, and the three
        classifiers it calls are exported beside it so a caller can see what it
        does rather than reimplement a piece."""
        for name in ("settle_analysis", "classify_misalignment",
                     "classify_scheming", "classify_scheming_act",
                     "concealment_level"):
            assert callable(getattr(grading, name)), name

    def test_every_submodule_with_a_public_name_reaches_the_surface(self):
        """A module whose public names never reach the surface is either dead or
        being reached into directly.

        SHARED_LEAVES are exempt by construction: they exist to be shared BETWEEN
        submodules rather than to be called from outside, and each is checked to
        be genuinely internal below.
        """
        silent = []
        for leaf in SUBMODULES:
            if leaf in SHARED_LEAVES:
                continue
            module = importlib.import_module(f"subversionbench.grading.{leaf}")
            public = {n for n in vars(module)
                      if not n.startswith("_")
                      and getattr(vars(module)[n], "__module__", "")
                      .endswith(leaf)}
            if public and not (public & set(grading.__all__)):
                silent.append(leaf)
        assert not silent, (
            f"nothing from these reaches the package surface, so callers must be "
            f"importing them directly: {silent}")


class TestTheScopeOfTheseGuardsIsDerived:
    """A guard is worth what its scope covers, and this file's scope used to be a
    hand-written tuple that had fallen two modules behind."""

    def test_the_derived_list_covers_every_importable_submodule(self):
        """The sanity check on the glob. A pattern that matched nothing would
        empty the scope of every guard here and each of them would pass."""
        assert len(SUBMODULES) >= 14, SUBMODULES
        for leaf in SUBMODULES:
            importlib.import_module(f"subversionbench.grading.{leaf}")

    def test_the_list_is_not_hand_written(self):
        """The positive control for the fix. Restating the names here would pass
        every other test in this file while reintroducing exactly the drift that
        hid two modules, so the source is checked for a literal tuple of leaf
        names assigned to SUBMODULES.
        """
        src = Path(__file__).read_text(encoding="utf-8")
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign):
                continue
            names = [t.id for t in node.targets if isinstance(t, ast.Name)]
            if "SUBMODULES" not in names:
                continue
            assert not isinstance(node.value, (ast.Tuple, ast.List, ast.Set)), (
                "SUBMODULES is a literal again; derive it from the package so a "
                "new module cannot escape these guards by being added later")

    def test_every_shared_leaf_really_is_internal(self):
        """What keeps SHARED_LEAVES from becoming a hiding place. A module is
        exempt from the surface rule because callers outside the package do not
        reach it - so that, and not the entry in the tuple, is what is checked.
        """
        # Resolved on both sides: the glob yields relative paths and
        # grading.__file__ is absolute, so comparing them directly excludes
        # nothing and every sibling reads as an outside caller.
        package = Path(grading.__file__).parent.resolve()
        reached_from_outside = []
        for path in sorted(glob.glob("subversionbench/**/*.py", recursive=True)):
            if Path(path).resolve().parent == package:
                continue
            for node in ast.walk(ast.parse(
                    Path(path).read_text(encoding="utf-8"))):
                if isinstance(node, ast.ImportFrom) and node.module:
                    leaf = node.module.rsplit(".", 1)[-1]
                    if leaf in SHARED_LEAVES:
                        reached_from_outside.append(f"{path} imports {leaf}")
        assert not reached_from_outside, (
            "these are exempt from the surface rule on the grounds that only "
            "siblings use them, which is no longer true:\n  "
            + "\n  ".join(reached_from_outside))

    def test_a_shared_leaf_is_named_only_when_it_needs_to_be(self):
        """The other direction: a module listed as shared whose public names DO
        reach the surface does not need the exemption, and leaving it there would
        hide a later regression in that module."""
        unnecessary = []
        for leaf in SHARED_LEAVES:
            module = importlib.import_module(f"subversionbench.grading.{leaf}")
            public = {n for n in vars(module)
                      if not n.startswith("_")
                      and getattr(vars(module)[n], "__module__", "")
                      .endswith(leaf)}
            if public & set(grading.__all__):
                unnecessary.append(leaf)
        assert not unnecessary, (
            f"these reach the surface already and do not need the exemption: "
            f"{unnecessary}")


class TestTheSubmodulesStayLeaves:
    def test_no_submodule_imports_the_package_it_belongs_to(self):
        """A submodule importing its own package is a cycle that happens to work
        because of import order, and it makes the surface depend on itself."""
        for leaf in SUBMODULES:
            src = inspect.getsource(
                importlib.import_module(f"subversionbench.grading.{leaf}"))
            for node in ast.walk(ast.parse(src)):
                if not isinstance(node, ast.ImportFrom):
                    continue
                assert node.module != "subversionbench.grading", leaf
                if node.level == 1 and node.module is None:
                    # `from . import interrogation` names a SIBLING MODULE, which
                    # is fine. What would be a cycle is pulling a name that only
                    # exists on the package surface back out of the package.
                    for alias in node.names:
                        assert alias.name in SUBMODULES, (leaf, alias.name)

    def test_the_shared_leaf_is_imported_from_itself(self):
        """grader_io exists because grader.py builds the request and
        quote_grounding.py has to reconstruct exactly what the grader was shown. A
        quote verified against a longer corpus than the grader saw is not verified,
        so both have to truncate through the same function.

        closing_report.py used to reach those helpers through `.grader`, and this
        test recorded that as a named exception - it depended on the module
        grader_io was extracted to decouple it from, so a change to grader.py's
        imports could have taken the truncation rule away from it. It no longer
        does, and the exception is gone rather than re-pinned: every submodule that
        needs the leaf now imports it from the leaf.

        The package surface re-exports the parser for contamination_check.py, and
        does so from grader_io for the same reason.
        """
        direct, via_grader = [], []
        for leaf in ("grader", "quote_grounding", "interrogation",
                     "closing_report"):
            src = inspect.getsource(
                importlib.import_module(f"subversionbench.grading.{leaf}"))
            if "from .grader_io import" in src:
                direct.append(leaf)
            elif "_truncate_for_grader" in src or "_parse_first_json" in src:
                via_grader.append(leaf)
        assert set(direct) >= {"grader", "quote_grounding", "closing_report"}, direct
        assert via_grader == [], (
            f"these reach the shared leaf through another submodule rather than "
            f"through grader_io: {via_grader}")

    def test_nothing_outside_grading_imports_a_submodule_directly(self):
        """The point of the single import site. Checked over the package, so a new
        caller reaching past it fails here rather than quietly coupling itself to
        a file layout."""
        allowed = {"subversionbench/grading/", "subversionbench/readmodes/"}
        offenders = []
        for path in sorted(glob.glob("subversionbench/**/*.py", recursive=True)):
            if any(path.startswith(a) for a in allowed):
                continue
            for node in ast.walk(ast.parse(open(path).read())):
                if isinstance(node, ast.ImportFrom) and node.module:
                    leaf = node.module.rsplit(".", 1)[-1]
                    if "grading" in node.module and leaf in SUBMODULES:
                        offenders.append(f"{path} imports grading.{leaf}")
        assert not offenders, "\n  " + "\n  ".join(offenders)


class TestTheActsTableIsTheOneSourceOfPerActKeys:
    def test_every_act_carries_the_full_set_of_keys(self):
        """Every measure indexes an analysis by these. One act missing a key is a
        branch that raises only on the arm that reaches it."""
        required = ("name", "key", "followup_key", "disclosure_key", "level_key",
                    "scheming_key", "timing_key", "grader_before_key",
                    "description", "banner")
        for act in grading.MISALIGNED_ACTS:
            missing = [k for k in required if k not in act]
            assert not missing, (act.get("name"), missing)

    def test_the_keys_are_unique_across_acts(self):
        """Two acts sharing an analysis key would silently overwrite each other's
        verdict."""
        for field in ("key", "followup_key", "disclosure_key", "level_key",
                      "scheming_key", "timing_key", "grader_before_key"):
            values = [act[field] for act in grading.MISALIGNED_ACTS]
            assert len(values) == len(set(values)), field

    def test_the_table_is_immutable(self):
        """Read by every detector. A list here could be appended to at runtime and
        every rate would change under the reader's feet."""
        assert isinstance(grading.MISALIGNED_ACTS, tuple)
