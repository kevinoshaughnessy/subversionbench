"""
Does the grader give the same verdict twice on the same transcript?

WHAT THIS IS FOR. The Agentic Benchmark Checklist's item on LLM judges asks for
evidence of "the judge's accuracy, self-consistency, and agreement with human"
- III/I.c.1 in the standalone checklist. This measures the middle one, which is
the only leg obtainable without labelled ground truth: run the same grader
twice over the same saved transcripts and count how often it changes its mind.

WHY NOT readout's "noise floor". `readout.report` prints the reference cell
against the STORED labels, which is a fair noise floor only where those labels
came from one grader version. On r10 they did not - the episodes carry at least
six analysis versions (v128, v62, v61, v79, v58, v55) - so that line measures
stochasticity PLUS per-episode grader drift. Two fresh passes isolate the
stochasticity, and this module compares two fresh result files.

THE DISTINCTION THAT MATTERS, and the one a raw disagreement count gets wrong:
a verdict can move without the grader changing its mind. A question that one
pass answered and the other dropped changes the input the classifier sees, so
the verdict flips while every shared answer is identical. Measured on the first
run of this: one of three flips was exactly that, and it accounted for the only
movement in the awareness rate. Counting it as disagreement overstates the
judge's instability by half.

WHY THE POOLED RATE IS NOT THE CORPUS RATE. The sample is balanced on the
stored verdict, so it is near half aware while the corpus is not. The two
strata are reported separately, and `reweighted` combines them at a caller-
supplied base rate as a point estimate only - the interval for that combination
is not a Wilson interval and is not invented here.
"""

from subversionbench.power import wilson_ci

from .prices import REFERENCE
from .readout import cell_verdict

JUDGEMENT = "judgement"
DROPPED_ANSWER = "dropped_answer"
REFERENCE_CELL = "|".join(REFERENCE)


def _shared_answers_differ(rubric_a: dict, rubric_b: dict) -> bool:
    """Whether any question ANSWERED ON BOTH SIDES got a different answer."""
    for key, a in rubric_a.items():
        b = rubric_b.get(key) or {}
        if a.get("answer") is None or b.get("answer") is None:
            continue
        if a["answer"] != b["answer"]:
            return True
    return False


def change_kind(rubric_a: dict, rubric_b: dict):
    """Why two passes' verdicts differ, or None where they agree.

    JUDGEMENT when a question both passes answered came back differently.
    DROPPED_ANSWER when none did - the verdict moved because a question one
    pass answered went missing from the other, which is a grader error rather
    than a change of mind, and has its own remedy: retry the failed call.
    """
    if cell_verdict(rubric_a) == cell_verdict(rubric_b):
        return None
    return (JUDGEMENT if _shared_answers_differ(rubric_a, rubric_b)
            else DROPPED_ANSWER)


def _rate(k: int, n: int) -> dict:
    lo, hi = wilson_ci(k, n) if n else (None, None)
    return {"k": k, "n": n,
            "rate": (k / n) if n else None,
            "ci95": (lo, hi)}


def compare(doc_a: dict, doc_b: dict, cell: str = REFERENCE_CELL) -> dict:
    """Two grader_ab result documents, compared episode by episode.

    Raises on a sample mismatch rather than intersecting silently: the sample
    is deterministic for a given set of arguments, so two documents that
    disagree on it were produced by different runs and comparing them measures
    something other than the grader - see sampling.stratified_sample, which
    states the determinism this relies on.
    """
    runs_a = [ep["run"] for ep in doc_a["sample"]]
    if runs_a != [ep["run"] for ep in doc_b["sample"]]:
        raise ValueError(
            "the two runs drew different samples, so their cells are not "
            "comparable - check that both were invoked with the same "
            "arguments against the same --output-dir")
    rubrics_a = doc_a["cells"].get(cell) or {}
    rubrics_b = doc_b["cells"].get(cell) or {}
    stored = {ep["run"]: ep["stored_aware"] for ep in doc_a["sample"]}

    resolved, unresolved, kinds = [], [], {}
    for run in sorted(set(rubrics_a) & set(rubrics_b)):
        a, b = rubrics_a[run], rubrics_b[run]
        if cell_verdict(a) is None or cell_verdict(b) is None:
            unresolved.append(run)
            continue
        resolved.append(run)
        kind = change_kind(a, b)
        if kind:
            kinds[run] = kind

    n = len(resolved)
    changed = [r for r in resolved if r in kinds]
    judgement = [r for r in changed if kinds[r] == JUDGEMENT]
    dropped = [r for r in changed if kinds[r] == DROPPED_ANSWER]
    strata = {}
    for stratum in (True, False):
        rows = [r for r in resolved if stored.get(r) is stratum]
        strata[stratum] = _rate(
            sum(1 for r in rows if kinds.get(r) == JUDGEMENT), len(rows))
    return {
        "cell": cell,
        "n_compared": n,
        "n_unresolved": len(unresolved),
        "any_change": _rate(len(changed), n),
        "judgement_change": _rate(len(judgement), n),
        "dropped_answer": _rate(len(dropped), n),
        "by_stored_verdict": strata,
        "changed_runs": {r: kinds[r] for r in sorted(kinds)},
    }


def reweighted_judgement_rate(result: dict, corpus_aware_rate: float):
    """The judgement-change rate a corpus at `corpus_aware_rate` would see.

    A POINT ESTIMATE and no interval, because the sample is balanced and the
    corpus is not: combining the two strata's Wilson intervals is not itself a
    Wilson interval, and this returns None rather than a number it cannot
    defend. Returns None where either stratum is empty.
    """
    aware = result["by_stored_verdict"][True]
    unaware = result["by_stored_verdict"][False]
    if not aware["n"] or not unaware["n"]:
        return None
    return (corpus_aware_rate * aware["rate"]
            + (1 - corpus_aware_rate) * unaware["rate"])
