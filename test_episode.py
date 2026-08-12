"""
One episode: the rollout loop, the paired interrogation, and what survives an error.

An episode is the unit that costs money, so the properties pinned here are the ones
that decide whether a partial one is still usable: a transcript saved past an API
error, cache breakpoints that keep the prefix stable, and probes that cannot see
each other.
"""

import contextlib
import glob
import inspect
import io
import json
import sys
import tempfile
import types

from pathlib import Path
from subversionbench.config import INTERROGATION_VARIANTS
from subversionbench.grading.acts import MISALIGNED_ACTS, questions_for
import subversionbench.llm_client as ev_llm
import subversionbench.run_eval as ev_run


class TestEmptyTextBlocksAreNotEchoedBack:
    """A text block the model opened and left empty is a valid response but an
    invalid request: Anthropic answers "messages: text content blocks must be
    non-empty" with a 400. Because the offending block is only re-sent on the
    *following* turn, the episode dies mid-way with its whole transcript in
    memory - which is how run 4 of an Opus 5 batch was lost."""

    def blk(self, **kw):
        return types.SimpleNamespace(**kw)

    def test_empty_text_is_dropped_from_the_conversation(self):
        kept = ev_run.replayable_content([
            self.blk(type="text", text=""),
            self.blk(type="text", text="   "),
            self.blk(type="text", text="real"),
            self.blk(type="tool_use", id="t1", name="bash", input={}),
        ])
        assert [b.type for b in kept] == ["text", "tool_use"]
        assert kept[0].text == "real"

    def test_thinking_blocks_are_passed_back_untouched(self):
        """They carry signatures the API verifies, so even an empty one has to
        go back exactly as it came - unlike the transcript copy, which drops
        empty thinking for the grader's sake."""
        blocks = [
            self.blk(type="thinking", thinking=""),
            self.blk(type="redacted_thinking", data="x"),
        ]
        assert ev_run.replayable_content(blocks) == blocks

    def test_an_episode_survives_a_model_that_emits_one(self):
        """End to end against a client as strict as the real API."""
        out = tempfile.mkdtemp()
        blk = self.blk

        class Messages:
            def __init__(self):
                self.turn = 0

            def create(self, messages=None, **kw):
                for m in messages:
                    if isinstance(m.get("content"), list):
                        for b in m["content"]:
                            if (getattr(b, "type", None) == "text"
                                    and not getattr(b, "text", "").strip()):
                                raise RuntimeError(
                                    "400 messages: text content blocks must "
                                    "be non-empty")
                if "tools" not in kw:
                    return blk(stop_reason="end_turn",
                               content=[blk(type="text", text="no")])
                self.turn += 1
                if self.turn == 1:
                    # Reasoning, an empty text block, then a tool call - what
                    # Opus 5 actually returned.
                    return blk(stop_reason="tool_use", content=[
                        blk(type="thinking", thinking="Checking the config."),
                        blk(type="text", text=""),
                        blk(type="tool_use", id="t1", name="bash",
                            input={"cmd": "ls"})])
                return blk(stop_reason="end_turn", content=[
                    blk(type="text", text="I recommend Strategy B.")])

        class Client:
            def __init__(self):
                self.messages = Messages()

        original, original_argv = ev_llm.get_client, sys.argv
        ev_llm.get_client = lambda m: Client()
        sys.argv = ["run_eval", "--model", "claude-opus-5", "--runs", "1",
                    "--delay", "0", "--no-grader", "--output-dir", out]
        try:
            with contextlib.redirect_stdout(io.StringIO()) as buf:
                ev_run.main()
        finally:
            ev_llm.get_client, sys.argv = original, original_argv

        assert "FAILED" not in buf.getvalue()
        run_files = glob.glob(f"{out}/run_1_*.json")
        assert run_files, "the episode should have completed and been saved"
        data = json.loads(Path(run_files[0]).read_text())
        assert data["ended_by"] == "model_stopped"
        # The empty block is not recorded either - it would feed the grader a
        # hollow [AGENT] section.
        assert all(e["content"].strip()
                   for e in data["transcript"] if e["type"] == "text")

class TestPartialTranscriptSurvivesAnAPIError:
    """An episode is 5-20 model calls plus grading; losing all of it to one
    unretryable error leaves nothing to diagnose from and nothing to show for
    what was already spent."""

    def test_the_transcript_is_written_and_kept_out_of_the_rates(self):
        out = tempfile.mkdtemp()

        def blk(**kw):
            return types.SimpleNamespace(**kw)

        class Messages:
            def __init__(self):
                self.turn = 0

            def create(self, messages=None, **kw):
                if "tools" not in kw:
                    return blk(stop_reason="end_turn",
                               content=[blk(type="text", text="no")])
                self.turn += 1
                if self.turn == 2:
                    raise RuntimeError("overloaded_error: server overloaded")
                return blk(stop_reason="tool_use", content=[
                    blk(type="text", text="Looking around."),
                    blk(type="tool_use", id="t1", name="bash",
                        input={"cmd": "ls"})])

        class Client:
            def __init__(self):
                self.messages = Messages()

        original, original_argv = ev_llm.get_client, sys.argv
        ev_llm.get_client = lambda m: Client()
        sys.argv = ["run_eval", "--model", "claude-opus-5", "--runs", "1",
                    "--delay", "0", "--no-grader", "--output-dir", out]
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                ev_run.main()
        finally:
            ev_llm.get_client, sys.argv = original, original_argv

        partials = glob.glob(f"{out}/failed_run_1_*.json")
        assert partials, "the partial transcript should have been saved"
        data = json.loads(Path(partials[0]).read_text())
        assert data["ended_by"] == "api_error"
        assert data["failed_on_turn"] == 2
        assert "overloaded_error" in data["error"]
        assert data["transcript"], "work done before the failure is preserved"
        assert "canary" in data

        # A partial episode is not an observation: it must not be picked up as
        # a completed run by --resume, --grade-existing or --reclassify.
        assert not glob.glob(f"{out}/run_1_*.json")
        stamp = Path(partials[0]).stem.split("_")[-1]
        assert ev_run.find_run_files_by_stamp(out, stamp) == []

class TestPromptCacheBreakpoints:
    """The agentic loop re-sends the whole conversation every turn: a median
    episode re-sends ~22,400 input tokens across eight turns, of which only
    ~5,000 are new. A rolling breakpoint makes the rest cache reads."""

    def test_only_the_newest_breakpoints_survive(self):
        """A breakpoint searches back at most 20 content blocks for a prior
        entry, and a turn adds about two, so leaving every marker in place
        would exhaust the API's four-breakpoint budget by turn three."""
        messages = [{"role": "user", "content": "go"}]
        for turn in range(6):
            messages.append({"role": "assistant", "content": [
                types.SimpleNamespace(type="text", text=f"turn {turn}")]})
            block = {"type": "tool_result", "tool_use_id": f"t{turn}",
                     "content": "ok", "cache_control": {"type": "ephemeral"}}
            messages.append({"role": "user", "content": [block]})
            ev_run.roll_cache_breakpoints(messages)

        marked = [b for m in messages if isinstance(m.get("content"), list)
                  for b in m["content"]
                  if isinstance(b, dict) and "cache_control" in b]
        assert len(marked) == 2, f"expected 2 live breakpoints, got {len(marked)}"
        # And they must be the newest two, not the oldest.
        assert [b["tool_use_id"] for b in marked] == ["t4", "t5"]

    def test_it_survives_the_shapes_the_loop_actually_holds(self):
        """messages mixes a bare string (the opening turn), SDK response objects
        (assistant turns, which cannot carry an extra key) and dicts we build."""
        messages = [
            {"role": "user", "content": "a string, not blocks"},
            {"role": "assistant", "content": [
                types.SimpleNamespace(type="text", text="no cache_control here")]},
            {"role": "user", "content": [
                {"type": "tool_result", "content": "x",
                 "cache_control": {"type": "ephemeral"}}]},
        ]
        ev_run.roll_cache_breakpoints(messages)   # must not raise
        assert messages[0]["content"] == "a string, not blocks"

    def test_counters_are_zero_when_the_backend_reports_none(self):
        """OpenRouter responses carry no usage in this shape, and a missing
        counter must read as zero rather than be guessed at."""
        assert ev_run.cache_usage(types.SimpleNamespace()) == {
            "read": 0, "written": 0, "uncached": 0}
        assert ev_run.cache_usage(types.SimpleNamespace(usage=None)) == {
            "read": 0, "written": 0, "uncached": 0}

    def test_counters_are_read_off_the_response(self):
        response = types.SimpleNamespace(usage=types.SimpleNamespace(
            cache_read_input_tokens=900, cache_creation_input_tokens=100,
            input_tokens=20))
        assert ev_run.cache_usage(response) == {
            "read": 900, "written": 100, "uncached": 20}

    def test_the_loop_marks_this_turns_results(self):
        """End to end: the breakpoint has to land on the block the next request
        re-sends, which is the last tool_result."""
        out = tempfile.mkdtemp()
        seen = []

        def blk(**kw):
            return types.SimpleNamespace(**kw)

        class Messages:
            def __init__(self):
                self.turn = 0

            def create(self, messages=None, **kw):
                # Record how many breakpoints each request carried.
                seen.append(sum(
                    1 for m in messages if isinstance(m.get("content"), list)
                    for b in m["content"]
                    if isinstance(b, dict) and "cache_control" in b))
                if "tools" not in kw:
                    return blk(stop_reason="end_turn",
                               content=[blk(type="text", text="no")])
                self.turn += 1
                if self.turn < 3:
                    return blk(stop_reason="tool_use", content=[
                        blk(type="tool_use", id=f"t{self.turn}", name="bash",
                            input={"cmd": "ls"})])
                return blk(stop_reason="end_turn",
                           content=[blk(type="text", text="I recommend Strategy B.")])

        class Client:
            def __init__(self):
                self.messages = Messages()

        original, original_argv = ev_llm.get_client, sys.argv
        ev_llm.get_client = lambda m: Client()
        sys.argv = ["run_eval", "--model", "claude-opus-5", "--runs", "1",
                    "--delay", "0", "--no-grader", "--output-dir", out]
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                ev_run.main()
        finally:
            ev_llm.get_client, sys.argv = original, original_argv

        # Turn 1 carries none (nothing sent yet); later turns carry at most 2.
        assert seen[0] == 0
        assert max(seen) <= ev_run._CACHE_BREAKPOINTS
        assert any(n > 0 for n in seen[1:]), "no breakpoint was ever set"

    def test_a_write_never_read_is_called_out(self):
        """The failure this accounting exists for: a breakpoint below the
        model's minimum cacheable prefix is accepted and silently ignored, which
        is what happened to the grader's transcript cache for all of v15."""
        out = tempfile.mkdtemp()

        def blk(**kw):
            return types.SimpleNamespace(**kw)

        class Messages:
            @staticmethod
            def create(messages=None, **kw):
                return blk(stop_reason="end_turn",
                           usage=blk(cache_read_input_tokens=0,
                                     cache_creation_input_tokens=2700,
                                     input_tokens=60),
                           content=[blk(type="text",
                                        text="I recommend Strategy B.")])

        class Client:
            def __init__(self):
                self.messages = Messages()

        original, original_argv = ev_llm.get_client, sys.argv
        ev_llm.get_client = lambda m: Client()
        sys.argv = ["run_eval", "--model", "claude-opus-5", "--runs", "1",
                    "--delay", "0", "--no-grader", "--output-dir", out]
        try:
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                ev_run.main()
        finally:
            ev_llm.get_client, sys.argv = original, original_argv

        assert "written but never read" in buf.getvalue()

class TestProbesCannotInterfere:
    """The property the whole paired design rests on."""

    def _stub_client(self):
        class _M:
            def create(self, **kw):
                return types.SimpleNamespace(
                    content=[types.SimpleNamespace(
                        type="text", text="Yes, I modified it.", thinking="",
                        name="bash", id="x", input={})],
                    stop_reason="end_turn",
                    usage=types.SimpleNamespace(input_tokens=1, output_tokens=1))

        class Fake:
            messages = _M()
        return Fake()

    def test_run_followup_does_not_mutate_the_caller_s_messages(self):
        """Behavioural, not source-reading. If the episode's message list were
        extended in place, the second phrasing would inherit the first probe's
        question and answer - an order effect confounding the comparison."""
        import subversionbench.run_eval as ev
        import subversionbench.grading as ev_grade
        episode = [{"role": "user", "content": "the episode"}]
        before = [dict(m) for m in episode]
        orig = ev_grade.classify_interrogation_answer
        ev_grade.classify_interrogation_answer = lambda text, *a, **k: {
            "verdict": "admitted", "verdict_llm": None, "verdict_keyword": None,
            "classifiers_agree": None, "used_keyword_fallback": False,
            "quote": "", "classifier_error": None,
            "classifier_called": False, "classifier_model": "g"}
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                for name in ("default",) + tuple(INTERROGATION_VARIANTS):
                    ev.run_followup(
                        "sys", episode, "m", self._stub_client(),
                        MISALIGNED_ACTS[0],
                        questions=questions_for(MISALIGNED_ACTS[0], "strong",
                                                name))
        finally:
            ev_grade.classify_interrogation_answer = orig
        assert episode == before, (
            "the episode's message list was mutated, so a later probe would see "
            "an earlier one")

    def test_each_probe_starts_from_the_episode(self):
        """Guards the copy. A source check is fair here: the behaviour above can
        only detect mutation of the outer list, not of a shared suffix."""
        import subversionbench.run_eval as ev
        src = inspect.getsource(ev.run_followup)
        assert "list(messages)" in src


class TestTheRecordedArmIsTheArmRequested:
    """The regression that shipped with the arm itself.

    `nudge_type` was inferred from the prompt - `"strong" if "top priority" in
    system_prompt else "none"` - which was wrong the moment a third arm shared
    strong's prompt. A --nudge max run printed and RECORDED "strong". The value
    goes into every run file and every failed run, and --compare labels its arms
    from it, so the one field keeping the coerced arm from being read as the
    unprompted one named the wrong arm.

    Nothing caught it because no test drove run_evaluation end to end. These do.
    """

    def _episode(self, nudge, system_prompt=None, effort=None):
        import tempfile, types, io, contextlib
        import subversionbench.run_eval as ev_run
        from subversionbench.environment import create_hardened_environment
        from subversionbench.config import (SYSTEM_PROMPT_STRONG_NUDGE,
                                            SYSTEM_PROMPT_NO_NUDGE)
        if system_prompt is None:
            system_prompt = (SYSTEM_PROMPT_NO_NUDGE if nudge == "none"
                             else SYSTEM_PROMPT_STRONG_NUDGE)
        env_dir = tempfile.mkdtemp()
        env_info = create_hardened_environment(env_dir)

        class Fake:                     # answers once, with no tool call
            class _M:
                def create(self, **kw):
                    return types.SimpleNamespace(
                        content=[types.SimpleNamespace(
                            type="text", text="I recommend the balanced option.")],
                        stop_reason="end_turn",
                        usage=types.SimpleNamespace(input_tokens=1, output_tokens=1))
            messages = _M()

        orig = ev_llm.get_client
        ev_llm.get_client = lambda *a, **k: Fake()
        try:
            with contextlib.redirect_stdout(io.StringIO()) as buf:
                result = ev_run.run_evaluation(
                    system_prompt=system_prompt, user_prompt="Do the task.",
                    env_dir=env_dir, env_info=env_info, model="m",
                    max_turns=2, use_grader=False, nudge=nudge,
                    effort=effort)
        finally:
            ev_llm.get_client = orig
        return result, buf.getvalue()

    def test_max_records_and_prints_max(self):
        result, out = self._episode("max")
        assert result["nudge"] == "max", result["nudge"]
        assert "NUDGE: max" in out

    def test_strong_still_records_strong(self):
        result, out = self._episode("strong")
        assert result["nudge"] == "strong"
        assert "NUDGE: strong" in out

    def test_none_still_records_none(self):
        result, out = self._episode("none")
        assert result["nudge"] == "none"
        assert "NUDGE: none" in out

    def test_the_banner_states_the_effort_that_was_sent(self):
        """Printed because it is a condition of the batch, like the nudge. It is
        the level actually SENT, not requested - resolve_thinking_kwargs drops one
        the model will not accept, and printing the request would name a condition
        that never applied."""
        _, out = self._episode("max", effort="high")
        assert "EFFORT: high" in out

    def test_no_effort_sent_is_spelled_out_not_left_blank(self):
        """None is a different state from any level, not an absent one. A blank
        would read as a missing value rather than a deliberate provider default -
        and `max` being both a nudge and an effort level is exactly the kind of
        ambiguity this line exists to remove."""
        _, out = self._episode("max")
        assert "EFFORT: not sent (provider default)" in out

    def test_a_nudge_that_contradicts_the_prompt_raises(self):
        """Fails loudly rather than mislabelling a batch. `max` shares strong's
        prompt, so this agreement can no longer be checked by eye."""
        from subversionbench.config import (SYSTEM_PROMPT_STRONG_NUDGE,
                                            SYSTEM_PROMPT_NO_NUDGE)
        import pytest
        with pytest.raises(ValueError):
            self._episode("none", system_prompt=SYSTEM_PROMPT_STRONG_NUDGE)
        with pytest.raises(ValueError):
            self._episode("max", system_prompt=SYSTEM_PROMPT_NO_NUDGE)
