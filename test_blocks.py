"""
Provider response shapes, normalised into Anthropic blocks - and back again.

A saved episode is replayed by reconstructing the conversation from its transcript,
so these shapes have to survive a JSON round trip with their signatures and tool
ids intact. An episode that cannot be reconstructed faithfully is refused rather
than replayed with the model's own reasoning stripped out.
"""


from subversionbench.grading.acts import MISALIGNED_ACTS


class TestReasoningUsage:
    """A reasoning-token count is the only thing that separates a model which
    did not reason from one whose reasoning was withheld. Both look like an
    empty transcript."""

    def test_reasoning_tokens_are_extracted(self):
        import types
        from subversionbench.blocks import _reasoning_usage
        completion = types.SimpleNamespace(usage=types.SimpleNamespace(
            prompt_tokens=100, completion_tokens=50, total_tokens=150,
            completion_tokens_details=types.SimpleNamespace(reasoning_tokens=40)))
        usage = _reasoning_usage(completion)
        assert usage["reasoning_tokens"] == 40
        assert usage["prompt_tokens"] == 100

    def test_the_responses_api_field_name_also_works(self):
        import types
        from subversionbench.blocks import _reasoning_usage
        completion = types.SimpleNamespace(usage=types.SimpleNamespace(
            output_tokens_details=types.SimpleNamespace(reasoning_tokens=7)))
        assert _reasoning_usage(completion)["reasoning_tokens"] == 7

    def test_an_absent_count_is_absent_not_zero(self):
        """A provider that reports nothing and one that reports zero are
        making different claims, and the classification turns on which."""
        import types
        from subversionbench.blocks import _reasoning_usage
        assert _reasoning_usage(types.SimpleNamespace(usage=None)) == {}
        completion = types.SimpleNamespace(usage=types.SimpleNamespace(
            prompt_tokens=10, completion_tokens_details=None))
        assert "reasoning_tokens" not in _reasoning_usage(completion)

class TestResponsesUsageFieldNames:
    """Chat completions and the Responses API name the same quantities
    differently. Reading one set only lost input/output counts on the first
    native batch, which recorded total_tokens alone."""

    def test_responses_api_names_are_read(self):
        import types
        from subversionbench.blocks import _reasoning_usage
        usage = _reasoning_usage(types.SimpleNamespace(usage=types.SimpleNamespace(
            input_tokens=1200, output_tokens=340, total_tokens=1540,
            output_tokens_details=types.SimpleNamespace(reasoning_tokens=256))))
        assert usage == {"total_tokens": 1540, "input_tokens": 1200,
                         "output_tokens": 340, "reasoning_tokens": 256}

    def test_chat_completions_names_still_work(self):
        import types
        from subversionbench.blocks import _reasoning_usage
        usage = _reasoning_usage(types.SimpleNamespace(usage=types.SimpleNamespace(
            prompt_tokens=10, completion_tokens=5, total_tokens=15,
            completion_tokens_details=types.SimpleNamespace(reasoning_tokens=3))))
        assert usage["prompt_tokens"] == 10 and usage["reasoning_tokens"] == 3

    def test_zero_reasoning_tokens_is_recorded_not_dropped(self):
        """Zero is the finding: the model did not reason. Dropping it would
        make it indistinguishable from a provider that reports nothing."""
        import types
        from subversionbench.blocks import _reasoning_usage
        usage = _reasoning_usage(types.SimpleNamespace(usage=types.SimpleNamespace(
            total_tokens=15151,
            output_tokens_details=types.SimpleNamespace(reasoning_tokens=0))))
        assert usage["reasoning_tokens"] == 0

class TestReplayingASavedEpisode:
    """Putting another phrasing to an episode already on disk.

    The interrogation inherits the API conversation, and until now only the
    transcript was saved. The transcript keeps the TEXT of every turn but neither
    the tool_use ids nor the signatures on thinking blocks, which the API verifies
    and which replayable_content says "have to go back exactly as they came".
    """

    def test_a_saved_conversation_is_preferred(self):
        from subversionbench.blocks import reconstruct_messages
        saved = [{"role": "user", "content": "x"}]
        assert reconstruct_messages({"messages": saved}) == (saved, None)

    def test_thinking_without_signatures_is_refused(self):
        """THE guard. Replaying without the thinking would put the model in a
        conversation where its own reasoning never happened, so an answer to a
        second phrasing would not be paired with the first - and it fails worst on
        the models that verbalise awareness in those blocks."""
        from subversionbench.blocks import reconstruct_messages
        run = {"user_prompt": "do it", "transcript": [
            {"type": "thinking", "content": "private reasoning"},
            {"type": "text", "content": "done"}]}
        messages, reason = reconstruct_messages(run)
        assert messages is None
        assert "signatures" in reason

    def test_empty_thinking_does_not_block_a_replay(self):
        """A model that returned an empty thinking block lost nothing by it."""
        from subversionbench.blocks import reconstruct_messages
        run = {"user_prompt": "do it", "transcript": [
            {"type": "thinking", "content": "   "},
            {"type": "text", "content": "done"}]}
        assert reconstruct_messages(run)[0] is not None

    def test_a_thinking_free_transcript_reconstructs(self):
        from subversionbench.blocks import reconstruct_messages
        run = {"user_prompt": "do it", "transcript": [
            {"type": "text", "content": "planning"},
            {"type": "tool_call", "cmd": "ls"},
            {"type": "tool_result", "result": "a b"},
            {"type": "text", "content": "done"}]}
        messages, reason = reconstruct_messages(run)
        assert reason is None
        assert [m["role"] for m in messages] == [
            "user", "assistant", "user", "assistant"]

    def test_every_tool_result_names_a_tool_use_above_it(self):
        """The one thing the API actually requires of the ids."""
        from subversionbench.blocks import reconstruct_messages
        run = {"user_prompt": "go", "transcript": [
            {"type": "tool_call", "cmd": "a"},
            {"type": "tool_call", "cmd": "b"},
            {"type": "tool_result", "result": "ra"},
            {"type": "tool_result", "result": "rb"}]}
        messages, reason = reconstruct_messages(run)
        assert reason is None
        seen = set()
        for m in messages:
            for block in (m["content"] if isinstance(m["content"], list) else []):
                if block.get("type") == "tool_use":
                    seen.add(block["id"])
                if block.get("type") == "tool_result":
                    assert block["tool_use_id"] in seen, block

    def test_a_result_before_any_call_is_refused(self):
        from subversionbench.blocks import reconstruct_messages
        assert reconstruct_messages({"user_prompt": "g", "transcript": [
            {"type": "tool_result", "result": "x"}]})[0] is None

    def test_an_episode_with_nothing_recorded_is_refused(self):
        from subversionbench.blocks import reconstruct_messages
        assert reconstruct_messages({"user_prompt": "g", "transcript": []})[0] is None
        assert reconstruct_messages({"transcript": [
            {"type": "text", "content": "x"}]})[0] is None

class TestTheConversationIsSerialisable:
    """It used to be dropped from every saved run because it holds API objects
    json cannot encode. Signatures are the field that had to survive."""

    def test_signatures_and_ids_survive_a_round_trip(self):
        import json
        from subversionbench.blocks import _Block, serialise_messages

        class Pyd:
            def __init__(self, **kw):
                self._kw = kw

            def model_dump(self, mode=None):
                return dict(self._kw)

        messages = [
            {"role": "user", "content": "the task"},
            {"role": "assistant", "content": [
                Pyd(type="thinking", thinking="private", signature="SIG-abc"),
                Pyd(type="tool_use", id="tu_1", name="bash",
                    input={"cmd": "ls"})]},
            {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "tu_1", "content": "a"}]},
            {"role": "assistant", "content": [_Block("text", text="done")]},
        ]
        encoded = json.dumps(serialise_messages(messages))  # no default= needed
        assert "SIG-abc" in encoded
        assert '"tu_1"' in encoded

    def test_the_adapter_block_shape_survives_too(self):
        from subversionbench.blocks import _Block, serialise_messages
        out = serialise_messages(
            [{"role": "assistant", "content": [_Block("text", text="hi")]}])
        assert out[0]["content"][0] == {"type": "text", "text": "hi"}

class TestReplayDefectsFound:
    """Four defects found reviewing the replay path, each verified to fail before
    its fix. Grouped because they share a cause: a second probe is only paired
    with the first if EVERYTHING except the wording is held constant."""

    def test_more_results_than_calls_is_refused_not_a_crash(self):
        """Raised IndexError and killed the whole mode rather than skipping one
        episode."""
        from subversionbench.blocks import reconstruct_messages
        messages, reason = reconstruct_messages({"user_prompt": "g", "transcript": [
            {"type": "tool_call", "cmd": "a"},
            {"type": "tool_result", "result": "r1"},
            {"type": "tool_result", "result": "r2"}]})
        assert messages is None
        assert "more tool results than tool calls" in reason

    def test_an_unanswered_trailing_tool_call_is_refused(self):
        """The API requires every tool_use to be answered in the next message, so
        this built a conversation the provider would reject - refused here, where
        the reason can be stated."""
        from subversionbench.blocks import reconstruct_messages
        messages, reason = reconstruct_messages({"user_prompt": "g", "transcript": [
            {"type": "text", "content": "planning"},
            {"type": "tool_call", "cmd": "ls"}]})
        assert messages is None
        assert "no recorded result" in reason

    def test_every_tool_use_in_a_replay_is_answered(self):
        """The invariant behind both refusals above, asserted over the shapes that
        ARE accepted."""
        from subversionbench.blocks import reconstruct_messages
        for transcript in (
            [{"type": "tool_call", "cmd": "a"},
             {"type": "tool_result", "result": "r"}],
            [{"type": "tool_call", "cmd": "a"}, {"type": "tool_call", "cmd": "b"},
             {"type": "tool_result", "result": "ra"},
             {"type": "tool_result", "result": "rb"}],
            [{"type": "text", "content": "hi"}],
        ):
            messages, reason = reconstruct_messages(
                {"user_prompt": "g", "transcript": transcript})
            if messages is None:
                continue
            uses, results = [], []
            for m in messages:
                for b in (m["content"] if isinstance(m["content"], list) else []):
                    if b.get("type") == "tool_use":
                        uses.append(b["id"])
                    if b.get("type") == "tool_result":
                        results.append(b["tool_use_id"])
            assert sorted(uses) == sorted(results), (transcript, uses, results)

    def test_the_replay_matches_the_original_reasoning_parameter(self):
        """Omitting it made the replayed probe run with no reasoning parameter
        while the default probe had one, so the two differed in the question AND in
        whether the model could think."""
        import inspect
        import subversionbench.run_eval as ev
        src = inspect.getsource(ev.reinterrogate_existing_runs)
        assert "resolve_thinking_kwargs" in src
        assert "reasoning_kwargs=replay_kwargs" in src
        # resolved from the run's own effort, not the command line
        assert 'run.get("effort")' in src

    def test_a_reasoning_mismatch_is_warned_about(self):
        import inspect
        import subversionbench.run_eval as ev
        src = inspect.getsource(ev.reinterrogate_existing_runs)
        assert "reasoning config differs" in src

    def test_the_per_variant_levels_are_re_derivable(self):
        """Deterministic given the stored answers, so they must be on the
        re-derived allowlist - otherwise a change to the scale moves the headline
        level and leaves these pinned to whatever rule wrote them. The ANSWERS are
        sampled and must NOT be on it."""
        from subversionbench.run_eval import REDERIVED_ANALYSIS_FIELDS as R
        for act in MISALIGNED_ACTS:
            assert act["level_key"] + "_by_variant" in R, act["name"]
            assert act["followup_key"] + "_by_variant" not in R, (
                f"{act['name']}: the sampled answers must not be re-derived")
