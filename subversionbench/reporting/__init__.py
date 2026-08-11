"""
Turning a batch of completed episodes into figures, a report and a summary.
"""

from .facts import (
    awareness_before_act_flag,
    awareness_flag,
    batch_facts,
    normalise_analyses,
    score_provenance,
)

__all__ = ["awareness_before_act_flag", "awareness_flag", "batch_facts",
           "normalise_analyses", "score_provenance"]
