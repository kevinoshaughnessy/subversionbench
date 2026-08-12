"""
Turning a batch of completed episodes into figures, a report and a summary.
"""

from .console import render_report
from .facts import (
    awareness_before_act_flag,
    awareness_flag,
    batch_facts,
    normalise_analyses,
    score_provenance,
)
from .summary import summarise_batch

__all__ = ["awareness_before_act_flag", "awareness_flag", "batch_facts",
           "normalise_analyses", "render_report", "score_provenance",
           "summarise_batch"]
