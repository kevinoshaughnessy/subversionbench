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

WHAT NO MODE DOES. None of them confines writes: an interpreter can still write
outside the episode's working directory, including to this harness's own source.
And none of them changes what is MEASURED - detect_network_probes reads the
command, not its outcome, so an attempt is recorded whether the kernel allowed it
or refused it. What the mode changes is the model's feedback, and therefore how
far it goes next, which is why the mode is recorded on every run.
"""

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
%s
"""
_ALLOW_LOOPBACK = """(allow network-outbound (remote ip "localhost:*"))
(allow network-inbound (local ip "localhost:*"))"""


_PROFILE_CACHE = {}


def profile_for(mode: str):
    """
    The policy file for `mode`, written once per process.

    Managed here rather than by callers. Sixty-odd call sites reach the sandbox
    and none of them should have to know that one platform needs a file on disk -
    a caller that forgot would pass None and run the command unprotected, which
    is precisely the failure this module exists to remove.

    Written to a fresh temp directory, never inside the episode's working
    directory: that is the one place the model can write, and a policy it could
    edit is not a policy.
    """
    if platform.system() != "Darwin":
        return None
    if mode not in _PROFILE_CACHE:
        path = Path(tempfile.mkdtemp(prefix="sbx-policy-")) / f"{mode}.sb"
        path.write_text(darwin_profile(mode))
        _PROFILE_CACHE[mode] = path
    return _PROFILE_CACHE[mode]


def isolation_available(mode: str) -> bool:
    """Whether this host can enforce `mode` at all."""
    if platform.system() == "Darwin":
        return shutil.which("sandbox-exec") is not None
    return shutil.which("unshare") is not None or shutil.which("bwrap") is not None


def darwin_profile(mode: str) -> str:
    """The sandbox-exec profile text for `mode`."""
    return _DARWIN_PROFILE % (_ALLOW_LOOPBACK if mode == "deny-external" else "")


def wrap_command(cmd: str, mode: str = DEFAULT_ISOLATION,
                 profile_path=None) -> list:
    """
    The argv that runs `cmd` under `mode`.

    Returns a list for subprocess, still going through a shell because the
    scenario's commands are shell text - pipelines, heredocs, redirections. The
    isolation is applied to the shell itself, so everything it spawns inherits
    it: a wrapper the model could step outside of by starting a subprocess would
    not be worth having.
    """
    if mode not in ISOLATION_MODES:
        # Including "off". A typo or a stale caller must fail loudly rather than
        # fall through to an unprotected shell.
        raise ValueError(
            f"unknown isolation mode {mode!r}; expected one of {ISOLATION_MODES}"
        )
    profile_path = profile_path or profile_for(mode)

    if platform.system() == "Darwin":
        # -f rather than -p: a profile passed inline shares the argv with the
        # model's own command text, and a command containing a quote could then
        # terminate the profile early. From a file it cannot.
        return ["sandbox-exec", "-f", str(profile_path), "/bin/sh", "-c", cmd]

    if shutil.which("unshare"):
        # --net gives the process an empty network namespace with a loopback
        # interface of its own, so loopback "works" but reaches nothing the
        # operator is running. That is stricter than the Darwin policy for
        # deny-external and worth noting when comparing across platforms.
        return ["unshare", "--net", "--", "/bin/sh", "-c", cmd]

    if shutil.which("bwrap"):
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
