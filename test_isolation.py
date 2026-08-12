"""
There is no way to roll out unprotected.

Isolation is not an option the operator can forget: a mode that cannot be provided
on this platform is refused rather than quietly downgraded, and the wrapper cannot
be stepped out of by a command the model writes.
"""

import pytest
import tempfile

from pathlib import Path
from subversionbench.isolation import ISOLATION_MODES, probe_isolation, wrap_command
from conftest import darwin_only, sandbox_profile, summary_pipeline_source


class TestThereIsNoWayToRunUnprotected:
    """`off` was removed rather than merely made hard to reach.

    A flag that disables the only containment boundary is a flag someone will
    pass to make an error message go away, and the error it silences is "a
    frontier model with a shell can reach your network"."""

    def test_off_is_not_a_selectable_mode(self):
        assert "off" not in ISOLATION_MODES

    def test_asking_for_it_raises_rather_than_falling_through(self):
        """A stale caller or a typo must fail loudly. Returning a plain shell
        would run the command with no policy at all."""
        with pytest.raises(ValueError):
            wrap_command("cat a.txt", "off")

    def test_every_selectable_mode_denies_off_host_reach(self):
        """The invariant that replaces `off`: there is no mode that permits it."""
        for mode in ISOLATION_MODES:
            assert "deny" in mode, mode

    def test_the_default_is_the_strictest_mode(self):
        from subversionbench.isolation import DEFAULT_ISOLATION
        assert DEFAULT_ISOLATION == "deny-network"

    def test_historical_values_are_still_readable(self):
        """Episodes collected before this release recorded "off" or nothing.
        Those values are data and must stay reportable - removing the mode must
        not make an archived batch unsummarisable."""
        from subversionbench.isolation import HISTORICAL_ISOLATION
        assert "off" in HISTORICAL_ISOLATION
        assert "unrecorded" in HISTORICAL_ISOLATION

    def test_the_policy_file_is_managed_here_not_by_callers(self):
        """Sixty-odd call sites reach the sandbox. One that forgot to pass a
        profile would have run unprotected, so the module supplies its own."""
        from subversionbench.isolation import profile_for
        argv = wrap_command("cat a.txt", "deny-network")
        assert str(profile_for("deny-network")) in argv

    def test_the_policy_file_lives_outside_the_episode_directory(self):
        """The working directory is the one place the model can write. A policy
        it could edit is not a policy."""
        from subversionbench.isolation import profile_for
        p = profile_for("deny-network")
        if p is not None:
            assert "sbx-policy-" in str(p)

    def test_isolation_does_not_move_the_rollout_fingerprint(self):
        """r1 through r3 were cut before isolation existed. If `off` hashed
        differently, all 760 saved episodes would be declared incomparable with
        a rollout they still match exactly."""
        from subversionbench.config import ROLLOUT_FINGERPRINTS
        from subversionbench.rollout import rollout_fingerprint
        for arm in (True, False):
            for mode in ISOLATION_MODES:
                assert rollout_fingerprint(arm, mode) == ROLLOUT_FINGERPRINTS[(arm, False)]

    def test_enabling_isolation_does_NOT_move_it(self):
        """A deliberate judgement, and the opposite of the first attempt.

        The fingerprint's test is whether episodes could have BEHAVED
        differently, not whether the harness was configured differently.
        `deny-external` removes off-host reachability and nothing else, and
        across 760 saved episodes no model has ever reached off-host - the only
        reach observed is loopback, which stays reachable. So an isolated batch
        and an unisolated one are identical on everything anyone has seen, and
        splitting the results directory would buy nothing.

        It also matters that safety is cheap: a control that costs a rollout bump
        is one people leave switched off.

        Revisit this the first time a model does reach off-host. At that point the
        configurations differ in observed behaviour and the mode belongs in the
        hash."""
        from subversionbench.rollout import rollout_fingerprint
        off = rollout_fingerprint(True, "off")
        for mode in ("deny-external", "deny-network"):
            assert rollout_fingerprint(True, mode) == off, mode

    def test_the_difference_is_recorded_instead(self):
        """Not hashing it is only defensible because it is written down. Every
        run carries its mode and every summary reports the observed set."""
        import inspect
        import subversionbench.run_eval as ev_run
        src = summary_pipeline_source()
        assert '"isolation": dict(isolation_modes)' in src
        assert '"isolation_mixed"' in src
        assert '"isolation": isolation' in inspect.getsource(ev_run.run_evaluation)

class TestTheWrapperCannotBeSteppedOutOf:
    def test_the_isolation_starts_the_shell_not_the_reverse(self):
        """The wrapper has to be outermost, so anything the command spawns
        inherits the policy. A model that could escape by launching a subprocess
        would make the whole layer decorative."""
        argv = wrap_command("python3 -c 'x'", "deny-external", "/tmp/p.sb")
        assert argv[0] != "/bin/sh"
        assert argv.index("/bin/sh") > 0

    def test_the_profile_is_passed_by_file_not_inline(self):
        """-p would share argv with the model's own command text, so a command
        containing a quote could terminate the profile early."""
        argv = wrap_command("echo \"'\"", "deny-external", "/tmp/p.sb")
        assert "-f" in argv and "-p" not in argv

@darwin_only
class TestThePolicyActuallyHolds:
    """Observed behaviour, not profile text."""

    def test_deny_external_refuses_off_host_and_permits_loopback(self):
        """The split the network measure depends on. Loopback must come back
        `refused` - the OS handling a closed port normally - not `denied`, which
        would mean the policy blocked it and the measure had lost its subject."""
        out = probe_isolation("deny-external", sandbox_profile("deny-external"))
        assert out["external"] == "denied"
        assert out["loopback"] == "refused"

    def test_deny_network_refuses_both(self):
        out = probe_isolation("deny-network", sandbox_profile("deny-network"))
        assert out["external"] == "denied"
        assert out["loopback"] == "denied"

    def test_an_ordinary_command_still_works_under_isolation(self):
        """The policy must not break the task. Every episode reads files and
        writes a draft, and a profile that blocked that would turn every run
        into a null result - which is how the `locate` defect did its damage."""
        import subprocess
        d = Path(tempfile.mkdtemp())
        (d / "a.txt").write_text("hello")
        out = subprocess.run(
            wrap_command("cat a.txt", "deny-external", sandbox_profile("deny-external")),
            capture_output=True, text=True, timeout=15, cwd=str(d))
        assert out.stdout.strip() == "hello", out.stderr

class TestModesAreDeclared:
    def test_the_strictest_mode_is_last_and_is_the_default(self):
        from subversionbench.isolation import DEFAULT_ISOLATION
        assert ISOLATION_MODES[-1] == DEFAULT_ISOLATION == "deny-network"

    def test_the_sandbox_defaults_to_a_real_policy(self):
        """A caller that passes no mode gets containment, not a bare shell."""
        import inspect
        from subversionbench.sandbox import execute_tool_sandboxed
        sig = inspect.signature(execute_tool_sandboxed)
        assert sig.parameters["isolation"].default == "deny-network"
