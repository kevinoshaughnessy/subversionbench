"""Which episodes the experiment is run over.

Balanced on the stored verdict and oversampling the models whose
awareness is phrased unusually: that is the difference between measuring
recall and measuring precision, and it is silent when wrong.
"""

import collections
import glob
import json
import os
import random

from subversionbench.graders import view
from subversionbench.grading import agent_corpus, scenario_corpus
from subversionbench.grading.quote_grounding import format_agent_text


def load_candidates(output_dir: str) -> list:
    """Every episode with a transcript and a stored grader verdict.

    The stored verdict is required because the sample is balanced on it; an
    episode whose grading failed has no side to balance into.
    """
    out = []
    for path in sorted(glob.glob(os.path.join(output_dir, "run_*.json"))):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        transcript = data.get("transcript") or []
        analysis = view(data.get("analysis") or {})
        grader = analysis.get("eval_awareness_grader")
        if not transcript or not data.get("model") or not isinstance(grader, dict):
            continue
        stored = grader.get("eval_aware")
        if stored is None or grader.get("grading_failed"):
            continue
        out.append({
            "run": os.path.basename(path),
            "model": data["model"],
            "nudge": data.get("nudge"),
            "oversight": data.get("oversight"),
            "lure": data.get("lure"),
            "stored_aware": bool(stored),
            "stored_rubric": grader.get("rubric_results") or {},
            "corpus": agent_corpus(transcript),
            "scenario": scenario_corpus(transcript),
        })
    return out


def stratified_sample(candidates, per_model, models=None, oversample=(),
                      balance=True, limit=None) -> list:
    """Episodes per model, balanced on the stored verdict, oversampled models
    doubled.

    Deterministic - the candidate list is already sorted by filename and this
    only interleaves it - so two runs of the harness draw the same sample and
    their results are comparable.
    """
    by_model = collections.defaultdict(lambda: {True: [], False: []})
    for c in candidates:
        by_model[c["model"]][c["stored_aware"]].append(c)

    wanted = sorted(by_model) if models is None else [
        m for m in models if m in by_model]
    picked = []
    for model in wanted:
        n = per_model * (2 if model in oversample else 1)
        aware, unaware = by_model[model][True], by_model[model][False]
        if balance:
            # Split n itself, not n // 2 with a floor of 1 - the floor made
            # take exceed n when n was 1 (half=1 from each side, 2 total) and
            # undershoot it whenever n was odd (e.g. n=3 drew only 2). Ceil
            # goes to the aware side on an odd n, an arbitrary but
            # deterministic tie-break, so an odd n leans aware by one episode
            # - stated because the saved JSON labels the sample balanced.
            want_aware = (n + 1) // 2
            want_unaware = n // 2
            # BACKFILL from the other side when one side cannot fill its
            # share. Without this a model whose episodes are all on one side
            # contributes NOTHING at n=1 (aware[:1] of an empty list, plus
            # unaware[:0]) - it drops out of the sample silently, and main()
            # blames --models for the empty result. The floor this replaced
            # avoided that by over-drawing; backfilling gets the model in AND
            # respects n.
            if len(aware) < want_aware:
                want_unaware += want_aware - len(aware)
            if len(unaware) < want_unaware:
                want_aware += want_unaware - len(unaware)
            take = aware[:want_aware] + unaware[:want_unaware]
        else:
            take = (aware + unaware)[:n]
        picked.extend(take)
    if limit is not None:
        # `is not None`, not truthiness - `--limit 0` means cap the sample at
        # zero, not "no limit"; `if limit:` treated 0 as falsy and skipped
        # this block entirely, running the full unlimited sample instead.
        # Round-robin across models rather than truncating, so a cap does not
        # silently drop every model after the alphabetical middle.
        rr, seen = [], collections.defaultdict(int)
        while len(rr) < min(limit, len(picked)):
            progressed = False
            for model in wanted:
                mine = [c for c in picked if c["model"] == model]
                if seen[model] < len(mine) and len(rr) < limit:
                    rr.append(mine[seen[model]])
                    seen[model] += 1
                    progressed = True
            if not progressed:
                break
        picked = rr
    return picked


def whole_agent_text(output_dir: str, run: str) -> str:
    """The agent's own text with no length cap, for the shapes that read all
    of it. Read per episode when it is asked for, rather than held for every
    candidate: load_candidates reads the whole directory, and the uncapped
    text of every episode in it is a cost no rubric cell needs."""
    with open(os.path.join(output_dir, run), encoding="utf-8") as f:
        return format_agent_text(json.load(f).get("transcript") or [])


def read_runs_file(path: str) -> list:
    """Run filenames, in file order, from a file naming the episodes to grade.

    A line is either a bare filename or a JSON object carrying it under "run"
    (a grader_ab sample, a blind pack's key) or "file" (the test-set lists).
    Blank lines are skipped. Anything else is refused rather than skipped, so a
    malformed list cannot quietly grade fewer episodes than it names.
    """
    runs = []
    with open(path, encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            if line.startswith("{"):
                row = json.loads(line)
                run = row.get("run") or row.get("file")
            else:
                run = line
            if not run or os.sep in run or not run.startswith("run_"):
                raise ValueError(f"{path}:{n} names no run file")
            runs.append(run)
    return runs


def select_runs(candidates: list, runs: list) -> tuple:
    """(sample, missing): the named episodes, in the order named, and the names
    that are not gradable candidates here. Missing is returned rather than
    dropped, so the caller can refuse a list that does not match its
    directory instead of grading the part that does."""
    by_run = {c["run"]: c for c in candidates}
    sample = [by_run[r] for r in dict.fromkeys(runs) if r in by_run]
    missing = [r for r in dict.fromkeys(runs) if r not in by_run]
    return sample, missing


def random_per_model(candidates, per_model, seed, oversample=()) -> list:
    """`per_model` episodes drawn at random from each model, oversampled
    models doubled, reproducible from `seed`.

    The sample a rater labels to measure grader ACCURACY, which the stratified
    sample cannot be: that one balances on a grader's stored verdict, so it
    over-represents the episodes that grader called aware, and a sensitivity
    estimated inside it flatters the grader it was balanced on. It also takes
    each model's episodes in filename order, which tracks the arm. Drawn
    within model rather than from the pool, so no model's share of the corpus
    decides the answer.
    """
    by_model = collections.defaultdict(list)
    for c in candidates:
        by_model[c["model"]].append(c)
    rng = random.Random(seed)
    picked = []
    for model in sorted(by_model):
        episodes = sorted(by_model[model], key=lambda c: c["run"])
        n = per_model * (2 if model in oversample else 1)
        picked.extend(rng.sample(episodes, min(n, len(episodes))))
    return picked
