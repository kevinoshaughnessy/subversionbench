"""
A bundle may ask for an unfinished turn to be asked again: one that came back
empty, with nothing at all, or with a tool call written as text. The
impossible-task r1 lost 23 of gemini-3.5-flash's 40 episodes to such turns,
eight of them provider errors. Without the key nothing changes.
"""

from types import SimpleNamespace as NS
from unittest import mock

from subversionbench import episode
from subversionbench.endings import EMPTY_TURN_MARKER

EMPTY = [NS(type="text", text=f"{EMPTY_TURN_MARKER} (finish_reason=error).]")]
LEAKED = [NS(type="text", text="call:default_api:bash{cmd:ls -la}")]
DONE = [NS(type="text", text="Report: the batch fails the check.")]


def _run(replies, retries):
    """Run the loop on scripted replies; the calls made and the final state."""
    pending, calls = list(replies), []

    def create(messages, **kw):
        calls.append(len(messages))
        content, reason = pending.pop(0)
        return NS(content=content, stop_reason=reason, usage=None, model="m")

    state, transcript = episode._new_loop_state(), []
    with mock.patch.object(episode, "UNFINISHED_TURN_RETRIES", retries):
        episode.run_agentic_loop(
            NS(messages=NS(create=create)), {}, [{"role": "user", "content": "go"}],
            transcript, state, max_turns=5, red=str,
            sandbox={"env_dir": "/x", "isolation": "deny-network",
                     "profile_path": None, "episode_root": "/x"})
    return calls, state, transcript


class TestUnfinishedTurnsAreAskedAgain:
    def test_an_empty_turn_then_a_report_ends_on_the_report(self):
        calls, state, transcript = _run([(EMPTY, "error"), (DONE, "stop")], 2)
        assert state["ended_by"] == "model_stopped"
        assert len(calls) == 2 and calls[0] == calls[1], "the retry was not the same request"
        assert state["resampled_turns"] == [
            {"turn": 1, "ending": "empty_turn", "reason": "error"}]
        assert [t["content"] for t in transcript if t["type"] == "text"] == [DONE[0].text]

    def test_a_tool_call_written_as_text_is_asked_again(self):
        _calls, state, _t = _run([(LEAKED, "stop"), (DONE, "stop")], 2)
        assert state["ended_by"] == "model_stopped"
        assert state["resampled_turns"][0]["ending"] == "raw_tool_call_text"

    def test_the_retries_are_bounded_and_the_last_answer_stands(self):
        calls, state, _t = _run([(EMPTY, "stop")] * 3, 2)
        assert len(calls) == 3 and state["ended_by"] == "empty_turn"
        assert len(state["resampled_turns"]) == 2

    def test_a_finished_turn_is_never_asked_again(self):
        calls, state, _t = _run([(DONE, "stop")], 2)
        assert len(calls) == 1 and state["resampled_turns"] == []


class TestWithoutTheKeyNothingChanges:
    def test_one_request_and_no_field(self):
        calls, state, _t = _run([(EMPTY, "error")], 0)
        assert len(calls) == 1 and state["ended_by"] == "empty_turn"
        assert "resampled_turns" not in state
        assert episode._resample_block(state) == {}
