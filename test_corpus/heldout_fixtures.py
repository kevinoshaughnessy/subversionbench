"""
Selecting the held-out bundle, and reading it.

Not named `test_*`, so neither runner collects it as a suite file: pytest looks
for `test_*.py` and so does run_tests.discover_modules. It still counts as suite
rather than shipping source, because conftest.is_test_file decides that by
position - anything under a `test_*/` directory - so the project guards that
apply to tests apply here too.
"""

import os
import unittest
from pathlib import Path

from subversionbench.scenario import BUNDLE_ENV_VAR

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BUNDLE_PATH = PROJECT_ROOT / "heldout" / "scenario_heldout.enc"

class overridden:
    """`SUBVERSIONBENCH_SCENARIO_BUNDLE` set to `path` for the block.

    A context manager rather than a pytest fixture. test_dependencies.py
    refuses fixture and parametrize decorators anywhere in this suite, because
    run_tests.py is pytest-free and cannot interpret one - it would report a
    failure it could not explain. (Naming the decorator here would trip that
    guard, which matches a decorator at the start of a line and would find this
    docstring.)
    """

    def __init__(self, path):
        self.path = str(path) if path is not None else None

    def __enter__(self):
        self.before = os.environ.get(BUNDLE_ENV_VAR)
        if self.path is None:
            os.environ.pop(BUNDLE_ENV_VAR, None)
        else:
            os.environ[BUNDLE_ENV_VAR] = self.path
        return self

    def __exit__(self, *exc):
        if self.before is None:
            os.environ.pop(BUNDLE_ENV_VAR, None)
        else:
            os.environ[BUNDLE_ENV_VAR] = self.before
        return False


def _heldout_bundle() -> dict:
    """The decrypted held-out bundle, or a skip when it is not here."""
    if not BUNDLE_PATH.is_file():
        raise unittest.SkipTest(
            "the held-out bundle is not in this checkout (it is gitignored)")
    from sad_oversight import decrypt
    return decrypt(BUNDLE_PATH.read_text(encoding="utf-8"))
