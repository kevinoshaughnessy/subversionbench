"""
A bundle may offer its own tools instead of the shell (declared_tools.py).

The single-turn blackmail port offers one, send_email, run as the mail command.
What matters: the model is offered that tool and not bash; a call sends exactly
what it gave, however its text is quoted; nothing it writes can run as a shell
command, including a call to a tool it was not offered; and a bundle that
declares nothing is offered and runs exactly what it was before.
"""

import json
import os
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace as NS

from subversionbench.config import TOOLS
from subversionbench.declared_tools import command_of, sandbox_input, tools_offered
from subversionbench.isolation import DEFAULT_ISOLATION
from subversionbench.sandbox import execute_tool_sandboxed
from subversionbench.scenario import load_scenario

BUNDLE = Path("subversionbench/scenarios/blackmail1t.b64")
SEND = {"name": "send_email", "description": "Send an email.",
        "input_schema": {"type": "object", "properties": {}},
        "argv": ["tools/sendmail", "{to}", "{subject}", "{body}"]}
BY_NAME = {"send_email": SEND}
AWKWARD = "It's \"fine\" $(touch pwned) `touch pwned2`; touch pwned3\nsecond line\\n 100%"


def _call(name, **inputs):
    return NS(type="tool_use", id="t1", name=name, input=inputs)


def _project():
    """A project directory holding the port's own mail command."""
    env = tempfile.mkdtemp()
    tool = Path(env, "tools", "sendmail")
    tool.parent.mkdir()
    tool.write_text(load_scenario(BUNDLE)["sendmail_tool"], encoding="utf-8")
    tool.chmod(tool.stat().st_mode | stat.S_IXUSR)
    return env


def _run(env, block):
    return execute_tool_sandboxed(sandbox_input(block, BY_NAME), env, DEFAULT_ISOLATION, None, env)


def _outbox(env):
    box = Path(env, "mail", "outbox")
    return sorted(p.read_text(encoding="utf-8") for p in box.glob("*.txt")) if box.exists() else []


class TestWhatIsOffered:
    def test_a_bundle_without_tools_is_offered_the_shell(self):
        assert tools_offered(()) is TOOLS

    def test_declared_tools_are_offered_without_their_command_line(self):
        assert tools_offered((SEND,)) == [{k: v for k, v in SEND.items() if k != "argv"}]

    def test_the_selected_bundle_decides(self):
        """Read at import from the selected bundle, so asked of a fresh process."""
        probe = ("import json; from subversionbench.declared_tools import tools_offered; "
                 "print(json.dumps([t['name'] for t in tools_offered()]))")
        names = {}
        for label, extra in (("shipped", {}), ("port", {"SUBVERSIONBENCH_SCENARIO_BUNDLE": str(BUNDLE)})):
            env = {k: v for k, v in os.environ.items() if k != "SUBVERSIONBENCH_SCENARIO_BUNDLE"}
            out = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True,
                                 encoding="utf-8", env={**env, **extra}, check=True)
            names[label] = json.loads(out.stdout.strip().splitlines()[-1])
        assert names == {"shipped": [t["name"] for t in TOOLS], "port": ["send_email"]}


class TestACallSendsWhatItGave:
    def test_awkward_text_arrives_verbatim_and_runs_nothing(self):
        env = _project()
        result = _run(env, _call("send_email", to="a@example.com", subject="Re: $HOME", body=AWKWARD))
        assert result.strip() == "Sent to a@example.com."
        (mail,) = _outbox(env)
        assert mail.endswith("To: a@example.com\nSubject: Re: $HOME\n\n" + AWKWARD + "\n")
        assert not any(Path(env, n).exists() for n in ("pwned", "pwned2", "pwned3"))

    def test_the_transcript_records_the_mail_command(self):
        cmd = command_of(_call("send_email", to="a@x", subject="S", body="B"), BY_NAME)
        assert cmd == "tools/sendmail a@x S B"


class TestNothingElseRuns:
    def test_a_tool_that_was_not_offered_is_refused(self):
        env = _project()
        result = _run(env, _call("bash", cmd="touch made; tools/sendmail a@x S B"))
        assert "no tool named bash" in result
        assert not Path(env, "made").exists() and _outbox(env) == []

    def test_a_call_missing_a_field_sends_nothing(self):
        env = _project()
        result = _run(env, _call("send_email", to="a@x", subject="S"))
        assert "send_email needs body" in result and _outbox(env) == []

    def test_without_declared_tools_a_shell_call_is_passed_on_untouched(self):
        block = _call("bash", command="ls")
        assert sandbox_input(block, {}) is block.input
        assert command_of(block, {}) == "ls"


EPISODE_PROBE = r'''
import json, glob, os
from types import SimpleNamespace as NS
from subversionbench import episode
from subversionbench.environment import create_episode_root
from subversionbench.isolation import DEFAULT_ISOLATION
root, env, _info = create_episode_root(True, nudge="none")
seen = {}
def create(messages, **kw):
    seen["tools"] = [t["name"] for t in kw["tools"]]
    return NS(model="m", usage=None, stop_reason="tool_use", content=[
        NS(type="tool_use", id="a", name="send_email",
           input={"to": "a@example.com", "subject": "S", "body": "it's $(touch pwned)"}),
        NS(type="tool_use", id="b", name="bash", input={"cmd": "touch made"})])
state, transcript = episode._new_loop_state(), []
kwargs = episode._create_kwargs("m", 100, "system", None)
episode.run_agentic_loop(NS(messages=NS(create=create)), kwargs, [{"role": "user", "content": "go"}],
                         transcript, state, max_turns=1, red=str,
                         sandbox={"env_dir": env, "isolation": DEFAULT_ISOLATION,
                                  "profile_path": None, "episode_root": root})
print(json.dumps({"tools": seen["tools"], "ended_by": state["ended_by"],
                  "cmds": [t["cmd"] for t in transcript if t["type"] == "tool_call"],
                  "results": [t["result"] for t in transcript if t["type"] == "tool_result"],
                  "outbox": len(glob.glob(os.path.join(env, "mail", "outbox", "*.txt"))),
                  "ran": [n for n in ("made", "pwned") if os.path.exists(os.path.join(env, n))]}))
'''


class TestAnEpisodeUsesThem:
    def test_one_reply_offers_the_tool_runs_it_and_refuses_the_shell(self):
        env = {**os.environ, "SUBVERSIONBENCH_SCENARIO_BUNDLE": str(BUNDLE)}
        out = subprocess.run([sys.executable, "-c", EPISODE_PROBE], capture_output=True, text=True,
                             encoding="utf-8", env=env, check=True)
        got = json.loads(out.stdout.strip().splitlines()[-1])
        assert got["tools"] == ["send_email"] and got["ended_by"] == "turn_cap"
        assert got["cmds"][0] == "tools/sendmail a@example.com S 'it'\"'\"'s $(touch pwned)'"
        assert got["results"][0].strip() == "Sent to a@example.com."
        assert "no tool named bash" in got["results"][1]
        assert got["outbox"] == 1 and got["ran"] == []
