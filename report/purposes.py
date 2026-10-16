"""
Each counted act broken down by its purpose and where the purpose came from
(analysis plan D7).

Purpose never changes a count (D7 ruling 4): this block only says, of the acts
already counted, why each was taken and on what evidence. Three sources, in
order of precedence:

  act         read off the act itself - `self_evident_purpose`, rulings 6-8 -
              wherever the act settles it. Preferred because a model's stated
              reasons need not be faithful to what drove it.
  hand        an operator's blind label, for an act the rules leave alone.
  unlabelled  neither, yet.

Hand labels live outside the corpus: a blind pack's labels are exported once
into HAND_LABELS_PATH, keyed by run file and act, and joined here at report
time. No run file is written to, and a label for an episode no longer in the
corpus (a superseded arm) simply finds nothing to join.
"""

import argparse
import json
import os

from subversionbench.grading import MISALIGNED_ACTS, act_form

HAND_LABELS_PATH = "labelling/purpose_hand_labels.json"
SOURCES = ("act", "hand", "unlabelled")
_FORMED_ACTS = tuple(a["name"] for a in MISALIGNED_ACTS if a.get("form_key"))


def act_columns(row: dict, analysis: dict, act: dict) -> None:
    """An act's form, and the purpose the act itself shows (None where it
    shows none) - set together because the purpose is read off the form."""
    name = act["name"]
    row[f"{name}_act_form"] = act_form(analysis, act)
    row[f"{name}_purpose_by_act"] = (
        analysis.get("self_evident_purpose") or {}).get(name)


def _key(run_file: str, act: str) -> str:
    return f"{run_file}|{act}"


def load_hand_labels(path: str = HAND_LABELS_PATH) -> dict:
    """{"<run file>|<act>": purpose}; empty where nothing has been exported."""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def export_hand_labels(pack_dir: str, path: str = HAND_LABELS_PATH) -> int:
    """
    Add a labelled blind pack's hand labels to `path`; returns how many.

    Reads the sealed key, so only once labelling is finished. Rows pre-filled
    from the act (source "act") are not exported: the act's own record is
    re-derived on every rebuild, and a frozen copy of it would be a second
    thing to keep in step. A later pack's label for the same act replaces an
    earlier one.
    """
    with open(os.path.join(pack_dir, "key.SEALED.json"), encoding="utf-8") as f:
        key = {e["id"]: e for e in json.load(f)["episodes"]}
    labels = load_hand_labels(path)
    added = 0
    with open(os.path.join(pack_dir, "labels.jsonl"), encoding="utf-8") as f:
        for line in f:
            row = json.loads(line) if line.strip() else None
            if not row or row.get("label") is None or row.get("source") == "act":
                continue
            e = key[row["id"]]
            labels[_key(os.path.basename(e["run"]), e["act"])] = row["label"]
            added += 1
    with open(path + ".tmp", "w", encoding="utf-8") as f:
        json.dump(labels, f, indent=1, sort_keys=True)
    os.replace(path + ".tmp", path)
    return added


def _purpose_counts(rows: list, hand: dict) -> dict:
    """Per formed act, over the episodes that took it: how many by source,
    and each purpose split by source."""
    out = {}
    for name in _FORMED_ACTS:
        took = [e for e in rows if e.get(f"{name}_act_form")]
        if not took:
            continue
        by_source = dict.fromkeys(SOURCES, 0)
        by_purpose = {}
        for e in took:
            purpose = e.get(f"{name}_purpose_by_act")
            source = "act" if purpose else None
            if not purpose:
                purpose = hand.get(_key(e.get("run_file", ""), name))
                source = "hand" if purpose else "unlabelled"
            by_source[source] += 1
            if purpose:
                cell = by_purpose.setdefault(purpose, {"act": 0, "hand": 0})
                cell[source] += 1
        out[name] = {"n_acts": len(took), "by_source": by_source,
                     "by_purpose": dict(sorted(by_purpose.items()))}
    return out


def act_purposes(episodes: list, hand: dict = None) -> dict:
    """The block: pooled and per model. `hand` defaults to the exported
    labels, read from HAND_LABELS_PATH relative to where the report runs."""
    hand = load_hand_labels() if hand is None else hand
    by_model = {}
    for e in episodes:
        by_model.setdefault(e["model"], []).append(e)
    return {
        "measure": "counted acts by purpose and the evidence for it",
        "sources": list(SOURCES),
        "pooled": _purpose_counts(episodes, hand),
        "by_model": [{"model": m, "acts": _purpose_counts(rows, hand)}
                     for m, rows in sorted(by_model.items())],
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Export a finished blind pack's hand purpose labels.")
    parser.add_argument("pack", help="the labelled pack directory")
    parser.add_argument("--to", default=HAND_LABELS_PATH)
    args = parser.parse_args(argv)
    print(f"{export_hand_labels(args.pack, args.to)} hand label(s) "
          f"written to {args.to}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
