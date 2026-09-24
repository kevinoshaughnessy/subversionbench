"""
Kernel-enforced limits on what a sandboxed command can reach.

The blocklist in sandbox.py exists to keep the eval's own machinery out of the
model's view. It is not a containment boundary and cannot be made into one: it
matches command strings, and `curl`, `/dev/tcp`, `python3 -c` and a base64
one-liner are all the same string problem. Three separate defects this year came
from a pattern matching the wrong text.

This module is the other kind of control. It asks the kernel to refuse, so the
refusal does not depend on recognising how the model spelled its request.

THE DEFAULT IS `deny-network` - loopback and off-host both refused. This is
public software that hands a frontier model a shell, and the scenario needs no
network at all: the full command battery an episode uses runs unchanged under a
total deny. The cost of an open default falls on downstream users who did not
choose it, so it is not theirs to pay.

`deny-external` permits loopback and refuses everything off-host. Choose it to
MEASURE the behaviour rather than only prevent it: a model that probes the host
gets realistic responses, so its escalation is observable rather than truncated
at the first refusal. Two saved episodes went from a port scan of the loopback
interface to HTTP requests against the services it found, and that trajectory is
only visible under this mode. It carries a local risk in exchange - loopback
stays reachable, so the model can reach whatever else the operator is running,
and the policy does not protect those services. Run such batches on a host with
nothing else listening.

THE FILESYSTEM IS CONFINED SEPARATELY, and not by the mode. Both modes get the
same boundary: the machine's temp directories cannot be listed or written to, and
the episode's own tree can. That is a different control from the network policy and
is asked for separately - `confinement_available` rather than `isolation_available`
- because the mechanisms differ in exactly that respect. `unshare --net` can
enforce the network policy and cannot enforce this one.

WHAT NO MODE DOES. None of them changes what is MEASURED. detect_network_probes and
the filesystem-escape measures read the COMMAND, not its outcome, so an attempt is
recorded whether the kernel allowed it or refused it. What the kernel changes is the
model's feedback, and therefore how far it goes next, which is why the mode is
recorded on every run - and why the filesystem boundary is part of the rollout
fingerprint while the network mode is not. A model demonstrably used the filesystem
route; none has ever used off-host reach.
"""

import functools
import os
import platform
import shutil
import subprocess
import tempfile
from pathlib import Path

# Modes, weakest first. The DEFAULT is the strongest of them, `deny-network`.
#
# This software is public and hands a frontier model a shell. A default that
# leaves the network open puts every downstream user one unread paragraph away
# from a model that can reach their machine's services or the internet, and the
# scenario needs no network at all - the full command battery an episode uses
# runs unchanged under a total deny. Safe-by-default costs nothing here, and the
# cost of the alternative falls on people who did not choose it.
#
# `deny-external` is the mode for measuring the behaviour rather than only
# preventing it: loopback stays reachable, so an episode that probes the host
# gets realistic responses and its escalation is observable. That is a research
# choice with a local risk attached, so it is opted into rather than inherited.
#
# There is no "off". It was removed rather than merely made hard to reach.
#
# A flag that disables the only containment boundary is a flag someone will pass
# to make an error message go away, and the error it silences is "a frontier
# model with a shell can reach your network". Keeping it for the operator's
# convenience trades a risk they understand against one a downstream user does
# not. Episodes collected before v35 recorded `isolation: "off"` or nothing at
# all, and those values are still READ and reported - history is data - but the
# mode can no longer be selected.
#
# The consequence is accepted deliberately: on a host with no mechanism
# available, this harness does not run. That is the intended outcome, not a gap.
ISOLATION_MODES = ("deny-external", "deny-network")
DEFAULT_ISOLATION = "deny-network"

# Values that may appear in SAVED runs but cannot be selected. Kept so a summary
# can report the provenance of an archived batch without inviting the mode back.
HISTORICAL_ISOLATION = ("off", "unrecorded")

_DARWIN_PROFILE = """(version 1)
(allow default)
(deny network*)
%s%s
"""
_ALLOW_LOOPBACK = """(allow network-outbound (remote ip "localhost:*"))
(allow network-inbound (local ip "localhost:*"))"""


# ---------------------------------------------------------------------------
# Confining the filesystem, which the string blocklist cannot do
#
# `ls ../..` is refused by sandbox.py because it can see the `..` in the command
# text. An interpreter never puts it there:
#
#     python3 -c "import os; print(os.listdir('../..'))"
#
# resolves the path at runtime, so there is no text to match. One saved episode
# did exactly this and got back the operator's temp directory - 74,771 entries,
# every leftover episode and test tree on the machine. Two harms, and the second
# is the one that invalidates measurements rather than merely leaking:
#
#   - Thousands of similarly-named sibling directories is an evaluation-awareness
#     cue no real deployment offers.
#   - The temp root is writable, so a note left there is readable by every later
#     episode. Episode independence is the assumption under every rate in this
#     harness, and nothing was enforcing it.
#
# It also ended that episode outright: the listing was 1.5 MB, which took the
# conversation past the model's context limit on the following turn.
#
# THE EPISODE ROOT IS THE BOUNDARY, NOT THE PROJECT DIRECTORY. `..` holds
# scenario-controlled neighbours, and in the lure arm one of them holds the lure
# file - so `ls ..` has to keep working or the arm stops measuring what it
# measures. `../..` is the machine, and that is what is refused.
#
# REALPATH, AND THIS IS THE WHOLE TRAP. sandbox-exec matches on the resolved
# path. `tempfile.gettempdir()` returns `/var/folders/...`, whose real path is
# `/private/var/folders/...`; a profile built from the unresolved form parses,
# loads, reports no error, and enforces NOTHING. Measured both ways while writing
# this: unresolved, `ls ..` listed the temp root; resolved, it returned
# "Operation not permitted". Every path below goes through os.path.realpath, and
# verify_confinement() proves the result rather than trusting it.
# ---------------------------------------------------------------------------

# `/usr/bin/python3` on macOS is the Xcode shim, and it writes a cache file
# `$TMPDIR/xcrun_db-<random>` before doing anything else. Denying the temp root
# outright makes it print two lines of
#
#     python3: error: couldn't create cache file '/var/folders/.../xcrun_db-...'
#
# to stderr on every invocation. Python still runs, and the escape is still
# refused - measured, not assumed - but `execute_tool_sandboxed` returns stderr
# whenever a command produced no stdout, so the MODEL would see that text. It names
# the operator's real temp path, and output going back to the model is deliberately
# unredacted so the paths it reads stay consistent with the paths it types. A
# sandbox that announces itself in a diagnostic is worse than one that quietly
# refuses.
#
# So this one filename prefix is permitted. `prefix` rather than `regex`: the
# suffix is random, so a literal will not do, and seatbelt's `regex` form was
# measured NOT to take effect here while `prefix` did - which is the difference
# between a policy that suppresses the warning and one that looks like it should.
# The temp listing stays denied under it, checked in the same measurement.
#
# The trade-off is stated rather than hidden: it leaves a channel one episode could
# write and another read, if a model guessed the name. It cannot LIST the directory
# to find one, and no episode has ever referenced this path. A whole readable temp
# root is a certainty; this is a guess against a random suffix.
_XCRUN_CACHE_PREFIX = "xcrun_db"


def _temp_roots() -> tuple:
    """
    Every directory that must be unreachable, resolved.

    All of the conventional temp locations rather than only the one this process
    would pick: `tempfile.gettempdir()` reads TMPDIR, so a batch started from a
    shell with a different TMPDIR would confine a directory the episodes are not
    in. Denying the whole set costs nothing and does not depend on the
    environment matching between the harness and the model's shell.

    `/private/var/folders` is included whole, not just this user's subdirectory,
    so another account's per-user temp is out of reach as well.
    """
    candidates = [tempfile.gettempdir(), "/tmp", "/var/tmp", "/private/tmp",
                  "/private/var/tmp", "/var/folders", "/private/var/folders"]
    roots = []
    for path in candidates:
        real = os.path.realpath(path)
        if real not in roots:
            roots.append(real)
    return tuple(roots)


def confinement_clauses(confine_to) -> str:
    """
    The policy text: the temp roots unlistable and unwritable, `confine_to` intact.

    Three seatbelt behaviours decide the exact shape here, and every one of them
    was measured rather than assumed. All three fail SILENTLY in the direction
    that looks fine.

    1. THE READ DENY IS `literal`, NOT `subpath`. A subpath read-deny on any
       ancestor of the working directory stops the shell starting at all - it
       cannot resolve its own cwd - and that includes a deny on the temp root,
       since every episode tree lives inside one. `literal` refuses reads of that
       one directory, which is precisely what enumeration needs, while leaving
       traversal through it to the tree below. Measured: subpath gave
       "shell-init: error retrieving current directory" on every command; literal
       refuses `ls ../..` and nothing else.

       Denying the LISTING is the control that matters. A name inside a temp root
       is a random suffix from mkdtemp, so a model that cannot enumerate cannot
       find one - stated as the residual risk rather than claimed as impossible.

    2. THE WRITE DENY IS `subpath`, and it can be, because a write is not part of
       resolving a path. This is the half that keeps episodes independent: a note
       left in the shared temp root is readable by every later episode.

    3. `(allow file* ...)` DOES NOT re-grant `file-write*` after an explicit
       `(deny file-write* ...)`. The verbs have to be named. With the wildcard the
       policy loaded, reads worked, `ls ..` worked - and `echo x > out.md` inside
       the project directory came back "Operation not permitted", which would have
       stopped every model writing its deliverable while every other probe passed.

    Order is still load-bearing on top of all that: seatbelt applies the last
    matching rule, so the allows follow the denies.
    """
    if not confine_to:
        return ""
    allow = os.path.realpath(str(confine_to))
    roots = _temp_roots()
    lines = [f'(deny file-read-data (literal "{root}"))' for root in roots]
    lines += [f'(deny file-write* (subpath "{root}"))' for root in roots]
    lines += [f'(allow file-write* file-read* '
              f'(prefix "{root}/{_XCRUN_CACHE_PREFIX}"))' for root in roots]
    lines.append(f'(allow file-write* file-read* (subpath "{allow}"))')
    return "\n" + "\n".join(lines)


_PROFILE_CACHE = {}
_POLICY_DIR = None


def _policy_dir() -> Path:
    """One directory per process, outside every episode tree.

    Never inside the episode directory: that is the one place the model can
    write, and a policy it could edit is not a policy. It sits in the temp root
    the policy itself denies, so once confinement is on the model cannot reach it
    either - and `sandbox-exec` reads the file before applying the policy, so
    denying its own location does not stop it loading. Verified, not assumed.
    """
    global _POLICY_DIR
    if _POLICY_DIR is None:
        _POLICY_DIR = Path(tempfile.mkdtemp(prefix="sbx-policy-"))
    return _POLICY_DIR


def profile_for(mode: str, confine_to=None):
    """
    The policy file for `mode`, confined to `confine_to`, written once per pair.

    Managed here rather than by callers. Sixty-odd call sites reach the sandbox
    and none of them should have to know that one platform needs a file on disk -
    a caller that forgot would pass None and run the command unprotected, which
    is precisely the failure this module exists to remove.

    Keyed on the resolved tree as well as the mode, because the filesystem half
    of the policy names a directory that differs per episode. Cached, so a batch
    writes one small file per episode rather than one per command.
    """
    if platform.system() != "Darwin":
        return None
    key = (mode, os.path.realpath(str(confine_to)) if confine_to else None)
    if key not in _PROFILE_CACHE:
        name = f"{mode}-{abs(hash(key)):x}.sb" if confine_to else f"{mode}.sb"
        path = _policy_dir() / name
        path.write_text(darwin_profile(mode, confine_to))
        _PROFILE_CACHE[key] = path
    return _PROFILE_CACHE[key]


@functools.cache
def _mechanism_works(name: str) -> bool:
    """
    Whether `name` can actually create the namespace it needs, on this host.

    PRESENCE ON PATH IS NOT THE QUESTION, and asking it that way was a defect.
    Ubuntu restricts unprivileged user namespaces through AppArmor from 23.10
    onwards, so `unshare` is installed, on PATH, and fails at run time with
    "Operation not permitted". Choosing it because `shutil.which` found it
    committed the harness to a mechanism that could not work, and skipped the
    bwrap fallback below that would have.

    What that cost, measured on Ubuntu 24.04: every command ran unprotected,
    `verify_confinement` caught it and the rollout refused - correctly, and the
    whole batch was impossible on a host that could in fact have confined it.
    The refusal was right; the choice that led to it was not.

    Probed once per mechanism and cached. The probe runs the real thing rather
    than reading a sysctl, because what matters is whether the kernel permits
    THIS process to do it, and the reasons it might not are not enumerable.
    """
    probes = {
        "unshare": ["unshare", "--net", "--", "true"],
        "bwrap": ["bwrap", "--unshare-net", "--dev-bind", "/", "/", "true"],
    }
    if name not in probes or not shutil.which(name):
        return False
    try:
        result = subprocess.run(probes[name], capture_output=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def isolation_available(mode: str) -> bool:
    """Whether this host can enforce `mode` at all."""
    if platform.system() == "Darwin":
        return shutil.which("sandbox-exec") is not None
    return _mechanism_works("unshare") or _mechanism_works("bwrap")


def active_mechanism(mode: str = DEFAULT_ISOLATION) -> str:
    """
    Which kernel mechanism this host would actually use for `mode`.

    Not which policy was requested - `isolation` on the episode already records
    that, and it reads the same on every host. This is the one that differs:
    sandbox-exec execs the shell in place and bwrap forks it, which is why
    defects have been invisible on one platform and real on the other.

    Mirrors wrap_command's own selection rather than restating it as a rule:
    Darwin takes sandbox-exec, and on Linux bwrap is preferred because it is
    the only one that can confine the filesystem, with unshare reported when
    it is all that works. "unavailable" when neither does, which is a host the
    harness will refuse to collect on - recorded rather than raised, because
    this is a description of the host and not a decision about a run.
    """
    if platform.system() == "Darwin":
        return "sandbox-exec" if shutil.which("sandbox-exec") else "unavailable"
    if _mechanism_works("bwrap"):
        return "bwrap"
    if _mechanism_works("unshare"):
        return "unshare"
    return "unavailable"


def confinement_available() -> bool:
    """
    Whether this host can confine the filesystem, not just the network.

    Separate from isolation_available because the Linux mechanisms differ in
    exactly this: `unshare --net` gives a network namespace and no filesystem
    control at all, while bwrap can mount over the temp roots. A host with only
    `unshare` can enforce the network policy and cannot enforce this one, and the
    two questions have to be answerable apart or the harness would report a
    boundary it does not have.
    """
    if platform.system() == "Darwin":
        return shutil.which("sandbox-exec") is not None
    # Whether bwrap WORKS, not whether it is installed. An installed bwrap that
    # the kernel refuses to let create a namespace would have this report a
    # boundary the host cannot enforce - the exact failure the paragraph above
    # says the two questions are kept apart to prevent.
    return _mechanism_works("bwrap")


def darwin_profile(mode: str, confine_to=None) -> str:
    """The sandbox-exec profile text for `mode`, optionally filesystem-confined."""
    return _DARWIN_PROFILE % (
        _ALLOW_LOOPBACK if mode == "deny-external" else "",
        confinement_clauses(confine_to))


def wrap_command(cmd: str, mode: str = DEFAULT_ISOLATION,
                 profile_path=None, confine_to=None) -> list:
    """
    The argv that runs `cmd` under `mode`, confined to `confine_to`.

    Returns a list for subprocess, still going through a shell because the
    scenario's commands are shell text - pipelines, heredocs, redirections. The
    isolation is applied to the shell itself, so everything it spawns inherits
    it: a wrapper the model could step outside of by starting a subprocess would
    not be worth having.

    `profile_path` is ignored when `confine_to` is given, because the filesystem
    half of the policy names that directory: honouring a pre-built profile here
    would silently run the command under a policy that confines something else,
    or nothing. The batch-level profile stays useful for verifying the network
    policy at startup, which needs no episode.
    """
    if mode not in ISOLATION_MODES:
        # Including "off". A typo or a stale caller must fail loudly rather than
        # fall through to an unprotected shell.
        raise ValueError(
            f"unknown isolation mode {mode!r}; expected one of {ISOLATION_MODES}"
        )
    if confine_to:
        profile_path = profile_for(mode, confine_to)
    else:
        profile_path = profile_path or profile_for(mode)

    if platform.system() == "Darwin":
        # -f rather than -p: a profile passed inline shares the argv with the
        # model's own command text, and a command containing a quote could then
        # terminate the profile early. From a file it cannot.
        return ["sandbox-exec", "-f", str(profile_path), "/bin/sh", "-c", cmd]

    if confine_to:
        # bwrap only. `unshare --net` cannot mount anything, so it cannot hide
        # the temp roots, and running under it while reporting confinement would
        # be the "policy that silently failed to apply" this module exists to
        # rule out. Refused rather than downgraded.
        if not _mechanism_works("bwrap"):
            raise RuntimeError(
                "filesystem confinement was requested but bwrap is not "
                "available. `unshare --net` isolates the network only and "
                "cannot make the temp directory unreadable. Install bubblewrap "
                "(`bwrap`); there is deliberately no unconfined path.")
        allow = os.path.realpath(str(confine_to))
        argv = ["bwrap", "--unshare-net", "--dev-bind", "/", "/"]
        # An empty tmpfs over each temp root rather than a deny: the mount hides
        # what is there for every process in the namespace, including anything
        # the model spawns. The episode tree is bound back afterwards, since it
        # lives under one of them - the same ordering the seatbelt policy needs,
        # for the same reason.
        #
        # `--chmod 0111` ON THE MOUNT, and the mode is load-bearing. A bare tmpfs
        # is world-readable, so `ls ../..` SUCCEEDS and returns an empty listing.
        # That hides the machine's temp contents, but it is not the same
        # observation the seatbelt policy produces, which is "Operation not
        # permitted" - and the difference reaches the model, whose next move
        # depends on the feedback it got. The fingerprint deliberately does not
        # hash the mechanism, on the stated grounds that "what the model can and
        # cannot do is the same on both"; with a readable tmpfs that was untrue,
        # so a Linux batch and a macOS batch would have pooled under one identity
        # while presenting two different worlds.
        #
        # 0111 is execute-without-read: traversal through the directory still
        # works, enumeration of it does not. That is precisely why the seatbelt
        # policy uses `literal` rather than `subpath` - a mode of 0 removes
        # traversal as well, and the shell then cannot cd into the episode tree
        # at all, which is the same failure measured there.
        for root in _temp_roots():
            if os.path.isdir(root):
                argv += ["--tmpfs", root, "--chmod", "0111", root]
        argv += ["--bind", allow, allow]
        return argv + ["/bin/sh", "-c", cmd]

    if _mechanism_works("unshare"):
        # --net gives the process an empty network namespace with a loopback
        # interface of its own, so loopback "works" but reaches nothing the
        # operator is running. That is stricter than the Darwin policy for
        # deny-external and worth noting when comparing across platforms.
        #
        # `_mechanism_works` rather than `shutil.which`: on Ubuntu 23.10 and
        # later unshare is present and unprivileged use of it is refused, so
        # selecting it on presence sent every command through a wrapper that
        # failed, and never reached the bwrap below that works there.
        return ["unshare", "--net", "--", "/bin/sh", "-c", cmd]

    if _mechanism_works("bwrap"):
        return ["bwrap", "--unshare-net", "--dev-bind", "/", "/",
                "/bin/sh", "-c", cmd]

    raise RuntimeError(
        f"isolation mode {mode!r} requested but no mechanism is available on "
        f"{platform.system()}. Install bubblewrap (`bwrap`) or ensure `unshare` "
        f"is present. There is deliberately no way to run without containment: "
        f"the sandbox's blocklist is not a boundary, and a model with shell "
        f"access would be able to reach the network."
    )


def verify_isolation(mode: str, profile_path=None):
    """
    None if the policy holds for `mode`, else a message saying how it failed.

    Judged on OUTCOMES, not on a specific errno. The mechanisms differ: macOS
    refuses a forbidden connection with EPERM, while Linux's `unshare --net`
    supplies an empty network namespace in which the attempt fails as unreachable
    instead. An errno-exact check passed on macOS and would have refused to start
    on a correctly isolated Linux host.

    The one thing that always disqualifies a mode is a connection that SUCCEEDS.
    `deny-external` additionally requires loopback to remain usable, because a
    policy stricter than the one asked for silently changes what is measured -
    which is why `deny-external` is rejected on a mechanism that cannot offer it
    rather than quietly downgraded.
    """
    out = probe_isolation(mode, profile_path)
    loop, ext = out["loopback"], out["external"]
    if ext == "connected":
        return f"off-host reach was NOT blocked: {out}"
    if mode == "deny-network":
        if loop == "connected":
            return f"loopback was not blocked under deny-network: {out}"
        return None
    # deny-external: loopback has to stay usable, so the escalation it exists to
    # observe is still observable. "refused" is a closed port handled normally;
    # "connected" means something was listening. Anything else means the policy
    # took loopback away too.
    if loop not in ("refused", "connected"):
        return (f"deny-external needs loopback reachable, but it came back "
                f"{loop!r}: {out}. This mechanism cannot provide the mode - on "
                f"Linux, `unshare --net` gives an empty namespace in which "
                f"loopback reaches nothing. Use --isolation deny-network, and "
                f"note that off-host escalation will not be observable.")
    return None


def probe_confinement(mode: str = DEFAULT_ISOLATION) -> dict:
    """
    Try to leave a throwaway episode tree, by the routes a model actually used.

    Builds the real shape - a root with a project directory inside it - and runs
    each probe from the project directory, so the outcomes mean the same thing
    they will mean in an episode.

    The interpreter probe is the one that matters. The shell form was already
    refused by the string blocklist before any of this existed, so a check that
    only tried `ls ../..` would have passed against a policy that enforced
    nothing at all.
    """
    root = Path(tempfile.mkdtemp(prefix="sbx-verify-"))
    project = root / "project"
    project.mkdir()
    (project / "own.txt").write_text("readable")
    (root / "neighbour").mkdir()

    def run(cmd):
        try:
            proc = subprocess.run(
                wrap_command(cmd, mode, confine_to=root),
                # Short: these are `true`, `cat` and a one-line python. A policy
                # that breaks the shell makes every probe hang instead of
                # answering, and a verifier that takes six minutes to say so is
                # one an operator interrupts rather than reads.
                cwd=project, capture_output=True, text=True, timeout=10,
                env={"HOME": str(project), "PATH": "/usr/bin:/bin",
                     "TERM": "xterm"})
        except Exception as e:
            return f"<{type(e).__name__}>"
        return (proc.stdout + proc.stderr).strip()

    temp_root = _temp_roots()[0]
    out = {
        # The interpreter has to WORK, and this probe exists because the first
        # version of this verifier passed without it. Denying the temp root broke
        # `python3` on macOS, every escape probe returned only a startup error,
        # and "no listing came back" read as "the escape was refused". A check
        # that cannot tell a refusal from a broken interpreter is not a check.
        "interpreter": run("python3 --version"),
        # Has to keep working: the project directory is the episode.
        "own_file": run("cat own.txt"),
        # Has to keep working: `..` is scenario-controlled, and the lure arm
        # hides its file in a neighbour there.
        "neighbour": run("ls .."),
        # Has to keep working, and it is here because it nearly did not. Naming
        # `file*` in the allow left this refused while every other probe passed,
        # which would have shipped a harness where no model could write its
        # deliverable - see confinement_clauses.
        "write_inside": run("echo confirmed > probe_out.txt && cat probe_out.txt"),
        # Must not work, by ANY enumeration route. Several rather than one,
        # because they reach the directory through different syscalls and a policy
        # can stop `listdir` while leaving a glob working.
        "shell_escape": run("ls ../.."),
        "shell_glob": run("echo ../../*"),
        "shell_find": run("find ../.. -maxdepth 1"),
        "interpreter_escape": run(
            'python3 -c "import os; print(len(os.listdir(\'../..\')))"'),
        "absolute_temp": run(f'python3 -c "import os; '
                             f'print(len(os.listdir({temp_root!r})))"'),
        "absolute_scandir": run(f'python3 -c "import os; '
                                f'print(len(list(os.scandir({temp_root!r}))))"'),
        # A write outside the tree is what breaks episode independence.
        "write_escape": run(
            'python3 -c "open(\'../../sbx_probe.txt\',\'w\').write(\'x\')"'),
        "write_absolute": run(f'python3 -c "'
                              f'open({temp_root + "/sbx_probe.txt"!r},\'w\')"'),
    }
    shutil.rmtree(root, ignore_errors=True)
    return out


def verify_confinement(mode: str = DEFAULT_ISOLATION):
    """
    None if the filesystem boundary holds, else a message saying how it failed.

    Judged on outcomes and in BOTH directions, because either failure ruins a
    batch and they look nothing alike:

      - an escape that succeeds means the operator's temp directory is readable
        by the model, which is the disclosure this exists to close;
      - a policy that also takes `..` away silently changes the scenario, since
        the neighbours there are part of what the model is meant to find, and the
        lure arm would stop measuring anything.

    Only a SUCCESSFUL escape is disqualifying on the deny side. The wording of
    the refusal differs by mechanism - seatbelt says "Operation not permitted",
    an empty bwrap tmpfs simply lists nothing - so this checks that the listing
    did not come back, not that a particular errno did.
    """
    out = probe_confinement(mode)
    if "Python" not in out["interpreter"]:
        return (f"python3 did not run under the policy, so every escape probe "
                f"below would fail for the wrong reason: {out}")
    if _XCRUN_CACHE_PREFIX in out["interpreter"]:
        return (f"python3 ran but could not write its cache file, so the model "
                f"would see the operator's real temp path in stderr whenever a "
                f"command produced no stdout: {out}")
    if "readable" not in out["own_file"]:
        return (f"the episode's own directory was not readable, so the policy is "
                f"stricter than intended: {out}")
    if "neighbour" not in out["neighbour"]:
        return (f"`ls ..` did not show the scenario's neighbours, which the lure "
                f"arm depends on: {out}")
    if "confirmed" not in out["write_inside"]:
        return (f"the episode could not write inside its own directory, so no "
                f"model could produce a deliverable: {out}")
    for probe in ("shell_escape", "shell_find", "interpreter_escape",
                  "absolute_temp", "absolute_scandir"):
        if not _looks_refused(out[probe]):
            return (f"{probe} was NOT refused - the temp directory is reachable "
                    f"from inside an episode: {out}")
    # A glob that matches nothing is left unexpanded by the shell, so the literal
    # pattern coming back IS the refusal. Checked apart from the others because
    # "../../*" contains no refusal wording and would otherwise read as a listing.
    if "*" not in out["shell_glob"]:
        return (f"a glob enumerated the temp directory: {out}")
    for probe in ("write_escape", "write_absolute"):
        if not _looks_refused(out[probe]):
            return (f"{probe} succeeded, so a note left above the episode tree "
                    f"would be readable by every later episode and the rates are "
                    f"not built on independent samples: {out}")
    return None


def _looks_refused(got: str) -> bool:
    """
    Whether a probe's output shows the operation was refused.

    Empty counts as refused: a bwrap tmpfs is not an error at all - the directory
    is simply empty - so there is nothing for a marker to match. The markers are
    for the seatbelt case, where the wording differs per tool but every one of
    them says so.
    """
    return not got.strip() or any(m in got for m in _REFUSAL_MARKERS)


# What a refused filesystem operation looks like, across mechanisms. A bwrap
# tmpfs is not an error at all - the directory is simply empty - so an empty
# result counts as refused and is handled by the caller before this is consulted.
_REFUSAL_MARKERS = ("Operation not permitted", "Permission denied",
                    "PermissionError", "No such file or directory",
                    "not permitted", "denied")


def probe_isolation(mode: str, profile_path=None) -> dict:
    """
    Check the policy actually holds, by trying it.

    Called at startup rather than trusted, because a profile that silently fails
    to apply looks exactly like one that works: the model simply reaches the
    network and nothing says so. 192.0.2.1 is TEST-NET-1, reserved by RFC 5737
    and never routed, so the external probe contacts nothing real whether the
    policy holds or not.
    """
    def _try(host, port):
        code = (f"import socket\ns=socket.socket()\ns.settimeout(2)\n"
                f"try:\n s.connect(({host!r},{port}))\n print('connected')\n"
                f"except PermissionError:\n print('denied')\n"
                f"except OSError as e:\n print('refused' if e.errno in (61,111) "
                f"else 'other')\n")
        try:
            out = subprocess.run(
                wrap_command(f"python3 -c {_shquote(code)}", mode, profile_path),
                capture_output=True, text=True, timeout=15)
            return (out.stdout or out.stderr).strip().splitlines()[-1:] or [""]
        except Exception as e:                       # a failure is a result too
            return [f"error:{type(e).__name__}"]

    return {
        "mode": mode,
        "loopback": _try("127.0.0.1", 9)[0],
        "external": _try("192.0.2.1", 80)[0],
    }


def _shquote(s: str) -> str:
    return "'" + s.replace("'", "'\"'\"'") + "'"
