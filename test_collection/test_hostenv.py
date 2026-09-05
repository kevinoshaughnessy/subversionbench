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

from subversionbench import hostenv
from subversionbench.episode import arm_identity
from subversionbench.isolation import DEFAULT_ISOLATION, active_mechanism


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

    def test_both_episode_records_are_built_from_this_one_function(self):
        """The drift these fields would otherwise repeat: arm_identity exists
        because the completed and failed records each carried their own copy of
        these keys and the copies diverged. Read off the source rather than
        asserted about one record, so a third record added later cannot quietly
        assemble its own."""
        import inspect

        from subversionbench import episode
        source = inspect.getsource(episode)
        assert source.count("**arm_identity(") == 2, (
            "a record is being assembled without arm_identity, which is how "
            "isolation went missing from the failed record before")


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
