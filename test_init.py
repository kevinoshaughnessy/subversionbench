"""
The package's import surface, and the points tests are allowed to stub.

`from X import f` copies the object, so patching `run_eval.f` stops working the
moment f's caller moves to another module. The stub points asserted here resolve at
call time in the module that owns them, which is what let the source split happen
without rewriting every test.
"""

import ast
import glob
import importlib
import inspect


# name -> the module that owns it, and so the module to patch
STUBBED = {
    "get_client": "subversionbench.llm_client",
    # Not an LLM call, but the same problem: three scripts drew charts and each
    # had its own copy of this, so a test patching one of them left the other
    # two on the real matplotlib. One owner, one patch point.
    "import_pyplot": "subversionbench.charting",
    "detect_eval_awareness_grader": "subversionbench.grading",
    "classify_interrogation_answer": "subversionbench.grading",
    "detect_disclosure": "subversionbench.grading",
    "detect_misrepresentation": "subversionbench.grading",
}

# Modules that call them, and so must do so module-qualified.
CALLERS = (
    "subversionbench.episode",
    "subversionbench.readmodes.grade",
    "subversionbench.readmodes.reclassify",
    "subversionbench.readmodes.reinterrogate",
    # The three that draw. Root scripts and a root package rather than package
    # modules, which the checks below do not care about - they import by name.
    "trends.charts",
    "report_charts",
    "sad_oversight",
)

# Modules a test might reasonably but wrongly patch. This is NOT the same list as
# CALLERS, and the difference is the point: run_eval no longer calls any of these -
# the code that did moved to episode.py and readmodes/ - yet it is still the module
# every test imports, so it is still where someone would reach for the old patch
# point. Patching a module that does not read the name is a silent no-op, so it has
# to stay watched after it stops being a caller.
WRONG_PATCH_TARGETS = ("subversionbench.run_eval",) + CALLERS

def _caller_aliases(tree):
    """Names in one test module bound to a module that is the wrong patch target."""
    aliases = set()
    # [-1], not [1]: a caller can be a top-level module with no dot in its
    # name, which every entry had until the chart scripts joined the list.
    short = {m.rsplit(".", 1)[-1] for m in WRONG_PATCH_TARGETS}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name in WRONG_PATCH_TARGETS:
                    aliases.add(a.asname or "subversionbench")
        elif isinstance(node, ast.ImportFrom):
            if node.module in ("subversionbench", "subversionbench."):
                for a in node.names:
                    if a.name in short:
                        aliases.add(a.asname or a.name)
    return aliases

class TestThePatchPointExists:
    def test_each_stubbed_name_lives_on_its_owning_module(self):
        for name, module in STUBBED.items():
            mod = importlib.import_module(module)
            assert hasattr(mod, name), (
                f"{module} does not expose {name}, so there is nothing to patch")

class TestTheCallersResolveAtCallTime:
    def test_no_caller_binds_a_stubbed_name_directly(self):
        """A bare binding is worse than no binding: patching it appears to work.

        Removed rather than left alongside the qualified calls, so that a test
        reaching for the old patch point fails on the read instead of silently
        no-opping on the write.
        """
        for module in WRONG_PATCH_TARGETS:
            mod = importlib.import_module(module)
            bound = [n for n in STUBBED if hasattr(mod, n)]
            assert not bound, (
                f"{module} binds {bound} as bare names - patch the owning module "
                f"instead, and remove these so nobody patches a dead reference")

    def test_every_call_is_module_qualified(self):
        """The other half: the calls have to actually go through the module."""
        for module in CALLERS:
            src = inspect.getsource(importlib.import_module(module))
            for node in ast.walk(ast.parse(src)):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                    assert node.func.id not in STUBBED, (
                        f"{module} line {node.lineno} calls {node.func.id} as a "
                        f"bare name; call it through its module so one patch "
                        f"point covers every caller")

class TestNoTestPatchesTheWrongModule:
    def test_nothing_stubs_through_a_calling_module(self):
        """The regression this file exists for.

        Patching a re-exporting module works by accident and breaks by accident.
        This scans the suite for it so the breakage is a failure here, with the
        right module named, rather than a test that quietly stops stubbing.
        """
        offenders = []
        import os
        for path in sorted(glob.glob("test_*.py") + glob.glob("test_*/*.py")):
            # This file names the patch points in order to look for them, so it
            # exempts ITSELF - derived, not written down. A hardcoded filename here
            # went stale when the file was renamed, leaving a dead exemption.
            if path == os.path.basename(__file__):
                continue
            tree = ast.parse(open(path).read())
            aliases = _caller_aliases(tree)
            if not aliases:
                continue
            for node in ast.walk(tree):
                if (isinstance(node, ast.Attribute)
                        and node.attr in STUBBED
                        and getattr(node.value, "id", None) in aliases):
                    offenders.append(
                        f"{path}:{node.lineno} patches {node.value.id}."
                        f"{node.attr} - use {STUBBED[node.attr]} instead")
        assert not offenders, "\n  " + "\n  ".join(offenders)
