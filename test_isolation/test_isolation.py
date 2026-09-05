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

    @darwin_only
    def test_the_policy_file_is_managed_here_not_by_callers(self):
        """Sixty-odd call sites reach the sandbox. One that forgot to pass a
        profile would have run unprotected, so the module supplies its own.

        Seatbelt-shaped, so macOS only: a policy FILE is how sandbox-exec is
        configured, and `profile_for` returns None elsewhere. The Linux
        mechanisms carry their policy in argv and have nothing to point at."""
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

    @darwin_only
    def test_the_profile_is_passed_by_file_not_inline(self):
        """-p would share argv with the model's own command text, so a command
        containing a quote could terminate the profile early.

        `-f` and `-p` are sandbox-exec's own flags, so this is macOS only."""
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


class TestTheMechanismProbeAsksWhetherItWorks:
    """_mechanism_works answers "can this host actually do it", not "is the
    binary installed".

    THE DEFECT IT EXISTS FOR, from its own docstring: Ubuntu restricts
    unprivileged user namespaces from 23.10, so `unshare` is on PATH and fails
    at run time. Choosing it because shutil.which found it committed the
    harness to a mechanism that could not work and skipped the bwrap fallback
    that would have.

    Untested until now, on either platform - the function that decides how
    every command in every episode is confined.
    """

    def test_an_unknown_mechanism_is_never_chosen(self):
        """Guards the lookup itself: an unrecognised name must not fall through
        to a probe built from a partially-populated dict."""
        from subversionbench.isolation import _mechanism_works
        _mechanism_works.cache_clear()
        assert _mechanism_works("nosuchmechanism") is False
        assert _mechanism_works("") is False

    def test_a_mechanism_absent_from_path_is_not_probed(self):
        """shutil.which is necessary but not sufficient. It is still checked
        first, because running a probe for a binary that is not there costs a
        subprocess launch per call on every host that lacks it."""
        import subversionbench.isolation as iso
        calls = []
        iso._mechanism_works.cache_clear()
        real_which, real_run = iso.shutil.which, iso.subprocess.run
        try:
            iso.shutil.which = lambda name: None
            iso.subprocess.run = lambda *a, **k: calls.append(a) or None
            assert iso._mechanism_works("bwrap") is False
            assert calls == [], "probed a mechanism that is not installed"
        finally:
            iso.shutil.which, iso.subprocess.run = real_which, real_run
            iso._mechanism_works.cache_clear()

    def test_a_probe_that_cannot_launch_is_not_a_working_mechanism(self):
        """OSError from the probe means the kernel or the binary refused. That
        is the AppArmor case reaching us as an exception rather than a nonzero
        exit, and it must read as 'does not work', never propagate."""
        import subversionbench.isolation as iso
        real_which, real_run = iso.shutil.which, iso.subprocess.run
        try:
            iso.shutil.which = lambda name: f"/usr/bin/{name}"
            for boom in (OSError("nope"),
                         iso.subprocess.SubprocessError("nope")):
                def _raise(*a, _b=boom, **k):
                    raise _b
                iso._mechanism_works.cache_clear()
                iso.subprocess.run = _raise
                assert iso._mechanism_works("unshare") is False
        finally:
            iso.shutil.which, iso.subprocess.run = real_which, real_run
            iso._mechanism_works.cache_clear()

    def test_the_exit_code_is_what_decides(self):
        """Nonzero is the AppArmor symptom: installed, launches, refuses.

        The cache is cleared between cases. _mechanism_works is
        @functools.cache - probed once per mechanism per process, which is
        correct in production and would otherwise make this test assert the
        first stub's answer three times.
        """
        import subversionbench.isolation as iso
        import types as _types
        real_which, real_run = iso.shutil.which, iso.subprocess.run
        try:
            iso.shutil.which = lambda name: f"/usr/bin/{name}"
            for code, expected in ((0, True), (1, False), (255, False)):
                iso._mechanism_works.cache_clear()
                iso.subprocess.run = (
                    lambda *a, _c=code, **k: _types.SimpleNamespace(
                        returncode=_c))
                assert iso._mechanism_works("bwrap") is expected, code
        finally:
            iso.shutil.which, iso.subprocess.run = real_which, real_run
            iso._mechanism_works.cache_clear()
