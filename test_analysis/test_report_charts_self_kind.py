"""
The self-graded kind questions' `primary_reading` parallel measure, and the
legend bug it exposed - a "parallel"-kind row's legend text used to be one
fixed per-KIND string, correct while only `text_reachable` used the kind and
silently wrong the moment `primary_reading` became a second row sharing it.

Split out of test_report_charts.py, which was at the 1000-line ceiling - the
same reason test_report_awareness_kind.py was split out earlier.
"""

import report_charts as rc
from test_analysis.chart_fixtures import _contrast, _plt, _section


class TestThePrimaryReadingParallelMeasure:
    """The self-graded questions' parallel row - the primary grader's OWN
    classification, recomputed over the exact episodes the self-graded rate
    is drawn from. A second, DIFFERENT measure from text_reachable's, sharing
    only the "parallel" kind with it."""

    def test_it_draws_its_own_row(self):
        with_primary = _section(primary_reading={
            "overall": _contrast(40, 200, 60, 200, diff=-0.1,
                                 ci=(-0.2, -0.02), separated=True)})
        row = next(r for r in rc._pooled_rows(with_primary)
                  if r.kind == "parallel")
        assert "primary grader" in row.label

    def test_both_parallel_rows_can_be_drawn_together_with_distinct_labels(self):
        """The bug this guards: the legend used to be built from a fixed
        per-KIND name, so a chart carrying both parallel measures at once
        would have shown "parallel measure (visible text only)" beside the
        primary-reading row too - a label contradicting what it points at."""
        both = _section(
            text_reachable={"overall": _contrast(
                300, 1179, 250, 1200, diff=0.0463,
                ci=(0.01, 0.08), separated=True)},
            primary_reading={"overall": _contrast(
                40, 200, 60, 200, diff=-0.1, ci=(-0.2, -0.02), separated=True)})
        rows = [r for r in rc._pooled_rows(both) if r.kind == "parallel"]
        assert len(rows) == 2
        assert {r.label for r in rows} == {
            "PARALLEL: awareness in visible text only",
            "PARALLEL: primary grader's reading, same episodes"}


class TestTheParallelKindLegendReadsFromTheRow:
    """_legend_handles used to hold one fixed string per row KIND. That broke
    the moment a second, differently-labelled row shared the "parallel" kind
    - see report_charts/draw.py's own comment on why the fix reads the label
    off the row instead."""

    def _handles(self, rows):
        """matplotlib is an optional extra - _plt() skips where it is absent,
        the same guard test_report_charts.py's own _labelled uses."""
        _plt()
        from report_charts.draw import _legend_handles
        return {h.get_label(): h for h in _legend_handles(rows)}

    def test_the_legend_text_comes_from_the_row_not_a_fixed_name(self):
        handles = self._handles([
            rc.Row("PARALLEL: primary grader's reading, same episodes",
                  -0.1, -0.2, -0.02, "parallel")])
        assert "primary grader's reading, same episodes" in handles
        assert not any("visible text" in label for label in handles)
