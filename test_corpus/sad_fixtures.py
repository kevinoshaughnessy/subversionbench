"""
The leaderboard, the awareness rows, and a report shaped like build_report's.

Not named `test_*`, so neither runner collects it as a suite file: pytest looks
for `test_*.py` and so does run_tests.discover_modules. It still counts as suite
rather than shipping source, because conftest.is_test_file decides that by
position - anything under a `test_*/` directory - so the project guards that
apply to tests apply here too.

`_synthetic_report` is assembled here rather than run off the shipped bundle:
what that bundle happens to carry today - which rows are unmatched, which
matches are inexact - is a fact about the corpus that moves as models are
evaluated, and pinning it would make the printer's guards untestable in
whichever direction it currently sits.
"""

import contextlib
import io

import sad_oversight as so

def _bundle():
    return so.load_bundle()


def _awareness(**models):
    out = {}
    for model, (aware, text, n) in models.items():
        out[model.replace("__", "/")] = {
            "n_aware": aware, "n_aware_text": text, "n": n,
            "n_episodes": n, "episodes_with_reasoning": n}
    return out


def _synthetic_report(pairs=None, correlations=None, sensitivity=None,
                      deliberately_unmatched=None, unmatched_rows=None):
    """A report shaped like build_report's, assembled here rather than run off
    the shipped bundle: what that bundle happens to carry today (which rows are
    unmatched, which matches are inexact) is a fact about the corpus that moves
    as models are evaluated, and pinning it in a test would make the printer's
    guards untestable in whichever direction the bundle currently sits."""
    return {
        "n_pairs": len(pairs or []), "n_leaderboard_rows": 12,
        "n_local_models": 9, "pairs": pairs or [],
        "correlations": correlations or [],
        "correlations_exact_matches_only": sensitivity or [],
        "effort_agreement": {"n_pairs": 0, "n_local_effort_unset": 0,
                             "note": "fixture effort note"},
        "unmatched_leaderboard_rows": unmatched_rows or [],
        "unmatched_local_models": [],
        "deliberately_unmatched": deliberately_unmatched or [],
    }


def _synthetic_pair(sad_model="Ext A", confidence="exact", local_models=("a",),
                    n_aware=6, n_aware_text=3, n=60, score=41.5):
    return {
        "sad_model": sad_model, "sad_effort": "high",
        "confidence": confidence, "match_note": None,
        "scores": {v: {"rank": 1, "score": score, "se": 2.0, "invalid": 0}
                   for v in so.VARIANTS},
        "local_models": list(local_models),
        "n_aware": n_aware, "n_aware_text": n_aware_text, "n": n,
        "n_episodes": n, "episodes_with_reasoning": n,
        "aware_rate": round(n_aware / n, 4),
        "text_rate": round(n_aware_text / n, 4),
        "pooled_routes": len(local_models) > 1,
    }


def _print(report):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        so.print_report(report)
    return buf.getvalue()
