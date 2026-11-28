"""
The judge against the labeller (turn_level/validation.py).

What matters: the pack is drawn per cell and capped, reproducibly, and shuffled; sensitivity and
specificity are weighted back to each cell's share, which the sample's own proportions are not;
the gate fails a judge whose accuracy differs between cases and controls; and labels are refused
unless complete, and unless they hash to what was recorded.
"""

import hashlib
import json
import os
import tempfile

from turn_level import store
from turn_level.validation import (PACK_SIZES, build_pack, checked_labels, draw, gate,
                                   load_labels, scores)


def _units(n_per_cell=30):
    return [(f"u-{g}-{r}-{j}-{i}", g, r, j) for g in ("A", "BC") for r in ("case", "control")
            for j in (True, False) for i in range(n_per_cell)]


def _key(cells):
    """cells: {(role, judged): (population, [labels])} -> (labels, key) for group A."""
    items, labels, population = [], {}, {}
    for (role, judged), (pop, labs) in cells.items():
        population[f"A/{role}/{judged}"] = pop
        for lab in labs:
            item = f"i{len(items)}"
            items.append({"item": item, "group": "A", "role": role, "judged_exposed": judged})
            labels[item] = lab
    return labels, {"items": items, "population": population}


class TestDraw:
    def test_capped_per_cell_reproducible_and_shuffled(self):
        drawn, population, per_cell = draw(_units())
        assert per_cell["A/case/True"] == PACK_SIZES["A"] and per_cell["BC/control/False"] == PACK_SIZES["BC"]
        assert population["A/case/True"] == 30
        assert drawn == draw(_units())[0]
        assert [d[1:] for d in drawn] != sorted(d[1:] for d in drawn)

    def test_a_short_cell_gives_what_it_has(self):
        units = [u for u in _units() if not (u[1:] == ("A", "case", True) and not u[0].endswith(("-0", "-1")))]
        assert draw(units)[2]["A/case/True"] == 2


class TestScores:
    def test_sensitivity_is_weighted_by_cell_population(self):
        """Judged exposed: 10 units, both labelled aware. Judged unexposed: 90 units, half of the
        two labelled aware. Weighted: 10 true positives against 45 false negatives, 10/55; the
        sample's own share would be 2/3."""
        labels, key = _key({("case", True): (10, ["aware", "aware"]),
                            ("case", False): (90, ["aware", "not_aware"])})
        sens = scores(labels, key, "A")["sensitivity"]
        assert abs(sens["estimate"] - 10 / 55) < 1e-3
        assert sens["ci95"][0] < sens["estimate"] < sens["ci95"][1]

    def test_the_gate_fails_a_judge_that_differs_by_role(self):
        perfect = ["aware"] * 3
        labels, key = _key({("case", True): (10, perfect), ("case", False): (90, ["not_aware"] * 3),
                            ("control", True): (10, perfect),
                            ("control", False): (90, ["not_aware", "not_aware", "aware"])})
        result = gate(labels, key)
        assert not result["passes"]
        assert any("differs by role" in r for r in result["reasons"])

    def test_the_gate_passes_a_judge_that_agrees_everywhere(self):
        labels, key = _key({(r, j): (50, ["aware" if j else "not_aware"] * 3)
                            for r in ("case", "control") for j in (True, False)})
        assert gate(labels, key)["passes"]


class TestLabels:
    def test_incomplete_or_invalid_labels_are_refused(self):
        key = {"items": [{"item": "u001"}, {"item": "u002"}]}
        for labels in ({"u001": "aware"}, {"u001": "aware", "u002": "maybe"}):
            try:
                checked_labels(labels, key)
            except ValueError:
                continue
            raise AssertionError(f"accepted {labels}")
        assert checked_labels({"u001": "aware", "u002": "not_aware"}, key)

    def test_labels_must_exist_and_match_their_recorded_hash(self):
        with tempfile.TemporaryDirectory() as work:
            store.append_verdict(work, {"unit": "x#1#in_view", "eval_aware": True})
            store.write_json(os.path.join(work, store.PACK_KEY), {
                "items": [{"item": "u001"}],
                "verdicts_sha256": store.sha256(os.path.join(work, store.VERDICTS))})
            path = os.path.join(work, "labels.json")
            for args in ((None, "0" * 64), (path, "0" * 64)):
                if args[0]:
                    with open(path, "w", encoding="utf-8") as f:
                        json.dump({"u001": "aware"}, f)
                try:
                    load_labels(args[0], args[1], work)
                except (FileNotFoundError, ValueError):
                    continue
                raise AssertionError(f"accepted {args}")
            with open(path, "rb") as f:
                digest = hashlib.sha256(f.read()).hexdigest()
            assert load_labels(path, digest, work)[0] == {"u001": "aware"}


class TestOrderOfSteps:
    def test_no_pack_while_a_unit_is_owed_a_call(self):
        """The pack's cell sizes are the validation weights, so it waits for the re-run pass."""
        with tempfile.TemporaryDirectory() as work:
            member = {"episode": "src/e", "turn": 2, "o": 1}
            store.write_json(store.sets_path(work, "A"), {
                "sets": [{"case": member, "controls": [{**member, "episode": "src/f"}]}],
                "episodes": {}})
            store.append_verdict(work, {"unit": store.unit_id("src/e", 2, "in_view"),
                                        "eval_aware": True})
            assert build_pack(work) == 1
            assert not os.path.exists(os.path.join(work, store.PACK))

    def test_no_estimate_once_the_verdicts_have_changed_since_the_pack(self):
        with tempfile.TemporaryDirectory() as work:
            store.append_verdict(work, {"unit": "x#1#in_view", "eval_aware": True})
            store.write_json(os.path.join(work, store.PACK_KEY), {
                "items": [{"item": "u001"}],
                "verdicts_sha256": store.sha256(os.path.join(work, store.VERDICTS))})
            path = os.path.join(work, "labels.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"u001": "aware"}, f)
            digest = store.sha256(path)
            assert load_labels(path, digest, work)
            store.append_verdict(work, {"unit": "x#2#in_view", "eval_aware": False})
            try:
                load_labels(path, digest, work)
            except ValueError:
                return
            raise AssertionError("labels accepted against a verdict file changed since the pack")
