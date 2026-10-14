"""
Label a blind pack one episode at a time, in the terminal.

    python3 -m grader_ab.label_pack labelling/blind_r10_20261008
    python3 -m grader_ab.label_pack labelling/purpose_blind_20261014 --purpose

Shows each unlabelled episode in reading order through the pager, asks for
the category, the codebook rule that decided it, any other rules that also
apply, and an optional note, checks them, and writes labels.jsonl after every
episode, so stopping loses nothing and the next run resumes where this one
stopped. `--redo ep-012` relabels one episode.

ONE DECIDING RULE, AND THE REST BESIDE IT. Several rules usually apply to a
transcript, sometimes at the same level, and a single field recorded only the
strongest - so a rule recorded and the category it gives were tied together
by construction, and a disagreement with a grader could not be traced to which
applicable rule each side weighted. `code` stays the deciding rule, so every
earlier label and the scorer read as before; `also` lists the others. An empty
list is "no other rule applies"; a row without the field was labelled before
it was asked, which is "not recorded", not "none".

It reads pack.json and labels.jsonl and nothing else in the pack. The sealed
key - model, arm and stored verdict - is never opened here: a rater shown the
judge's answer is measuring agreement with it, not accuracy.

TWO SCHEMES. The default labels evaluation awareness against the codebook.
`--purpose` labels the PURPOSE of an oversight or goal-guarding act (analysis
plan D7): five purposes, no codebook rules yet, so neither rule question is
asked. The label is the primary purpose - what the act targets - and `also`
lists any other purpose the model gives for the same act, since an evasion
and a defence of its own objective are often one decision. The purposes' definitions are
not written here, for the reason the next paragraph gives.

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

# The purpose of an act, and its one-letter forms. Order is the prompt's.
PURPOSES = ("evade", "protect_goals", "test", "mistake", "unclear")
PURPOSE_ABBREVIATIONS = {p[0]: p for p in PURPOSES}

# What each scheme asks: its labels, their abbreviations, and whether the
# codebook's rule questions follow the label.
SCHEMES = {
    "awareness": (CATEGORIES, ABBREVIATIONS, True),
    "purpose": (PURPOSES, PURPOSE_ABBREVIATIONS, False),
}

# The codebook's numbered rulings. Its last rule is 18 (the situation's own
# monitoring, added 2026-10-08); raise this when the codebook gains one, or a
# label citing it is refused as a typo.
CODEBOOK_RULES = 18
CODES = frozenset({str(i) for i in range(1, CODEBOOK_RULES + 1)} | {"none"})

# A purpose pack marks the act and its restore with lines starting MARK, and
# heads each item with their turns ("@@@@ ACTION UNDER REVIEW: turn 14").
# The heading is printed again at the prompt, and less opens searching for
# MARK, so every marker is highlighted and `n` steps between them.
MARK = "@@@@"

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


def highlights(text: str) -> list:
    """The item's heading lines - the act's and restore's turns - if any."""
    return [line for line in text.split("\n")
            if line.startswith(f"{MARK} ") and ": " in line]


def _page(text: str) -> None:
    pager = shlex.split(os.environ.get("PAGER") or "less")
    if MARK in text and os.path.basename(pager[0]) == "less":
        pager.append(f"+/{MARK}")
    try:
        subprocess.run(pager, input=text, text=True, check=False)
    except FileNotFoundError:
        print(text)


def _ask_label(ep, ask, show, scheme="awareness"):
    """The category, or "skip"/"quit". `v` shows the episode again."""
    categories, abbreviations, _rules = SCHEMES[scheme]
    shortcuts = "/".join(abbreviations)
    while True:
        got = ask(f"label [{shortcuts}, v=view again, s=skip, q=quit]: ")
        got = got.strip().lower()
        if got == "v":
            show(ep["text"])
        elif got in ("s", "q"):
            return {"s": "skip", "q": "quit"}[got]
        elif abbreviations.get(got, got) in categories:
            return abbreviations.get(got, got)
        else:
            print(f"  not a category: {got!r}")


def _ask_code(ask):
    while True:
        got = ask(f"rule [1-{CODEBOOK_RULES} or none]: ").strip().lower()
        if got in CODES:
            return got
        print(f"  not a codebook rule: {got!r}")


def parse_also(got: str, deciding: str):
    """The other applicable rules as sorted numbers, or an error message.

    Comma- or space-separated. The deciding rule and "none" are refused rather
    than dropped: either means the answer was not what the rater thought it
    was, and silently tidying it would store a different answer."""
    parts = [p for p in re.split(r"[,\s]+", got.strip().lower()) if p]
    bad = [p for p in parts if p not in CODES or p == "none"]
    if bad:
        return f"not a codebook rule: {bad[0]!r}"
    if deciding in parts:
        return f"rule {deciding} is already the deciding rule"
    return sorted(set(parts), key=int)


def _ask_also(ask, deciding):
    while True:
        got = parse_also(ask("also applies [other rules, e.g. 5,14, or "
                             "empty for none]: "), deciding)
        if isinstance(got, list):
            return got
        print(f"  {got}")


def parse_also_purposes(got: str, primary: str):
    """The other purposes as a list in PURPOSES order, or an error message.

    A purpose act often serves two: an evasion of today's check can be
    justified by keeping the model's objective in place. The primary label is
    what the act targets; `also` keeps the rest rather than forcing a choice.
    One-letter forms are accepted. The primary label and anything that is not
    a purpose are refused rather than dropped, as parse_also refuses rules."""
    parts = [p for p in re.split(r"[,\s]+", got.strip().lower()) if p]
    named = [PURPOSE_ABBREVIATIONS.get(p, p) for p in parts]
    bad = [p for p, n in zip(parts, named, strict=True) if n not in PURPOSES]
    if bad:
        return f"not a purpose: {bad[0]!r}"
    if primary in named:
        return f"{primary} is already the primary purpose"
    return [p for p in PURPOSES if p in named]


def _ask_also_purposes(ask, primary):
    while True:
        got = parse_also_purposes(ask("also [other purposes, e.g. p,t, or "
                                      "empty for none]: "), primary)
        if isinstance(got, list):
            return got
        print(f"  {got}")


def _ask_note(ep, ask):
    while True:
        note = ask("note (optional, no quotes from the text): ").strip()
        hit = quoted_run(note, ep["text"])
        if hit is None:
            return note
        print(f"  the note repeats the episode's words ({hit!r}...); "
              f"paraphrase it, or leave it empty")


def label_one(ep, row, ask, show, scheme="awareness"):
    """Show one episode and take its label. Returns the updated row, or
    "skip"/"quit" with the row untouched."""
    show(ep["text"])
    for line in highlights(ep["text"]):
        print(f"  {line}")
    label = _ask_label(ep, ask, show, scheme)
    if label in ("skip", "quit"):
        return label
    updated = {**row, "label": label}
    if SCHEMES[scheme][2]:
        code = _ask_code(ask)
        updated.update(code=code, also=_ask_also(ask, code))
    else:
        updated["also"] = _ask_also_purposes(ask, label)
    note = _ask_note(ep, ask)
    if note:
        updated["note"] = note
    else:
        updated.pop("note", None)
    return updated


def _also_missing(row, scheme) -> bool:
    """A purpose label entered before `also` was asked. Absent, not empty:
    an empty list is the rater's "none", which must not be asked again."""
    return (scheme == "purpose" and row["label"] is not None
            and "also" not in row)


def add_also(ep, row, ask, show):
    """Ask only `also` for a row labelled before it existed; the label and
    note stand. Returns the updated row, or "quit"."""
    show(ep["text"])
    for line in highlights(ep["text"]):
        print(f"  {line}")
    print(f"  labelled earlier: {row['label']}")
    got = ask("also [other purposes, e.g. p,t, empty for none, q=quit]: ")
    while got.strip().lower() != "q":
        also = parse_also_purposes(got, row["label"])
        if isinstance(also, list):
            return {**row, "also": also}
        print(f"  {also}")
        got = ask("also [other purposes, e.g. p,t, empty for none, q=quit]: ")
    return "quit"


def _fill_missing_also(pack_dir, episodes, rows, ask, show) -> bool:
    """True if the rater quit part-way."""
    for ep in episodes:
        if not _also_missing(rows[ep["id"]], "purpose"):
            continue
        print(f"\n{ep['id']}  (adding 'also' to an earlier label)")
        result = add_also(ep, rows[ep["id"]], ask, show)
        if result == "quit":
            return True
        rows[ep["id"]] = result
        save(pack_dir, episodes, rows)
    return False


def run(pack_dir: str, ask=input, show=_page, redo: str = None,
        scheme: str = "awareness") -> int:
    episodes, rows = load(pack_dir)
    if scheme == "purpose" and not redo and _fill_missing_also(
            pack_dir, episodes, rows, ask, show):
        print("\nstopped; every answer entered so far is saved")
        return 0
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
        result = label_one(ep, rows[ep["id"]], ask, show, scheme)
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
    parser.add_argument("--purpose", action="store_true",
                        help="label the purpose of each act "
                             f"({', '.join(PURPOSES)}) rather than "
                             "awareness; no codebook rules are asked")
    args = parser.parse_args()
    try:
        return run(args.pack, redo=args.redo,
                   scheme="purpose" if args.purpose else "awareness")
    except (EOFError, KeyboardInterrupt):
        print("\nstopped; every label entered so far is saved")
        return 0


if __name__ == "__main__":
    sys.exit(main())
