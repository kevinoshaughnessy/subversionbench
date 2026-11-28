"""
Judge every unit the matched sets name, with the headline grader's category question.

A unit is an episode, a turn and a view (store.SET_FILES says which views each set file needs).
It is judged by subversionbench.grading.category.awareness_block - the call, prompt and parser
every category pass uses, unchanged - on the unit's text as in_view.unit_texts renders it,
untruncated. The judge is told nothing about the unit's role, and a unit in several sets is
judged once.

Resumable and safe to re-run: a unit with a usable verdict is skipped, a failed one is asked
again until it has had store.MAX_ATTEMPTS calls, and every attempt is appended to the verdict
file. A unit whose earlier view holds no text is unexposed and costs no call. Without `run=True`
it counts what it would call and calls nothing. Prints counts and error classes, never text.
"""

import concurrent.futures
import datetime
import json
import time

from subversionbench import usage_ledger
from subversionbench.config import CATEGORY_INSTRUMENT, HEADLINE_AWARENESS_GRADER
from subversionbench.grading import category
from subversionbench.grading.quote_grounding import format_agent_text, scenario_corpus
from subversionbench.turn_context import reasoning_sent_back

from . import store
from .in_view import current_cut, unit_texts

# Words a provider's content filter uses when it refuses the prompt rather than failing to answer
# it. Counted apart from other failures, because a refusal is likely to fall on case turns.
REFUSAL_MARKERS = ("403", "flagged", "moderation", "content policy", "safety system")


def is_refusal(error) -> bool:
    return bool(error) and any(m in str(error).lower() for m in REFUSAL_MARKERS)


def units(sets_docs: dict) -> list:
    """Every (unit id, episode key, turn, view) the set files need, once each, in a fixed order."""
    out = {}
    for name, doc in sets_docs.items():
        spec = store.SET_FILES[name]
        for s in doc["sets"]:
            for member in [s["case"], *s["controls"]]:
                for v in spec["views"]:
                    uid = store.unit_id(member["episode"], member["turn"], v)
                    out[uid] = (uid, member["episode"], member["turn"], v)
        if spec["episode_level"]:
            for key in doc["episodes"]:
                uid = store.unit_id(key, None, "whole")
                out[uid] = (uid, key, None, "whole")
    return [out[k] for k in sorted(out)]


def episode_paths(sets_docs: dict) -> dict:
    return {k: e["path"] for doc in sets_docs.values() for k, e in doc["episodes"].items()}


def unit_text(episode: dict, turn, view: str) -> dict:
    """The text the judge reads for a unit, the scenario text for its quote check, and lengths."""
    tr = episode.get("transcript") or []
    if view == "whole":
        text = format_agent_text(tr)
        return {"text": text, "scenario": scenario_corpus(tr), "in_view_chars": len(text)}
    texts = unit_texts(tr, turn, reasoning_sent_back(episode))
    return {"text": texts[view], "scenario": scenario_corpus(tr[:current_cut(tr, turn)]),
            "in_view_chars": len(texts["in_view"]), "current_chars": texts["current_chars"],
            "current_has_reasoning": texts["current_has_reasoning"]}


def to_judge(all_units: list, verdicts: dict) -> list:
    """The units still owed a call: no usable verdict, and fewer than MAX_ATTEMPTS calls."""
    return [u for u in all_units
            if (verdicts.get(u[0]) or {}).get("record") is None
            and (verdicts.get(u[0]) or {}).get("attempts", 0) < store.MAX_ATTEMPTS]


def plan_counts(all_units: list, verdicts: dict) -> dict:
    """Per view: units, judged, failed for good, still to call."""
    owed = {u[0] for u in to_judge(all_units, verdicts)}
    out = {}
    for uid, _key, _turn, v in all_units:
        c = out.setdefault(v, {"units": 0, "judged": 0, "failed for good": 0, "to call": 0})
        c["units"] += 1
        slot = verdicts.get(uid) or {}
        if slot.get("record") is not None:
            c["judged"] += 1
        elif uid in owed:
            c["to call"] += 1
        else:
            c["failed for good"] += 1
    return out


def judge_unit(unit: tuple, prepared: dict, model: str) -> dict:
    """One unit's record. Runs on a worker thread and writes nothing."""
    uid, key, turn, v = unit
    lengths = {k: prepared[k] for k in ("in_view_chars", "current_chars", "current_has_reasoning")
               if k in prepared}
    base = {"unit": uid, "episode": key, "turn": turn, "view": v, "judge": model,
            "instrument": CATEGORY_INSTRUMENT, **lengths,
            "time": datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds")}
    if not prepared["text"].strip():
        return {**base, "no_call": True, "empty": True, "eval_aware": False, "category": None,
                "grading_failed": False}
    block = category.awareness_block(prepared["text"], model, CATEGORY_INSTRUMENT,
                                     scenario=prepared["scenario"])
    return {**base, "category": block["category"], "eval_aware": block["eval_aware"],
            "grading_failed": block["grading_failed"], "quote": block["quote"],
            "quote_grounded": block["quote_grounded"], "error_kind": block["error_kind"],
            "error": (block["error"] or "")[:300] or None, "refused": is_refusal(block["error"])}


class EpisodeCache:
    """The last episode loaded: units come sorted by episode, so one is enough."""

    def __init__(self, paths: dict):
        self.paths, self.key, self.episode = paths, None, None

    def get(self, key: str) -> dict:
        if key != self.key:
            with open(self.paths[key], encoding="utf-8") as f:
                self.key, self.episode = key, json.load(f)
        return self.episode


def _absorb(work: str, record: dict, tally: dict):
    store.append_verdict(work, record)
    if record.get("grading_failed"):
        tally["failed"] += 1
        tally["refused"] += bool(record.get("refused"))
        print(f"  failed: {record['unit'].rsplit('/', 1)[-1]} ({record.get('error_kind')})")
    else:
        tally["judged"] += 1
    return record.get("error_kind") if record.get("error_kind") in category.FATAL_ERROR_KINDS else None


def run_pass(work: str, todo: list, paths: dict, model: str, delay: float, concurrency: int) -> dict:
    """Judge `todo`, at most `concurrency` calls in flight and launches `delay` seconds apart.
    Stops launching on an error every remaining call would repeat. Returns the tally."""
    tally = {"judged": 0, "failed": 0, "refused": 0, "fatal": None}
    episodes, remaining, futures = EpisodeCache(paths), iter(todo), {}
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=max(1, concurrency))

    def launch(first: bool) -> bool:
        unit = next(remaining, None)
        if unit is None:
            return False
        if not first and delay:
            time.sleep(delay)
        prepared = unit_text(episodes.get(unit[1]), unit[2], unit[3])
        futures[pool.submit(judge_unit, unit, prepared, model)] = unit
        return True

    try:
        with usage_ledger.recording(work, "turn-level"):
            first = True
            while len(futures) < max(1, concurrency) and launch(first):
                first = False
            while futures:
                done, _ = concurrent.futures.wait(list(futures),
                                                  return_when=concurrent.futures.FIRST_COMPLETED)
                for future in done:
                    futures.pop(future)
                    tally["fatal"] = _absorb(work, future.result(), tally) or tally["fatal"]
                while tally["fatal"] is None and len(futures) < max(1, concurrency) and launch(False):
                    pass
    except KeyboardInterrupt:
        running = [f for f in futures if not f.cancel()]
        print(f"\nInterrupted: saving the {len(running)} call(s) in flight.")
        for future in concurrent.futures.as_completed(running):
            _absorb(work, future.result(), tally)
        tally["interrupted"] = True
    finally:
        pool.shutdown(wait=True, cancel_futures=True)
    return tally


def judge(work: str, run: bool = False, delay: float = 30, concurrency: int = 1,
          model: str = HEADLINE_AWARENESS_GRADER) -> int:
    """The `judge` step. Returns an exit code."""
    sets_docs = store.read_sets(work)
    if not sets_docs:
        print(f"No set files in {work}: run the sets step first.")
        return 1
    all_units, verdicts = units(sets_docs), store.read_verdicts(work)
    for v, c in plan_counts(all_units, verdicts).items():
        print(f"{v:8} " + ", ".join(f"{k} {n}" for k, n in c.items()))
    todo = to_judge(all_units, verdicts)
    if not todo or not run:
        print("Nothing to call." if not todo else
              f"Plan only: {len(todo)} unit(s) would be judged by {model}. Add --run to judge them.")
        return 0
    tally = run_pass(work, todo, episode_paths(sets_docs), model, delay, concurrency)
    print(f"judged {tally['judged']}, failed {tally['failed']} (refused {tally['refused']})"
          + (f"; stopped on {tally['fatal']}" if tally["fatal"] else ""))
    return 130 if tally.get("interrupted") else (1 if tally["fatal"] else 0)
