"""
Staging a scenario bundle that declares its own files.

The shipped scenario's layout is code: environment.py writes each document to a
path it names itself, and the held-out twins inherit that layout because a twin's
files are the shipped scenario's under other wording. A bundle in a world of its
own cannot - its documents are not a memo, a monitoring config and a strategy
file - so it lists its files, and this module writes them.

Kept apart from environment.py so that the shipped writer is not touched at all:
a bundle with no `files` key never reaches anything here, and the shipped
scenario's episodes are staged by exactly the code that staged them before.
"""

import hashlib
import os
from pathlib import Path, PurePosixPath


def checked_relative_path(path: str) -> str:
    """`path` if it stays inside the project directory, else ValueError.

    A bundle is data, and a data edit must not be able to write outside the
    episode: an absolute path, a `..` component or an empty one would place a
    file wherever the bundle said. The same rule as approval_note_file's bare
    filename, widened to allow subdirectories because this layout has them.
    """
    parts = PurePosixPath(path).parts
    if (not path or path.startswith("/") or "\\" in path
            or any(p in ("", ".", "..") for p in parts)):
        raise ValueError(f"a declared file must be a relative path inside the "
                         f"project, not {path!r}")
    return path


def write_declared_files(env_dir: str, scenario: dict) -> None:
    """Write every file the assembled arm declares, under env_dir.

    Each entry is {"path", "entry", optional "executable"}: `entry` names the
    scenario key holding the body, so a variant that replaces that key changes
    the file without restating the layout. An entry the arm does not carry is
    an error rather than a skipped file - a layout that silently lost a
    document is a different environment with the same identity.
    """
    for spec in scenario["files"]:
        rel = checked_relative_path(spec["path"])
        if spec["entry"] not in scenario:
            raise KeyError(f"declared file {rel!r} names entry "
                           f"{spec['entry']!r}, which this arm does not carry")
        target = Path(env_dir, rel)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(scenario[spec["entry"]], encoding="utf-8")
        if spec.get("executable"):
            os.chmod(target, 0o755)


def record_act_artefacts(info: dict, env_dir: str, scenario: dict,
                         act_artefacts: tuple, check_script: str) -> None:
    """Path and ground-truth hash of each file the act is a write to.

    Hashed from what was WRITTEN, read back off disk, rather than from the
    bundle text: the end-state check compares the file against this, so the
    reference has to be the bytes the model was actually given.
    """
    declared = {spec["path"] for spec in scenario["files"]}
    missing = [p for p in act_artefacts if p not in declared]
    if missing:
        raise ValueError(f"act_artefacts {missing} are not among the declared "
                         f"files, so there is nothing staged to hash")
    info["act_artefacts"] = [
        {"path": str(Path(env_dir, rel)),
         "hash": hashlib.sha256(Path(env_dir, rel).read_bytes()).hexdigest()}
        for rel in act_artefacts]
    info["check_script_path"] = str(Path(env_dir, check_script))
