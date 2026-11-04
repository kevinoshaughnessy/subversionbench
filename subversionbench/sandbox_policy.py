"""
What a scenario bundle may declare about how its sandbox answers, and the one
place the sandbox and grading both ask.

The shipped scenario and the goal-guarding one declare nothing, and for them
every function here is the sandbox's own rule unchanged: their episodes are
refused, and scored, exactly as before. A bundle in a world of its own may
declare `sandbox_policy` with any of three keys, each fixing a defect the
impossible-task scenario's r1 found:

- `refusals`: a message per refusal kind (sandbox.refusal_kind), so a refusal
  says what happened. r1 answered a Python version check with "path outside the
  engagement workspace", which was untrue.
- `tool_discovery`: `which`, `command -v` and `type` answer truthfully rather
  than being refused. r1 refused `which python3` in 84 episodes while Python
  ran in 1,333 commands: the sandbox denied a tool the model then found works.
- `interpreter_programs_are_data`: a quoted awk, perl, sed, python, ruby or
  node program is data to the traversal check, not navigation, so a `..` in a
  regex is not refused as leaving the project. r1 refused three commands that
  way. The kernel boundary still holds whatever the program does.

Read from the selected bundle at import, as act artefacts are, so collection
and every later re-reading of a corpus apply the same rule - provided the
bundle the corpus was collected under is selected (r1: impossible1.b64).
"""

import re
import shutil

from .config import SANDBOX_REFUSAL
from .scenario import SANDBOX_POLICY
from .shell_text import _quoted_spans

_SEPARATOR = re.compile(r"&&|\|\||;|\||\n")
_DISCOVERY = re.compile(
    r"^\s*(?:which|command\s+-v|type(?:\s+-[pP])?)\s+((?:[\w.+-]+\s*)+)$")
_INTERPRETERS = {"awk", "gawk", "mawk", "nawk", "perl", "sed", "python",
                 "python3", "ruby", "node", "jq"}


def _segments(cmd: str):
    """(start, end) of each command between sequencing operators."""
    start = 0
    for match in _SEPARATOR.finditer(cmd):
        yield start, match.start()
        start = match.end()
    yield start, len(cmd)


def _discovery_answer(names: list) -> str:
    """A shell fragment that prints what `which` would for `names`, and fails
    if any is missing, as which does. Found tools are reported under /usr/bin,
    which names no host layout; a missing one prints nothing."""
    found = [n for n in names if shutil.which(n)]
    shown = "printf '%s\\n' " + " ".join(f"/usr/bin/{n}" for n in found)
    return f"({shown if found else 'true'}; exit {0 if len(found) == len(names) else 1})"


def rewrite_discovery(cmd: str, answer=_discovery_answer) -> str:
    """`cmd` with each discovery segment replaced by its answer. The blocking
    check passes an answer of `true`: the path an answer prints is its text,
    not a path the command reads, and checked as written it would be refused as
    reading /usr/bin."""
    parts, last = [], 0
    for start, end in _segments(cmd):
        match = _DISCOVERY.match(cmd[start:end])
        if match:
            parts += [cmd[last:start], answer(match.group(1).split())]
            last = end
    return "".join(parts) + cmd[last:]


def _programs_blanked(cmd: str) -> str:
    """`cmd` with every quoted argument of an interpreter replaced by spaces,
    for the traversal check only; the command that runs is unchanged."""
    out = list(cmd)
    for start, end in _quoted_spans(cmd):
        boundary = max([m.end() for m in _SEPARATOR.finditer(cmd, 0, start)],
                       default=0)
        words = cmd[boundary:start].split()
        if words and words[0].rsplit("/", 1)[-1] in _INTERPRETERS:
            out[start:end] = " " * (end - start)
    return "".join(out)


def _as_checked(cmd: str) -> str:
    """The text the blocking rule is applied to under the policy."""
    if SANDBOX_POLICY.get("tool_discovery"):
        cmd = rewrite_discovery(cmd, answer=lambda names: "true")
    if SANDBOX_POLICY.get("interpreter_programs_are_data"):
        cmd = _programs_blanked(cmd)
    return cmd


def blocked(cmd: str, env_dir: str) -> bool:
    """Whether the sandbox refuses `cmd`: would_be_blocked under the policy."""
    from .sandbox import would_be_blocked
    return would_be_blocked(_as_checked(cmd), env_dir)


def kind(cmd: str, env_dir: str):
    """Why the sandbox refused `cmd`: refusal_kind under the policy."""
    from .sandbox import refusal_kind
    return refusal_kind(_as_checked(cmd), env_dir)


def screen(cmd: str, env_dir: str) -> tuple:
    """(refusal text or None, the command to run)."""
    run = (rewrite_discovery(cmd) if SANDBOX_POLICY.get("tool_discovery")
           else cmd)
    if not blocked(cmd, env_dir):
        return None, run
    message = SANDBOX_POLICY.get("refusals", {}).get(kind(cmd, env_dir))
    return message or SANDBOX_REFUSAL, run
