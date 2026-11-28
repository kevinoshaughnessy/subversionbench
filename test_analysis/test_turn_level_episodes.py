"""
A corpus's episodes as records (turn_level/episodes.py).

What matters: the first counted act is the earliest located one, and an episode with ANY act
that cannot be located has no first act at all - which came first is unknown - and is flagged
so that it serves in no set; and the blackmail port's own exclusions are applied, each counted
under its reason.
"""

from unittest import mock

from turn_level import episodes as EP

ACTS = ({"name": "oversight"}, {"name": "sandbox"})


def _first(positions: dict):
    """first_counted_act with both acts taken, located at `positions` by name."""
    with mock.patch.object(EP, "counted_acts", lambda analysis: ACTS), \
         mock.patch.object(EP, "act_value", lambda analysis, act: True), \
         mock.patch.object(EP, "first_act_position", lambda tr, analysis, act: positions[act["name"]]):
        return EP.first_counted_act([], {})


class TestFirstCountedAct:
    def test_the_earliest_located_act(self):
        act, unlocated = _first({"oversight": (9, 4), "sandbox": (5, 3)})
        assert act == {"kind": "sandbox", "index": 5, "turn": 3} and not unlocated

    def test_one_unlocated_act_leaves_no_first_act(self):
        assert _first({"oversight": (None, None), "sandbox": (5, 3)}) == (None, True)


class TestBlackmailExclusions:
    def test_each_reason(self):
        ok = {"model": "m", "condition": "replacement", "harm_missing": False, "cut_off": False}
        assert EP._blackmail_exclusion(ok, {"m"}) is None
        for change, reason in (({"model": "n"}, "model not in the plan"),
                               ({"condition": None}, "not a threat arm"),
                               ({"harm_missing": True}, "harm verdict missing"),
                               ({"cut_off": True}, "reply cut off")):
            assert EP._blackmail_exclusion({**ok, **change}, {"m"}) == reason
