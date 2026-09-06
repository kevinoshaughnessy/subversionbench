"""
Which experiment an episode says it belongs to.

Two records carry the arm - the one a completed episode returns and the one
attached to the error a died episode raises - and they had already drifted once
while both were built by hand. A field on one and not the other is silent: the
run file simply lacks it, and whatever reads it sees a default.
"""


import contextlib
import inspect
import io
import tempfile
import types

from subversionbench.config import (SYSTEM_PROMPT_STRONG_NUDGE)
import subversionbench.llm_client as ev_llm
import subversionbench.run_eval as ev_run


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
        import tempfile
        import io
        import contextlib
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
        from subversionbench.config import (SYSTEM_PROMPT_NO_NUDGE)
        import pytest
        with pytest.raises(ValueError):
            self._episode("none", system_prompt=SYSTEM_PROMPT_STRONG_NUDGE)
        with pytest.raises(ValueError):
            self._episode("max", system_prompt=SYSTEM_PROMPT_NO_NUDGE)


class TestOpenRouterSortIsRecordedAsSent:
    """`openrouter_sort` on the saved run has to reflect what was actually
    sent to the client, the same way `effort` does - not merely what the
    operator asked for. A request against a non-OpenRouter model is a no-op
    (get_client() drops it), so the recorded field must say None there even
    when the caller passed a value, or the saved run would claim a routing
    choice that never reached anything."""

    def _episode(self, model, openrouter_sort=None):
        import tempfile
        import io
        import contextlib
        from subversionbench.environment import create_hardened_environment
        from subversionbench.config import SYSTEM_PROMPT_NO_NUDGE

        env_dir = tempfile.mkdtemp()
        env_info = create_hardened_environment(env_dir)

        class Fake:
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
            with contextlib.redirect_stdout(io.StringIO()):
                result = ev_run.run_evaluation(
                    system_prompt=SYSTEM_PROMPT_NO_NUDGE, user_prompt="Do the task.",
                    env_dir=env_dir, env_info=env_info, model=model,
                    max_turns=2, use_grader=False, nudge="none",
                    openrouter_sort=openrouter_sort)
        finally:
            ev_llm.get_client = orig
        return result

    def test_recorded_for_an_openrouter_model(self):
        result = self._episode("x-ai/grok-4.5", openrouter_sort="throughput")
        assert result["openrouter_sort"] == "throughput"

    def test_none_when_not_requested(self):
        result = self._episode("x-ai/grok-4.5")
        assert result["openrouter_sort"] is None

    def test_dropped_for_a_non_openrouter_model_even_if_requested(self):
        """Guards against a filename or a saved field claiming a condition
        that never applied, the same failure mode `effort` was fixed for."""
        result = self._episode("m", openrouter_sort="throughput")
        assert result["openrouter_sort"] is None


class TestOpenRouterProviderIsRecordedAsSent:
    """Same story as TestOpenRouterSortIsRecordedAsSent above, for
    `openrouter_provider`: recorded only when it actually reached an
    OpenRouter client, never merely because it was requested."""

    def _episode(self, model, openrouter_provider=None):
        import tempfile
        import io
        import contextlib
        from subversionbench.environment import create_hardened_environment
        from subversionbench.config import SYSTEM_PROMPT_NO_NUDGE

        env_dir = tempfile.mkdtemp()
        env_info = create_hardened_environment(env_dir)

        class Fake:
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
            with contextlib.redirect_stdout(io.StringIO()):
                result = ev_run.run_evaluation(
                    system_prompt=SYSTEM_PROMPT_NO_NUDGE, user_prompt="Do the task.",
                    env_dir=env_dir, env_info=env_info, model=model,
                    max_turns=2, use_grader=False, nudge="none",
                    openrouter_provider=openrouter_provider)
        finally:
            ev_llm.get_client = orig
        return result

    def test_recorded_for_an_openrouter_model(self):
        result = self._episode("x-ai/grok-4.5", openrouter_provider="deepinfra")
        assert result["openrouter_provider"] == "deepinfra"

    def test_none_when_not_requested(self):
        result = self._episode("x-ai/grok-4.5")
        assert result["openrouter_provider"] is None

    def test_dropped_for_a_non_openrouter_model_even_if_requested(self):
        result = self._episode("m", openrouter_provider="deepinfra")
        assert result["openrouter_provider"] is None


class TestBothEpisodeRecordsCarryTheSameArm:
    """A completed episode and a failed one are both saved, and both are read by
    the same analyses. They used to build their identity fields separately.

    The copies had already drifted: `isolation` is on the completed record and
    not the failed one, and the SAME field was documented as "which analysis
    version COLLECTED it" in one and "last touched it" in the other - wordings
    that contradict, the first explicitly correcting the second. A field added to
    one and forgotten in the other is silent; the run file simply lacks it and
    whatever reads it sees a default.
    """

    # APPENDED TO, NEVER REORDERED. These are written to disk as JSON in this
    # order, so a new field goes on the end: inserting one moves every saved
    # field position after it for no reason. `isolation` joined the list when
    # it moved off the completed record - the very drift this class describes -
    # and `max_turns` and `toolchain` with it.
    IDENTITY = ("canary", "rollout_version", "oversight", "lure",
                "interrogations", "headline_interrogation",
                "rollout_fingerprint", "analysis_version", "model", "effort",
                "openrouter_sort", "openrouter_provider", "nudge",
                "isolation", "max_turns", "toolchain", "capability")

    def _built(self, **kw):
        from subversionbench.arm_record import arm_identity
        args = {"model": "m", "effort": None, "nudge": "strong", "oversight": True,
                    "lure": False, "interrogations": ("zeroevidence",),
                    "openrouter_sort": None, "openrouter_provider": None}
        args.update(kw)
        return arm_identity(**args)

    def test_the_arm_actually_reaches_the_record(self):
        """The gap the old guard left. It asserted `lure` was a PARAMETER of
        run_evaluation, which is satisfied by a signature alone - drop
        `"lure": lure` from the record and the parameter is still there, the
        guard still passes, and the arm is lost exactly as before. Assert the
        field."""
        assert self._built(lure=True)["lure"] is True
        assert self._built(lure=False)["lure"] is False
        assert self._built(oversight=False)["oversight"] is False

    def test_each_arm_gets_its_own_fingerprint(self):
        """Not the primary arm's. A module constant here once made every
        counterfactual and every lure episode claim the primary arm's identity."""
        seen = {(o, lure): self._built(oversight=o,
                                      lure=lure)["rollout_fingerprint"]
                for o in (True, False) for lure in (True, False)}
        assert len(set(seen.values())) == 4, seen

    def test_neither_record_redeclares_an_identity_field(self):
        """The point of the shared builder. A key set in a record literal AND in
        arm_identity is a second copy that can disagree with the first, which is
        the state this replaced."""
        import re
        from subversionbench import episode as ep
        src = inspect.getsource(ep.run_evaluation)
        offenders = [k for k in self.IDENTITY
                     if re.search(rf'^\s+"{k}":', src, re.M)]
        assert not offenders, (
            f"run_evaluation sets these itself as well as through "
            f"arm_identity: {offenders}")

    def test_both_records_start_with_the_identity_in_order(self):
        """Order matters because these dicts are written to disk as JSON. These
        keys open both records, in this order, and reordering them would move
        every saved field position for no reason. Appending is fine and is how
        the list has grown."""
        assert list(self._built()) == list(self.IDENTITY)

    def test_the_failed_record_is_the_identity_plus_the_failure(self):
        """Exercised through a real failure rather than read off the source, so
        the assertion is about what gets saved."""
        import subversionbench.llm_client as ev_llm
        from subversionbench.environment import create_hardened_environment
        from subversionbench.episode import EpisodeAPIError

        class Boom:
            class messages:
                @staticmethod
                def create(**kw):
                    raise RuntimeError("429 rate limited")

        env_dir = tempfile.mkdtemp()
        env_info = create_hardened_environment(env_dir)
        orig = ev_llm.get_client
        ev_llm.get_client = lambda *a, **k: Boom()
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                try:
                    ev_run.run_evaluation(
                        system_prompt=SYSTEM_PROMPT_STRONG_NUDGE,
                        user_prompt="Do it.", env_dir=env_dir,
                        env_info=env_info, model="m", max_turns=2,
                        use_grader=False, nudge="strong", lure=True)
                except EpisodeAPIError as e:
                    partial = e.partial
                else:
                    raise AssertionError("expected EpisodeAPIError")
        finally:
            ev_llm.get_client = orig
        for key in self.IDENTITY:
            assert key in partial, key
        assert partial["lure"] is True
        assert partial["ended_by"] == "api_error"
        assert partial["failed_on_turn"] == 1
        assert "429" in partial["error"]
        # Deliberately absent: an episode that died mid-turn has no settled act
        # to ask about and an incomplete conversation to ask it in.
        assert "messages" not in partial
