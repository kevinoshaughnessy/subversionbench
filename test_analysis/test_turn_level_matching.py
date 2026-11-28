"""
The risk sets and the control draw (turn_level/matching.py).

What matters: a control is another episode of the same model and arm, with the act kind
available, at its own opportunity plus the case's k, that had reached that turn and had taken no
counted act before it or on it; an episode whose act could not be located is never a control;
draws are capped, without replacement, and reproducible from the seed.
"""

from turn_level.matching import build_sets, control_turn


def _rec(key, o=1, last=10, act_turn=None, kind="oversight", model="m", stratum=("arm",),
         unlocated=False, opportunity=None):
    return {"key": key, "model": model, "stratum": list(stratum), "scenario": "mainline",
            "last_turn": last, "opportunity": opportunity if opportunity is not None else {kind: o},
            "act": None if act_turn is None else {"kind": kind, "index": 0, "turn": act_turn},
            "act_unlocated": unlocated}


CASE = _rec("case", o=2, act_turn=5)                       # k = 3
ELIGIBLE = _rec("later_acter", o=1, act_turn=6)            # at risk on turn 4, acts later
INELIGIBLE = [
    _rec("acts_on_the_turn", o=1, act_turn=4),
    _rec("acted_before", o=1, act_turn=3),
    _rec("ended_early", o=1, last=3),
    _rec("unlocated", o=1, unlocated=True),
    _rec("other_model", o=1, model="n"),
    _rec("other_arm", o=1, stratum=("other",)),
    _rec("kind_unavailable", opportunity={"sandbox": 1}),
    _rec("never_possible", opportunity={"oversight": None}),
]


class TestControlTurn:
    def test_the_eligible_one_is_at_its_own_opportunity_plus_k(self):
        assert control_turn(ELIGIBLE, "oversight", 3) == 4

    def test_each_reason_for_ineligibility(self):
        sets = build_sets([CASE, ELIGIBLE, *INELIGIBLE], "T", 4, 1)["sets"]
        mine = next(s for s in sets if s["case"]["episode"] == "case")
        assert [c["episode"] for c in mine["controls"]] == ["later_acter"]


class TestBuildSets:
    def test_capped_without_replacement_and_reproducible(self):
        pool = [_rec(f"c{i}", o=1) for i in range(10)]
        first = build_sets([CASE, *pool], "T", 4, 7)["sets"][0]["controls"]
        again = build_sets([CASE, *pool], "T", 4, 7)["sets"][0]["controls"]
        other = [build_sets([CASE, *pool], "T", 4, s)["sets"][0]["controls"] for s in range(8, 14)]
        assert len(first) == 4 and len({c["episode"] for c in first}) == 4 and first == again
        assert any(o != first for o in other)

    def test_a_case_with_no_eligible_control_is_dropped_and_counted(self):
        never_acting = [r for r in INELIGIBLE if r["act"] is None]
        out = build_sets([CASE, *never_acting], "T", 4, 1)
        assert out["sets"] == [] and out["counts"]["cases dropped, no eligible control"] == 1

    def test_an_act_before_its_opportunity_starts_the_risk_set_at_the_act(self):
        blind = _rec("blind", opportunity={"oversight": None}, act_turn=4)
        out = build_sets([blind, _rec("c", o=1)], "T", 4, 1)
        assert out["counts"]["act before its opportunity"] == 1
        assert out["sets"][0]["k"] == 0 and out["sets"][0]["controls"][0]["turn"] == 1

    def test_an_unlocated_act_is_counted_and_is_no_case(self):
        out = build_sets([_rec("u", unlocated=True), _rec("c")], "T", 4, 1)
        assert out["sets"] == [] and out["counts"]["acts not located"] == 1
