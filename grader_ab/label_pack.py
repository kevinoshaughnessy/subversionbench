"""
Label a blind pack one episode at a time, in the terminal.

    python3 -m grader_ab.label_pack labelling/blind_r10_20261008

Shows each unlabelled episode in reading order through the pager, asks for
the category, the codebook rule that decided it and an optional note, checks
them, and writes labels.jsonl after every episode, so stopping loses nothing
and the next run resumes where this one stopped. `--redo ep-012` relabels
one episode.

It reads pack.json and labels.jsonl and nothing else in the pack. The sealed
key - model, arm and stored verdict - is never opened here: a rater shown the
judge's answer is measuring agreement with it, not accuracy.

A NOTE MAY NOT QUOTE THE TRANSCRIPT. labelling/ is gitignored plaintext, and a
note carrying the words that decided a boundary is the codebook leak the
encrypted archive exists to prevent. A note sharing a run of QUOTE_WORDS
consecutive words with the episode is refused; paraphrase the shape of the
remark, or put the words in the encrypted archive.
"""

import argparse
import json
import os
import re
import shlex
import subprocess
import sys

from .shapes import CATEGORIES

# Typed at the prompt; the stored label is always the full category.
ABBREVIATIONS = {"t": "true", "at": "ambiguous_true",
                 "af": "ambiguous_false", "f": "false"}

# The codebook's numbered rulings. Its last rule is 18 (the situation's own
# monitoring, added 2026-10-08); raise this when the codebook gains one, or a
# label citing it is refused as a typo.
CODEBOOK_RULES = 18
CODES = frozenset({str(i) for i in range(1, CODEBOOK_RULES + 1)} | {"none"})

# Six consecutive words in common with the episode is a quotation, not a
# coincidence of phrasing.
QUOTE_WORDS = 6


def load(pack_dir: str) -> tuple:
    """(episodes in reading order, label rows keyed by id)."""
    with open(os.path.join(pack_dir, "pack.json"), encoding="utf-8") as f:
        episodes = json.load(f)["episodes"]
    rows = {}
    with open(os.path.join(pack_dir, "labels.jsonl"), encoding="utf-8") as f:
        for line in f:
            if line.strip():
                row = json.loads(line)
                rows[row["id"]] = row
    missing = [e["id"] for e in episodes if e["id"] not in rows]
    if missing:
        raise ValueError(f"labels.jsonl has no row for {missing[:3]}")
    return episodes, rows


def save(pack_dir: str, episodes: list, rows: dict) -> None:
    """Rewrite labels.jsonl in reading order, atomically: a kill mid-write
    leaves the previous file, never a truncated one."""
    path = os.path.join(pack_dir, "labels.jsonl")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        for ep in episodes:
            f.write(json.dumps(rows[ep["id"]], sort_keys=True) + "\n")
    os.replace(tmp, path)


def _words(text: str) -> list:
    return re.findall(r"[a-z0-9']+", text.lower())


def quoted_run(note: str, text: str, n: int = QUOTE_WORDS) -> str | None:
    """The first run of `n` words the note shares with the text, or None."""
    words = _words(note)
    if len(words) < n:
        return None
    padded = " " + " ".join(_words(text)) + " "
    for i in range(len(words) - n + 1):
        run = " ".join(words[i:i + n])
        if f" {run} " in padded:
            return run
    return None


def _page(text: str) -> None:
    pager = shlex.split(os.environ.get("PAGER") or "less")
    try:
        subprocess.run(pager, input=text, text=True, check=False)
    except FileNotFoundError:
        print(text)


def _ask_label(ep, ask, show):
    """The category, or "skip"/"quit". `v` shows the episode again."""
    while True:
        got = ask("label [t/at/af/f, v=view again, s=skip, q=quit]: ")
        got = got.strip().lower()
        if got == "v":
            show(ep["text"])
        elif got in ("s", "q"):
            return {"s": "skip", "q": "quit"}[got]
        elif ABBREVIATIONS.get(got, got) in CATEGORIES:
            return ABBREVIATIONS.get(got, got)
        else:
            print(f"  not a category: {got!r}")


def _ask_code(ask):
    while True:
        got = ask(f"rule [1-{CODEBOOK_RULES} or none]: ").strip().lower()
        if got in CODES:
            return got
        print(f"  not a codebook rule: {got!r}")


def _ask_note(ep, ask):
    while True:
        note = ask("note (optional, no quotes from the text): ").strip()
        hit = quoted_run(note, ep["text"])
        if hit is None:
            return note
        print(f"  the note repeats the episode's words ({hit!r}...); "
              f"paraphrase it, or leave it empty")


def label_one(ep, row, ask, show):
    """Show one episode and take its label. Returns the updated row, or
    "skip"/"quit" with the row untouched."""
    show(ep["text"])
    label = _ask_label(ep, ask, show)
    if label in ("skip", "quit"):
        return label
    code = _ask_code(ask)
    note = _ask_note(ep, ask)
    updated = {**row, "label": label, "code": code}
    if note:
        updated["note"] = note
    else:
        updated.pop("note", None)
    return updated


def run(pack_dir: str, ask=input, show=_page, redo: str = None) -> int:
    episodes, rows = load(pack_dir)
    todo = [e for e in episodes
            if (e["id"] == redo if redo else rows[e["id"]]["label"] is None)]
    if redo and not todo:
        print(f"no episode {redo!r} in this pack")
        return 1
    done = sum(1 for r in rows.values() if r["label"] is not None)
    print(f"{done}/{len(episodes)} labelled; {len(todo)} to go")
    for ep in todo:
        position = episodes.index(ep) + 1
        print(f"\n{ep['id']}  ({position}/{len(episodes)}, block "
              f"{ep['block']}, {len(ep['text']):,} characters)")
        result = label_one(ep, rows[ep["id"]], ask, show)
        if result == "quit":
            break
        if result == "skip":
            continue
        rows[ep["id"]] = result
        save(pack_dir, episodes, rows)
    done = sum(1 for r in rows.values() if r["label"] is not None)
    print(f"\n{done}/{len(episodes)} labelled, saved to "
          f"{os.path.join(pack_dir, 'labels.jsonl')}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Label a blind pack one episode at a time.")
    parser.add_argument("pack", help="the pack directory")
    parser.add_argument("--redo", metavar="ID",
                        help="relabel one episode, e.g. ep-012")
    args = parser.parse_args()
    try:
        return run(args.pack, redo=args.redo)
    except (EOFError, KeyboardInterrupt):
        print("\nstopped; every label entered so far is saved")
        return 0


if __name__ == "__main__":
    sys.exit(main())
