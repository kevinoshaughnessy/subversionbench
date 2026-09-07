"""
The rollout loop: what the model was sent, what came back, and what survives an
error.

An episode is the unit that costs money, so the properties pinned here are the
ones that decide whether a partial one is still usable: a transcript saved past
an API error, cache breakpoints that keep the prefix stable, and blocks the API
returned as placeholders that must not be recorded as content.
"""


import contextlib
import glob
import io
import json
import sys
import tempfile
import types

from pathlib import Path
from subversionbench.config import (SYSTEM_PROMPT_STRONG_NUDGE)
import subversionbench.blocks as ev_blocks
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
        ev_llm.get_client = lambda m, **_kw: Client()
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
        ev_llm.get_client = lambda m, **_kw: Client()
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
        """A response with no usage record at all reports zeros rather than
        guesses.

        This used to say "OpenRouter responses carry no usage in this shape",
        which was the belief that let the cache counters read zero on every
        non-native episode for versions. They do carry one - as a dict, under
        other names - see TestTheCacheCountersAreReadOnEveryRoute below.
        """
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
        ev_llm.get_client = lambda m, **_kw: Client()
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
        ev_llm.get_client = lambda m, **_kw: Client()
        sys.argv = ["run_eval", "--model", "claude-opus-5", "--runs", "1",
                    "--delay", "0", "--no-grader", "--output-dir", out]
        try:
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                ev_run.main()
        finally:
            ev_llm.get_client, sys.argv = original, original_argv

        assert "written but never read" in buf.getvalue()


class TestTheLoopGuardsTheRequestAndNothingElse:
    def test_a_sandbox_failure_is_not_reported_as_an_api_error(self):
        """Only `client.messages.create` sits inside the try. A harness fault
        from the shell must propagate as itself - folding it into
        EpisodeAPIError would file a broken sandbox as a provider outage, and
        the batch runner treats those differently."""
        import subversionbench.llm_client as ev_llm
        from subversionbench import episode as ep
        from subversionbench.environment import create_hardened_environment
        from subversionbench.episode import EpisodeAPIError
        from subversionbench.config import SYSTEM_PROMPT_STRONG_NUDGE
        import subversionbench.run_eval as ev_run

        class Calls:
            class messages:
                @staticmethod
                def create(**kw):
                    return types.SimpleNamespace(
                        content=[types.SimpleNamespace(
                            type="tool_use", id="t1", input={"command": "ls"})],
                        stop_reason="tool_use",
                        usage=types.SimpleNamespace(input_tokens=1,
                                                    output_tokens=1))

        env_dir = tempfile.mkdtemp()
        env_info = create_hardened_environment(env_dir)
        orig_client, orig_tool = ev_llm.get_client, ep.execute_tool_sandboxed
        ev_llm.get_client = lambda *a, **k: Calls()

        def broken(*a, **k):
            raise OSError("sandbox-exec is missing")

        ep.execute_tool_sandboxed = broken
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                try:
                    ev_run.run_evaluation(
                        system_prompt=SYSTEM_PROMPT_STRONG_NUDGE,
                        user_prompt="Do it.", env_dir=env_dir,
                        env_info=env_info, model="m", max_turns=2,
                        use_grader=False, nudge="strong")
                except EpisodeAPIError as e:
                    raise AssertionError(
                        "a sandbox fault was reported as an API error") from e
                except OSError as e:
                    assert "sandbox-exec" in str(e)
                else:
                    raise AssertionError("expected the OSError to propagate")
        finally:
            ep.execute_tool_sandboxed = orig_tool
            ev_llm.get_client = orig_client


class TestReasoningTheProviderWithheldIsRecordedAsWithheld:
    """A `redacted_thinking` block is reasoning the model produced and the
    provider's safety systems declined to show. The transcript has to carry a
    placeholder for it, because the alternative readings are both wrong: drop
    it and the turn looks like one the model did not think about, count its
    characters and the reasoning-captured figure claims text nobody has.
    """

    class _Block:
        def __init__(self, block_type, **fields):
            self.type = block_type
            for k, v in fields.items():
                setattr(self, k, v)

    def _record(self, blocks):
        transcript = []
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            from subversionbench.turns import record_turn_blocks
            _calls, chars = record_turn_blocks(
                blocks, 0, transcript, lambda s: s)
        return transcript, chars, buf.getvalue()

    def test_a_redacted_block_leaves_a_placeholder_in_the_transcript(self):
        transcript, _chars, printed = self._record(
            [self._Block("redacted_thinking", data="opaque")])
        assert transcript == [{"turn": 1, "type": "thinking",
                               "content": "[redacted]"}]
        assert "redacted by provider" in printed

    def test_it_contributes_no_reasoning_characters(self):
        """The reasoning-captured figure is what makes two batches comparable
        on awareness, and it counts text the grader can read. There is none
        here."""
        _transcript, chars, _printed = self._record(
            [self._Block("redacted_thinking", data="opaque")])
        assert chars == 0

    def test_visible_reasoning_in_the_same_turn_is_still_counted(self):
        """The control: without it both tests above would pass against a
        version that recorded no thinking at all."""
        transcript, chars, _printed = self._record([
            self._Block("thinking", thinking="a visible thought"),
            self._Block("redacted_thinking", data="opaque")])
        assert [t["content"] for t in transcript] == ["a visible thought",
                                                      "[redacted]"]
        assert chars == len("a visible thought")


class TestHowTheProviderLabelledItsOwnReasoningIsRecordedPerTurn:
    """`reasoning_details` is the router's own statement about what kind of
    reasoning it returned, and the router can change its mind mid-episode: one
    episode's turns are not guaranteed to have come back the same way. So it
    is recorded per turn rather than once, and only for the turns that
    reported it - an empty list means the field was never sent, not that the
    reasoning was unlabelled.
    """

    def _episode(self, per_turn_details):
        """`per_turn_details` is what the client reports on each turn, in
        order; None means the field is absent from that response."""
        import tempfile
        import types
        import subversionbench.run_eval as ev_run
        from subversionbench.environment import create_hardened_environment
        from subversionbench.config import SYSTEM_PROMPT_NO_NUDGE

        env_dir = tempfile.mkdtemp()
        env_info = create_hardened_environment(env_dir)
        remaining = list(per_turn_details)

        class Fake:
            class _M:
                def create(self, **kw):
                    details = remaining.pop(0) if remaining else None
                    reply = types.SimpleNamespace(
                        content=[types.SimpleNamespace(
                            type="text",
                            text="I recommend the balanced option.")],
                        stop_reason="end_turn",
                        usage=types.SimpleNamespace(input_tokens=1,
                                                    output_tokens=1))
                    if details is not None:
                        reply.reasoning_details = details
                    return reply
            messages = _M()

        orig = ev_llm.get_client
        ev_llm.get_client = lambda *a, **k: Fake()
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                return ev_run.run_evaluation(
                    system_prompt=SYSTEM_PROMPT_NO_NUDGE,
                    user_prompt="Do the task.", env_dir=env_dir,
                    env_info=env_info, model="m", max_turns=2,
                    use_grader=False, nudge="none")
        finally:
            ev_llm.get_client = orig

    def test_a_turn_that_reported_a_label_is_recorded_with_its_turn_number(self):
        result = self._episode([{"format": "anthropic", "type": "encrypted"}])
        details = result["reasoning_details"]
        assert len(details) == 1
        assert details[0]["turn"] == 1, (
            "a per-turn record with no turn number cannot be read against the "
            "turn it describes")
        assert details[0]["format"] == "anthropic"
        assert details[0]["type"] == "encrypted"

    def test_a_route_that_never_reported_one_records_an_empty_list(self):
        """Not a list of nulls: an absent field is the router saying nothing,
        which is a different claim from it saying the reasoning was
        unlabelled."""
        result = self._episode([None])
        assert result["reasoning_details"] == []


class TestHowAnEpisodeEndsIsRecorded:
    """`ended_by` names the reason a loop stopped, and two of its values had
    never been produced.

    The distinction matters downstream: an episode that stopped because the
    model returned nothing usable is not one that finished, and a rate built
    over both without saying so counts a transport-shaped failure as a
    decision the model made.
    """

    def _env(self):
        from subversionbench.environment import create_hardened_environment
        env_dir = tempfile.mkdtemp()
        return env_dir, create_hardened_environment(env_dir)

    def _client(self, responses):
        calls = []

        class _M:
            def create(self, **kw):
                calls.append(kw)
                return responses[min(len(calls) - 1, len(responses) - 1)]

        class Fake:
            messages = _M()
        return Fake(), calls

    def _run(self, responses, **over):
        env_dir, env_info = self._env()
        client, calls = self._client(responses)
        orig = ev_llm.get_client
        ev_llm.get_client = lambda *a, **k: client
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                result = ev_run.run_evaluation(
                    system_prompt=SYSTEM_PROMPT_STRONG_NUDGE,
                    user_prompt="Do the task.", env_dir=env_dir,
                    env_info=env_info, model="m", max_turns=4,
                    use_grader=False, nudge="strong",
                    isolation="deny-network", **over)
        finally:
            ev_llm.get_client = orig
        return result, buf.getvalue(), calls

    def _response(self, blocks, stop_reason="end_turn", **extra):
        return types.SimpleNamespace(
            content=blocks, stop_reason=stop_reason,
            usage=types.SimpleNamespace(input_tokens=10, output_tokens=10),
            **extra)

    def test_a_turn_with_nothing_usable_ends_the_episode_and_says_why(self):
        """No text and no tool call. Continuing would re-send a turn the API
        rejects; ending silently would look like a model that chose to stop."""
        result, text, calls = self._run([self._response([], stop_reason="length")])
        assert result["ended_by"] == "no_content"
        assert len(calls) == 1, "the loop kept asking after an empty turn"
        assert "no_content" in text or "no content" in text.lower()

    def test_a_tool_call_left_as_prose_ends_the_episode_distinctly(self):
        """A backend that ignored the tools parameter. Recorded under its own
        reason rather than as an ordinary finish, because the model DID ask to
        act and the harness could not carry it out."""
        from subversionbench.tool_parsing import _RAW_TOOL_CALL_START
        blocks = [types.SimpleNamespace(
            type="text",
            text=f"Let me look.{_RAW_TOOL_CALL_START}<tool>bash</tool>")]
        result, _text, calls = self._run([self._response(blocks)])
        assert result["ended_by"] == "raw_tool_call_text"
        assert len(calls) == 1

    def test_an_ordinary_finish_is_not_labelled_as_a_failure(self):
        """The control. Without it both tests above would pass against a loop
        that always recorded a failure reason."""
        result, _text, _calls = self._run([self._response(
            [types.SimpleNamespace(type="text", text="Recommendation: B.")])])
        assert result["ended_by"] not in ("no_content", "raw_tool_call_text")

    def test_the_serving_backend_is_recorded_per_turn(self):
        """It can differ BETWEEN turns of one episode when the router falls
        back mid-run, which is the drift `openrouter_provider` cannot show
        because that records only what was asked for."""
        first = self._response(
            [types.SimpleNamespace(type="text", text="thinking about it")],
            stop_reason="end_turn", provider="Fireworks")
        result, _text, _calls = self._run([first])
        served = result.get("served_by") or []
        assert served, "no backend was recorded at all"
        assert served[0]["provider"] == "Fireworks"
        assert served[0]["turn"] == 1

    def test_provider_token_usage_is_accumulated_across_turns(self):
        """Reported by some routes as a dict rather than the SDK's own usage
        object. Summed rather than overwritten, or a multi-turn episode
        reports only its last turn's spend."""
        blocks = [types.SimpleNamespace(type="text", text="done")]
        response = self._response(blocks)
        response.usage = {"prompt_tokens": 7, "completion_tokens": 3,
                          "note": "not an int"}
        result, _text, _calls = self._run([response])
        usage = result.get("token_usage") or {}
        assert usage.get("prompt_tokens") == 7
        assert "note" not in usage, "a non-integer field was accumulated"


class TestTheCacheCountersAreReadOnEveryRoute:
    """`cache` is the only evidence that prompt caching engaged, and it was
    blind everywhere except the native route.

    The adapters build their usage record with `blocks._reasoning_usage`, which
    returns a DICT under the OpenAI family's names, so `token_counts`'
    getattr-or-zero chain fell through on every one of them. Measured on r10:
    the `cache` counters were populated on all 120 native-Anthropic episodes
    and on none of the 3,093 others.

    `uncached: 0` beside a thousand-token prompt is the tell, and it is why a
    rename-only fix would not have been enough: the two families disagree on
    whether the input total already excludes the cached part.
    """

    def _chat(self, prompt, cached, written, completion):
        """A chat-completions response, as OpenRouter returns one."""
        usage = types.SimpleNamespace(
            prompt_tokens=prompt, completion_tokens=completion,
            total_tokens=prompt + completion,
            prompt_tokens_details=types.SimpleNamespace(
                cached_tokens=cached, cache_write_tokens=written))
        return ev_blocks._Response(
            [], ev_blocks._reasoning_usage(
                types.SimpleNamespace(usage=usage)))

    def _responses(self, inp, cached, written, out):
        """A Responses API response, as a bare `gpt-*` model returns one."""
        usage = types.SimpleNamespace(
            input_tokens=inp, output_tokens=out, total_tokens=inp + out,
            input_tokens_details=types.SimpleNamespace(
                cached_tokens=cached, cache_write_tokens=written))
        return ev_blocks._Response(
            [], ev_blocks._reasoning_usage(
                types.SimpleNamespace(usage=usage)))

    def test_chat_completions_counters_are_found(self):
        assert ev_run.cache_usage(self._chat(1000, 900, 100, 7)) == {
            "read": 900, "written": 100, "uncached": 100}

    def test_responses_api_counters_are_found(self):
        """The route a bare `gpt-*` model takes, which nests the same two
        counts under a different parent."""
        assert ev_run.cache_usage(self._responses(1000, 900, 100, 7)) == {
            "read": 900, "written": 100, "uncached": 100}

    def test_the_cached_part_is_subtracted_from_the_input_total(self):
        """THE HALF A RENAME WOULD HAVE MISSED. On these routes the input total
        INCLUDES the cached tokens, so reading it raw would report a fully
        cached prompt as entirely uncached - caching's own signal inverted."""
        counts = ev_run.cache_usage(self._chat(1000, 1000, 0, 7))
        assert counts == {"read": 1000, "written": 0, "uncached": 0}, counts

    def test_a_prompt_with_no_cache_reports_all_of_it_uncached(self):
        """The control, and the number the old code got wrong in the other
        direction: it reported zero uncached tokens for every such prompt."""
        assert ev_run.cache_usage(self._chat(1000, 0, 0, 7)) == {
            "read": 0, "written": 0, "uncached": 1000}

    def test_the_native_mapping_is_unchanged(self):
        """r9 and r10 hold values under this mapping, so it must not move.
        Its `uncached` is the raw field, because that route reports it already
        net of both cache counters."""
        native = types.SimpleNamespace(usage=types.SimpleNamespace(
            cache_read_input_tokens=900, cache_creation_input_tokens=100,
            input_tokens=20, output_tokens=7))
        assert ev_run.cache_usage(native) == {
            "read": 900, "written": 100, "uncached": 20}
        from subversionbench.usage import token_counts
        assert token_counts(native)["output"] == 7

    def test_more_cached_than_prompt_tokens_cannot_go_negative(self):
        """These feed `+=` accumulators over a whole episode, so one
        inconsistent provider report must not push a negative into them."""
        counts = ev_run.cache_usage(self._chat(100, 900, 0, 7))
        assert counts["uncached"] == 0, counts
