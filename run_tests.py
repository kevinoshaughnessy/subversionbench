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
import traceback

from conftest import FIXTURE_FACTORIES

HERE = pathlib.Path(__file__).parent


def discover_modules(argv):
    """Test modules to run: those named on the command line, else all of them."""
    if argv:
        names = [pathlib.Path(a).stem for a in argv]
    else:
        names = sorted(p.stem for p in HERE.glob("test_*.py"))
    return [importlib.import_module(n) for n in names]


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
