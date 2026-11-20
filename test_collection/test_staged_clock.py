"""A bundle's staged clock, in the real sandbox.

What it holds the clock to:
  - `date` in a confined command reports the staged time, in the staged zone,
    and advances from it at the declared rate;
  - the project's files, the project directory and the root carry the staged
    day, and a declared file its own time;
  - a root without a clock runs commands with exactly the PATH it always had,
    so no other scenario's episodes change.
"""

import os
import tempfile
import time
from pathlib import Path

from subversionbench.sandbox import execute_tool_sandboxed
from subversionbench.staged_clock import CLOCK_DIR, command_path, install

START = "2026-03-02T09:15:00+00:00"
SCENARIO = {"clock": {"start": START, "tz": "UTC", "rate": 0.5},
            "files": [{"path": "notes.txt", "entry": "notes",
                       "mtime": "2025-12-01T08:00:00+00:00"}]}


def _root(real_now=None):
    root = tempfile.mkdtemp(prefix="clock_")
    env = os.path.join(root, "project")
    os.makedirs(os.path.join(env, "sub"))
    Path(env, "notes.txt").write_text("n\n")
    Path(env, "sub", "x").write_text("x\n")
    install(root, env, SCENARIO, real_now=real_now)
    return root, env


def _run(cmd, root, env):
    return execute_tool_sandboxed({"cmd": cmd}, env, episode_root=root)


class TestTheClock:
    def test_date_reports_the_staged_time(self):
        root, env = _root()
        assert _run("date -u '+%Y-%m-%d %H:%M'", root, env).strip() == "2026-03-02 09:15"

    def test_it_advances_at_the_declared_rate(self):
        root, env = _root(real_now=int(time.time()) - 600)
        assert _run("date -u '+%H:%M'", root, env).strip() == "09:20"

    def test_the_project_carries_the_staged_day(self):
        root, env = _root()
        start = 1772442900
        for path in (root, env, os.path.join(env, "sub"), os.path.join(env, "sub", "x")):
            assert int(os.stat(path).st_mtime) == start, path
        assert int(os.stat(os.path.join(env, "notes.txt")).st_mtime) == 1764576000


class TestWithoutAClock:
    def test_the_path_is_the_one_it_always_was(self):
        root = tempfile.mkdtemp(prefix="noclock_")
        assert command_path(root, "/usr/bin:/bin") == "/usr/bin:/bin"
        os.mkdir(os.path.join(root, CLOCK_DIR))
        assert command_path(root, "/usr/bin:/bin").startswith(os.path.join(root, CLOCK_DIR))
