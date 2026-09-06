"""What the finished cells say, as a table.

Every read-out here is computed after the calls are paid for, so a crash
in this module costs the whole run - which is why it is exercised on
synthetic cells rather than only end to end.
"""

import collections

from subversionbench.grading.grader import classify_awareness_from_rubric
from subversionbench.power import fisher_exact_p, wilson_ci

from .prices import REFERENCE


def cell_verdict(rubric: dict) -> bool | None:
    """The published eval_aware flag, through the real classifier.

    None when nothing was answered: a cell that failed on every question has no
    verdict, and scoring that as not-aware would be the absence-is-a-no error
    the rubric parser exists to prevent.
    """
    if all(v.get("answer") is None for v in rubric.values()):
        return None
    return classify_awareness_from_rubric(rubric).get("eval_aware")


def signal_correlation(rubrics: list) -> float | None:
    """Mean pairwise agreement among the five eval-signal questions.

    The contamination proxy. Higher means the five move together more, which is
    what answering them in one generation would encourage - and what would
    change what classify_awareness_from_rubric's span counting is fed.
    """
    from subversionbench.grading.grader import _EVAL_SIGNAL_KEYS
    pairs, agree = 0, 0
    for r in rubrics:
        answers = [r.get(k, {}).get("answer") for k in _EVAL_SIGNAL_KEYS]
        for i in range(len(answers)):
            for j in range(i + 1, len(answers)):
                if answers[i] is None or answers[j] is None:
                    continue
                pairs += 1
                agree += 1 if answers[i] == answers[j] else 0
    return agree / pairs if pairs else None


def per_question_table(results: dict, keys: list) -> dict:
    """{cell: {key: counters}} - yes, decided, verbatim-of-yes, unanswered."""
    table = {}
    for cell, rubrics in results.items():
        per = {}
        for key in keys:
            c = collections.Counter()
            for r in rubrics.values():
                entry = r.get(key) or {}
                if entry.get("answer") is None:
                    c["unanswered"] += 1
                    continue
                c["decided"] += 1
                if entry["answer"]:
                    c["yes"] += 1
                    if entry.get("quote_grounded") == "verbatim":
                        c["verbatim"] += 1
            per[key] = c
        table[cell] = per
    return table


def agreement(a: dict, b: dict, keys: list) -> dict:
    """Per-question and verdict agreement between two cells' rubrics."""
    shared = sorted(set(a) & set(b))
    per_key = {}
    for key in keys:
        same = both = 0
        for run in shared:
            x = (a[run].get(key) or {}).get("answer")
            y = (b[run].get(key) or {}).get("answer")
            if x is None or y is None:
                continue
            both += 1
            same += 1 if x == y else 0
        per_key[key] = (same, both)
    v_same = v_both = 0
    for run in shared:
        x, y = cell_verdict(a[run]), cell_verdict(b[run])
        if x is None or y is None:
            continue
        v_both += 1
        v_same += 1 if x == y else 0
    return {"per_question": per_key, "verdict": (v_same, v_both),
            "n_shared": len(shared)}


def _pct(num, den):
    return f"{100 * num / den:5.1f}%" if den else "    -"


def _short_cell(cell: str) -> str:
    """`claude-sonnet-5|batched` -> `sonnet-5|batched`, to fit a column.

    The provider prefix is the same across every cell, so dropping it loses
    nothing that distinguishes them; the full name is in the JSON.
    """
    grader, _, shape = cell.partition("|")
    return f"{grader.removeprefix('claude-')}|{shape}"


def report(results, sample, keys, stored_rubrics):
    print(f"\n{'=' * 78}")
    print("PER-QUESTION RATES BY CELL")
    print(f"{'=' * 78}")
    table = per_question_table(results, keys)
    cells = sorted(table)
    print(f"{'pos':>3} {'question':30} " +
          " ".join(f"{_short_cell(c):>22}" for c in cells))
    for i, key in enumerate(keys, 1):
        row = f"{i:3} {key:30} "
        for cell in cells:
            c = table[cell][key]
            row += f" {_pct(c['yes'], c['decided'])} v{_pct(c['verbatim'], c['yes']).strip():>6} e{c['unanswered']:<2}"
        print(row)
    print("\n  rate = yes/decided, v = verbatim share of the yes answers, "
          "e = unanswered")

    ref = "|".join(REFERENCE)
    if ref not in results:
        print(f"\n! reference cell {ref} absent, so no comparison is possible")
        return
    print(f"\n{'=' * 78}")
    print(f"AGREEMENT AGAINST THE REFERENCE CELL ({ref})")
    print(f"{'=' * 78}")

    # The noise floor first: the same cell against the labels in the run files.
    floor = agreement(results[ref], stored_rubrics, keys)
    fs, fb = floor["verdict"]
    print("\nNoise floor - the reference cell re-run against the STORED labels")
    print(f"  verdict agreement {fs}/{fb} = {_pct(fs, fb).strip()}   "
          f"<- graders are non-deterministic; every number below has to beat "
          f"this to mean anything")

    # Computed once per non-reference cell and reused below - this used to be
    # recomputed from scratch in both the AGREEMENT and POSITION GRADIENT
    # sections, redoing the full per-question/verdict pass over every shared
    # episode a second time for no different result.
    agreements = {cell: agreement(results[cell], results[ref], keys)
                 for cell in cells if cell != ref}

    for cell in cells:
        if cell == ref:
            continue
        a = agreements[cell]
        vs, vb = a["verdict"]
        print(f"\n{cell}  (n={a['n_shared']})")
        print(f"  verdict agreement {vs}/{vb} = {_pct(vs, vb).strip()}")
        worst = sorted(((s / b if b else 1.0), k)
                       for k, (s, b) in a["per_question"].items())[:3]
        for _rate, key in worst:
            s, b = a["per_question"][key]
            print(f"    lowest-agreeing: {key:30} {s}/{b} = {_pct(s, b).strip()}")

    print(f"\n{'=' * 78}")
    print("POSITION GRADIENT - the pre-registered read-out for batching")
    print(f"{'=' * 78}")
    print("Independent calls cannot produce a slope here, so the per_question")
    print("cells are the control. A batched cell that agrees less with the")
    print("reference at position 9 than at position 1 is losing late answers.\n")
    print(f"{'cell':34} " + " ".join(f"q{i}" for i in range(1, len(keys) + 1)))
    for cell in cells:
        if cell == ref:
            continue
        a = agreements[cell]
        row = f"{cell:34} "
        for key in keys:
            s, b = a["per_question"][key]
            row += f"{(100 * s / b if b else 0):3.0f} "
        print(row)

    print(f"\n{'=' * 78}")
    print("CONTAMINATION AND ROBUSTNESS")
    print(f"{'=' * 78}")
    print(f"{'cell':30} {'signal agreement':>17} {'lost some':>10} "
          f"{'lost all 9':>11} {'reply':>6} {'other':>6}")
    for cell in cells:
        rubrics = list(results[cell].values())
        corr = signal_correlation(rubrics)
        some = sum(1 for r in rubrics
                   if any(v.get("answer") is None for v in r.values()))
        allnine = sum(1 for r in rubrics
                      if all(v.get("answer") is None for v in r.values()))
        kinds = collections.Counter(v.get("error_kind") for r in rubrics
                                    for v in r.values() if v.get("error_kind"))
        print(f"{_short_cell(cell):30} "
              f"{'-' if corr is None else f'{100*corr:16.1f}%':>17} "
              f"{some:10} {allnine:11} {kinds['reply']:6} {kinds['other']:6}")
    print("\n  signal agreement = mean pairwise agreement among the five "
          "eval-signal")
    print("  questions. Higher under batching means the answers moved together.")
    print("\n  reply / other = why an answer is missing. `reply` is the grader's")
    print("  own output - the fragility batching is suspected of. `other` is")
    print("  everything else, transport included, and a run with any of those")
    print("  is not evidence about the shape: re-run it with --delay before")
    print("  reading the two columns to its left. Only the batched path can")
    print("  distinguish the two, because the shipped per-question asker reports")
    print("  one error string for both, so per_question cells show `other`.")

    print(f"\n{'=' * 78}")
    print("VERDICT RATE BY CELL")
    print(f"{'=' * 78}")
    # Computed from results[ref] directly, not by waiting for `cell == ref`
    # during the loop below - `cells` is alphabetically sorted, and any shape
    # name that sorts before "per_question" (batched, for instance) reached
    # the reference cell only after being printed, so it silently got no
    # Fisher p-value at all under the old order-dependent version.
    ref_verdicts = [cell_verdict(r) for r in results[ref].values()]
    ref_decided = [v for v in ref_verdicts if v is not None]
    base = (sum(1 for v in ref_decided if v), len(ref_decided))
    for cell in cells:
        verdicts = [cell_verdict(r) for r in results[cell].values()]
        decided = [v for v in verdicts if v is not None]
        aware = sum(1 for v in decided if v)
        lo, hi = wilson_ci(aware, len(decided)) if decided else (0, 0)
        line = (f"{cell:34} {aware:3}/{len(decided):<3} "
                f"{_pct(aware, len(decided))} [{100*lo:4.1f},{100*hi:5.1f}]")
        if cell == ref:
            line += "   <- reference"
        else:
            line += f"   Fisher p={fisher_exact_p(base[0], base[1], aware, len(decided)):.3g}"
        print(line)
