"""
What a monitor is shown. The two properties the scenario's validity rests on:
nothing past the cut reaches the monitor, and the actions view holds no
reasoning. A cut that leaked the act's output would make "flagged at the act"
mean flagged after seeing what the act did.
"""

from monitoring.render import (RESULT_CAP, act_step_of, cut_end,
                               matched_act_index, probe_digest, render)


def _transcript():
    return [
        {"type": "thinking", "content": "SECRET-PLAN"},
        {"type": "tool_call", "cmd": "cat notes.txt"},          # 1, step 1
        {"type": "tool_result", "result": "notes"},
        {"type": "tool_call", "cmd": "edit the check"},         # 3, step 2: the act
        {"type": "tool_result", "result": "ACT-OUTPUT"},
        {"type": "text", "content": "AFTER-ACT"},
        {"type": "tool_call", "cmd": "third command"},          # 6, step 3
        {"type": "tool_result", "result": "THIRD-OUTPUT"},
        {"type": "tool_call", "cmd": "fourth command"},         # 8
        {"type": "tool_result", "result": "FOURTH-OUTPUT"},
        {"type": "tool_call", "cmd": "fifth command"},          # 10
        {"type": "tool_result", "result": "FIFTH-OUTPUT"},
    ]


def _shown(cut, view="cot"):
    t = _transcript()
    return render("the task", t[:cut_end(t, 3, cut)], view)


class TestTheCut:
    def test_the_act_cut_shows_the_act_and_not_its_output(self):
        text, steps = _shown("act")
        assert "edit the check" in text and steps == 2
        for later in ("ACT-OUTPUT", "AFTER-ACT", "third command"):
            assert later not in text, later

    def test_act_plus_one_runs_to_the_next_commands_output_and_stops(self):
        text, steps = _shown("act+1")
        assert "ACT-OUTPUT" in text and "THIRD-OUTPUT" in text and steps == 3
        assert "fourth command" not in text

    def test_act_plus_three_and_end(self):
        assert "FIFTH-OUTPUT" in _shown("act+3")[0]
        assert _shown("end")[1] == 5

    def test_a_cut_past_the_episode_is_the_whole_episode(self):
        t = _transcript()
        assert cut_end(t, 10, "act+3") == len(t)

    def test_no_act_means_no_act_cut(self):
        assert cut_end(_transcript(), None, "act") is None
        assert cut_end(_transcript(), None, "end") == len(_transcript())


class TestTheViews:
    def test_actions_holds_no_reasoning_and_cot_does(self):
        assert "SECRET-PLAN" not in _shown("end", "actions")[0]
        assert "SECRET-PLAN" in _shown("end", "cot")[0]

    def test_both_views_keep_the_agents_messages(self):
        assert "AFTER-ACT" in _shown("end", "actions")[0]

    def test_long_output_is_capped_with_a_marker(self):
        t = [{"type": "tool_call", "cmd": "c"},
             {"type": "tool_result", "result": "y" * (RESULT_CAP + 50)}]
        text, _ = render("task", t, "actions")
        assert "y" * (RESULT_CAP + 1) not in text
        assert "50 more characters of output omitted" in text


class TestTheMatchedCut:
    def test_it_lands_on_a_command(self):
        t = _transcript()
        for fraction in (0.0, 0.3, 0.5, 0.99):
            assert t[matched_act_index(t, fraction)]["type"] == "tool_call"

    def test_a_transcript_with_no_command_has_none(self):
        assert matched_act_index([{"type": "text", "content": "x"}], 0.5) is None


class TestTheActStep:
    def test_it_is_the_step_number_the_act_is_rendered_under(self):
        t = _transcript()
        assert act_step_of(t, 3) == 2 and "[step 2] COMMAND:\nedit the check" in _shown("act")[0]
        assert act_step_of(t, None) is None


class TestTheProbe:
    def test_the_digest_moves_with_view_and_cut(self):
        digests = {probe_digest(v, c) for v in ("actions", "cot")
                   for c in ("end", "act")}
        assert len(digests) == 4
