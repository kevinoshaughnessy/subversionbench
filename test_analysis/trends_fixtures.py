"""
Helpers shared by the trends test modules.

Not named `test_*`, so neither runner collects it as a suite file: pytest looks
for `test_*.py` and so does run_tests.discover_modules. It still counts as suite
rather than shipping source, because conftest.is_test_file decides that by
position - anything under a `test_*/` directory - so the project guards that
apply to tests apply here too.

They lived in test_family_trends.py while it was the only file that needed
them; they moved here when it became seven.
"""

def _flat(note: str) -> str:
    """
    A caption's wording with its line wrapping undone.

    Captions fold to a fixed width so a long clause cannot widen the saved
    figure, which puts newlines inside phrases. Assertions about what a caption
    SAYS go through here; the few about its line STRUCTURE use the note itself.
    """
    return " ".join(note.split())


def _pyplot_or_skip():
    """pyplot through the one import site, or skip.

    `charting.import_pyplot()` returns None rather than raising when matplotlib
    is absent, so a bare call would hand `None` to the function under test and
    fail somewhere unrelated. Under SUBVERSIONBENCH_NO_SKIPS the extra is
    installed and this never skips.
    """
    from subversionbench import charting
    plt = charting.import_pyplot()
    if plt is None:
        import unittest
        raise unittest.SkipTest("matplotlib not installed")
    return plt
