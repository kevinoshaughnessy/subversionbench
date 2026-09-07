"""
What the host contributed to an episode, and what must never be recorded
alongside it.

Two properties, and the second is a publication constraint rather than a
measurement one.

THE HOST IS RECORDED. Two episodes with identical rollout fingerprints can
have run under different shells, different coreutils and different kernel
isolation mechanisms, and this repository has already had defects that were
invisible on one platform and real on the other. None of that changes the arm,
so none of it is hashed; all of it changes what a command DID, so all of it is
recorded.

NOTHING IDENTIFYING IS RECORDED. Results are meant to be pasteable into a
write-up without redaction. A field that needs redacting before publication is
one that will eventually be published unredacted, so the hostname, the
username and every path stay out by construction rather than by being scrubbed
later.
"""

import getpass
import json
import os
import platform

from subversionbench import episode as episode_mod
from subversionbench import hostenv
from subversionbench.arm_record import arm_identity
from subversionbench.config import DEFAULT_INTERROGATION
from subversionbench.isolation import DEFAULT_ISOLATION, active_mechanism


def _served_keys(record: dict) -> dict:
    """Just the three served-by fields, for comparing a record against the
    owner's output without dragging the other thirty keys in."""
    return {k: v for k, v in record.items() if k.startswith("served_by")}


class TestNothingIdentifyingIsRecorded:
    """The publication constraint. Checked against this machine's real
    identifiers rather than against a pattern, so it fails on the actual thing
    it is trying to keep out."""

    def _identifiers(self):
        out = {platform.node(), os.path.expanduser("~")}
        try:
            out.add(getpass.getuser())
        except Exception:      # noqa: BLE001 - no user on some CI images
            pass
        return {v for v in out if v and len(v) > 2}

    def test_the_toolchain_record_names_no_host_or_user(self):
        blob = json.dumps(hostenv.toolchain_facts())
        for identifier in self._identifiers():
            assert identifier not in blob, identifier

    def test_the_hostname_is_not_recorded_even_though_platform_offers_it(self):
        """platform.node() sits one call away from everything else here, so
        its absence is a decision and is asserted as one."""
        facts = hostenv.toolchain_facts()
        assert platform.node() not in facts.values()
        assert not any("node" in k or "host" in k for k in facts)

    def test_no_value_looks_like_a_filesystem_path(self):
        """A version banner that embedded a build path would carry the
        builder's directory layout into every run file."""
        for key, value in hostenv.toolchain_facts().items():
            if not isinstance(value, str):
                continue
            assert not value.startswith("/"), (key, value)
            assert os.path.expanduser("~") not in value, (key, value)


class TestTheHostIsActuallyDescribed:
    def test_every_field_is_populated_on_this_host(self):
        """A probe that silently returned None everywhere would satisfy the
        privacy tests above perfectly and record nothing at all."""
        facts = hostenv.toolchain_facts()
        for key in ("platform", "platform_release", "machine", "python",
                    "isolation_mechanism"):
            assert facts[key], key

    def test_a_missing_tool_reads_as_unknown_rather_than_empty(self):
        """None says "this host did not answer"; an empty string would read as
        "this host reported nothing", which is a different fact."""
        assert hostenv._first_line(["definitely-not-a-real-binary-xyz"]) is None

    def test_the_shell_probed_is_the_one_the_sandbox_uses(self):
        """wrap_command runs `/bin/sh -c`. Probing $SHELL instead would record
        the operator's interactive shell, which executed nothing."""
        import inspect
        assert '"/bin/sh"' in inspect.getsource(hostenv.shell_version)

    def test_the_mechanism_matches_what_this_platform_would_use(self):
        got = active_mechanism(DEFAULT_ISOLATION)
        if platform.system() == "Darwin":
            assert got in ("sandbox-exec", "unavailable")
        else:
            assert got in ("bwrap", "unshare", "unavailable")

    def test_the_mechanism_is_not_the_policy(self):
        """`isolation` already records the policy and reads the same on every
        host; this field exists because the mechanism does not."""
        assert active_mechanism("deny-network") not in ("deny-network",
                                                        "deny-external")


class TestTheEpisodeRecordCarriesTheScaffold:
    """Both records - the completed one and the one attached to a mid-turn
    failure - come from arm_identity, which is why these fields go there. The
    two had already drifted once on `isolation`."""

    def _record(self, **kw):
        return arm_identity("m", None, "strong", True, False, ["zeroevidence"],
                            None, None, **kw)

    def test_max_turns_is_recorded(self):
        """An episode that ended because the model stopped and one that ran out
        of turns are different observations. `ended_by` says which; nothing said
        what the limit was, so a batch collected at another cap was
        indistinguishable."""
        assert self._record(max_turns=40)["max_turns"] == 40
        assert self._record(max_turns=8)["max_turns"] == 8

    def test_isolation_is_on_the_shared_record_not_just_the_completed_one(self):
        assert self._record(isolation="deny-external")["isolation"] == \
            "deny-external"

    def test_the_toolchain_is_recorded_per_episode(self):
        record = self._record(max_turns=40)
        assert record["toolchain"]["platform"] == platform.system()

    ARM = {"model": "m", "nudge": "strong", "lure": True, "max_turns": 2,
           "use_grader": False}

    def _two_episode_records(self) -> tuple:
        """The record a completed episode returns, and the one a died one raises.

        Both from the same arm, so the two are directly comparable. This test
        counted "**arm_identity(" in episode.py's source until the identity's
        eleven arguments were bound once and both call sites became "**arm()",
        at which point it failed while the property held better than before.
        And a count of call sites was never the property anyway: two calls to
        one function with DIFFERENT arguments produce exactly the drift the
        function exists to prevent, and would have counted as two.
        """
        import contextlib
        import io
        import tempfile
        import types

        import subversionbench.llm_client as ev_llm
        from subversionbench.environment import create_hardened_environment
        from subversionbench.episode import EpisodeAPIError, run_evaluation
        from subversionbench.config import SYSTEM_PROMPT_STRONG_NUDGE

        def episode(client):
            env_dir = tempfile.mkdtemp()
            env_info = create_hardened_environment(env_dir)
            real = ev_llm.get_client
            ev_llm.get_client = lambda *a, **k: client
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    return run_evaluation(
                        system_prompt=SYSTEM_PROMPT_STRONG_NUDGE,
                        user_prompt="Do it.", env_dir=env_dir,
                        env_info=env_info, **self.ARM)
            finally:
                ev_llm.get_client = real

        def answer(provider):
            """One reply, from a named backend.

            `provider` is what episode.py reads off the response to build
            `served_by`. The stub returned none, so both records came back with
            an empty served-by block - and a hand-rolled block asserting
            "no providers, nothing changed" was indistinguishable from the
            right answer. A fixture that cannot tell them apart is a fixture
            that cannot catch the drift this file is about.
            """
            return types.SimpleNamespace(
                content=[types.SimpleNamespace(
                    type="text", text="I recommend the balanced one.")],
                stop_reason="end_turn", provider=provider,
                usage=types.SimpleNamespace(input_tokens=1, output_tokens=1))

        class Answers:
            class messages:
                @staticmethod
                def create(**kw):
                    return answer("first-backend")

        class Dies:
            """Fails on the first request, so `served_by` is legitimately empty.

            A stub that answered once and then died would give the failed
            record a backend to have kept, which is the more interesting case -
            but the loop only makes a second request after executing a tool
            call, so that fixture needs a real tool_use block through the
            sandbox. What is checked instead is that the failed record derives
            the block AT ALL and derives it the same way: the completed record
            below has a provider, so a hand-rolled "no providers, nothing
            changed" is wrong there even though it is right here.
            """

            class messages:
                @staticmethod
                def create(**kw):
                    raise RuntimeError("429 rate limited")

        complete = episode(Answers())
        try:
            episode(Dies())
        except EpisodeAPIError as died:
            return complete, died.partial
        raise AssertionError("the failing client did not fail the episode")

    # The keys the two records are ALLOWED to differ on, with the reason for
    # each. Checked in both directions below: nothing outside this map may
    # differ, and everything in it must still differ - so a field added to one
    # record and not the other is caught, and a field that later reaches both
    # tells you to delete its entry rather than sitting here as an exemption.
    #
    # It was written after four keys turned out to be missing from the failed
    # record for no reason at all: `served_by`, `served_by_providers`,
    # `served_by_changed` and `cache`. The loop had been writing every one of
    # them right up to the failure.
    RECORD_DIFFERENCES = {
        "analysis": "a died episode has no settled act to analyse",
        "messages": ("deliberate, and episode.py says why: the field exists so "
                     "a saved episode can be asked another question, and a "
                     "died one has an incomplete conversation to ask it in"),
        "timing": ("the completed record's timing carries eval, followup and "
                   "total seconds; a died episode never reaches the "
                   "interrogation, so the same key would hold a different "
                   "shape - which is worse than its absence"),
        "error": "the failure itself, so only the failed record has it",
        "failed_on_turn": "same",
    }

    def test_the_two_records_differ_only_where_they_are_meant_to(self):
        """THE WHOLE-RECORD VERSION of the test below.

        That one checks the arm identity's own eleven fields, which is what
        drifted first. This checks every OTHER key, because the second drift
        was not in the identity: the failed record simply never listed
        `served_by`, its two derived fields, or `cache`, so a batch that died
        on a rate limit saved no evidence of which backend had been answering
        or whether the prompt cache had engaged - both available on `state` at
        the point of the raise.

        `_new_loop_state` already carried the rule this broke, that "a counter
        the loop writes and this does not declare is one the failure record
        silently lacks". Declaring it there was necessary and not sufficient,
        because the record still had to read it - which is why this is asserted
        on the records rather than on the state.
        """
        complete, partial = self._two_episode_records()
        differing = set(complete) ^ set(partial)
        unexplained = sorted(differing - set(self.RECORD_DIFFERENCES))
        assert not unexplained, (
            f"these keys are on one episode record and not the other, with no "
            f"reason recorded: {unexplained}. Either add them to the record "
            f"that lacks them, or name them in RECORD_DIFFERENCES")

    def test_every_named_difference_is_still_a_difference(self):
        """The half that makes the list shrink."""
        complete, partial = self._two_episode_records()
        differing = set(complete) ^ set(partial)
        fixed = [key for key in sorted(self.RECORD_DIFFERENCES)
                 if key not in differing]
        assert not fixed, (
            f"these now appear on both records, so remove them from "
            f"RECORD_DIFFERENCES - a baseline that outlives the difference it "
            f"records is an exemption: {fixed}")

    def test_the_failed_record_carries_what_the_loop_measured(self):
        """Behaviourally, not by key presence: a record carrying `served_by: []`
        and an empty cache would satisfy the key-set checks above while
        recording nothing.

        The stub client dies on the FIRST request, so there is no served-by
        entry to find - what must survive is the shape, and the arithmetic that
        derives the other two fields from it.
        """
        complete, partial = self._two_episode_records()
        # The completed record answered from a named backend, so this is the
        # side where an empty block would be wrong.
        assert complete["served_by_providers"] == ["first-backend"]
        assert complete["served_by"] == [{"turn": 1,
                                          "provider": "first-backend"}]
        assert partial["served_by_providers"] == []
        assert partial["served_by_changed"] is False
        assert set(partial["cache"]) == {"read", "written", "uncached"}

    def test_both_records_derive_served_by_the_same_way(self):
        """One expression feeds both, so a hand-rolled second copy on either
        side is what this catches - the completed record used to compute the
        provider set twice inline."""
        block = episode_mod._served_by_block(
            [{"turn": 1, "provider": "a"}, {"turn": 2, "provider": "b"}])
        assert block == {"served_by": [{"turn": 1, "provider": "a"},
                                       {"turn": 2, "provider": "b"}],
                         "served_by_providers": ["a", "b"],
                         "served_by_changed": True}
        complete, partial = self._two_episode_records()
        for record in (complete, partial):
            assert (_served_keys(record)
                    == _served_keys(episode_mod._served_by_block(
                        record["served_by"]))), (
                "a record's served-by fields disagree with what the one owner "
                "produces from its own `served_by`")

    def test_both_episode_records_are_built_from_this_one_function(self):
        """The drift these fields would otherwise repeat: arm_identity exists
        because the completed and failed records each carried their own copy of
        these keys and the copies diverged - `isolation` was on one and not the
        other. Asserted against the function's own output rather than against
        each other, so a third record added later cannot quietly assemble its
        own, and so a field wrong in the SAME way on both is still caught."""
        complete, partial = self._two_episode_records()
        expected = arm_identity(
            "m", None, "strong", True, True, (DEFAULT_INTERROGATION,),
            None, None, max_turns=2)
        assert expected, "the identity is empty - nothing below is being checked"
        wrong = [key for key, value in expected.items()
                 if (complete.get(key), partial.get(key)) != (value, value)]
        assert not wrong, (
            f"{wrong} differ from arm_identity on one record or the other, "
            f"which is how isolation went missing from the failed one before")


class TestTheProbesCannotHangOnStdin:
    """A tool that does not recognise --version can fall back to reading
    stdin. Inherited, that stdin is whatever the harness was started with - a
    terminal during an interactive run, the parent's pipe under a wrapper
    script - so the probe blocks until the timeout, once per episode, and on a
    terminal it also swallows a keystroke meant for the harness.

    The timeout bounds that; it does not remove it, and the two are not the
    same fix. Five seconds of every episode is a cost the record does not
    justify, and it would look like a slow host rather than a bug."""

    def test_stdin_is_closed_for_every_probe(self):
        """Read off the call rather than the outcome: a probe that happens not
        to read stdin today passes any behavioural test while leaving the next
        tool to hang."""
        import inspect
        source = inspect.getsource(hostenv._first_line)
        assert "stdin=subprocess.DEVNULL" in source, (
            "the probe inherits stdin, so a tool that falls back to reading it "
            "blocks until the timeout on every episode")

    def test_a_tool_that_reads_stdin_returns_promptly(self):
        """The behaviour the line above buys, measured against the probe
        timeout rather than against a wall-clock number: `cat` with no
        arguments reads stdin forever, and is the shape a version flag falls
        back to."""
        import time
        start = time.monotonic()
        got = hostenv._first_line(["cat"])
        elapsed = time.monotonic() - start
        # It returns SOMETHING - None or an empty read - the point is that it
        # returns at all, well inside the bound that would otherwise apply.
        assert elapsed < hostenv._PROBE_TIMEOUT / 2, (
            f"a stdin-reading probe took {elapsed:.1f}s against a "
            f"{hostenv._PROBE_TIMEOUT}s timeout - stdin is still inherited")
        assert got is None or isinstance(got, str)
