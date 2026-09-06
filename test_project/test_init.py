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
#
# Hand-written, and checked for completeness below rather than trusted: a
# module that binds or bare-calls a stubbed name and is missing from here is a
# failure of `test_the_caller_list_is_complete`, which derives the same set
# from the source. That is the two-directional shape AGENTS.md prescribes where
# a list cannot be purely derived - and a caller written CORRECTLY leaves no
# textual trace of the name, so a derivation alone can only find offenders.
CALLERS = (
    "subversionbench.episode",
    "subversionbench.readmodes.grade",
    "subversionbench.readmodes.reclassify",
    "subversionbench.readmodes.reinterrogate",
    # The ones that draw or grade from outside the package. Root packages and a
    # root script rather than package modules, which the checks below do not
    # care about - they import by name.
    "trends.charts",
    "report_charts",
    "sad_oversight",
    "agentic_misalignment",
    "grader_ab",
)


def _submodules(name: str) -> list:
    """`name`, plus every submodule if it is a package.

    `inspect.getsource` of a package returns its __init__ and nothing else, so
    an entry naming a package covered one file. Two of the entries above became
    packages, and the checks below silently stopped reading the modules that
    actually call anything - which is the "an empty scope makes every guard
    pass" failure this file is otherwise careful about.
    """
    import pkgutil
    module = importlib.import_module(name)
    if not hasattr(module, "__path__"):
        return [name]
    return [name] + [f"{name}.{m.name}" for m in pkgutil.iter_modules(module.__path__)
                     if m.name != "__main__"]


CALLER_MODULES = tuple(m for name in CALLERS for m in _submodules(name))

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

def _stubbed_bindings(source: str) -> set:
    """The stubbed names `source` binds at module level or bare-calls.

    Three things are deliberately NOT offences:

    - defining the function. The owner is where the patch goes.
    - a facade naming it in `__all__`. That is a re-export on purpose, and
      `subversionbench/__init__.py` is one.
    - a LAZY import - `from ..llm_client import get_client` inside a function
      body. That statement runs on every call and re-reads the owning module's
      attribute, so it is the module-qualified behaviour under another
      spelling. Three grading modules use it to break an import cycle, and a
      patch of the owner reaches all three.

    A string rather than a path, so the scan can be shown catching a planted
    binding and excusing a lazy one - a scan nothing has ever seen fire is
    indistinguishable from a clean codebase.
    """
    tree = ast.parse(source)
    excused = {n.name for n in ast.walk(tree)
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    for node in ast.walk(tree):
        if (isinstance(node, ast.Assign)
                and any(getattr(target, "id", "") == "__all__"
                        for target in node.targets)
                and isinstance(node.value, (ast.List, ast.Tuple))):
            excused |= {e.value for e in node.value.elts
                        if isinstance(e, ast.Constant)}
    # Node ids of everything inside a function that lazily imported the name,
    # so that function's calls to it are excused too.
    lazily = {}
    for func in ast.walk(tree):
        if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        names = {a.asname or a.name for n in ast.walk(func)
                 if isinstance(n, ast.ImportFrom) for a in n.names}
        for node in ast.walk(func):
            lazily.setdefault(id(node), set()).update(names)
    found = set()
    for node in ast.walk(tree):
        here = excused | lazily.get(id(node), set())
        names = []
        if isinstance(node, ast.ImportFrom):
            names = [a.asname or a.name for a in node.names]
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            names = [node.func.id]
        found |= {n for n in names if n in STUBBED and n not in here}
    return found


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
        for module in CALLER_MODULES:
            mod = importlib.import_module(module)
            bound = [n for n in STUBBED if hasattr(mod, n)]
            assert not bound, (
                f"{module} binds {bound} as bare names - patch the owning module "
                f"instead, and remove these so nobody patches a dead reference")

    def test_every_call_is_module_qualified(self):
        """The other half: the calls have to actually go through the module."""
        for module in CALLER_MODULES:
            src = inspect.getsource(importlib.import_module(module))
            for node in ast.walk(ast.parse(src)):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                    assert node.func.id not in STUBBED, (
                        f"{module} line {node.lineno} calls {node.func.id} as a "
                        f"bare name; call it through its module so one patch "
                        f"point covers every caller")

class TestTheCallerListIsComplete:
    """The other direction on CALLERS, so the list cannot fall behind the code.

    It already had: grader_ab bound `get_client` as a bare name and was not on
    the list, so neither check above covered the script that spends the most
    money per run. Nothing said so, because a one-directional list is an
    exemption for whatever is missing from it.

    A caller written CORRECTLY leaves no trace of the name - it imports the
    owning module and calls through it - so this cannot derive the list. What
    it can derive is the set of modules that bind or bare-call a stubbed name,
    which is exactly the set the two checks above must reach.
    """

    def _offenders(self):
        """(module, name) for every source module outside its owner."""
        from conftest import PROJECT_ROOT, source_python_files
        owners = set(STUBBED.values())
        found, scanned = [], 0
        for relative in source_python_files():
            module = str(relative)[:-len(".py")].replace("/", ".")
            module = module.removesuffix(".__init__")
            if module in owners:
                continue
            scanned += 1
            text = (PROJECT_ROOT / relative).read_text(encoding="utf-8")
            found += [(module, name) for name in _stubbed_bindings(text)]
        assert scanned > 50, f"only {scanned} files scanned - the scope broke"
        return sorted(set(found))

    def test_every_module_that_binds_a_stubbed_name_is_a_known_caller(self):
        """`known` covers a package by any of its modules, because CALLERS may
        name either."""
        known = set(CALLER_MODULES)
        missing = sorted({module for module, _name in self._offenders()
                          if module not in known})
        assert not missing, (
            "these bind or bare-call a stubbed name and are not reached by "
            "CALLERS, so nothing checks that their patch point works. Add "
            "them, or call through the owning module:\n  " + "\n  ".join(missing))

    def test_the_scan_catches_a_planted_binding(self):
        """The half that stops an empty result reading as a clean codebase.

        Every source module satisfies the rule today, so the check above finds
        nothing - which is the same answer a broken scan gives. Planting one
        offender is the difference.
        """
        name = sorted(STUBBED)[0]
        owner = STUBBED[name]
        assert _stubbed_bindings(
            f"from {owner} import {name}\n\n"
            f"def use():\n    return {name}(1)\n") == {name}

    def test_the_scan_excuses_a_lazy_import(self):
        """The other direction, and the one three grading modules rely on: an
        import inside a function re-reads the owner's attribute on every call,
        so a patch of the owner reaches it."""
        name = sorted(STUBBED)[0]
        owner = STUBBED[name]
        assert _stubbed_bindings(
            f"def use():\n"
            f"    from {owner} import {name}\n"
            f"    return {name}(1)\n") == set()

    def test_the_scan_excuses_the_module_that_defines_it(self):
        name = sorted(STUBBED)[0]
        assert _stubbed_bindings(f"def {name}(x):\n    return x\n") == set()


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
