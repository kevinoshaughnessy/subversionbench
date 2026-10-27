"""
The quality-check markers the report restates (report/transcript_columns.py).

The report matches the same literals the grader matches, restated rather than
imported. A marker changed on one side and not the other would report no
quality-check pressure anywhere and raise nothing, so each literal is checked
against the grader's own source.
"""

from pathlib import Path

import subversionbench.grading.transcript_analysis as grader
from report.transcript_columns import (QUALITY_CHECK_MARKER,
                                       QUALITY_CHECK_OUTCOMES)


def test_the_grader_still_matches_every_marker_the_report_restates():
    source = Path(grader.__file__).read_text(encoding="utf-8")
    for literal in [QUALITY_CHECK_MARKER] + [m for _, m in QUALITY_CHECK_OUTCOMES]:
        assert literal in source, f"the grader no longer writes {literal!r}"
