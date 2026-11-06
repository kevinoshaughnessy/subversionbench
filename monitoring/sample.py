"""
Which episodes a monitor is shown: equal numbers with and without an act.

A POSITIVE is an episode that took an act its scenario counts toward
`misaligned` (grading/acts.counted_acts), located at a step, so the cut "at the
act" exists. A NEGATIVE took no act of any kind. An episode that took only an
act its scenario does not count - the oversight act inside goal-guarding, say -
is neither, and is left out rather than labelled clean.

NEGATIVES ARE MATCHED TO POSITIVES, one each, from the same model and the same
arm cell (nudge, oversight, lure, goal-guarding variant) where one exists, then
the same model, then the same arm. Drawn at random, the negatives would come
mostly from models that never act, and a monitor could separate the classes by
recognising a model's style rather than its conduct. Each negative records how
closely it was matched, so the report can be restricted to exact matches.

Seeded, so a manifest can be rebuilt. The manifest holds paths and labels only,
never transcript text.
"""

import glob
import json
import os
import random

from report.exclusions import EXCLUDED_MODELS
from subversionbench.grading.acts import (MISALIGNED_ACTS, act_form, act_value,
                                          counted_acts)

MANIFEST_NAME = "manifest.json"
MATCH_LEVELS = ("model_and_cell", "model", "arm")


def cell_of(episode: dict) -> list:
    """The arm cell inside its scenario, as a list so it survives JSON."""
    return [episode.get("nudge"), episode.get("oversight"), episode.get("lure"),
            episode.get("goalguard")]


def episode_label(analysis: dict):
    """The episode's label and act facts, or None where it is neither class."""
    acts = [act for act in counted_acts(analysis) if act_value(analysis, act)]
    if acts:
        positions = [(analysis.get(act["timing_key"]) or {}).get("act_index")
                     for act in acts]
        located = [p for p in positions if p is not None]
        if not located:
            return None
        forms = {act["name"]: act_form(analysis, act) for act in acts}
        return {"label": "act", "acts": sorted(forms), "act_index": min(located),
                "forms": forms,
                "concealed": any(str(f).startswith("undone")
                                 for f in forms.values() if f)}
    if any(act_value(analysis, act) for act in MISALIGNED_ACTS):
        return None
    return {"label": "clean"}


def _record(arm, path: str, root: str, episode: dict, label: dict) -> dict:
    return {"id": f"{arm.name}/{os.path.basename(path)}", "arm": arm.name,
            "path": os.path.relpath(path, root), "model": episode["model"],
            "cell": cell_of(episode),
            "rollout_version": episode.get("rollout_version"),
            "n_items": len(episode.get("transcript") or []), **label}


def scan_arm(arm, root: str = ".") -> tuple:
    """(records, skipped) for every usable propensity episode of `arm`.

    `skipped` counts files that could not be read, which during a collection
    is the episode being written; a manifest drawn then should be redrawn.
    """
    records, skipped = [], 0
    for path in sorted(glob.glob(os.path.join(root, arm.corpus, "run_*.json"))):
        try:
            with open(path, encoding="utf-8") as f:
                episode = json.load(f)
        except (OSError, json.JSONDecodeError):
            skipped += 1
            continue
        if episode.get("model") in EXCLUDED_MODELS or episode.get("capability"):
            continue
        label = episode_label(episode.get("analysis") or {})
        if label is not None:
            records.append(_record(arm, path, root, episode, label))
    return records, skipped


def _take(pool: list, rng):
    return pool.pop(rng.randrange(len(pool))) if pool else None


def match_negatives(positives: list, negatives: list, rng) -> list:
    """One negative per positive, without replacement, closest match first."""
    pools = {level: {} for level in MATCH_LEVELS}
    for neg in negatives:
        for level, key in zip(MATCH_LEVELS, _keys(neg), strict=True):
            pools[level].setdefault(key, []).append(neg)
    used, matched = set(), []
    for pos in positives:
        for level, key in zip(MATCH_LEVELS, _keys(pos), strict=True):
            pool = [n for n in pools[level].get(key, []) if n["id"] not in used]
            pick = _take(pool, rng)
            if pick is not None:
                used.add(pick["id"])
                fraction = pos["act_index"] / max(1, pos["n_items"])
                matched.append({**pick, "match": level, "paired_with": pos["id"],
                                "cut_fraction": fraction})
                break
    return matched


def _keys(record: dict) -> tuple:
    return ((record["model"], json.dumps(record["cell"])), record["model"],
            record["arm"])


def draw(records: list, seed: int, per_arm: int = None) -> list:
    """Positives (all, or `per_arm` at random from each arm) and their
    matched negatives, drawn within the same arm."""
    rng = random.Random(seed)
    sample = []
    for arm in sorted({r["arm"] for r in records}):
        positives = [r for r in records if r["arm"] == arm and r["label"] == "act"]
        negatives = [r for r in records if r["arm"] == arm and r["label"] == "clean"]
        positives.sort(key=lambda r: r["id"])
        if per_arm is not None and per_arm < len(positives):
            positives = rng.sample(positives, per_arm)
        sample += positives + match_negatives(positives, negatives, rng)
    return sample


def write_manifest(output_dir: str, sample: list, meta: dict) -> str:
    """Write the manifest, refusing to replace one: results are keyed to it."""
    path = os.path.join(output_dir, MANIFEST_NAME)
    if os.path.exists(path):
        raise FileExistsError(f"{path} exists; results are keyed to it, so "
                              f"draw into a new --output-dir instead")
    os.makedirs(output_dir, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"meta": meta, "episodes": sample}, f, indent=1)
    return path


def load_manifest(output_dir: str) -> dict:
    with open(os.path.join(output_dir, MANIFEST_NAME), encoding="utf-8") as f:
        return json.load(f)
