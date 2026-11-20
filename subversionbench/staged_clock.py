"""
A clock that tells the scenario's time rather than the batch's.

A bundle set on a named day and hour is contradicted by `date`, which reports the
moment the batch ran. In the insider-threat scenario's r2, 34 of 40 episodes ran
`date` and were told it was the day after the emergency they were reading about,
so the call they could cancel had been due a day earlier.

A bundle that declares `clock` gets two things, both installed after every file is
written:

  - a `date` on the command PATH that reports the staged time, advancing from
    `start` at `rate` staged seconds per real second. It lives in the episode
    root, beside the project directory rather than in it, so it is not among the
    files a model lists, and `..` is refused as outside the project;
  - every file and directory in the project stamped with a modification time
    from the staged day: `start` itself, or the `mtime` a declared file names.

What it does not cover: a file the model writes itself carries the real time
(a bundle's own tools can stamp theirs from `date`, as the insider console does), and a
program that reads the clock itself (python's datetime, an absolute /bin/date)
sees the host's. The clock is in the assembled arm, so declaring it moves the
rollout fingerprint; a bundle without it is staged and run exactly as before.
"""

import os
from datetime import datetime
from pathlib import Path

CLOCK_DIR = ".clock"

_SHIM = """#!/bin/sh
now=$(( {start} + ($(/bin/date +%s) - {real0}) * {permille} / 1000 ))
export TZ='{tz}'
case "$(uname)" in
  Darwin) exec /bin/date -r "$now" "$@" ;;
  *) exec /bin/date -d "@$now" "$@" ;;
esac
"""


def _epoch(stamp: str) -> int:
    """Seconds since the epoch of an ISO time that names its offset."""
    when = datetime.fromisoformat(stamp)
    if when.tzinfo is None:
        raise ValueError(f"a staged time must name its UTC offset, not {stamp!r}")
    return int(when.timestamp())


def _stamp_project(episode_root: str, env_dir: str, scenario: dict, start: int) -> None:
    """Every file and directory at `start`, then each declared `mtime` over it.

    The project directory and the root as well as what they hold: `ls -la`
    prints `.` and `..` with the rest, and `..` is the root.
    """
    for folder in (episode_root, env_dir):
        os.utime(folder, (start, start))
    for parent, dirs, files in os.walk(env_dir):
        for name in dirs + files:
            os.utime(os.path.join(parent, name), (start, start))
    for spec in scenario.get("files", ()):
        if "mtime" in spec:
            at = _epoch(spec["mtime"])
            os.utime(Path(env_dir, spec["path"]), (at, at))


def install(episode_root: str, env_dir: str, scenario: dict, real_now: int = None) -> dict:
    """Stage the bundle's clock for one episode, returning what was staged."""
    clock = scenario["clock"]
    start = _epoch(clock["start"])
    real0 = int(datetime.now().timestamp()) if real_now is None else real_now
    permille = round(1000 * clock.get("rate", 1))
    shim_dir = Path(episode_root, CLOCK_DIR)
    shim_dir.mkdir()
    shim = shim_dir / "date"
    shim.write_text(_SHIM.format(start=start, real0=real0, permille=permille,
                                 tz=clock.get("tz", "UTC")), encoding="utf-8")
    os.chmod(shim, 0o755)
    _stamp_project(episode_root, env_dir, scenario, start)
    return {"start": clock["start"], "rate": clock.get("rate", 1),
            "tz": clock.get("tz", "UTC"), "real_start": real0}


def command_path(confine_to: str, default: str) -> str:
    """The PATH a confined command runs with: the staged clock first, if any."""
    shim_dir = os.path.join(confine_to, CLOCK_DIR)
    return f"{shim_dir}:{default}" if os.path.isdir(shim_dir) else default
