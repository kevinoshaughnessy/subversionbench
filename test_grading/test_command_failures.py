"""
grading/command_failures.py: which commands visibly failed, and how.

Read off the result text because the harness keeps no exit status, so the tests
are about what each kind of result is taken to mean, and about which result
answers which command.
"""

from subversionbench.config import SANDBOX_REFUSAL
from subversionbench.grading import detect_command_failures
from subversionbench.grading.command_failures import failure_kind
from subversionbench.rederive import rederive_free_measures
from subversionbench.reporting.facts.quality import _command_failures


def _turn(turn, *pairs):
    """One turn: every call, then every result, as the runner writes them."""
    return ([{"turn": turn, "type": "tool_call", "cmd": c} for c, _ in pairs]
            + [{"turn": turn, "type": "tool_result", "result": r}
               for _, r in pairs])


class TestEachResultIsReadForWhatItMeans:
    def test_the_harness_own_results_are_their_own_kinds(self):
        assert failure_kind(SANDBOX_REFUSAL) == "refused"
        assert failure_kind("Command timed out.") == "timed_out"
        assert failure_kind("Error: [Errno 2] spawn failed") == "harness_error"

    def test_shell_diagnostics_are_errors(self):
        for result in ("cat: notes.txt: No such file or directory",
                       'sed: 1: "config/a.yaml": command c expects \\ followed by text',
                       "usage: grep [-abc] pattern",
                       "cp: cannot stat 'x': No such file or directory",
                       "mv: can't rename 'a'",
                       "bash: rg: command not found"):
            assert failure_kind(result) == "error", result

    def test_ordinary_output_is_not_a_failure(self):
        for result in ("(no output)", "total 8\ndrwxr-xr-x  data",
                       "Result: passed", "Error rates by month:\n1.2"):
            assert failure_kind(result) is None, result


class TestCommandsAreCountedAgainstTheirOwnResults:
    def test_the_second_call_of_a_turn_is_answered_by_the_second_result(self):
        transcript = _turn(1, ("ls", "data"),
                           ("cat x", "cat: x: No such file or directory"),
                           ("pwd", "/work"))
        found = detect_command_failures(transcript)
        assert (found["n_commands"], found["n_failed"]) == (3, 1)
        assert found["by_kind"]["error"] == 1

    def test_a_call_with_no_result_is_in_neither_count(self):
        transcript = _turn(1, ("ls", "data")) + [
            {"turn": 2, "type": "tool_call", "cmd": "cat missing"}]
        found = detect_command_failures(transcript)
        assert (found["n_commands"], found["n_failed"]) == (1, 0)

    def test_a_refusal_is_counted_once_as_a_refusal(self):
        found = detect_command_failures(_turn(1, ("ls /", SANDBOX_REFUSAL)))
        assert found["by_kind"] == {"refused": 1, "timed_out": 0,
                                    "harness_error": 0, "error": 0}


class TestSavedEpisodesAreBackfilled:
    def test_rederive_fills_an_analysis_saved_without_it(self):
        analysis = {}
        rederive_free_measures(analysis, _turn(1, ("cat x", "Command timed out.")))
        assert analysis["command_failures"]["by_kind"]["timed_out"] == 1

    def test_without_a_transcript_a_stored_count_is_left_alone(self):
        stored = {"n_commands": 4, "n_failed": 1, "by_kind": {"error": 1}}
        analysis = {"command_failures": stored}
        rederive_free_measures(analysis, [])
        assert analysis["command_failures"] is stored


class TestTheBatchRateIsPooledOverCommands:
    def _result(self, n_commands, n_failed):
        return {"analysis": {"command_failures": {
            "n_commands": n_commands, "n_failed": n_failed,
            "by_kind": {"error": n_failed}}}}

    def test_pooled_rather_than_averaged_and_unrecorded_left_out(self):
        pooled = _command_failures([self._result(2, 2), self._result(38, 2),
                                    {"analysis": {}}])
        assert (pooled["n_commands"], pooled["n_failed"]) == (40, 4)
        assert pooled["rate"] == 0.1
        assert pooled["by_kind"] == {"error": 4}

    def test_a_batch_with_nothing_recorded_has_no_rate(self):
        assert _command_failures([{"analysis": {}}])["rate"] is None
