"""
Computing an alternative bundle's fingerprints, under the override that selects it.

Pinning cannot be done in the process that wants the pins. The fingerprint
covers the sandbox display path and the task file's name as well as the
scenario text, and both are derived from the bundle at import - so the
computation has to run with SUBVERSIONBENCH_SCENARIO_BUNDLE set, in a fresh
interpreter. And rollout_pins refuses to import under the override without the
very sidecar the computation is producing. A provisional sidecar breaks that
cycle, in a subprocess, and is taken away again whatever happens.

One implementation for every bundle tool, because the restore is the part that
was once wrong: heldout_tool.py had it to itself, and a second copy for the next
bundle would be a second chance to leave a provisional sidecar behind.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

# Fingerprints for the provisional sidecar. Not hex, so they can never equal a
# real fingerprint: if a pin is interrupted and one is left behind, the drift
# guard refuses to start rather than letting a batch collect against pins
# nothing produced.
PROVISIONAL = "PROVISIONAL-"


def run_under_override(root: Path, bundle_for_run: Path, sidecar: Path,
                       provisional: dict, probe: str):
    """`probe`'s JSON output, run with `bundle_for_run` selected and
    `provisional` standing in as its sidecar."""
    previous = sidecar.read_bytes() if sidecar.is_file() else None
    sidecar.write_text(json.dumps(provisional), encoding="utf-8")
    env = dict(os.environ)
    env["SUBVERSIONBENCH_SCENARIO_BUNDLE"] = str(bundle_for_run)
    try:
        result = subprocess.run([sys.executable, "-c", probe],
                                cwd=root, env=env, capture_output=True,
                                text=True)
        if result.returncode:
            raise RuntimeError(
                f"computing fingerprints under the override failed:\n"
                f"{result.stderr.rstrip()}")
        return json.loads(result.stdout)
    finally:
        # Restores on EVERY exit, not only on failure. This function computes;
        # the caller decides whether to accept. Leaving the provisional sidecar
        # behind on success made the accept step implicit, and an interrupted
        # --pin then left the bundle pinned to a value nothing produced.
        if previous is None:
            sidecar.unlink(missing_ok=True)
        else:
            sidecar.write_bytes(previous)
