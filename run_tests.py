"""
Standalone test runner for SubversionBench — works without pytest.

Prefer `pytest` when it's available; this exists so the suite is still
runnable in a bare environment. Test modules and classes are discovered
rather than listed, so a new test file or class is picked up automatically.

Run: python run_tests.py [test_sandbox.py ...]
"""

import sys
import inspect
import pathlib
import importlib
import importlib.util
import traceback

from conftest import FIXTURE_FACTORIES

HERE = pathlib.Path(__file__).parent


def _load(path: pathlib.Path):
    """Import one test file by location, wherever it sits."""
    name = ".".join(path.relative_to(HERE).with_suffix("").parts)
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def discover_modules(argv):
    """
    Test modules to run: those named on the command line, else all of them.

    Recursive, and loaded by path rather than by importable name. The test tree
    mirrors the package tree - test_grading/, test_readmodes/ and
    test_reporting/facts/ beside the packages of those names - and a top-level
    glob silently ran 363 of 495 tests while reporting success, which is worse
    than failing.
    """
    if argv:
        paths = [pathlib.Path(a) for a in argv]
    else:
        paths = sorted(HERE.rglob("test_*.py"))
        paths = [p for p in paths
                 if not any(part.startswith(".") or part == "eval_results"
                            for part in p.parts)]
    return [_load(p if p.is_absolute() else HERE / p) for p in paths]


def run():
    modules = discover_modules(sys.argv[1:])
    if not modules:
        print("No test modules found.")
        return 1

    passed = failed = 0
    errors = []

    for module in modules:
        classes = [
            obj for name, obj in vars(module).items()
            if inspect.isclass(obj) and name.startswith("Test")
            and obj.__module__ == module.__name__
        ]
        print(f"\n{module.__name__} ({len(classes)} class(es))")

        for cls in classes:
            instance = cls()
            methods = sorted(
                m for m in dir(instance) if m.startswith("test_")
            )
            for method_name in methods:
                method = getattr(instance, method_name)
                label = f"{cls.__name__}.{method_name}"

                try:
                    # Build whichever fixtures this test's signature asks for.
                    kwargs = {
                        name: factory()
                        for name, factory in FIXTURE_FACTORIES.items()
                        if name in inspect.signature(method).parameters
                    }
                    method(**kwargs)
                    passed += 1
                    print(f"  PASS  {label}")
                except Exception as e:
                    failed += 1
                    errors.append((label, e))
                    print(f"  FAIL  {label}: {e}")

    print(f"\n{'='*60}")
    print(f"Results: {passed} passed, {failed} failed, {passed + failed} total")
    print(f"{'='*60}")

    if errors:
        print("\nFailures:")
        for label, err in errors:
            print(f"\n  {label}:")
            traceback.print_exception(type(err), err, err.__traceback__)

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(run())
