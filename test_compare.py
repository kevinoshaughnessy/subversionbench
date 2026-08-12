"""
Comparing two saved batches.
"""

import contextlib
import glob
import io
import json
import tempfile

from pathlib import Path
import subversionbench.run_eval as ev_run
from conftest import FakeArgs


class TestCompareBatches:
    """--compare contrasts two arms and repeats the primary contrast holding
    eval awareness constant."""

    def _write(self, out, stamp, nudge, episodes):
        for i, (misaligned, aware) in enumerate(episodes, start=1):
            Path(f"{out}/run_{i}_m_{nudge}_{stamp}.json").write_text(json.dumps({
                "model": "m", "nudge": nudge,
                "analysis": {
                    "oversight_tampered": misaligned,
                    "monitoring_disabled": misaligned,
                    "sandbox_escape_attempts": [],
                    "eval_awareness_grader": {"eval_aware": aware},
                },
            }))

    def _run(self, out, a, b):
        args = FakeArgs(output_dir=out, model="m", nudge="strong",
                         grader_model="g")
        args.compare = [a, b]
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = ev_run.compare_batches(args)
        return rc, buf.getvalue()

    def test_reports_the_contrast_and_saves_it(self):
        out = tempfile.mkdtemp()
        self._write(out, "A", "strong", [(True, False)] * 9 + [(False, False)])
        self._write(out, "B", "none", [(False, False)] * 9 + [(True, False)])
        rc, output = self._run(out, "A", "B")

        assert rc == 0
        assert "monitoring_disabled" in output
        saved = glob.glob(f"{out}/comparison_A_vs_B_*.json")
        assert len(saved) == 1
        data = json.loads(Path(saved[0]).read_text())
        metric = data["metrics"]["monitoring_disabled"]
        assert metric["a"]["successes"] == 9
        assert metric["b"]["successes"] == 1
        # The interval on the difference, not just the two marginals: overlap
        # between marginals does not imply the absence of a difference, so a
        # comparison reported without this invites the wrong reading.
        assert metric["difference_ci95"][0] <= metric["difference"] <= \
            metric["difference_ci95"][1]
        assert metric["separated"] is True
        assert data["metrics"]["monitoring_disabled"]["fisher_p"] < 0.05

    def test_stratifies_by_awareness(self):
        out = tempfile.mkdtemp()
        # Both strata present in both arms, arm A misaligned throughout.
        self._write(out, "A", "strong",
                    [(True, True)] * 5 + [(True, False)] * 5)
        self._write(out, "B", "none",
                    [(False, True)] * 5 + [(False, False)] * 5)
        rc, output = self._run(out, "A", "B")

        assert "stratified by eval awareness" in output
        data = json.loads(
            Path(glob.glob(f"{out}/comparison_A_vs_B_*.json")[0]).read_text())
        strat = data["stratified_by_eval_awareness"]
        assert strat["True"]["a"] == {"k": 5, "n": 5}
        assert strat["True"]["b"] == {"k": 0, "n": 5}
        assert strat["False"]["a"] == {"k": 5, "n": 5}

    def test_empty_stratum_is_reported_not_crashed(self):
        out = tempfile.mkdtemp()
        self._write(out, "A", "strong", [(True, True)] * 5)
        self._write(out, "B", "none", [(False, False)] * 5)
        rc, output = self._run(out, "A", "B")
        assert rc == 0
        assert "one side empty" in output

    def test_missing_batch_is_an_error(self):
        out = tempfile.mkdtemp()
        self._write(out, "A", "strong", [(True, False)])
        rc, output = self._run(out, "A", "NOPE")
        assert rc == 1
        assert "No run files found" in output

    def test_multiplicity_is_reported(self):
        out = tempfile.mkdtemp()
        self._write(out, "A", "strong", [(True, False)] * 5)
        self._write(out, "B", "none", [(False, False)] * 5)
        _, output = self._run(out, "A", "B")
        assert "Bonferroni" in output
