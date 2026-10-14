"""
No function is over 100 lines, source and suite alike.

WHY THIS IS CHECKED RATHER THAN REMEMBERED. AGENTS.md stated the limit as a
ratchet - nothing new over it, anything over it only shrinking - and nothing
checked it. Thirty-four functions were over when that was written; thirty-eight
were by the time it was measured again, six of them having grown on one branch
and one having crossed the line there. A rule a reviewer has to measure by hand
is a rule that is measured once in a while.

So all of them were brought under it and the rule is now plain, with no baseline
to add an entry to - the same shape as the file limit in test_project_files.py.
Scope comes from conftest, so a module added later inherits the rule.

LENGTH IS THE DEF'S LINE TO ITS LAST LINE, docstring and comments included,
decorators not: what a reader has to hold to read the function. A nested
function counts toward its parent as well as on its own, because it is read as
part of the parent.
"""

import ast
import tempfile
from pathlib import Path

from conftest import PROJECT_ROOT, source_python_files, suite_python_files

MAX_FUNCTION_LINES = 100


def _too_long(paths) -> list:
    """`path:line name: N lines` for every function over the limit, longest
    first."""
    found = []
    for rel in paths:
        tree = ast.parse((PROJECT_ROOT / rel).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                n = node.end_lineno - node.lineno + 1
                if n > MAX_FUNCTION_LINES:
                    found.append((n, f"{rel}:{node.lineno} {node.name}"))
    return [f"{where}: {n} lines" for n, where in sorted(found, reverse=True)]


class TestNoFunctionIsOverTheLimit:

    def test_no_source_function_is_over_the_limit(self):
        files = source_python_files()
        assert files, "no source files - the guard would pass vacuously"
        assert not _too_long(files), (
            f"over {MAX_FUNCTION_LINES} lines. Split on a division the "
            f"function already has - a comment acting as a section header is "
            f"the usual one - rather than for the number (see AGENTS.md):\n  "
            + "\n  ".join(_too_long(files)))

    def test_no_suite_function_is_over_the_limit(self):
        files = suite_python_files()
        assert files, "no suite files - the guard would pass vacuously"
        assert not _too_long(files), (
            f"over {MAX_FUNCTION_LINES} lines:\n  "
            + "\n  ".join(_too_long(files)))

    def test_the_check_fires_on_a_function_that_is_over(self):
        """Every function satisfies the rule, so both checks above find
        nothing - which is the same answer a broken scan gives."""
        body = "    x = 1\n" * MAX_FUNCTION_LINES
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT) as tmp:
            path = Path(tmp) / "long_function.py"
            path.write_text(f"def f():\n{body}", encoding="utf-8")
            found = _too_long([path.relative_to(PROJECT_ROOT)])
        assert len(found) == 1, found
        assert found[0].endswith(f"f: {MAX_FUNCTION_LINES + 1} lines"), found

    def test_a_nested_function_counts_toward_its_parent(self):
        """Hiding the length in an inner def does not make the outer one any
        shorter to read."""
        inner = "    def g():\n" + "        x = 1\n" * MAX_FUNCTION_LINES
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT) as tmp:
            path = Path(tmp) / "nested.py"
            path.write_text(f"def f():\n{inner}", encoding="utf-8")
            found = _too_long([path.relative_to(PROJECT_ROOT)])
        assert [f.split()[1].rstrip(":") for f in found] == ["f", "g"], found

    def test_a_function_exactly_at_the_limit_passes(self):
        body = "    x = 1\n" * (MAX_FUNCTION_LINES - 1)
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT) as tmp:
            path = Path(tmp) / "at_limit.py"
            path.write_text(f"def f():\n{body}", encoding="utf-8")
            assert _too_long([path.relative_to(PROJECT_ROOT)]) == []
