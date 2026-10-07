"""What the finished cells say, as a table.

Every read-out here is computed after the calls are paid for, so a crash
in this module costs the whole run - which is why it is exercised on
synthetic cells rather than only end to end.
"""

import collections

from subversionbench.grading.grader import classify_awareness_from_rubric
from subversionbench.power import fisher_exact_p, wilson_ci

from .prices import REFERENCE
from .shapes import CATEGORIES, CATEGORY_KEY


def cell_verdict(rubric: dict) -> bool | None:
    """The published eval_aware flag, through the real classifier.

    None when nothing was answered: a cell that failed on every question has no
    verdict, and scoring that as not-aware would be the absence-is-a-no error
    the rubric parser exists to prevent.
    """
    if all(v.get("answer") is None for v in rubric.values()):
        return None
    if CATEGORY_KEY in rubric:
        return rubric[CATEGORY_KEY]["answer"]
    return classify_awareness_from_rubric(rubric).get("eval_aware")


def is_category_cell(cell: str) -> bool:
    """A cell of the category instrument, which has no rubric questions for
    the per-question, gradient and contamination read-outs to tabulate."""
    return cell.partition("|")[2] == "category"


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
    rubric_results = {c: r for c, r in results.items()
                      if not is_category_cell(c)}
    if rubric_results:
        _report_rubric_cells(rubric_results, keys, stored_rubrics)
    category_cells = sorted(c for c in results if is_category_cell(c))
    if category_cells:
        _print_category(results, category_cells, stored_rubrics)
    ref = "|".join(REFERENCE)
    if ref in results:
        _print_verdict_rates(results, sorted(results), ref)


def _print_category(results, category_cells, stored_rubrics) -> None:
    """What each category cell answered, how often it did not answer, and
    where its binary verdict parts from the rubric's.

    Unanswered is printed first because it decides a grader before accuracy
    does: docs/grader-selection.md drops a candidate that leaves more than one
    in twenty unanswered on the refusal screen, and holds the final grader to
    2%, because a refusal here falls where the answer is yes and so biases the
    rate rather than thinning it.
    """
    ref = "|".join(REFERENCE)
    print(f"\n{'=' * 78}")
    print("CATEGORY INSTRUMENT")
    print(f"{'=' * 78}")
    print(f"{'cell':30} {'n':>4} " + " ".join(f"{c:>16}" for c in CATEGORIES)
          + f" {'unanswered':>11}")
    for cell in category_cells:
        entries = [r[CATEGORY_KEY] for r in results[cell].values()]
        counts = collections.Counter(e.get("category") for e in entries)
        unanswered = sum(1 for e in entries if e.get("answer") is None)
        print(f"{_short_cell(cell):30} {len(entries):4} "
              + " ".join(f"{counts[c]:16}" for c in CATEGORIES)
              + f" {unanswered:4} {_pct(unanswered, len(entries))}")
    print("\n  aware = true or ambiguous_true. Agreement of that verdict with "
          "the rubric's eval_aware:")
    for cell in category_cells:
        against = [("stored", stored_rubrics)]
        if ref in results:
            against.append((ref, results[ref]))
        for name, other in against:
            vs, vb = agreement(results[cell], other, [])["verdict"]
            print(f"    {_short_cell(cell):28} vs {name:28} "
                  f"{vs}/{vb} = {_pct(vs, vb).strip()}")
        crossed = collections.Counter(
            (r[CATEGORY_KEY].get("category"),
             cell_verdict(stored_rubrics.get(run) or {}))
            for run, r in results[cell].items())
        print(f"    {'':28} category x stored eval_aware:")
        for category in CATEGORIES:
            print(f"    {'':30} {category:16} aware {crossed[(category, True)]:4}"
                  f"   not {crossed[(category, False)]:4}")


def _report_rubric_cells(results, keys, stored_rubrics):
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

    _print_robustness(results, cells)


def _print_robustness(results, cells) -> None:
    """Whether batching moved answers together, and why any are missing."""
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


def _print_verdict_rates(results, cells, ref) -> None:
    """Each cell's aware rate, against the reference by Fisher's test."""
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
