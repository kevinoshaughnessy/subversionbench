"""
Charts for the twelve research questions answered by the report package.

Every number drawn here is already in that script's printed output and in its
JSON. A chart is a second reading of the same figures, never a new claim, which
is why matplotlib stays an optional extra: losing these costs presentation and
never analysis.

WHY A FOREST PLOT AND NOT A BAR CHART
-------------------------------------
Two bars for "oversight present" and "oversight absent" show the rates and hide
everything the report actually spends its length on. Questions 1-10 are each
answered four ways - the crude pooled effect, the model-stratified effect, the
per-model consistency, and how the effect moves under the other axes - and three
of those four are statements about the SPREAD across models rather than about
the pooled number. A forest is the shape that holds them together: one row per
model with its interval, then the two pooled estimates underneath.

It also makes the failure mode the report warns about visible instead of
inferable. `crude_vs_stratified` exists because a crude contrast can separate at
p<0.001 with no within-model evidence behind it - question 9 on r9 is exactly
that, with all 24 of its outcome events inside one model. On a forest, that is a
row of intervals straddling zero under a summary diamond that does not, which a
reader sees before reading a word.

Drawing only one of the two pooled estimates would defeat that check, so both
are always drawn, and where the crude and stratified rows disagree in sign or
separation the caption says so in the report's own words.

RISK DIFFERENCES, NOT ODDS RATIOS
---------------------------------
The Mantel-Haenszel block carries both, and the odds ratio is the better-behaved
estimate. The charts still plot the risk difference, because that is the number
the printed report leads with and the one the questions are phrased in - "does
oversight increase or decrease the rate" is a question about percentage points.
A chart whose headline figure cannot be found in the text it illustrates is
worse than no chart. The odds ratio stays in the JSON and in the console.

WHAT IS DRAWN WHEN THERE IS NOTHING TO DRAW
-------------------------------------------
A model with no episodes on one side of the contrast has no difference and no
interval. Those models are drawn as an open marker on the zero line with the
reason beside them rather than dropped, because dropping them would silently
shrink the denominator of the consistency count printed above the chart - the
report says "18/28 had data on both sides", and a chart showing 18 rows makes
that sentence unverifiable.

QUESTIONS 11 AND 12 ARE A DIFFERENT SHAPE
-----------------------------------------
Every interrogation phrasing is put to the same act in the same episode, so
those questions are paired: exact McNemar over discordant pairs, reported as a
list of contrasts that are deliberately never pooled. Their charts hold one row
per contrast rather than one row per model, and each row is annotated with the
discordant counts, because those two numbers ARE the test - the concordant pairs
contribute nothing to the p-value, and a reader who sees n=803 without seeing
that 66 pairs carried the whole comparison will over-read the precision.

ONE MODULE PER THING A CHART IS ABOUT
-------------------------------------
This was one 1,580-line file divided by nine section banners, two of which had
gone stale - the drawing primitives were spread across three of them, and the
one titled "Entry point" held the signal charts. The divisions were real; only
the file was missing them.

`draw` owns HOW a chart is drawn and every plot module calls it through
`draw.`, so a test that wants to see the rows a plot built - without rendering
them - has one patch point rather than one per caller.

Everything the rest of the project reads is re-exported here, so
`report_charts.write_charts(...)` and `report_charts.exposure_of(...)` still
resolve.
"""

from . import (captions, characteristics, draw, exclusion, labels,
               lure, questions, rows, style, write)
from .captions import (_divergence_caption, _model_count_caption,
                       _rate_caption, _wrap)
from .characteristics import (_awareness_refusal_rows,
                              _encoded_payload_rate_rows,
                              _persistence_rate_rows, _persistence_slope_rows,
                              _signal_clusters,
                              plot_awareness_refusal_timing,
                              plot_encoded_payload_rate,
                              plot_eval_signal_rates, plot_persistence_rate,
                              plot_persistence_within_model)
from .draw import (_BelowAxes, _draw_forest, _draw_rate_chart,
                   _draw_signal_chart, _draw_slope_chart, _legend_handles)
from .exclusion import (_excluded_stratum, _exclusion_captions,
                        _exclusion_title_suffix, _scope_caption)
from .labels import arm_labels, exposure_of, short_label
from .lure import (_honeypot_rows, _lure_effect_rows, plot_honeypot_access,
                   plot_lure_misalignment)
from .questions import _question_title, plot_overview, plot_question
from .rows import Row, _ci, _model_rows, _paired_rows, _pooled_rows
from .style import (CHART_DPI, EXCLUDED_NOTE, MULTIPLICITY_NOTE, PP,
                    WILSON_NOTE, has_chart_support)
from .write import write_charts

__all__ = [
    "CHART_DPI", "EXCLUDED_NOTE", "MULTIPLICITY_NOTE", "PP", "Row",
    "WILSON_NOTE", "_BelowAxes", "_awareness_refusal_rows", "_ci",
    "_divergence_caption", "_draw_forest", "_draw_rate_chart",
    "_draw_signal_chart", "_draw_slope_chart", "_encoded_payload_rate_rows",
    "_excluded_stratum", "_exclusion_captions", "_exclusion_title_suffix",
    "_honeypot_rows", "_legend_handles", "_lure_effect_rows", "_model_count_caption",
    "_model_rows", "_paired_rows", "_persistence_rate_rows",
    "_persistence_slope_rows", "_pooled_rows", "_question_title",
    "_rate_caption", "_scope_caption", "_signal_clusters", "_wrap",
    "arm_labels", "captions", "characteristics", "charting", "draw",
    "exclusion", "exposure_of", "labels", "lure", "questions", "rows",
    "style", "write", "has_chart_support",
    "plot_awareness_refusal_timing", "plot_encoded_payload_rate",
    "plot_eval_signal_rates", "plot_honeypot_access", "plot_lure_misalignment",
    "plot_overview", "plot_persistence_rate", "plot_persistence_within_model",
    "plot_question", "short_label", "write_charts",
]

from subversionbench import charting  # noqa: E402 - re-exported for tests that
                                      # reach report_charts.charting.import_pyplot
