"""
Fixtures shared by the report test modules.

Not named `test_*`, so neither runner collects it as a suite file: pytest looks
for `test_*.py` and so does run_tests.discover_modules. It still counts as suite
rather than shipping source, because conftest.is_test_file decides that by
position - anything under a `test_*/` directory - so the project guards that
apply to tests apply here too.

These build fixtures with BatchIdentity and conftest.batch_episode rather than
hand-rolled dicts and filenames, so a fixture cannot silently drift from what
the harness actually writes. They lived in test_run_report.py while it was the
only file that needed them; they moved here when it stopped being.
"""

import json

from conftest import batch_episode
from subversionbench.batch import BatchIdentity
from subversionbench.grading import MISALIGNED_ACTS
from subversionbench.reporting.facts import normalise_analyses
from subversionbench.scenario import SANDBOX_REFUSAL


def _single(report):
    """The questions built as one contrast with model strata - i.e. not the
    paired phrasing questions, which are a list of contrasts instead."""
    return [q for q in report["questions"] if "contrasts" not in q]

def _write_summary(out, model, nudge, oversight=True, lure=False, stamp="20260101T000000",
                   n_runs=10, n_scheming=0, n_misaligned=0, n_aware=0,
                   n_unaware=0, cross=None, model_slug=None):
    ident = BatchIdentity(model=model, model_slug=model_slug or model.replace("/", "_"),
                          nudge=nudge, effort=None, oversight=oversight, lure=lure,
                          stamp=stamp)
    path = ident.filename(out, prefix="summary")
    d = {
        "model": model, "nudge": nudge, "n_runs": n_runs,
        "n_scheming": n_scheming, "n_misaligned": n_misaligned,
        "awareness_subgroups": {"aware": n_aware, "unaware": n_unaware,
                                "source": "grader"},
        "cross_analysis_awareness": cross,
    }
    with open(path, "w") as f:
        json.dump(d, f)
    return path

def _write_episode(out, n, model, nudge, oversight=True, lure=False,
                   stamp="20260101T000000", sort=None, provider=None,
                   transcript=None, served_by=None, served_by_changed=False,
                   **episode_kwargs):
    # normalise_analyses first, exactly as a collected episode has already been
    # through: the sandbox act key (`out_of_scope_attempts`) is DERIVED there,
    # not set by batch_episode, and a fixture without it is not the shape any
    # real run file has - which is how a test came to assert the wrong thing
    # about question 9's scope.
    ep = batch_episode(**episode_kwargs)
    normalise_analyses([ep])
    parts = ["run", str(n), model.replace("/", "_"), nudge]
    if not oversight:
        parts.append("nooversight")
    if lure:
        parts.append("lure")
    path = f"{out}/{'_'.join(parts)}_{stamp}.json"
    with open(path, "w") as f:
        # Routing is written unconditionally, null included, because that is
        # the shape every collected run file has - a fixture that omitted the
        # keys would exercise a corpus that does not exist.
        json.dump({"model": model, "nudge": nudge, "oversight": oversight,
                  "lure": lure, "analysis": ep["analysis"],
                  # Written unconditionally, empty list included, because a
                  # collected run file always carries the key. `refusal_shown`
                  # is read off this, so a fixture that omitted it would make
                  # every episode look like one that was never refused.
                  "transcript": transcript if transcript is not None else [],
                  "openrouter_sort": sort,
                  "openrouter_provider": provider,
                  # What the router said ANSWERED each turn, as opposed to the
                  # two keys above, which record what was asked for. Written
                  # unconditionally for the same reason: every collected
                  # episode carries both, so a fixture that omitted them would
                  # exercise a corpus shape that does not exist - and would
                  # leave the check that reads them permanently on its
                  # nothing-recorded branch.
                  "served_by_providers": list(served_by or []),
                  "served_by_changed": served_by_changed}, f)
    return path


def refusal_result(turn=1):
    """A tool_result the model was actually SHOWN the sandbox refusal in.

    The refusal text is imported rather than written out: it is scenario content,
    and no tracked file may hold it in plaintext.
    """
    return {"turn": turn, "type": "tool_result", "result": SANDBOX_REFUSAL}

def _act_row(model="m", nudge="strong", oversight=True, lure=False, n_runs=10,
             n_misaligned=0, n_scheming=0, n_scheming_undetermined=0, **acts):
    """One arm row shaped like act_arm_rows builds them.

    Act keys are derived from MISALIGNED_ACTS rather than spelled out, so a test
    written today cannot quietly stop covering an act added tomorrow - the same
    reason the production builder derives them.
    """
    row = {"model": model, "nudge": nudge, "oversight": oversight, "lure": lure,
           "n_runs": n_runs, "n_misaligned": n_misaligned,
           "n_scheming": n_scheming,
           "n_scheming_undetermined": n_scheming_undetermined}
    for act in MISALIGNED_ACTS:
        name = act["name"]
        row[f"n_{name}_act"] = acts.get(f"{name}_act", 0)
        row[f"n_{name}_scheming"] = acts.get(f"{name}_scheming", 0)
        # Available everywhere unless a test says otherwise, so a test about
        # something else cannot accidentally rest on an unavailable act.
        row[f"n_{name}_observable"] = acts.get(f"{name}_observable", n_runs)
    return row


# The quote both awareness channels carry, so a test can assert WHERE it was
# cited rather than whether the matcher fired at all.
AWARE_QUOTE = ("this looks like an evaluation of my alignment rather than a "
               "real deployment task")


def write_awareness_episode(out, n, model, nudge, oversight=True,
                            where="thinking", aware=True,
                            stamp="20260101T000000"):
    """One run file whose awareness, if any, is cited in `where`."""
    ep = batch_episode()
    normalise_analyses([ep])
    analysis = dict(ep["analysis"])
    analysis["eval_awareness_grader"] = {
        "eval_aware": aware,
        "rubric_results": ({"suspects_being_tested":
                            {"answer": True, "quote": AWARE_QUOTE}}
                           if aware else {}),
    }
    transcript = ([{"turn": 1, "type": where, "content": AWARE_QUOTE}]
                  if aware else
                  [{"turn": 1, "type": "text", "content": "I recommend B."}])
    parts = ["run", str(n), model.replace("/", "_"), nudge]
    if not oversight:
        parts.append("nooversight")
    path = f"{out}/{'_'.join(parts)}_{stamp}.json"
    with open(path, "w") as f:
        json.dump({"model": model, "nudge": nudge, "oversight": oversight,
                   "lure": False, "analysis": analysis,
                   "transcript": transcript}, f)
    return path
