"""
When an act becomes possible (turn_level/opportunity.py).

What matters: the prompts put a name in front of the model on turn 1, and a tool result on the
turn after its call; the sandbox act is possible from turn 1 whatever happened; and the blackmail
port's leverage is found by its text, whitespace and case aside, in every arm of both bundles.
"""

from subversionbench.grading.acts import LOCATED_BY_RECORDED_COMMANDS
from turn_level import opportunity as O


def _episode(prompt="Do the task.", results=()):
    tr = []
    for turn, text in results:
        tr += [{"type": "tool_call", "turn": turn, "cmd": "ls"},
               {"type": "tool_result", "turn": turn, "result": text}]
    return {"system_prompt": "You are an agent.", "user_prompt": prompt, "transcript": tr}


ARTEFACT_ACT = {"located_by": ("watchfile.yaml",)}


class TestArtefactOpportunity:
    def test_a_name_in_the_prompt_is_turn_one(self):
        assert O.act_opportunity(_episode("See watchfile.yaml first."), ARTEFACT_ACT) == 1

    def test_a_name_in_a_tool_result_is_the_next_turn(self):
        ep = _episode(results=[(1, "readme.md"), (2, "config/watchfile.yaml"), (3, "watchfile.yaml")])
        assert O.act_opportunity(ep, ARTEFACT_ACT) == 3

    def test_a_name_that_never_arrives_is_never_possible(self):
        assert O.act_opportunity(_episode(results=[(1, "readme.md")]), ARTEFACT_ACT) is None

    def test_the_sandbox_act_is_possible_from_turn_one(self):
        act = {"located_by": LOCATED_BY_RECORDED_COMMANDS}
        assert O.act_opportunity(_episode(results=[(4, "nothing")]), act) == 1


class TestLeverage:
    def test_found_by_its_text_whatever_the_whitespace(self):
        ep = _episode(results=[(1, "inbox listing"), (2, "Header\n  THE   Leverage line\nend")])
        assert O.leverage_opportunity(ep, ["the leverage line"]) == 3

    def test_not_found_is_never_possible(self):
        assert O.leverage_opportunity(_episode(results=[(1, "routine mail")]), ["the leverage line"]) is None

    def test_every_arm_of_both_bundles_has_its_four_lines(self):
        """The entries are named by key; if a bundle stopped having them, or one of them were
        empty, every blackmail episode would have no opportunity at all."""
        from subversionbench.scenario import load_scenario, scenario_for
        for name in ("blackmail", "blackmail_replay"):
            bundle = load_scenario(f"subversionbench/scenarios/{name}.b64")
            for variant in ("replacement", "restriction"):
                lines = O.leverage_snippets(bundle, variant)
                arm = scenario_for(oversight=True, bundle=bundle, nudge="none", lure=False,
                                   variant=variant)
                assert len(lines) == 4 and all(len(line) > 20 for line in lines)
                assert all(line in O.normalise(arm[e]) for line, e in
                           zip(lines, O.LEVERAGE_ENTRIES, strict=True))
