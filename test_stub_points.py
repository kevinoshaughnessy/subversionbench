"""
One patch point per stubbed dependency, and it does not move when files do.

The test suite replaces five things to keep itself off the network and out of the
grader's bill: the API client, the awareness grader, the interrogation classifier,
the disclosure reading and the misrepresentation check.

WHY THIS NEEDS A TEST
---------------------
`from X import f` copies the function object. So a test that patches
`run_eval.f` works only while f's CALLER lives in run_eval, and stops working the
moment that caller moves to another module - silently, because assigning to a
module attribute that nothing reads is not an error. The test then hits the real
API, or fails somewhere that says nothing about the cause.

Called as `llm_client.get_client(...)`, the lookup happens at call time in the
owning module. There is one patch point, it is the same for every caller, and it
survives any file reorganisation.

That mattered immediately: converting these five surfaced a third test file
patching through a run_eval alias that the first sweep missed. It failed loudly
only because the bare name had been REMOVED from run_eval - reading it to save the
original raised. Had that test only assigned, it would have quietly stopped
stubbing and started spending.
"""

import ast
import glob
import importlib
import inspect

# name -> the module that owns it, and so the module to patch
STUBBED = {
    "get_client": "subversionbench.llm_client",
    "detect_eval_awareness_grader": "subversionbench.grading",
    "classify_interrogation_answer": "subversionbench.grading",
    "detect_disclosure": "subversionbench.grading",
    "detect_misrepresentation": "subversionbench.grading",
}

# Modules that call them, and must do so module-qualified.
CALLERS = ("subversionbench.run_eval",)


def _run_eval_aliases(tree):
    """Names in one test module that are bound to subversionbench.run_eval."""
    aliases = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name == "subversionbench.run_eval":
                    aliases.add(a.asname or "subversionbench")
        elif isinstance(node, ast.ImportFrom):
            if node.module in ("subversionbench", "subversionbench."):
                for a in node.names:
                    if a.name == "run_eval":
                        aliases.add(a.asname or "run_eval")
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
        for module in CALLERS:
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
    def test_nothing_stubs_through_a_run_eval_alias(self):
        """The regression this file exists for.

        Patching a re-exporting module works by accident and breaks by accident.
        This scans the suite for it so the breakage is a failure here, with the
        right module named, rather than a test that quietly stops stubbing.
        """
        offenders = []
        for path in sorted(glob.glob("test_*.py") + glob.glob("test_*/*.py")):
            if path == "test_stub_points.py":
                continue
            tree = ast.parse(open(path).read())
            aliases = _run_eval_aliases(tree)
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
