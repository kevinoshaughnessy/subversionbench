"""
The package's own shape: analysis above presentation, and one import site.

Not tests of behaviour. `trends/__init__.py` states why the package is a
package - matplotlib is an optional extra and losing it must cost presentation,
never analysis - and these are what stop that from becoming a comment about
something that used to be true.
"""


import os
import tempfile

import trends as ft
from subversionbench import charting
from test_analysis.report_fixtures import _write_summary


class TestTheAnalysisDoesNotDependOnTheDrawing:
    """The seam the package is split on, asserted rather than described.

    The old single file said in its own comments that matplotlib was optional
    and that "losing the charts costs presentation, never analysis" - but
    nothing checked it, and nothing could: with the drawing and the p-values in
    one module, importing either imported both. These are the tests that make
    the claim mean something, and they are the reason to keep the boundary where
    it is when the next chart is added.
    """

    ANALYSIS = ("model_ids", "metrics", "report")
    NO_PYPLOT = ANALYSIS + ("chart_geometry", "captions")

    def _imports(self, leaf):
        import ast
        names = set()
        tree = ast.parse(open(f"trends/{leaf}.py").read())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names |= {a.name for a in node.names}
            elif isinstance(node, ast.ImportFrom):
                names.add(("." * node.level) + (node.module or ""))
        return names

    def test_the_analysis_modules_import_no_chart_module(self):
        """Not a style preference. `report.py` is what the console, the charts
        and the JSON all read, and a report that imported a chart module could
        not be computed on a machine without matplotlib installed."""
        charts = {".chart_style", ".chart_geometry", ".captions",
                  ".version_charts", ".date_charts", ".charts"}
        for leaf in self.ANALYSIS:
            crossed = self._imports(leaf) & charts
            assert not crossed, f"trends/{leaf}.py imports {sorted(crossed)}"

    def test_only_one_module_in_the_repository_reaches_matplotlib(self):
        """One import site for the optional dependency, so the install hint is
        printed in one place and cannot be bypassed by a second import.

        Scoped to the RULE and not to a path. This was `glob("trends/*.py")`
        with chart_style exempt, which passed while report_charts.py and
        sad_oversight.py each carried their own copy of the same function - two
        of the three character-for-character identical. A guard written against
        a directory only ever guards that directory.
        """
        import glob
        offenders = []
        for path in sorted(set(
                glob.glob("subversionbench/**/*.py", recursive=True)
                + glob.glob("trends/*.py") + glob.glob("report/*.py")
                + glob.glob("*.py"))):
            if path == "subversionbench/charting.py":
                continue            # the one implementation
            if os.path.basename(path).startswith("test_"):
                continue            # a test may check whether it is installed
            body = open(path).read()
            if "import matplotlib" in body:
                offenders.append(path)
        assert not offenders, (
            f"these import matplotlib themselves rather than going through "
            f"charting.import_pyplot: {offenders}")

    def test_the_layout_and_caption_passes_never_draw(self):
        """They are the part of the chart code most likely to be wrong, and they
        are testable without the optional dependency only while this holds: a
        layout that took an `ax` would have to be exercised through a figure."""
        for leaf in self.NO_PYPLOT:
            assert not any("matplotlib" in n for n in self._imports(leaf)), leaf

    def test_the_analysis_modules_import_in_a_bare_environment(self):
        """The claim itself, run rather than inferred from the imports: every
        module above loads with matplotlib made unimportable."""
        import subprocess
        import sys
        script = (
            "import builtins, sys\n"
            "real = builtins.__import__\n"
            "def blocked(name, *a, **k):\n"
            "    if name.split('.')[0] == 'matplotlib':\n"
            "        raise ImportError('no matplotlib')\n"
            "    return real(name, *a, **k)\n"
            "builtins.__import__ = blocked\n"
            "from trends.report import build_report\n"
            "from trends.chart_geometry import axis_top, release_span\n"
            "from trends.captions import _exposure_note\n"
            "assert axis_top([3.0]) == 5\n"
            "print('ok')\n")
        out = subprocess.run([sys.executable, "-c", script],
                             capture_output=True, text=True)
        assert out.returncode == 0, out.stderr
        assert "ok" in out.stdout

    def test_the_charts_still_degrade_rather_than_fail(self):
        """The other half of "optional": write_charts returns no paths and the
        report is unaffected. This is what the analysis/presentation split is
        FOR, so it is asserted here and not only where charts are drawn.

        Two things this got wrong when it was written, both of which made it
        pass while testing nothing. It patched `chart_style._import_pyplot`,
        but write_charts had bound that name at import time, so the patch never
        reached it - the documented reason this repo calls stubbed dependencies
        through their module. And it passed a report with NO FAMILIES, which
        returns no paths whether matplotlib is there or not. It now patches the
        owning module and asserts against a report that does produce charts.
        """
        with tempfile.TemporaryDirectory() as out:
            report = self._report_with_one_family(out)

            # Not vacuous: the same report DOES write charts with pyplot present.
            if charting.import_pyplot() is not None:
                assert ft.write_charts(report, os.path.join(out, "on")), (
                    "the fixture draws nothing even with matplotlib installed, "
                    "so the degraded assertion below would pass for the wrong "
                    "reason")

            saved = charting.import_pyplot
            charting.import_pyplot = lambda *a, **k: None
            try:
                assert ft.write_charts(report, os.path.join(out, "off")) == []
            finally:
                charting.import_pyplot = saved

    def _report_with_one_family(self, out):
        """A report that really produces charts, so the degraded case has
        something to be the absence of.

        Built by build_report from written summaries rather than hand-rolled: a
        literal dict here needs every key the plotting code happens to read
        today, and the first attempt at one was missing `ordering_ambiguous`.
        A fixture that has to track a consumer's field list is a fixture that
        goes stale silently.
        """
        for model, n in (("x-ai/grok-4", 12), ("x-ai/grok-4.5", 6)):
            _write_summary(out, model, "strong", n_runs=60, n_misaligned=n,
                           n_aware=2, n_unaware=8)
        report = ft.build_report(out, "misaligned")
        assert report["families"], "the fixture produced no family to chart"
        return report


class TestTheSingleImportSite:
    def test_every_name_the_package_offers_is_declared(self):
        """`trends/__init__.py` re-exports 70 names, most of them private, and
        without `__all__` each one reads as a stray import to the dead-import
        guard. So the declaration is the interface, and this is what keeps it
        from going stale in either direction."""
        import trends
        declared = set(trends.__all__)
        reachable = {n for n in dir(trends)
                     if not n.startswith("__")
                     and n not in {"captions", "chart_geometry", "chart_style",
                                   "charts", "console", "date_charts",
                                   "family_trends", "metrics", "model_ids",
                                   "report", "version_charts"}}
        assert declared == reachable, (
            f"declared but absent: {sorted(declared - reachable)}; "
            f"present but undeclared: {sorted(reachable - declared)}")

    def test_no_test_rebinds_a_name_through_the_package(self):
        """Why the re-export is safe. A function resolves globals in ITS OWN
        module, so patching `trends.axis_top` would not reach a caller that
        lives in trends/version_charts.py - it would silently assert nothing.
        A config.py re-export walked into exactly that."""
        import re
        body = open(__file__).read()
        offenders = re.findall(r"(?:setattr\(ft,|ft\.\w+\s*=(?!=))", body)
        assert not offenders, (
            f"rebound through the package rather than on the module that "
            f"defines the name: {offenders}. Patch the submodule instead - see "
            f"test_the_charts_still_degrade_rather_than_fail.")
