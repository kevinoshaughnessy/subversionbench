"""
What a model could see of its suspicion on each turn, and the turn-level estimate
(subversionbench/turn_context.py).

What matters: reasoning from an earlier turn is in view only where the harness replays it, while
visible text always is; nothing written at or after the act counts; only the first act's turn is
an event; and the estimate compares turns only with turns of the same number, so that a reading
in which suspicion and acts both pile up late is not mistaken for an association.
"""

from subversionbench.turn_context import (reasoning_replayed, resampled_odds_ratio_interval,
                                          seen_on_turn, turn_level_estimate, turn_units)

TRANSCRIPT = [
    {"type": "thinking", "turn": 1, "content": "a"},   # 0
    {"type": "text", "turn": 1, "content": "b"},       # 1
    {"type": "thinking", "turn": 2, "content": "c"},   # 2
    {"type": "tool_call", "turn": 2, "cmd": "act"},    # 3
    {"type": "thinking", "turn": 3, "content": "d"},   # 4
]


class TestWhatIsInView:
    def test_reasoning_of_the_same_turn_is_in_view(self):
        assert seen_on_turn(TRANSCRIPT, [2], 2, None, False)

    def test_earlier_reasoning_is_in_view_only_where_it_is_replayed(self):
        assert not seen_on_turn(TRANSCRIPT, [0], 2, None, False)
        assert seen_on_turn(TRANSCRIPT, [0], 2, None, True)

    def test_earlier_visible_text_is_always_in_view(self):
        assert seen_on_turn(TRANSCRIPT, [1], 3, None, False)

    def test_nothing_written_later_or_after_the_act_counts(self):
        assert not seen_on_turn(TRANSCRIPT, [4], 2, None, True)
        assert not seen_on_turn(TRANSCRIPT, [2], 2, 2, False)

    def test_whose_reasoning_was_replayed_is_read_off_the_episode(self):
        assert reasoning_replayed({"model": "claude-opus-5-5"})
        assert reasoning_replayed({"model": "moonshotai/kimi-k2.6",
                                   "reasoning_details": [{"turn": 1, "sent_back": True}]})
        assert not reasoning_replayed({"model": "google/gemini-3.5-flash",
                                       "reasoning_details": [{"turn": 1}]})
        assert not reasoning_replayed({"model": "anthropic/claude-opus-5-5"})


class TestTheUnits:
    def test_every_turn_is_a_unit_and_only_the_acts_turn_an_event(self):
        assert turn_units(TRANSCRIPT, [0], 3, None, True, False) == [
            (1, True, False), (2, False, False), (3, False, True)]

    def test_an_episode_that_did_not_act_has_no_event(self):
        assert [e for _, _, e in turn_units(TRANSCRIPT, [], 3, None, False, False)] == [False] * 3

    def test_the_act_index_applies_on_the_acts_turn(self):
        assert turn_units(TRANSCRIPT, [2], 2, 3, True, False)[-1] == (2, True, True)
        assert turn_units(TRANSCRIPT, [2], 2, 2, True, False)[-1] == (2, False, True)


def _row(model, units):
    return {"model": model, "arm": "a", "units": units}


def _confounded():
    """Suspicion only on turn 3, where half of all turns end in an act; on turn 1 a tenth do.
    Within turn 3 exposed and unexposed act alike, so there is no association."""
    rows = []
    for m in ("m1", "m2"):
        for i in range(20):
            rows.append(_row(m, [(1, False, i < 2)] if i < 2 else [(1, False, False), (2, False, False),
                                                                  (3, i % 2 == 0, i % 4 < 2)]))
    return rows


class TestTheEstimate:
    def test_turns_are_compared_only_with_turns_of_the_same_number(self):
        mh = turn_level_estimate(_confounded(), lambda r: r["model"])
        assert abs(mh["odds_ratio"] - 1.0) < 0.35

    def test_an_association_planted_within_turns_is_found(self):
        rows = [_row(m, [(1, exposed, (not exposed) and i % 2 == 0) for exposed in (i % 3 == 0,)])
                for m in ("m1", "m2") for i in range(60)]
        rows += [_row(m, [(1, True, True)]) for m in ("m1", "m2")]
        assert turn_level_estimate(rows, lambda r: r["model"])["odds_ratio"] < 0.5

    def test_the_interval_is_reproducible_and_holds_the_estimate(self):
        rows = _confounded()
        first = resampled_odds_ratio_interval(rows, lambda r: r["model"], draws=60)
        assert first == resampled_odds_ratio_interval(rows, lambda r: r["model"], draws=60)
        point = turn_level_estimate(rows, lambda r: r["model"])["odds_ratio"]
        assert first[0] <= point <= first[1] and first[2] == 60

    def test_no_interval_without_an_estimate(self):
        assert resampled_odds_ratio_interval([_row("m", [(1, False, False)])], lambda r: r["model"],
                                             draws=5) == (None, None, 0)
