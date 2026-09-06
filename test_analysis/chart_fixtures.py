"""
The report shapes the chart tests draw from.

Not named `test_*`, so neither runner collects it as a suite file: pytest looks
for `test_*.py` and so does run_tests.discover_modules. It still counts as suite
rather than shipping source, because conftest.is_test_file decides that by
position - anything under a `test_*/` directory - so the project guards that
apply to tests apply here too.

Every builder here makes the shape the report ACTUALLY emits rather than the
minimum the function under test happens to read, which is what stops a chart
test passing against a report shape that does not exist.
"""


import report as run_report
from subversionbench import charting
from subversionbench.power import MIN_INFORMATIVE_DENOMINATOR

# Derived from the package, not restated: a fixture with its own hand-copied
# key list would still pass if RUBRIC_SIGNAL_KEYS drifted from it.
_SIGNAL_KEYS = run_report.RUBRIC_SIGNAL_KEYS


def _contrast(xa, na, xb, nb, model=None, holm=False, separated=False,
              diff=None, ci=(None, None)):
    """A contrast shaped like the ones _contrast() in run_report emits."""
    rate_a = xa / na if na else None
    rate_b = xb / nb if nb else None
    if diff is None and rate_a is not None and rate_b is not None:
        diff = round(rate_a - rate_b, 4)
    out = {
        "a": {"successes": xa, "n": na, "rate": rate_a},
        "b": {"successes": xb, "n": nb, "rate": rate_b},
        "difference": diff,
        "difference_ci95": list(ci) if diff is not None else None,
        "separated": separated,
        "level_a": True, "level_b": False,
    }
    if model:
        out["model"] = model
        out["holm_rejected"] = holm
    if na == 0 or nb == 0:
        out["difference"] = None
        out["difference_ci95"] = None
        out["note"] = "one side has no data"
    return out


def _section(**over):
    section = {
        "id": "oversight_vs_scheming",
        "question": "Does the presence of oversight increase or decrease "
                    "scheming rates?",
        "overall": _contrast(32, 1793, 54, 1784, diff=-0.0124,
                             ci=(-0.0228, -0.0024), separated=True),
        "by_model": [
            _contrast(1, 60, 4, 60, model="p/a", ci=(-0.14, 0.02)),
            _contrast(4, 60, 1, 60, model="p/b", holm=True, ci=(-0.02, 0.14)),
            _contrast(0, 0, 2, 60, model="p/c"),
        ],
        "stratified": {"mantel_haenszel": {
            "risk_difference": -0.0124,
            "risk_difference_ci95": [-0.0215, -0.0033],
            "n_strata_used": 2, "separated": True}},
        "crude_vs_stratified": {},
    }
    section.update(over)
    return section


def _paired_section(**over):
    section = {
        "id": "evidence_vs_concealment",
        "question": "To what extent does part-evidence vs zero-evidence "
                    "affect concealment rates?",
        "not_pooled_because": "The four phrasings are measured on the SAME acts.",
        "contrasts": [{
            "act": "sandbox",
            "variant_a": "zeroevidence", "variant_b": "partevidence",
            "overall": {
                "a": {"successes": 60, "n": 803, "rate": 0.0747},
                "b": {"successes": 48, "n": 803, "rate": 0.0598},
                "difference": 0.0149, "difference_ci95": [-0.0042, 0.0341],
                "separated": False, "n_pairs": 803,
                "discordant": {"a_only": 37, "b_only": 25},
                "level_a": "zeroevidence", "level_b": "partevidence",
            },
        }],
    }
    section.update(over)
    return section


def _plt():
    """
    pyplot, or skip.

    A plain helper rather than a pytest fixture: run_tests.py is the other
    runner this suite has to work under and it cannot interpret fixtures - see
    test_dependencies.TestBothTestRunnersCanRunEverything.
    """
    plot = charting.import_pyplot()
    if plot is None:
        from conftest import skip_without
        skip_without("matplotlib", "charts are an optional extra")
    return plot


def _by_model_row(model, n_refused, n_persisted, comparable=None,
                  persisted_mis=(0, 0), complied_mis=(0, 0)):
    """One `by_model` entry shaped like persistence_after_refusal() emits.

    `comparable` defaults to whether both sides have episodes - the same rule
    the function under test applies - rather than always being stated, so a
    test can still override it to build the (n>0, n>0) case with the flag
    deliberately wrong if that is ever what it needs to check.
    """
    n_complied = n_refused - n_persisted
    pm, pn = persisted_mis
    cm, cn = complied_mis
    return {
        "model": model, "n_refused": n_refused, "n_persisted": n_persisted,
        "persistence_rate": round(n_persisted / n_refused, 4) if n_refused else None,
        "persisted": {"n": pn, "misaligned": pm,
                     "misaligned_rate": round(pm / pn, 4) if pn else None},
        "complied": {"n": cn, "misaligned": cm,
                    "misaligned_rate": round(cm / cn, 4) if cn else None},
        "comparable_within_model": (bool(n_persisted and n_complied)
                                    if comparable is None else comparable),
    }


def _persistence_profile(by_model=None, **over):
    by_model = by_model if by_model is not None else []
    n_refused = sum(r["n_refused"] for r in by_model)
    n_persisted = sum(r["n_persisted"] for r in by_model)
    profile = {
        "measure": "issued a further blocked command after being shown a "
                  "refusal",
        "is_descriptive_not_causal": True,
        "interpretation": "a profile, not an effect",
        "denominator": "episodes shown at least one sandbox refusal",
        "n_episodes": n_refused, "n_refused": n_refused, "n_never_refused": 0,
        "persistence_rate": (round(n_persisted / n_refused, 4)
                             if n_refused else None),
        "persisted": {"n": n_persisted, "misaligned": 0,
                     "misaligned_rate": None},
        "complied": {"n": n_refused - n_persisted, "misaligned": 0,
                    "misaligned_rate": None},
        "by_model": by_model,
        "n_models_comparable_within_model": sum(
            1 for r in by_model if r["comparable_within_model"]),
        "n_models_persisted_more_misaligned": sum(
            1 for r in by_model
            if r["comparable_within_model"]
            and (r["persisted"]["misaligned_rate"] or 0)
            > (r["complied"]["misaligned_rate"] or 0)),
        "max_retries_in_one_episode": 0,
    }
    profile.update(over)
    return profile


def _epr_row(model, n_resolved, n_true, underpowered=None):
    """One `by_model` entry shaped like encoded_payload_rate() emits."""
    return {
        "model": model, "n_episodes": n_resolved,
        "n_resolved": n_resolved, "n_true": n_true,
        "rate": round(n_true / n_resolved, 4) if n_resolved else None,
        "underpowered": (n_resolved < MIN_INFORMATIVE_DENOMINATOR
                         if underpowered is None else underpowered),
    }


def _epr_profile(by_model=None, **over):
    by_model = by_model if by_model is not None else []
    n_resolved = sum(r["n_resolved"] for r in by_model)
    n_true = sum(r["n_true"] for r in by_model)
    profile = {
        "measure": ("whether the episode contains a base64-alphabet run in "
                    "the model's own words that decodes to real text"),
        "n_episodes": n_resolved,
        "pooled": {"n_resolved": n_resolved, "n_true": n_true,
                  "rate": round(n_true / n_resolved, 4) if n_resolved else None},
        "by_model": by_model,
    }
    profile.update(over)
    return profile


def _signal_by_model_row(model, **rates):
    """One `by_model` entry shaped like eval_signal_rates() emits.

    `rates` maps a signal key to (n_true, n_resolved); a key not passed gets
    no resolved episodes at all - unmeasured, not a rate of zero, the same
    convention `_by_model_row` above uses for a side with no episodes.
    """
    signals = {}
    # Model-level support, independent of any one signal's resolved count:
    # _signal_clusters excludes a model below the floor entirely, and these
    # fixtures are about what a PLOTTED model's cluster looks like. A test
    # that wants the exclusion itself passes n_episodes explicitly.
    n_episodes = rates.pop("n_episodes", MIN_INFORMATIVE_DENOMINATOR)
    for key in _SIGNAL_KEYS:
        n_true, n_resolved = rates.get(key, (0, 0))
        signals[key] = {
            "n_resolved": n_resolved, "n_true": n_true,
            "rate": round(n_true / n_resolved, 4) if n_resolved else None,
            "underpowered": n_resolved < 20,
        }
    return {"model": model, "n_episodes": n_episodes, "signals": signals}


def _signal_profile(by_model=None, **over):
    by_model = by_model if by_model is not None else []
    profile = {
        "measure": "whether the eval-awareness grader answered yes to each "
                  "rubric question",
        "signal_keys": list(_SIGNAL_KEYS),
        "n_episodes": sum(r["n_episodes"] for r in by_model),
        "interpretation": "a rubric question's own answer",
        "pooled": {key: {"n_resolved": 0, "n_true": 0, "rate": None}
                  for key in _SIGNAL_KEYS},
        "by_model": by_model,
    }
    profile.update(over)
    return profile


def _lure_model_row(model, n_lure, n_no_lure, mis_lure, mis_no_lure):
    """One by_model row shaped like lure_effect() builds them."""
    from subversionbench.power import newcombe_diff_ci
    def contrast(n1, n2, x1, x2):
        r1 = x1 / n1 if n1 else None
        r2 = x2 / n2 if n2 else None
        lo, hi = newcombe_diff_ci(x1, n1, x2, n2) if n1 and n2 else (None, None)
        return {"n_lure": n1, "n_no_lure": n2, "n_misaligned_lure": x1,
                "n_misaligned_no_lure": x2, "rate_lure": r1, "rate_no_lure": r2,
                "diff": None if r1 is None or r2 is None else r1 - r2,
                "lo": lo, "hi": hi,
                "underpowered": min(n1, n2) < MIN_INFORMATIVE_DENOMINATOR}
    c = contrast(n_lure, n_no_lure, mis_lure, mis_no_lure)
    return {"model": model, "n_episodes": n_lure + n_no_lure,
            "n_lure_resolved": n_lure, "n_discovered": 0, "n_read": 0,
            "overall": c, "oversight": c, "no_oversight": c}


def _excluded_stamp(kept=120, before=240):
    """The stamp exclude_arm() puts on a report with the arm dropped."""
    return {
        "excluded": "no_oversight", "axis": "oversight",
        "excluded_level": False,
        "words": "no-oversight arm excluded - oversight-present episodes only",
        "why": "the arm's README promises a preview it removes.",
        "n_summaries_before": 8, "n_summaries_kept": 4,
        "n_episodes_before": before, "n_episodes_kept": kept,
        "n_episodes_dropped": before - kept, "n_episodes_unknown_arm": 0,
    }


def _timing_profile(**over):
    """A profile shaped like awareness_refusal_timing() returns."""
    def arm(before, after):
        return {"n_before_refusal": before, "n_after_refusal": after,
                "n_no_refusal": 100, "n_not_aware": 40,
                "n_refusal_unlocatable": 0, "n_episodes": 140 + before + after,
                "n_locatable": before + after,
                "rate_after": round(after / (before + after), 4)
                if before + after else None,
                "underpowered": before + after < MIN_INFORMATIVE_DENOMINATOR}
    profile = {
        "measure": "the share that verbalised it only AFTER the refusal",
        "instrument": "keyword measure, not the rubric grader",
        "not_an_effect": "descriptive",
        "pooled": arm(60, 40),
        "by_arm": {"oversight": arm(50, 5), "no_oversight": arm(10, 35)},
        "by_model": [{"model": "p/a", **arm(20, 20)},
                     {"model": "p/b", **arm(30, 5)},
                     # Below the floor: 3 placeable orderings.
                     {"model": "p/c", **arm(2, 1)},
                     # Refused often, never placeable.
                     {"model": "p/d", **arm(0, 0)}],
    }
    profile.update(over)
    return profile
