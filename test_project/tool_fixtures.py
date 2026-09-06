"""
Watching a root tool's subprocess boundary without crossing it.

Not named `test_*`, so neither runner collects it as a suite file: pytest looks
for `test_*.py` and so does run_tests.discover_modules. It still counts as suite
rather than shipping source, because conftest.is_test_file decides that by
position - anything under a `test_*/` directory - so the project guards that
apply to tests apply here too.
"""

import json
import subprocess


class _ProbeSpy:
    """Stands in for the fingerprint subprocess, recording what it could see.

    The real probe is a Python subprocess that imports the harness under the
    bundle override, which takes seconds and needs the held-out bundle. What
    is under test is not what it computes but the state it is handed and the
    state left behind afterwards, and both are observable from here.
    """

    def __init__(self, module, returncode=0, stdout=None):
        self.module = module
        self.returncode = returncode
        # Every arm gets a distinguishable fingerprint, so a mapping rebuilt
        # with its pairs the wrong way round does not come back identical.
        self.stdout = stdout if stdout is not None else json.dumps(
            [[o, lure, f"fp-o{o}-l{lure}"]
             for o in (True, False) for lure in (True, False)])
        self.sidecar_at_probe_time = None
        self.env_at_probe_time = None

    def __enter__(self):
        self.saved = self.module.subprocess.run

        def _run(argv, **kwargs):
            path = self.module.PINS_PATH
            self.sidecar_at_probe_time = (
                json.loads(path.read_text(encoding="utf-8"))
                if path.is_file() else None)
            self.env_at_probe_time = dict(kwargs.get("env") or {})
            return subprocess.CompletedProcess(
                argv, self.returncode, self.stdout, "probe failed")

        self.module.subprocess.run = _run
        return self

    def __exit__(self, *exc):
        self.module.subprocess.run = self.saved
        return False
