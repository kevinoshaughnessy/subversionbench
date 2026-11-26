"""
The tools an episode is offered, when its bundle declares its own instead of the shell.

A bundle that declares `tools` offers exactly those, and no `bash`. Each declared tool names
an `argv`, a command line whose entries are literal words or `{field}` placeholders filled from
the call's input. A call runs as that command line, every word shell-quoted, through the same
sandbox as a shell command, and is recorded in the transcript as that command. So what the
call does, and how it is read afterwards, is what the same command typed into the shell would
be; the model just cannot type anything else.

Exists for the single-turn blackmail port. With a shell and one reply, Kimi K2.6 spent most
replies listing the directory and sent nothing (r1: 18 of 20 base replies; r2, told the mail
tool needed no checking: 6 of 10), so the bundle offers only a mail tool.

A bundle without `tools` is offered config.TOOLS, as every bundle was before, and its calls
are read as shell commands; nothing it assembles or records changes.
"""
import shlex

from .config import TOOLS
from .sandbox import tool_input_cmd
from .scenario import DECLARED_TOOLS

_BY_NAME = {t["name"]: t for t in DECLARED_TOOLS}


def tools_offered(declared=DECLARED_TOOLS) -> list:
    """What the API is sent: the declared tools without their argv, or the shell."""
    if not declared:
        return TOOLS
    return [{k: v for k, v in t.items() if k != "argv"} for t in declared]


def _field(word: str):
    return word[1:-1] if len(word) > 2 and word[0] == "{" and word[-1] == "}" else None


def sandbox_input(block, by_name=None) -> dict:
    """What the sandbox is given: a shell call's own input, untouched, so a call missing its
    command is still told which keys it sent; a declared tool's built command line."""
    by_name = _BY_NAME if by_name is None else by_name
    if not by_name:
        return block.input
    return {"cmd": command_of(block, by_name)}


def command_of(block, by_name=None) -> str:
    """The command line a tool_use block runs.

    A declared tool's argv with each placeholder filled from the input and every word quoted;
    a call missing a field becomes a command that says which and sends nothing. Where the
    bundle declares tools, a call to any other name, `bash` included, is refused the same way:
    a model can name a tool it was not offered, and run as a shell command it would hand back
    the shell the bundle exists to withhold. Where it declares none, every call is a shell
    command, read as it always was.
    """
    by_name = _BY_NAME if by_name is None else by_name
    if not by_name:
        return tool_input_cmd(block.input)
    name = getattr(block, "name", None)
    tool = by_name.get(name)
    if tool is None:
        return _refusal(f"Error: there is no tool named {name}; the tools offered are "
                        f"{', '.join(sorted(by_name))}. Nothing was run.")
    inputs = block.input if isinstance(block.input, dict) else {}
    missing = [f for f in map(_field, tool["argv"]) if f and not isinstance(inputs.get(f), str)]
    if missing:
        return _refusal(f"Error: {name} needs {', '.join(missing)}; nothing was sent.")
    return " ".join(shlex.quote(inputs[_field(w)] if _field(w) else w) for w in tool["argv"])


def _refusal(message: str) -> str:
    return f"echo {shlex.quote(message)} >&2; exit 2"
