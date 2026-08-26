"""
Is misalignment falling as a model family advances?

Run it as `python3 -m trends`. This file is the single import
site: everything below is reached through `trends`, never through
`trends.chart_geometry` and its kin, so the layout inside can change without
moving anyone else's imports.

WHY THIS IS A PACKAGE AND NOT ONE FILE
--------------------------------------
Not size. It was 2,132 lines, but the reason to split was that a third of its
history changed only how a figure LOOKS - where a label sits, which caption a
chart carries, where the date axis starts - in a file that also computes
Cochran-Armitage p-values. The seam was already written into the old file's own
comments: matplotlib is an optional extra, and "losing the charts costs
presentation, never analysis". It just had no file boundary at it.

So the modules run analysis first, then presentation, and nothing points back:

  model_ids       an ID into a family and a version order. No metric, no rate.
  metrics         what can be trended, and the per-model rate and exposure.
  report          families, trends, release fits, data quality. THE analysis.
                  Imports no drawing code and needs no matplotlib.
  ---------------- everything above is a number; everything below shows it -----
  chart_style     what every chart looks like: palette, notes, resolution.
  chart_geometry  axis tops and label layouts, as arithmetic. No pyplot at all.
  captions        the words on a chart. Text only.
  version_charts  rate against version position - the axis the tests run on.
  date_charts     the same rates against the calendar.
  charts          write_charts: the one entry point the CLI calls.
  console         the report as a table on a terminal.
  family_trends   the command line. Arguments, and one report per metric.

The three renderings - table, charts, JSON - all read the document `report.py`
returns and none of them computes a figure of its own, which is what stops a
rate on a chart from disagreeing with the same rate in the table.
"""

from .captions import (_CAPTION_WRAP, _EXPOSURE_READING, _exposure_note,
                       _exposure_range_note, _member_labels,
                       _release_point_name, _slope_label, _wrap_caption)
from .chart_geometry import (_COMBINED_AXIS_PT, _DATE_LABEL_CEILING,
                             _DATE_LABEL_DX, _DATE_LABEL_DY, _DATE_LABEL_ROW,
                             _DATE_LABEL_XGAP, _LABEL_CHAR_PT, _LABEL_DX,
                             _LABEL_GAP, _LABEL_ROW, _MIN_AXIS_TOP,
                             _PER_FAMILY_AXIS_PT, RELEASE_AXIS_START,
                             _date_label_layout, _label_extent, _label_layout,
                             _lower_error, _point_label, _upper_error,
                             axis_top, release_span)
from .chart_style import (CHART_DPI, FIT_NOTE, WILSON_NOTE,
                          WILSON_NOTE_BRACKETS_ONLY, WILSON_NOTE_WITH_BRACKETS,
                          _BRAND_COLOURS, _family_colours)
from .charts import write_charts
from .console import (_fmt_rate, _print_family, _print_release_date_errors,
                      _print_release_fit, _print_report)
from .date_charts import (_dated_members, _date_axis, _draw_release_fit,
                          _plot_all_family_dates, _plot_family_dates)
# Last, and importing nothing else here: family_trends reaches the siblings
# directly, so this line closes no cycle.
from .family_trends import _report_one_metric, main
from .metrics import (AWARENESS_METRICS, METRIC_ALL, METRICS,
                      _MAX_NAMED_SILENT, TEXT_REACHABLE, model_exposure,
                      model_rates)
from .model_ids import (QUALIFIER_TAGS, VERSION_STYLES, ModelId, family_key,
                        ordering_is_ambiguous, parse_model_id,
                        version_sort_key)
from .report import (_member_release_date, _verdict, build_report,
                     data_quality, family_trend, group_families, release_fit)
from .version_charts import _plot_all_families, _plot_family

# Named rather than left implicit because the private names above are here on
# purpose: the tests reach _label_layout, _date_label_layout, _exposure_note and
# their kin through this one site rather than importing the module that happens
# to hold them today. That is the whole point of a single import site - and
# without `__all__` every one of them reads as a stray import to anything
# checking this file.
__all__ = [
    "AWARENESS_METRICS", "CHART_DPI", "FIT_NOTE", "METRICS", "METRIC_ALL",
    "ModelId", "QUALIFIER_TAGS", "RELEASE_AXIS_START", "TEXT_REACHABLE",
    "VERSION_STYLES", "WILSON_NOTE", "WILSON_NOTE_BRACKETS_ONLY",
    "WILSON_NOTE_WITH_BRACKETS",
    "_BRAND_COLOURS", "_CAPTION_WRAP", "_COMBINED_AXIS_PT",
    "_DATE_LABEL_CEILING", "_DATE_LABEL_DX", "_DATE_LABEL_DY",
    "_DATE_LABEL_ROW", "_DATE_LABEL_XGAP", "_EXPOSURE_READING",
    "_LABEL_CHAR_PT", "_LABEL_DX", "_LABEL_GAP", "_LABEL_ROW",
    "_MAX_NAMED_SILENT", "_MIN_AXIS_TOP", "_PER_FAMILY_AXIS_PT",
    "_date_axis", "_date_label_layout", "_dated_members", "_draw_release_fit",
    "_exposure_note", "_exposure_range_note", "_family_colours", "_fmt_rate",
    "_label_extent", "_label_layout", "_lower_error",
    "_member_labels", "_member_release_date", "_plot_all_families",
    "_plot_all_family_dates", "_plot_family", "_plot_family_dates",
    "_point_label", "_print_family", "_print_release_date_errors",
    "_print_release_fit", "_print_report", "_release_point_name",
    "_report_one_metric", "_slope_label", "_upper_error", "_verdict",
    "_wrap_caption",
    "axis_top", "build_report", "data_quality", "family_key", "family_trend",
    "group_families", "main", "model_exposure", "model_rates",
    "ordering_is_ambiguous", "parse_model_id", "release_fit", "release_span",
    "version_sort_key", "write_charts",
]
