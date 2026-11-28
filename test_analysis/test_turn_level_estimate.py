"""
The readings and the estimate step (turn_level/readings.py, turn_level/estimate.py).

What matters: a set whose case has no verdict is dropped and a control without one leaves its
set, unless a bound fills them; reading 6 keeps only controls in the case's opportunity band;
reading 2 leaves each dominant model out and then all of them; the estimate refuses to run
without the labels and their hash, and states no finding for a judge that failed validation;
and, end to end on a small working directory, writes a document whose A estimate is the hand
count.
"""

import hashlib
import json
import os
import tempfile

from turn_level import estimate as E
from turn_level import readings as R
from turn_level import store


def _set(model, case, controls, o=1, control_o=None):
    return {"model": model, "kind": "oversight", "scenario": "mainline",
            "case": {"episode": case[0], "turn": 3, "o": o, "_e": case[1]},
            "controls": [{"episode": e, "turn": 3, "o": control_o or o, "_e": x} for e, x in controls]}


def exposed(member):
    return member["_e"]


class TestReadings:
    def test_missing_verdicts_drop_a_set_or_a_control_unless_filled(self):
        sets = [_set("m", ("a", None), [("b", False)]),
                _set("m", ("c", True), [("d", None), ("e", False)])]
        plain = R.odds_ratio(sets, exposed)
        assert plain["sets dropped for a missing verdict"] == 1
        assert plain["controls left out for a missing verdict"] == 1 and plain["controls"] == 1
        filled = R.odds_ratio(sets, exposed, fill=True)
        assert filled.get("sets dropped for a missing verdict", 0) == 0 and filled["controls"] == 3

    def test_reading_six_keeps_controls_in_the_case_band(self):
        s = _set("m", ("a", True), [("b", False)], o=2)
        s["controls"].append({"episode": "c", "turn": 3, "o": 7, "_e": False})
        assert [c["episode"] for c in R.matched_on_opportunity([s])[0]["controls"]] == ["b"]

    def test_reading_two_leaves_each_dominant_model_out_and_then_all(self):
        sets = [_set("big", ("a", True), [("b", False)])] * 8 + [_set("mid", ("a", True), [("b", False)])] * 2
        out = R.leaving_models_out(sets, exposed)
        assert set(out) == {"without big", "without mid", "without all of big, mid"}
        assert out["without big"]["sets given"] == 2


class TestEstimateStep:
    def test_refuses_without_labels(self):
        with tempfile.TemporaryDirectory() as work:
            assert E.estimate(work, None, "0" * 64) == 1
            assert E.estimate(work, os.path.join(work, "missing.json"), "0" * 64) == 1
            assert not os.path.exists(os.path.join(work, store.ESTIMATE))

    def test_no_finding_from_an_unvalidated_judge(self):
        d = E.decision({"category": "includes 1"}, {"passes": False})
        assert d["finding"] is None and d["category"] == "includes 1"

    def test_end_to_end_on_a_small_working_directory(self):
        with tempfile.TemporaryDirectory() as root:
            work, labels_path = _small_work(root)
            with open(labels_path, "rb") as f:
                digest = hashlib.sha256(f.read()).hexdigest()
            assert E.estimate(work, labels_path, digest) == 0
            doc = store.read_json(os.path.join(work, store.ESTIMATE))
            # 6 sets with only the case exposed, 3 with only the control: 2.0.
            assert doc["primary"]["A"]["odds_ratio"] == 2.0
            assert doc["decision on A"]["validated"] is False


def _small_work(root: str) -> tuple:
    """Nine discordant 1:1 sets in A, their verdicts, and a pack of all their units, labelled so
    the judge fails validation."""
    work = os.path.join(root, "work")
    path = os.path.join(root, "ep.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"model": "x/m", "analysis": {}, "transcript": [
            {"type": "thinking", "turn": t, "content": f"r{t}"} for t in (1, 2, 3)]}, f)
    episodes, sets, items, labels = {}, [], [], {}
    for i, case_exposed in enumerate([True] * 6 + [False] * 3):
        case, control = f"src/c{i}", f"src/k{i}"
        for key in (case, control):
            episodes[key] = {"path": path, "model": "m", "source": "src", "scenario": "mainline",
                             "stratum": ["m"], "acted": key == case}
        sets.append({"id": f"A-{i}", "kind": "oversight", "model": "m", "stratum": ["m"],
                     "scenario": "mainline", "k": 0, "case": {"episode": case, "turn": 3, "o": 3},
                     "controls": [{"episode": control, "turn": 3, "o": 3}]})
        for role, key, aware in (("case", case, case_exposed), ("control", control, not case_exposed)):
            store.append_verdict(work, {"unit": store.unit_id(key, 3, "in_view"), "eval_aware": aware,
                                        "grading_failed": False, "current_chars": 5,
                                        "in_view_chars": 9, "current_has_reasoning": True})
            item = f"u{len(items):03d}"
            items.append({"item": item, "unit": key, "group": "A", "role": role, "judged_exposed": aware})
            labels[item] = "not_aware"
    store.write_json(store.sets_path(work, "A"), {
        "sets": sets, "episodes": episodes, "inputs": {}, "counts": {}, "opportunity_turns": {},
        "located_by_model": {}, "models_without_a_case": []})
    population = {f"A/{r}/{j}": sum(1 for i in items if (i["role"], i["judged_exposed"]) == (r, j))
                  for r in ("case", "control") for j in (True, False)}
    store.write_json(os.path.join(work, store.PACK_KEY), {
        "items": items, "population": population,
        "verdicts_sha256": store.sha256(os.path.join(work, store.VERDICTS))})
    labels_path = os.path.join(root, "labels.json")
    with open(labels_path, "w", encoding="utf-8") as f:
        json.dump(labels, f)
    return work, labels_path
