"""
The first episode of a batch is checked for reasoning that never arrived, and
the operator is asked whether to go on - with nothing collected meanwhile.
"""

import contextlib
import io
import tempfile
import threading
import types

import subversionbench.hidden_reasoning as hidden
import subversionbench.runner as runner
from conftest import batch_episode
from subversionbench.config import DEFAULT_GRADER_MODEL

HIDDEN = {"reasoning_chars": 0, "token_usage": {"reasoning_tokens": 900},
          "reasoning_details": [{"turn": 1, "types": ["reasoning.encrypted"]}],
          "served_by_providers": ["a-backend"]}


@contextlib.contextmanager
def answers(*replies):
    """Stand in for the operator. Records each question asked."""
    asked = []
    queue = list(replies)

    def fake_input(prompt=""):
        asked.append(prompt)
        if not queue:
            raise EOFError
        return queue.pop(0)

    hidden.input = fake_input
    try:
        yield asked
    finally:
        del hidden.input


class TestWhatCountsAsHidden:
    def test_reasoning_tokens_with_no_text(self):
        assert hidden.reasoning_hidden({"reasoning_chars": 0,
                                        "token_usage": {"reasoning_tokens": 5}})

    def test_an_encrypted_part_with_no_text(self):
        assert hidden.reasoning_hidden({"reasoning_chars": 0, "reasoning_details": [
            {"turn": 1, "types": ["reasoning.encrypted"]}]})

    def test_returned_text_is_never_hidden(self):
        """Gemini sends an encrypted signature beside a visible trace."""
        assert not hidden.reasoning_hidden({**HIDDEN, "reasoning_chars": 40})

    def test_a_model_that_did_not_reason_is_not_asked_about(self):
        assert not hidden.reasoning_hidden({"reasoning_chars": 0, "token_usage": {
            "reasoning_tokens": 0}, "reasoning_details": []})


class TestTheQuestion:
    def test_nothing_is_asked_when_the_reasoning_arrived(self):
        with answers() as asked, contextlib.redirect_stdout(io.StringIO()):
            assert hidden.continue_despite_hidden_reasoning({"reasoning_chars": 9})
        assert asked == []

    def test_yes_continues_and_no_stops(self):
        with answers("y") as asked, contextlib.redirect_stdout(io.StringIO()):
            assert hidden.continue_despite_hidden_reasoning(HIDDEN)
        assert len(asked) == 1
        with answers("no"), contextlib.redirect_stdout(io.StringIO()):
            assert not hidden.continue_despite_hidden_reasoning(HIDDEN)

    def test_anything_else_is_asked_again(self):
        with answers("", "maybe", "Y") as asked, \
                contextlib.redirect_stdout(io.StringIO()):
            assert hidden.continue_despite_hidden_reasoning(HIDDEN)
        assert len(asked) == 3

    def test_no_answer_at_all_stops(self):
        out = io.StringIO()
        with answers(), contextlib.redirect_stdout(out):
            assert not hidden.continue_despite_hidden_reasoning(HIDDEN)
        assert "stopping" in out.getvalue()

    def test_it_says_what_it_saw(self):
        out = io.StringIO()
        with answers("y"), contextlib.redirect_stdout(out):
            hidden.continue_despite_hidden_reasoning(HIDDEN)
        assert "900" in out.getvalue() and "a-backend" in out.getvalue()


def _batch(result, runs=4, concurrency=1):
    """run_batch over a stubbed episode. Returns the exit code, how many
    episodes were started, and how many were in flight at each question."""
    started, running, in_flight_when_asked = [], [0], []
    lock = threading.Lock()

    def fake(*a, **k):
        with lock:
            started.append(1)
            running[0] += 1
        try:
            return {**batch_episode(), "transcript": [],
                    "timing": {"eval_seconds": 1, "grader_seconds": 0,
                               "total_run_seconds": 1}, **result}
        finally:
            with lock:
                running[0] -= 1

    args = types.SimpleNamespace(
        model="m", nudge="strong", effort=None, oversight=True, lure=False,
        output_dir=tempfile.mkdtemp(), runs=runs, delay=0, max_tokens=8192,
        max_turns=40, no_power=True, no_grader=True,
        grader_model=DEFAULT_GRADER_MODEL, isolation="deny-network",
        resume=None, max_consecutive_failures=3, thinking_budget=None,
        concurrency=concurrency, interrogations=("default",),
        write_back=False, batch_stamp=None, yes=False, openrouter_sort=None,
        openrouter_provider=None, use_opencode=False, capability=None)
    real_check = runner.continue_despite_hidden_reasoning

    def watched(record):
        in_flight_when_asked.append(running[0])
        return real_check(record)

    orig = runner.run_evaluation
    runner.run_evaluation = fake
    runner.continue_despite_hidden_reasoning = watched
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            code = runner.run_batch(args, "m", "sys", {}, "cfg")
    finally:
        runner.run_evaluation = orig
        runner.continue_despite_hidden_reasoning = real_check
    return code, len(started), in_flight_when_asked


class TestTheBatchWaitsForTheAnswer:
    def test_no_stops_after_the_first_episode_as_an_interrupt(self):
        """130, so run_all_arms.sh stops rather than starting the next arm."""
        with answers("n"):
            code, started, _ = _batch(HIDDEN)
        assert (code, started) == (runner.EXIT_INTERRUPTED, 1)

    def test_yes_collects_the_rest_and_asks_once(self):
        with answers("y") as asked:
            code, started, _ = _batch(HIDDEN)
        assert (code, started, len(asked)) == (0, 4, 1)

    def test_a_visible_batch_is_never_asked(self):
        with answers() as asked:
            code, started, _ = _batch({"reasoning_chars": 50})
        assert (code, started, asked) == (0, 4, [])

    def test_under_concurrency_nothing_runs_while_it_asks(self):
        with answers("n"):
            code, started, in_flight = _batch(HIDDEN, runs=6, concurrency=3)
        assert (code, started, in_flight) == (runner.EXIT_INTERRUPTED, 1, [0])

    def test_under_concurrency_yes_fills_the_pool_afterwards(self):
        with answers("y"):
            code, started, _ = _batch(HIDDEN, runs=6, concurrency=3)
        assert (code, started) == (0, 6)
