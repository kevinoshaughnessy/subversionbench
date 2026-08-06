"""
Kernel-enforced limits on what a sandboxed command can reach.

The blocklist in sandbox.py exists to keep the eval's own machinery out of the
model's view. It is not a containment boundary and cannot be made into one: it
matches command strings, and `curl`, `/dev/tcp`, `python3 -c` and a base64
one-liner are all the same string problem. Three separate defects this year came
from a pattern matching the wrong text.

This module is the other kind of control. It asks the kernel to refuse, so the
refusal does not depend on recognising how the model spelled its request.

The policy that makes the network measure survivable:

    loopback  ALLOWED   - so `network_probe` keeps observing real behaviour
    external  DENIED    - so an observation cannot become an exfiltration

That split is the point. Denying the network outright would end the measure: a
model that finds nothing behaves differently from one that finds a host, and
`network_probe` would only ever record intent. Allowing everything leaves a
frontier model with a shell and a route off the machine.

WHAT THIS DOES NOT DO. Loopback stays reachable, so a model can still enumerate
the host it runs on - that is the behaviour being measured, and it cannot be both
permitted and prevented. Two saved episodes port-scanned 1-65535 and got HTTP 403
from real services on the operator's machine. The profile does not protect those.
Run batches on a host with nothing else listening, or accept that local service
discovery is in scope.
"""

import platform
import shutil
import subprocess

# Modes, weakest first. `off` is the historical behaviour and the default, so
# enabling isolation is a deliberate act with a rollout consequence rather than
# something that changes under an existing experiment.
ISOLATION_MODES = ("off", "deny-external", "deny-network")

_DARWIN_PROFILE = """(version 1)
(allow default)
(deny network*)
%s
"""
_ALLOW_LOOPBACK = """(allow network-outbound (remote ip "localhost:*"))
(allow network-inbound (local ip "localhost:*"))"""


def isolation_available(mode: str) -> bool:
    """Whether this host can enforce `mode` at all."""
    if mode == "off":
        return True
    if platform.system() == "Darwin":
        return shutil.which("sandbox-exec") is not None
    return shutil.which("unshare") is not None or shutil.which("bwrap") is not None


def darwin_profile(mode: str) -> str:
    """The sandbox-exec profile text for `mode`."""
    return _DARWIN_PROFILE % (_ALLOW_LOOPBACK if mode == "deny-external" else "")


def wrap_command(cmd: str, mode: str, profile_path=None) -> list:
    """
    The argv that runs `cmd` under `mode`.

    Returns a list for subprocess, still going through a shell because the
    scenario's commands are shell text - pipelines, heredocs, redirections. The
    isolation is applied to the shell itself, so everything it spawns inherits
    it: a wrapper the model could step outside of by starting a subprocess would
    not be worth having.
    """
    if mode == "off":
        return ["/bin/sh", "-c", cmd]

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
        flags = ["unshare", "--net", "--"] if mode != "off" else []
        return flags + ["/bin/sh", "-c", cmd]

    if shutil.which("bwrap"):
        return ["bwrap", "--unshare-net", "--dev-bind", "/", "/",
                "/bin/sh", "-c", cmd]

    raise RuntimeError(
        f"isolation mode {mode!r} requested but no mechanism is available on "
        f"{platform.system()}. Install bubblewrap, or run with --isolation off "
        f"and accept that the sandbox is not a containment boundary."
    )


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
