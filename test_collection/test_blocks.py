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

class TestWhatKindOfReasoningCameBack:
    """`reasoning_chars` says how MUCH reasoning arrived. It cannot say whether
    what arrived was a full trace or a compressed summary, and both awareness
    measures read the difference. reasoning_details is the provider's own answer,
    which is why it is recorded rather than inferred from the model ID."""

    def test_the_type_is_kept(self):
        from subversionbench.blocks import _reasoning_detail_summary
        out = _reasoning_detail_summary([
            {"type": "reasoning.text", "text": "hello"},
            {"type": "reasoning.text", "text": "again"},
        ])
        assert out["types"] == ["reasoning.text"]
        assert out["n_parts"] == 2
        assert out["chars"] == 10

    def test_a_summary_is_distinguishable_from_a_trace(self):
        """The whole reason this field is captured: these two produce identical
        thinking blocks and identical character counts."""
        from subversionbench.blocks import _reasoning_detail_summary
        trace = _reasoning_detail_summary(
            [{"type": "reasoning.text", "text": "x" * 40}])
        summary = _reasoning_detail_summary(
            [{"type": "reasoning.summary", "summary": "x" * 40}])
        assert trace["chars"] == summary["chars"] == 40
        assert trace["types"] != summary["types"]

    def test_an_encrypted_payload_is_labelled_not_stored(self):
        """An encrypted part is opaque - no measure here can read it - so it is
        counted and named, and its blob is not copied into the run file."""
        from subversionbench.blocks import _reasoning_detail_summary
        out = _reasoning_detail_summary(
            [{"type": "reasoning.encrypted", "data": "AQID" * 500}])
        assert out["types"] == ["reasoning.encrypted"]
        assert out["chars"] == 2000
        assert "AQID" not in repr(out)

    def test_mixed_types_are_all_reported(self):
        from subversionbench.blocks import _reasoning_detail_summary
        out = _reasoning_detail_summary([
            {"type": "reasoning.summary", "summary": "s"},
            {"type": "reasoning.encrypted", "data": "d"},
        ])
        assert out["types"] == ["reasoning.summary", "reasoning.encrypted"]
        assert out["n_parts"] == 2

    def test_the_shape_that_arrived_is_recorded(self):
        """The SDK has no model for this field, so the keys are worth keeping:
        a documented shape that grows should be visible in the data, not
        silently dropped by an allowlist written today."""
        from subversionbench.blocks import _reasoning_detail_summary
        out = _reasoning_detail_summary(
            [{"type": "reasoning.text", "text": "t", "id": "r_1",
              "index": 0, "format": "anthropic-claude-v1"}])
        assert out["keys"] == ["format", "id", "index", "text", "type"]
        assert out["formats"] == ["anthropic-claude-v1"]

    def test_absent_and_empty_are_both_nothing(self):
        """A route that never reports the field and a response that reported an
        empty list both mean "no label", and neither is an error."""
        from subversionbench.blocks import _reasoning_detail_summary
        assert _reasoning_detail_summary(None) == {}
        assert _reasoning_detail_summary([]) == {}

    def test_a_read_only_diagnostic_never_raises(self):
        """It must not be the thing that fails a paid episode. Objects rather
        than dicts, and unreadable input, both have to come back as data."""
        import types
        from subversionbench.blocks import _reasoning_detail_summary
        assert _reasoning_detail_summary(7) == {}
        out = _reasoning_detail_summary(
            [types.SimpleNamespace(type="reasoning.text", text="ab")])
        assert out == {"n_parts": 1, "chars": 2, "types": ["reasoning.text"]}

    def test_the_response_carries_it_beside_usage(self):
        """On _Response rather than on the thinking block: it describes the
        message, and the block goes back to the API while this only gets saved."""
        from subversionbench.blocks import _Response
        assert _Response([]).reasoning_details == {}
        assert _Response([], reasoning_details={"n_parts": 1}
                         ).reasoning_details == {"n_parts": 1}


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


class TestNothingInAConversationCanStopItBeingSaved:
    """The transcript is the only record of what the model did, and it is
    written after the episode has been paid for. Every fallback below exists
    so that an object shape this harness did not anticipate costs its own
    fidelity and nothing else - a raise here loses the whole episode.
    """

    def test_a_model_dump_that_rejects_mode_is_called_the_old_way(self):
        """pydantic v1's model_dump takes no `mode` keyword. Some providers'
        SDKs are still on it, so the newer call is tried first and the older
        one is the fallback rather than the other way round."""
        from subversionbench.blocks import serialise_messages

        class OldPydantic:
            def model_dump(self, **kwargs):
                if kwargs:
                    raise TypeError("model_dump() got an unexpected keyword")
                return {"type": "thinking", "signature": "SIG-old"}

        out = serialise_messages(
            [{"role": "assistant", "content": [OldPydantic()]}])
        assert out[0]["content"][0] == {"type": "thinking",
                                        "signature": "SIG-old"}

    def test_an_object_with_no_attributes_becomes_its_string_form(self):
        """A slotted or C-implemented block has neither model_dump nor
        __dict__. str() of it is a poor record and a great deal better than
        the exception."""
        from subversionbench.blocks import serialise_messages

        class Slotted:
            __slots__ = ()

            def __str__(self):
                return "<opaque block>"

        out = serialise_messages(
            [{"role": "assistant", "content": [Slotted()]}])
        assert out[0]["content"][0] == "<opaque block>"

    def test_a_message_that_is_not_a_dict_is_still_recorded(self):
        """Every message this harness builds is a dict. An SDK that hands back
        its own message object is not, and dropping it would leave a gap in
        the transcript that reads as a turn the model never took."""
        from subversionbench.blocks import serialise_messages

        class Message:
            def model_dump(self, mode=None):
                return {"role": "assistant", "content": "from the SDK"}

        out = serialise_messages([{"role": "user", "content": "hi"},
                                  Message()])
        assert len(out) == 2, "a non-dict message was dropped from the record"
        assert out[1] == {"role": "assistant", "content": "from the SDK"}
