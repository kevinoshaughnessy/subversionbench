"""
Human verdicts on episodes the graders disagree about, and scoring BOTH
graders against them.

WHY THIS EXISTS AT ALL
-----------------------
Everything else in this package measures agreement with claude-opus-5, and
agreement is a proxy that quietly becomes the target. The aim is a grader
that is RIGHT. claude-opus-5 is not right by definition: of the first seven
disagreements adjudicated by hand, it was wrong on at least one and
over-called another on the strength of a single word.

So a disagreement is not an error until someone says which side it is on.
This holds those decisions, and scores jev and the LLM grader against them
rather than against each other. With gold labels the interesting number
stops being "how often does jev match opus-5" and becomes "which of the two
is closer to correct, on the episodes where it matters".

WHY THE LABELS LIVE BESIDE THE CORPUS AND NOT IN GIT
-----------------------------------------------------
A label's rationale is a note about what an agent said, and agent text
quotes the scenario freely - the client's name, the strategies, the file
names. AGENTS.md forbids any of that in a tracked file. The labels are
therefore written into the results directory, which is gitignored and
published only through zip.sh's encrypted archive, exactly as the
transcripts they describe are.

They are still precious: each one is a human reading a whole episode, which
is the most expensive evidence in this repository and the only kind that
settles anything.

A LABEL IS ABOUT ONE (episode, question). Not one episode: the same
transcript can be a clear yes on one rubric question and a clear no on
another, and a file keyed by episode alone would make the second
unrecordable.
"""

import json
import os

GOLD_FILE = "jev_gold_labels.json"

# A verdict of None means READ AND NOT SETTLED - which is a real outcome and
# a different one from not yet looked at. Scoring skips these rather than
# guessing, and keeping them means the next person does not re-adjudicate an
# episode already found to be genuinely ambiguous.
UNSETTLED = None


def gold_path(output_dir: str) -> str:
    return os.path.join(output_dir, GOLD_FILE)


def load_gold(output_dir: str) -> dict:
    """{(run, key): {"answer": bool|None, "note": str}}, or empty."""
    path = gold_path(output_dir)
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    return {(entry["run"], entry["key"]): entry
            for entry in raw.get("labels", [])}


def save_gold(output_dir: str, labels: dict) -> str:
    """Written sorted, so two sessions adding different labels produce a
    diffable file rather than a reshuffled one."""
    path = gold_path(output_dir)
    ordered = [labels[k] for k in sorted(labels)]
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"labels": ordered}, f, indent=2, ensure_ascii=False)
    return path


def add_label(labels: dict, run: str, key: str, answer, note: str = "") -> dict:
    """Record one human verdict, replacing any earlier one for that pair."""
    labels[(run, key)] = {"run": run, "key": key, "answer": answer,
                          "note": note}
    return labels


def score_against_gold(labels: dict, cases: list) -> dict:
    """How often each grader was right, on the settled labels only.

    `cases` are disagreement records from jev_tune.disagreements, which carry
    both verdicts - so on a settled label exactly one of the two is correct
    and the counts are complements. That is the point: these are episodes the
    two answered differently, so this measures who wins the arguments, not
    overall accuracy.
    """
    jev_right = llm_right = unsettled = unlabelled = 0
    for case in cases:
        label = labels.get((case["run"], case["key"]))
        if label is None:
            unlabelled += 1
            continue
        if label["answer"] is UNSETTLED:
            unsettled += 1
            continue
        if case["jev"] == label["answer"]:
            jev_right += 1
        if case["stored"] == label["answer"]:
            llm_right += 1
    return {"jev_right": jev_right, "llm_right": llm_right,
            "settled": jev_right + llm_right,
            "unsettled": unsettled, "unlabelled": unlabelled}


def print_scoreboard(score: dict, llm_name: str = "claude-opus-5") -> None:
    settled = score["settled"]
    print(f"\n{'=' * 78}")
    print("ON THE DISAGREEMENTS A HUMAN HAS SETTLED")
    print(f"{'=' * 78}")
    if not settled:
        print(f"  Nothing settled yet. {score['unlabelled']} disagreement(s) "
              f"await a verdict,\n  {score['unsettled']} were read and found "
              f"genuinely ambiguous.")
        return
    print(f"  jev was right    {score['jev_right']:4} / {settled}")
    print(f"  {llm_name:14} was right {score['llm_right']:4} / {settled}")
    print(f"\n  {score['unsettled']} read and left unsettled, "
          f"{score['unlabelled']} not yet judged.")
    print("\n  These are ONLY the episodes the two answered differently, so "
          "this says\n  who wins the arguments - not how accurate either is "
          "overall.")
