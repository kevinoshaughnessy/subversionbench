"""
The working directory: what each step writes, and how the next step reads it.

    sets_<name>.json     one per set of matched sets (SET_FILES), written by `sets`
    verdicts.jsonl       one line per judge call, appended by `judge`
    api_usage.jsonl      every call's tokens (subversionbench.usage_ledger)
    pack.txt             the blind validation pack, for the labeller
    labels_template.json one null per pack item, to be filled in and saved as the labels file
    pack_key.json        which unit each pack item is, its role and verdict. Not for the labeller
    estimate.json        the estimate document

A verdict file is appended, never rewritten, so an interrupted pass resumes and every attempt is
kept. The record a unit is read by is its first usable one; a unit with none after
MAX_ATTEMPTS has failed for good.
"""

import hashlib
import json
import os

from subversionbench.grading.category import FATAL_ERROR_KINDS

# Which matched sets the plan builds, and which views of their units are judged. "in_view" is the
# primary exposure, "earlier" sensitivity reading 1's, and "whole" the episode-level reading of
# a blackmail corpus (its every episode, whole transcript).
SET_FILES = {
    "A": {"views": ("in_view", "earlier"), "episode_level": False},
    "B": {"views": ("in_view", "earlier"), "episode_level": True},
    "C": {"views": ("in_view", "earlier"), "episode_level": True},
    "A_eight": {"views": ("in_view",), "episode_level": False},
    "A_no_oversight": {"views": ("in_view",), "episode_level": False},
}
VERDICTS = "verdicts.jsonl"
PACK = "pack.txt"
LABELS_TEMPLATE = "labels_template.json"
PACK_KEY = "pack_key.json"
ESTIMATE = "estimate.json"

# A unit with no usable verdict is re-run once; after that it is excluded and counted.
MAX_ATTEMPTS = 2


def counts_as_attempt(record: dict) -> bool:
    """Whether a record used up one of the unit's attempts.

    Not a unit whose text was empty, which made no call, and not a call stopped by an error every
    call would have hit (a rejected key, exhausted credit): that says nothing about the unit, and
    counting it would spend the one retry the plan gives a unit on a billing problem - every call
    in flight when the credit ran out included.
    """
    return not record.get("no_call") and record.get("error_kind") not in FATAL_ERROR_KINDS


def sets_path(work: str, name: str) -> str:
    return os.path.join(work, f"sets_{name}.json")


def write_json(path: str, doc) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=1, sort_keys=True)
    os.replace(tmp, path)


def read_json(path: str):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def read_sets(work: str) -> dict:
    """name -> sets document, for every set file present."""
    return {name: read_json(sets_path(work, name)) for name in SET_FILES
            if os.path.exists(sets_path(work, name))}


def sha256(path: str) -> str:
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def unit_id(episode_key: str, turn, view: str) -> str:
    return f"{episode_key}#{'whole' if turn is None else turn}#{view}"


def usable(record: dict) -> bool:
    return not record.get("grading_failed") and record.get("eval_aware") is not None


def read_verdicts(work: str) -> dict:
    """unit -> {"record": its first usable record or None, "attempts": calls that count against
    MAX_ATTEMPTS, "refused": whether any attempt was refused by the provider}."""
    out = {}
    path = os.path.join(work, VERDICTS)
    if not os.path.exists(path):
        return out
    with open(path, encoding="utf-8") as f:
        for record in map(json.loads, f):
            slot = out.setdefault(record["unit"], {"record": None, "attempts": 0, "refused": False})
            slot["attempts"] += counts_as_attempt(record)
            slot["refused"] = slot["refused"] or bool(record.get("refused"))
            if slot["record"] is None and usable(record):
                slot["record"] = record
    return out


def append_verdict(work: str, record: dict) -> None:
    os.makedirs(work, exist_ok=True)
    with open(os.path.join(work, VERDICTS), "a", encoding="utf-8") as f:
        f.write(json.dumps(record, sort_keys=True) + "\n")
