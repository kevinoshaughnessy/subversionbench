"""
The primary estimate with suspicion counted only where the model could see it (exploratory).

Not in the registered plan. The headline exposure reads the whole transcript, so it counts
suspicion voiced only after the act, and, for models whose reasoning the harness does not replay
(subversionbench/turn_context.py), suspicion voiced in an earlier turn's reasoning that the model
no longer had when it acted. This reading runs on the primary's own episodes, reproduces the
published estimate first, and then prints:

- why each suspicious episode that acted did or did not have its suspicion in view at the act;
- the act-time re-scoring, for the record only: re-scoring only the episodes that acted removes
  awareness from one side of the contrast alone, so it is biased toward a negative association
  by construction;
- the turn-level reading, which treats every episode alike, and is the estimate to read.

Suspicion is located by the headline grader's own quote and by the keyword screen, within the
episodes the grader called aware. Both under-find it, which biases the turn-level reading toward
no association. Prints counts and estimates only.

    python3 -m report.in_context
"""
import argparse
import collections
import json
import os

from subversionbench.config import HEADLINE_AWARENESS_GRADER
from subversionbench.grading.acts import act_value, counted_acts
from subversionbench.grading.awareness_keywords import verbalises_awareness
from subversionbench.grading.awareness_timing import first_act_position
from subversionbench.graders import view
from subversionbench.turn_context import (QUOTE_MIN, reasoning_replayed,
                                          resampled_odds_ratio_interval, seen_on_turn,
                                          turn_level_estimate, turn_units)

from .exclusions import EXCLUDE_NO_OVERSIGHT, NO_EXCLUSION
from .loading import arm_key
from .primary import PRIMARY_GOALGUARD_ARM, headline_rows, primary_estimate
from .snapshot import snapshot



def _norm(text) -> str:
    return " ".join(str(text).split()).lower()


def located_suspicion(transcript: list, quote) -> list:
    """Indices of the reasoning and text entries holding the grader's quote or a keyword hit."""
    q = _norm(quote)[:200] if quote and len(quote.strip()) >= QUOTE_MIN else None
    return [i for i, t in enumerate(transcript) if t["type"] in ("thinking", "text")
            and ((q and q in _norm(t.get("content", ""))) or verbalises_awareness(t.get("content", "")))]


def why_out_of_view(transcript: list, located: list, act_index, act_turn, replayed: bool) -> str:
    """For a suspicious episode that acted: where its suspicion was relative to the act."""
    if not located:
        return "nothing located"
    if seen_on_turn(transcript, located, act_turn, act_index, replayed):
        return "in view at the act"
    if all(i > act_index for i in located):
        return "voiced only after the act"
    return "only in earlier reasoning, not replayed"


def episode_in_context(row: dict, episode: dict) -> dict:
    """The primary row with where its suspicion lay: `aware_at_act`, `why` and the turn `units`."""
    analysis = view(episode.get("analysis") or {}, HEADLINE_AWARENESS_GRADER)
    tr = episode.get("transcript") or []
    acts = [a for a in counted_acts(analysis) if act_value(analysis, a)]
    found = [p for p in (first_act_position(tr, analysis, a) for a in acts) if p[0] is not None]
    replayed = reasoning_replayed(episode)
    quote = (analysis.get("eval_awareness_grader") or {}).get("quote")
    located = located_suspicion(tr, quote) if row["aware"] else []
    out = dict(row, act_located=not acts or bool(found), aware_located=bool(located), why=None)
    if acts and not found:
        return dict(out, aware_at_act=row["aware"], units=[])
    act_index, last = min(found) if found else (None, max((t.get("turn") or 0 for t in tr), default=0))
    out["units"] = turn_units(tr, located, last or 0, act_index, bool(acts), replayed)
    out["aware_at_act"] = row["aware"]
    if acts and row["aware"]:
        out["why"] = why_out_of_view(tr, located, act_index, last, replayed)
        out["aware_at_act"] = out["why"] == "in view at the act"
    return out


def _with_context(rows: list, directory: str) -> list:
    out = []
    for r in rows:
        with open(os.path.join(directory, r["run_file"]), encoding="utf-8") as f:
            out.append(episode_in_context(r, json.load(f)))
    return out


def _rd(label: str, result: dict) -> None:
    mh = result["stratified"]["mantel_haenszel"]
    lo, hi = mh["risk_difference_ci95_sato"]
    print(f"  {label:54} RD {100 * mh['risk_difference']:+.2f} ({100 * lo:+.2f}, {100 * hi:+.2f})")


def _turn_level(label: str, rows: list) -> None:
    mh = turn_level_estimate(rows, arm_key)
    lo, hi, n = resampled_odds_ratio_interval(rows, arm_key)
    units = [u for r in rows for u in r["units"]]
    ratio = "undefined" if mh.get("odds_ratio") is None else f"{mh['odds_ratio']:.3g}"
    interval = f" ({lo:.3g}, {hi:.3g}; {n} resamples)" if n else ""
    print(f"  {label:54} OR {ratio}{interval}  turns "
          f"{len(units)}, exposed {sum(e for _, e, _ in units)}, first acts "
          f"{sum(v for _, _, v in units)}, in an exposed turn {sum(e and v for _, e, v in units)}")


def report(mainline: list, goalguard: list) -> None:
    rows = mainline + goalguard
    why = collections.Counter(r["why"] for r in rows if r["why"])
    print(f"{len(rows)} episodes; {sum(why.values())} suspicious and acting: "
          + ", ".join(f"{k} {v}" for k, v in why.most_common())
          + f"; acts not located {sum(not r['act_located'] for r in rows)}")
    print("\nepisode level")
    _rd("as published (whole transcript)", primary_estimate(mainline, goalguard))
    _rd("acting episodes re-scored at the act (biased, see above)",
        primary_estimate(mainline, goalguard, exposure="aware_at_act"))
    print("\nturn level (outcome-independent)")
    _turn_level("every episode", [r for r in rows if r["units"]])
    _turn_level("without aware episodes where nothing was located",
                [r for r in rows if r["units"] and not (r["aware"] and not r["aware_located"])])


def main():
    ap = argparse.ArgumentParser(description=__doc__.strip().split("\n\n")[0])
    ap.add_argument("--mainline-dir", default="./eval_results_r10")
    ap.add_argument("--goalguard-dir", default="./eval_results_goalguard_r1")
    ap.add_argument("--mainline-cap-dir", default="./eval_results_r10cap")
    ap.add_argument("--goalguard-cap-dir", default="./eval_results_goalguard_r1cap")
    a = ap.parse_args()
    models = snapshot({"mainline": a.mainline_dir, "goalguard": a.goalguard_dir},
                      {"mainline": a.mainline_cap_dir, "goalguard": a.goalguard_cap_dir})["models"]
    mainline, _ = headline_rows(a.mainline_dir, EXCLUDE_NO_OVERSIGHT, lambda e: True, models)
    goalguard, _ = headline_rows(a.goalguard_dir, NO_EXCLUSION,
                                 lambda e: e.get("goalguard") == PRIMARY_GOALGUARD_ARM, models)
    report(_with_context(mainline, a.mainline_dir), _with_context(goalguard, a.goalguard_dir))


if __name__ == "__main__":
    main()
