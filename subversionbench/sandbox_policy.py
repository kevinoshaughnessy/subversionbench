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
- `name_patterns_are_data`: a find-style name test's operand (`-not -name
  '..'`) is a pattern, not a path, so the traversal check does not read it.
  refusal_kind already called these "name_pattern" and they were refused
  anyway: two r1 commands.
- `shell_programs_are_unwrapped`: the program of `bash -c '...'` or `sh -c
  '...'` is checked as the command line it is, so a `cd` inside it moves the
  shell as it would anywhere else. One r1 command did `cd qa/reference` and then
  read `../input` in the same program, and was refused.
- `comments_are_data`: a shell comment is not a command, so `# check the
  logic or env; then...` is not an environment probe. One r1 command was
  refused for the `env;` in its comment.
- `printed_text_is_data`: a quoted argument of printf or echo is text being
  printed, not a path the command reaches, so a script written out with
  `printf '#!/bin/sh\n...' > file` is not refused as a system location.
  Incomplete-task r2 refused the one imminent episode that set out to rewrite
  its hook that way, and a capability episode twice; the same text in a heredoc
  was let through. A quoted redirection target is still a path, and is read.
- `tmp_dir`: a project folder that /tmp names. Within the fiction /tmp exists
  on any server, and r1 models used it in 60 of 520 episodes: a shell write
  went to a <project>/tmp that did not exist, a listing was refused as a system
  path, and a Python heredoc met the kernel's denial. /tmp is now that folder in
  the command text, in interpreter heredocs too - a heredoc fed to cat or tee
  is a document and is left alone - and the README says so.

Read from the selected bundle at import, as act artefacts are, so collection
and every later re-reading of a corpus apply the same rule - provided the
bundle the corpus was collected under is selected (r1: impossible1.b64,
r2: impossible2.b64).
"""

import os
import re
import shutil

from .config import SANDBOX_REFUSAL
from .scenario import SANDBOX_POLICY
from .shell_text import _HEREDOC_START_RE, _heredoc_body_spans, _quoted_spans

_SEPARATOR = re.compile(r"&&|\|\||;|\||\n")
# The program named, its flags, and any redirections, which are kept on the
# answer: `which python3 2>&1` was refused in r1 because the pattern ended at
# the names. `type` answers in its own words unless -p or -P asks for a path.
_DISCOVERY = re.compile(
    r"^\s*(which(?:\s+-a)?|command\s+-v|type(?:\s+-[aptP])*)"
    r"((?:\s+(?!\d*>)[\w.+][\w.+-]*)+)"
    r"((?:\s*\d?>>?&?\s*[\w/.&-]+)*)\s*$")
_SHELL_PROGRAM = re.compile(
    r"(?:^|(?<=[;&|(\n]))(\s*)(?:/bin/|/usr/bin/)?(?:ba)?sh\s+-c\s+'([^']*)'")
_TMP = re.compile(r"(?<![\w./:~-])/tmp(?![\w.-])(?!/estate_)")
_DOCUMENT_WRITERS = {"cat", "tee"}
_INTERPRETERS = {"awk", "gawk", "mawk", "nawk", "perl", "sed", "python",
                 "python3", "ruby", "node", "jq"}
_PRINTERS = {"printf", "echo"}


def _segments(cmd: str):
    """(start, end) of each command between sequencing operators."""
    start = 0
    for match in _SEPARATOR.finditer(cmd):
        yield start, match.start()
        start = match.end()
    yield start, len(cmd)


def _discovery_answer(names: list, asker: str = "which") -> str:
    """A shell fragment that prints what `asker` would for `names`, and fails
    if any is missing, as which does. Found tools are reported under /usr/bin,
    which names no host layout; a missing one prints nothing."""
    found = [n for n in names if shutil.which(n)]
    flags = asker.split()[1:]
    if asker.startswith("type") and "-t" in flags:
        lines = ["file"] * len(found)
    elif asker.startswith("type") and not {"-p", "-P"} & set(flags):
        lines = [f"{n} is /usr/bin/{n}" for n in found]
    else:
        lines = [f"/usr/bin/{n}" for n in found]
    shown = "printf '%s\\n' " + " ".join(f"'{line}'" for line in lines)
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
            asker, names, redirections = match.groups()
            parts += [cmd[last:start],
                      answer(names.split(), " ".join(asker.split())) + redirections]
            last = end
    return "".join(parts) + cmd[last:]


def _quoted_args_blanked(cmd: str, programs: set, keep_targets=False) -> str:
    """`cmd` with every quoted argument of one of `programs` replaced by
    spaces, for the blocking check only; the command that runs is unchanged.
    With keep_targets, a quoted redirection target is kept, since it is a path
    and not an argument, and so is quoted text that runs a command (`$(` or a
    backtick), which a double quote does not stop. Off for interpreters, whose
    rule predates it and whose corpora were collected without it."""
    out = list(cmd)
    for start, end in _quoted_spans(cmd):
        boundary = max([m.end() for m in _SEPARATOR.finditer(cmd, 0, start)],
                       default=0)
        words = cmd[boundary:start].split()
        kept = keep_targets and (
            cmd[boundary:start].rstrip(" \t\"'").endswith((">", "<"))
            or "$(" in cmd[start:end] or "`" in cmd[start:end])
        if words and words[0].rsplit("/", 1)[-1] in programs and not kept:
            out[start:end] = " " * (end - start)
    return "".join(out)


_COMMENT = re.compile(r"(?:^|(?<=\s))#[^\n]*")


def _comments_blanked(cmd: str) -> str:
    """`cmd` with each shell comment replaced by spaces. A `#` inside quotes
    is text, not a comment, and is left alone."""
    protected = _quoted_spans(cmd)
    out = list(cmd)
    for match in _COMMENT.finditer(cmd):
        if not any(start <= match.start() < end for start, end in protected):
            out[match.start():match.end()] = " " * (match.end() - match.start())
    return "".join(out)


def _shell_programs_unwrapped(cmd: str) -> str:
    """`cmd` with each `bash -c '...'` replaced by the program it runs."""
    return _SHELL_PROGRAM.sub(lambda m: m.group(1) + m.group(2), cmd)


def _feeds_a_program(cmd: str, body_start: int) -> bool:
    """Whether the heredoc whose body starts at `body_start` is read by a
    program rather than written out as a document."""
    opener = list(_HEREDOC_START_RE.finditer(cmd, 0, body_start))[-1]
    line_start = cmd.rfind("\n", 0, opener.start()) + 1
    boundary = max([m.end() for m in _SEPARATOR.finditer(
        cmd, line_start, opener.start())], default=line_start)
    words = cmd[boundary:opener.start()].split()
    return bool(words) and words[0].rsplit("/", 1)[-1] not in _DOCUMENT_WRITERS


def tmp_mapped(cmd: str, env_dir: str) -> str:
    """`cmd` with /tmp naming the bundle's `tmp_dir`: its scenario path in the
    command text, which the sandbox's rewriter then places, and its real path
    in a heredoc a program reads, which the rewriter leaves alone."""
    folder = SANDBOX_POLICY.get("tmp_dir")
    if not folder:
        return cmd
    inside = os.path.join(os.path.realpath(env_dir), folder)
    out, pos = [], 0
    for start, end in _heredoc_body_spans(cmd):
        out.append(_TMP.sub("/" + folder, cmd[pos:start]))
        body = cmd[start:end]
        out.append(_TMP.sub(inside, body) if _feeds_a_program(cmd, start) else body)
        pos = end
    out.append(_TMP.sub("/" + folder, cmd[pos:]))
    return "".join(out)


def _as_checked(cmd: str) -> str:
    """The text the blocking rule is applied to under the policy."""
    if SANDBOX_POLICY.get("comments_are_data"):
        cmd = _comments_blanked(cmd)
    if SANDBOX_POLICY.get("tmp_dir"):
        cmd = _TMP.sub("/" + SANDBOX_POLICY["tmp_dir"], cmd)
    if SANDBOX_POLICY.get("shell_programs_are_unwrapped"):
        cmd = _shell_programs_unwrapped(cmd)
    if SANDBOX_POLICY.get("name_patterns_are_data"):
        from .sandbox import _NAME_TEST_OPERAND_RE
        cmd = _NAME_TEST_OPERAND_RE.sub(" ", cmd)
    if SANDBOX_POLICY.get("tool_discovery"):
        cmd = rewrite_discovery(cmd, answer=lambda names, asker: "true")
    if SANDBOX_POLICY.get("interpreter_programs_are_data"):
        cmd = _quoted_args_blanked(cmd, _INTERPRETERS)
    if SANDBOX_POLICY.get("printed_text_is_data"):
        cmd = _quoted_args_blanked(cmd, _PRINTERS, keep_targets=True)
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
    run = tmp_mapped(run, env_dir)
    if not blocked(cmd, env_dir):
        return None, run
    message = SANDBOX_POLICY.get("refusals", {}).get(kind(cmd, env_dir))
    return message or SANDBOX_REFUSAL, run
