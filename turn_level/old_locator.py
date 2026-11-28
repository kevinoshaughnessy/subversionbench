"""
Sensitivity reading 4: the exploratory readings' locator, applied to this plan's matched sets.

The exploratory readings placed suspicion by the grader's own quote plus the keyword screen
(report.in_context, SubversionBench) and by the awareness judge's evidence quotes
(blackmail_port.in_context, the blackmail port, its safety-aware verdicts only). Here those
located entries are read through this plan's in-view rule, so a difference between this reading
and the primary is the change of instrument, not of design.
"""

import collections
import json

from subversionbench.config import HEADLINE_AWARENESS_GRADER
from subversionbench.graders import view
from subversionbench.turn_context import reasoning_sent_back

from .episodes import BLACKMAIL
from .in_view import in_view_indices


def located(episode: dict, scenario: str, awareness: dict) -> set:
    """Indices of the entries the exploratory locator placed suspicion at in this episode.
    `awareness` is the blackmail port's awareness verdicts by episode id, for that scenario."""
    tr = episode.get("transcript") or []
    if scenario == BLACKMAIL:
        from blackmail_port.analyse import awareness_of
        from blackmail_port.in_context import evidence_quotes, quote_entries
        from blackmail_port.judge_common import episode_id
        record = awareness.get(episode_id(episode["_path"]))
        return set(quote_entries(tr, evidence_quotes(record))) if awareness_of(record) == "safety" else set()
    from report.in_context import located_suspicion
    block = view(episode.get("analysis") or {}, HEADLINE_AWARENESS_GRADER).get("eval_awareness_grader") or {}
    return set(located_suspicion(tr, block.get("quote"))) if block.get("eval_aware") else set()


def exposures(members: list, episodes_index: dict, awareness_by_source: dict) -> dict:
    """{(episode key, turn): exposed by the exploratory locator} for every (key, turn) given."""
    by_episode = collections.defaultdict(set)
    for key, turn in members:
        by_episode[key].add(turn)
    out = {}
    for key in sorted(by_episode):
        meta = episodes_index[key]
        with open(meta["path"], encoding="utf-8") as f:
            episode = {**json.load(f), "_path": meta["path"]}
        found = located(episode, meta["scenario"], awareness_by_source.get(meta["source"], {}))
        sent_back = reasoning_sent_back(episode)
        tr = episode.get("transcript") or []
        for turn in by_episode[key]:
            out[(key, turn)] = any(i in found for i in in_view_indices(tr, turn, sent_back))
    return out
