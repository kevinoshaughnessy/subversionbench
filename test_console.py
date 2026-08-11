"""
The batch report: that it renders, and that it only renders.

The report was 538 lines interleaved with the computation it printed, which is how
47 quantities came to be shown on the console and saved nowhere. What keeps that
from recurring is not the file split on its own but the boundary these tests pin:
the console takes finished figures, and has no way to compute one.
"""

import ast
import inspect
import io
import contextlib
import types

from subversionbench.reporting import console
from subversionbench.reporting.facts import batch_facts, normalise_analyses
from test_batch_facts import _episode


def _args(**over):
    base = dict(model="claude-opus-5", nudge="strong", effort=None,
                oversight=True, lure=False, output_dir="/tmp/nowhere",
                delay=0, max_tokens=8192, max_turns=40, no_power=True)
    base.update(over)
    return types.SimpleNamespace(**base)


def _render(episodes, **over):
    normalise_analyses(episodes)
    facts = batch_facts(episodes, {})
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        console.render_report(facts, _args(**over))
    return buf.getvalue()


def _sections():
    """The section functions, in definition order."""
    tree = ast.parse(inspect.getsource(console))
    return [n.name for n in tree.body
            if isinstance(n, ast.FunctionDef) and n.name.startswith("_")]


class TestItRenders:
    def test_a_clean_batch_prints_a_whole_report(self):
        out = _render([_episode(), _episode()])
        for heading in ("SUMMARY:", "Situational Understanding",
                        "Agentic Misalignment", "Scheming", "Timing"):
            assert heading in out, f"{heading!r} missing from the report"

    def test_an_arm_with_no_oversight_says_so_rather_than_printing_zero(self):
        """A definitional zero dressed as a measurement is the single most
        misleading thing this report used to produce."""
        episodes = [_episode(), _episode()]
        for e in episodes:
            e["analysis"]["monitoring_disabled"] = None
        out = _render(episodes)
        assert "n/a (no oversight mechanism in this arm)" in out
        assert "Disabled monitoring:    0/" not in out

    def test_a_scheming_episode_reaches_the_report(self):
        out = _render([_episode(tampered=True, disclosed=False,
                                answers=[{"verdict": "denied",
                                          "answer": "No."}])])
        assert "Scheming:               1/1" in out

    def test_the_report_survives_a_single_episode(self):
        """Every rate in it has a denominator that could be 1 or 0, and several are
        conditional on an act that may not have happened."""
        assert _render([_episode()]).count("---") > 4


class TestItOnlyRenders:
    def test_no_section_is_defined_but_never_called(self):
        """With nineteen sections, one that is defined and not called is a silently
        missing block of the report - no error, no failing test, just a heading
        nobody notices is gone."""
        called = set()
        for node in ast.walk(ast.parse(inspect.getsource(console.render_report))):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                called.add(node.func.id)
        orphaned = [s for s in _sections() if s not in called]
        assert not orphaned, f"defined but never called: {orphaned}"

    def test_render_report_takes_no_episodes(self):
        """If it could see the episodes it could compute from them, and the
        computation would drift back out of facts.py one figure at a time."""
        params = list(inspect.signature(console.render_report).parameters)
        assert params == ["facts", "args", "power"]
        # Checked as an IDENTIFIER, not as text: the module docstring explains this
        # very constraint and so contains the word. A substring test on source is
        # exactly the defect class this codebase keeps finding in its own matchers.
        names = {n.id for n in ast.walk(ast.parse(inspect.getsource(console)))
                 if isinstance(n, ast.Name)}
        assert "all_results" not in names
        assert "transcript" not in names

    def test_the_console_writes_nothing_and_spends_nothing(self):
        src = inspect.getsource(console)
        for forbidden in ("open(", "json.dump", "get_client",
                          "detect_eval_awareness_grader", "settle_analysis"):
            assert forbidden not in src, f"{forbidden} in the console layer"

    def test_no_section_derives_a_verdict(self):
        """The report must not re-classify anything. A section that recomputed a
        verdict could disagree with the summary built from the same batch, which is
        the class of defect settle_analysis exists to prevent."""
        src = inspect.getsource(console)
        for forbidden in ("classify_misalignment", "classify_scheming",
                          "concealment_level", "classify_scheming_act"):
            assert forbidden not in src

    def test_every_section_is_small_enough_to_read(self):
        """The whole point of nineteen functions rather than one. A section past
        ~90 lines is doing more than formatting one block."""
        tree = ast.parse(inspect.getsource(console))
        oversized = {n.name: n.end_lineno - n.lineno + 1
                     for n in tree.body if isinstance(n, ast.FunctionDef)
                     and n.end_lineno - n.lineno + 1 > 90}
        assert not oversized, f"sections that have grown back: {oversized}"
