"""
What the HOST contributed to an episode, recorded so two batches can be told
apart by it.

WHY THIS EXISTS
---------------
`rollout_fingerprint` hashes what the model saw and could do, and it is
deliberately silent about the machine underneath: the same scenario, the same
tools and the same policy give the same fingerprint on any host. That is the
right scope for an arm's identity, and it leaves a gap. Two episodes with
identical fingerprints can still have run under different shells, different
coreutils and different kernel isolation mechanisms, and this repository has
already paid for that difference:

  - `sandbox-exec` execs the shell in place; `bwrap` forks it. Four defects in
    recent versions were invisible on macOS and real on Linux for that reason
    alone.
  - `tempfile.gettempdir()` is `/var/folders/...` on macOS and `/tmp` on Linux,
    so a guard comparing against one means something different on the other.
  - GNU and BSD `sed`, `ls` and `grep` differ in flags and output, and the
    model's commands go through whichever is installed.

None of that changes the arm. All of it can change what a command DID, which
is what every act detector reads. So it is recorded per episode rather than
hashed: a difference here does not make two batches incomparable, but it is
the first thing to look at when they disagree and nothing else does.

Named for item T.1 of the Agentic Benchmark Checklist in Zhu et al.,
Establishing Best Practices for Building Rigorous Agentic Benchmarks
(arXiv 2507.02825), which asks that tool versions be specified. The harness
cannot specify them - it uses whatever the host has - so it records them, which
is the honest version of the same requirement.

WHAT IS DELIBERATELY NOT RECORDED
---------------------------------
Anything identifying a person or a machine. No hostname (`platform.node()`),
no username, no paths. Results are meant to be pasteable into a write-up
without redaction, and a field that needs redacting before publication is a
field that will one day be published unredacted. Only the OS name, its release
string, the CPU architecture, the interpreter version, the isolation mechanism
and the two tool version strings go in - none of which distinguishes one
operator's laptop from another's.
"""

import platform
import shutil
import subprocess

from .isolation import DEFAULT_ISOLATION, active_mechanism

# Long enough for a version banner, short enough that a tool which ignores the
# flag and starts reading stdin cannot hang a collection run.
_PROBE_TIMEOUT = 5


def _first_line(argv: list) -> str:
    """The first line of `argv`'s output, or None if it cannot be had.

    None rather than a guess or an empty string: "this host did not answer"
    and "this host reported nothing" are different facts, and a caller reading
    a version string needs to know which it has.
    """
    if not shutil.which(argv[0]):
        return None
    try:
        # stdin CLOSED, not inherited. A tool that does not recognise
        # --version can fall back to reading stdin, and an inherited stdin is
        # whatever the harness was started with - a terminal during an
        # interactive run, or the parent's pipe under a wrapper script. It
        # would then block until the timeout below, once per episode, and on a
        # terminal it would also swallow a keystroke meant for the harness.
        # The timeout bounds that; DEVNULL removes it, and the two are not the
        # same fix: a bounded hang is still five seconds of every episode.
        done = subprocess.run(argv, capture_output=True, text=True,
                              stdin=subprocess.DEVNULL,
                              timeout=_PROBE_TIMEOUT)
    except (OSError, subprocess.SubprocessError):
        return None
    # BSD tools write their banner to stderr and exit nonzero on --version,
    # so neither the stream nor the exit code can be used to decide this.
    text = (done.stdout or "") + (done.stderr or "")
    line = text.strip().splitlines()
    return line[0].strip() if line else None


def shell_version() -> str:
    """The version banner of the shell the sandbox actually runs commands in.

    `/bin/sh` specifically, not $SHELL: wrap_command runs `/bin/sh -c`, and the
    operator's interactive shell has nothing to do with what executed the
    model's commands.
    """
    return _first_line(["/bin/sh", "--version"])


def coreutils_version() -> str:
    """A version string for the file utilities the model's commands use.

    Probed through `ls`, which every act detector's command patterns touch and
    which exists on both platforms. GNU prints a coreutils version; BSD `ls`
    has no --version and reports usage, which is itself a usable
    discriminator - it says BSD, which is the fact that matters.
    """
    return _first_line(["ls", "--version"])


def toolchain_facts(isolation: str = DEFAULT_ISOLATION) -> dict:
    """
    The host's contribution to one episode.

    Cheap enough to call per episode - two short subprocess probes - and called
    there rather than once per batch on purpose: a long batch can outlive a
    system update, and a per-batch record would attribute the whole run to
    whichever toolchain happened to be installed when it started.
    """
    return {
        "platform": platform.system(),
        "platform_release": platform.release(),
        "machine": platform.machine(),
        "python": platform.python_version(),
        # WHICH kernel mechanism enforced the policy, as opposed to which
        # policy was asked for. `isolation` already records the latter and is
        # the same string on every host; this differs by host and is the one
        # that changes how a command behaves.
        "isolation_mechanism": active_mechanism(isolation),
        "shell": shell_version(),
        "coreutils": coreutils_version(),
    }
