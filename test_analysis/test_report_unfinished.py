"""An episode that ended with no closing turn is not a model that stopped.

The fourth way a propensity rate counts a model as having declined, after the
three the provider's word surfaces (truncated, refused, errored): an empty turn
the provider called a stop, or a tool call written as text. Read from the
settled ending, so it covers stored episodes recorded as "model_stopped".
"""

import contextlib
import io
import tempfile

import report as rr
from subversionbench.endings import EMPTY_TURN_MARKER
from test_analysis.report_fixtures import _write_episode


def _final(text):
    return [{"turn": 1, "type": "tool_call", "cmd": "ls"},
            {"turn": 1, "type": "tool_result", "result": ""},
            {"turn": 2, "type": "text", "content": text}]


def _corpus(*episodes):
    out = tempfile.mkdtemp()
    for i, (text, provider, ended_by) in enumerate(episodes, 1):
        _write_episode(out, i, "m", "strong", ended_by=ended_by,
                       ended_by_provider=provider, transcript=_final(text))
    return out


def _facts(*episodes):
    return rr.data_quality_facts(rr.load_episodes(_corpus(*episodes)))


EMPTY = f"{EMPTY_TURN_MARKER} (finish_reason=stop).]"
LEAKED = "call:default_api:bash{cmd:ls}"


class TestUnfinishedEpisodesAreFlagged:
    def test_an_empty_stop_and_a_leaked_call_are_flagged(self):
        facts = _facts((EMPTY, "stop", "model_stopped"),
                       (LEAKED, "stop", "model_stopped"),
                       ("Recommendation: B.", "stop", "model_stopped"))
        [arm] = facts["unfinished_as_stopped_arms"]
        assert arm["n_unfinished"] == 2 and arm["n_episodes"] == 3
        assert arm["endings"] == [{"ending": "empty_turn", "n_episodes": 1},
                                  {"ending": "raw_tool_call_text",
                                   "n_episodes": 1}]

    def test_the_finding_reaches_the_printed_report(self):
        from report.console_data_quality import _print_data_quality
        out = _corpus((EMPTY, "stop", "model_stopped"))
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            _print_data_quality(rr.build_report(out)["data_quality"])
        text = buf.getvalue()
        assert "read as stopped but unfinished: 1" in text, text[-2000:]
        assert "empty_turn x1" in text

    def test_a_closing_report_is_not_flagged(self):
        """The discriminating half: without it the check could flag every
        episode and pass the test above."""
        facts = _facts(("Recommendation: B.", "stop", "model_stopped"))
        assert facts["unfinished_as_stopped_arms"] == []

    def test_one_the_provider_explains_is_left_to_its_own_check(self):
        facts = _facts((EMPTY, "error", "model_stopped"))
        assert facts["unfinished_as_stopped_arms"] == []
        assert facts["errored_as_stopped_arms"]


class TestAnEmptyTurnStillReachesTheProviderChecks:
    def test_an_empty_turn_recorded_as_one_is_still_read_as_truncated(self):
        """Collected since v287 an empty turn is recorded as "empty_turn";
        one the provider cut off is still a truncation."""
        facts = _facts((EMPTY, "length", "empty_turn"))
        assert facts["truncated_as_stopped_arms"]
