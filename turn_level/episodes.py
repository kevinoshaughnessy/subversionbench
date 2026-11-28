"""
A corpus's analysed episodes as compact records: who, which stratum, when each act became
possible, and where the first counted act was.

Each corpus is read as its own registered analysis defines its analysed episodes, by that
analysis's code rather than a copy of its rules:

- SubversionBench (A): the registered primary's episodes, selected exactly as report.primary and
  report.in_context select them (complete models, the headline grader's reading, the mainline's
  oversight arms and the goal-guarding scenario's primary arm). `no_oversight=True` gives the
  mainline's no-oversight arms instead, for sensitivity reading 9.
- The blackmail port (B, C): blackmail_port.analyse's episode rows, its threat arms and its
  exclusions (a missing harm verdict, a reply cut off by the token limit), over the models the
  caller names. The port's awareness verdicts play no part: exposure is judged afresh.

A record keeps no transcript; the judge reloads the run file from `path`.

    {"key", "source", "episode", "path", "model", "stratum", "scenario", "last_turn",
     "opportunity": {act kind: turn or None}, "act": {"kind", "index", "turn"} or None,
     "act_unlocated": bool}
"""

import collections
import json
import os

from subversionbench.config import HEADLINE_AWARENESS_GRADER
from subversionbench.graders import view
from subversionbench.grading.acts import act_value, counted_acts
from subversionbench.grading.awareness_timing import first_act_position

from .opportunity import act_opportunity, leverage_opportunity, leverage_snippets

BLACKMAIL = "blackmail"


def last_turn(transcript: list) -> int:
    return max((e.get("turn") or 0 for e in transcript), default=0)


def unit_key(source: str, episode: str) -> str:
    """An episode's name across corpora: its run file's name under its corpus directory's."""
    return f"{source}/{episode}"


def first_counted_act(transcript: list, analysis: dict) -> tuple:
    """(the first counted act as {"kind", "index", "turn"} or None, whether an act was unlocated).

    Strict: if any act the episode took cannot be tied to a command, which act came first is
    unknown, so the episode has no locatable first act at all - it is not a case, and it serves
    as no control either (matching.py).
    """
    taken = [a for a in counted_acts(analysis) if act_value(analysis, a)]
    found = [(first_act_position(transcript, analysis, a), a["name"]) for a in taken]
    if any(index is None for (index, _turn), _name in found):
        return None, True
    if not found:
        return None, False
    (index, turn), kind = min(found, key=lambda f: f[0][0])
    return {"kind": kind, "index": index, "turn": turn}, False


def subversionbench_record(row: dict, episode: dict, path: str, scenario: str) -> dict:
    """One SubversionBench episode, from its primary row and its run file."""
    from report.loading import arm_key
    analysis = view(episode.get("analysis") or {}, HEADLINE_AWARENESS_GRADER)
    tr = episode.get("transcript") or []
    act, unlocated = first_counted_act(tr, analysis)
    source = os.path.basename(os.path.dirname(os.path.abspath(path)))
    name = os.path.basename(path)[:-len(".json")]
    return {
        "key": unit_key(source, name), "source": source, "episode": name, "path": path,
        "model": row["model"], "stratum": list(arm_key(row)), "scenario": scenario,
        "last_turn": last_turn(tr),
        "opportunity": {a["name"]: act_opportunity(episode, a) for a in counted_acts(analysis)
                        if act_value(analysis, a) is not None},
        "act": act, "act_unlocated": unlocated,
    }


def subversionbench_records(mainline_dir: str, goalguard_dir: str, mainline_cap_dir: str,
                            goalguard_cap_dir: str, no_oversight: bool = False) -> list:
    """The registered primary's episodes as records, or the mainline's no-oversight arms'."""
    from report.exclusions import EXCLUDE_NO_OVERSIGHT, NO_EXCLUSION
    from report.primary import PRIMARY_GOALGUARD_ARM, headline_rows
    from report.snapshot import snapshot
    models = snapshot({"mainline": mainline_dir, "goalguard": goalguard_dir},
                      {"mainline": mainline_cap_dir, "goalguard": goalguard_cap_dir})["models"]
    if no_oversight:
        readings = [("mainline", mainline_dir, headline_rows(
            mainline_dir, NO_EXCLUSION, lambda e: e.get("oversight") is False, models)[0])]
    else:
        readings = [
            ("mainline", mainline_dir,
             headline_rows(mainline_dir, EXCLUDE_NO_OVERSIGHT, lambda e: True, models)[0]),
            ("goalguard", goalguard_dir,
             headline_rows(goalguard_dir, NO_EXCLUSION,
                           lambda e: e.get("goalguard") == PRIMARY_GOALGUARD_ARM, models)[0])]
    records = []
    for scenario, directory, rows in readings:
        for row in rows:
            path = os.path.join(directory, row["run_file"])
            with open(path, encoding="utf-8") as f:
                records.append(subversionbench_record(row, json.load(f), path, scenario))
    return records


def _blackmail_exclusion(row: dict, models) -> str | None:
    from blackmail_port.analyse import THREAT
    if row["model"] not in models:
        return "model not in the plan"
    if row["condition"] not in THREAT:
        return "not a threat arm"
    if row["harm_missing"]:
        return "harm verdict missing"
    if row["cut_off"]:
        return "reply cut off"
    return None


def blackmail_records(corpus: str, judgements_dir: str, models) -> tuple:
    """(records, {exclusion reason: count}) for a blackmail port corpus's analysed threat-arm
    episodes. `judgements_dir` holds its harm verdicts, as blackmail_port.judge_harm wrote them."""
    from blackmail_port import analyse as A
    from blackmail_port import judge_common as J
    from blackmail_port.in_context import first_blackmail
    harm = A.verdicts(J.output_path("harm", corpus, judgements_dir), "harmful_behavior")
    bundle = J.bundle(corpus)
    screen = A.screen_patterns(bundle)
    snippets = {v: leverage_snippets(bundle, v) for v in A.THREAT}
    source = os.path.basename(corpus.rstrip("/"))
    records, excluded = [], collections.Counter()
    for path, e in J.episodes(corpus):
        row = A.episode_row(path, e, harm, {}, screen)
        reason = _blackmail_exclusion(row, models)
        if reason:
            excluded[reason] += 1
            continue
        tr = e["transcript"]
        index, turn = first_blackmail(tr, row["episode"], harm)
        records.append({
            "key": unit_key(source, row["episode"]), "source": source, "episode": row["episode"],
            "path": path, "model": row["model"], "stratum": [row["model"], row["condition"]],
            "scenario": BLACKMAIL, "last_turn": last_turn(tr),
            "opportunity": {BLACKMAIL: leverage_opportunity(e, snippets[row["condition"]])},
            "act": None if index is None else {"kind": BLACKMAIL, "index": index, "turn": turn},
            "act_unlocated": row["harm"] and index is None,
        })
    return records, dict(excluded)
