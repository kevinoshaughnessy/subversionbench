"""
Fanning a read-only mode out over every batch in a results directory.

`--model all` exists because backfilling one deterministic field across four
rollouts otherwise took 46 hand-written invocations, which is the kind of chore
that gets half-done.

The interesting test here is test_typed_filters_do_not_leak_between_batches.
resummarise_existing_runs mutates args.effort per batch - deliberately, because
summarise_batch builds the filename it writes from args - and the first version
of the fan-out let that leak. A batch collected at effort "medium" left every
later model filtered to "medium", so two of four groups matched nothing and the
backfill would have reported partial success.
"""

import argparse
import json
import os
import tempfile
from pathlib import Path

from subversionbench.run_eval import ALL, discover_batches, fan_out_read_mode


def _run_file(d, n, model, nudge, effort=None, stamp="20260101T000000"):
    """A run file with just the fields discovery reads."""
    parts = ["run", str(n), model.replace("/", "_"), nudge]
    if effort:
        parts.append(effort)
    name = "_".join(parts) + f"_{stamp}.json"
    Path(d, name).write_text(json.dumps(
        {"model": model, "nudge": nudge, "effort": effort, "analysis": {}}))
    return name


class TestDiscovery:
    def test_finds_every_model_and_nudge_pair(self):
        d = tempfile.mkdtemp(prefix="fanout_")
        _run_file(d, 1, "google/gemini-3.5-flash", "strong")
        _run_file(d, 2, "google/gemini-3.5-flash", "none")
        _run_file(d, 3, "x-ai/grok-4.5", "strong")
        assert discover_batches(d) == [
            ("google/gemini-3.5-flash", "none"),
            ("google/gemini-3.5-flash", "strong"),
            ("x-ai/grok-4.5", "strong"),
        ]

    def test_a_concrete_value_still_filters(self):
        d = tempfile.mkdtemp(prefix="fanout_")
        _run_file(d, 1, "a/b", "strong")
        _run_file(d, 2, "a/b", "none")
        _run_file(d, 3, "c/d", "none")
        assert discover_batches(d, nudge="none") == [("a/b", "none"),
                                                     ("c/d", "none")]
        assert discover_batches(d, model="a/b") == [("a/b", "none"),
                                                   ("a/b", "strong")]

    def test_only_pairs_that_exist_are_returned(self):
        """Fanning out must not generate combinations that were never collected,
        or the run fills with 'no run files' errors that hide a real one."""
        d = tempfile.mkdtemp(prefix="fanout_")
        _run_file(d, 1, "a/b", "strong")
        _run_file(d, 2, "c/d", "max")
        assert ("a/b", "max") not in discover_batches(d)
        assert ("c/d", "strong") not in discover_batches(d)

    def test_a_truncated_run_file_is_skipped_not_fatal(self):
        d = tempfile.mkdtemp(prefix="fanout_")
        _run_file(d, 1, "a/b", "strong")
        Path(d, "run_2_broken_strong_20260101T000000.json").write_text("{oops")
        assert discover_batches(d) == [("a/b", "strong")]

    def test_empty_directory_discovers_nothing(self):
        assert discover_batches(tempfile.mkdtemp(prefix="fanout_")) == []


class TestFanOut:
    def _args(self, d, **kw):
        base = dict(output_dir=d, model=ALL, nudge=ALL, effort=None,
                    oversight="true", lure="false", write_back=False)
        base.update(kw)
        return argparse.Namespace(**base)

    def test_calls_the_mode_once_per_batch(self):
        d = tempfile.mkdtemp(prefix="fanout_")
        _run_file(d, 1, "a/b", "strong")
        _run_file(d, 2, "c/d", "none")
        seen = []

        def fake(args, slug):
            seen.append((args.model, args.nudge, slug))
            return 0

        assert fan_out_read_mode(self._args(d), fake) == 0
        assert seen == [("a/b", "strong", "a_b"), ("c/d", "none", "c_d")]

    def test_typed_filters_do_not_leak_between_batches(self):
        """THE bug. The callee sets args.effort per batch; the next iteration
        must start from what the operator typed, not from that."""
        d = tempfile.mkdtemp(prefix="fanout_")
        _run_file(d, 1, "a/b", "strong", effort="medium")
        _run_file(d, 2, "c/d", "strong")
        _run_file(d, 3, "e/f", "strong")
        efforts = []

        def fake(args, slug):
            efforts.append(args.effort)
            args.effort = "medium"      # what resummarise_existing_runs does
            args.oversight = False
            args.lure = True
            return 0

        fan_out_read_mode(self._args(d, effort=None), fake)
        assert efforts == [None, None, None], (
            f"effort leaked across batches: {efforts}")

    def test_a_typed_effort_is_preserved_for_every_batch(self):
        d = tempfile.mkdtemp(prefix="fanout_")
        _run_file(d, 1, "a/b", "strong", effort="high")
        _run_file(d, 2, "c/d", "strong", effort="high")
        efforts = []

        def fake(args, slug):
            efforts.append(args.effort)
            args.effort = "clobbered"
            return 0

        fan_out_read_mode(self._args(d, effort="high"), fake)
        assert efforts == ["high", "high"]

    def test_one_failing_batch_does_not_abandon_the_rest(self):
        d = tempfile.mkdtemp(prefix="fanout_")
        for i, m in enumerate(("a/b", "c/d", "e/f"), 1):
            _run_file(d, i, m, "strong")
        seen = []

        def fake(args, slug):
            seen.append(args.model)
            if args.model == "c/d":
                raise RuntimeError("unreadable")
            return 0

        rc = fan_out_read_mode(self._args(d), fake)
        assert len(seen) == 3, "a raise stopped the fan out"
        assert rc == 1, "a failed batch must surface in the exit code"

    def test_worst_exit_code_wins(self):
        d = tempfile.mkdtemp(prefix="fanout_")
        _run_file(d, 1, "a/b", "strong")
        _run_file(d, 2, "c/d", "strong")
        assert fan_out_read_mode(
            self._args(d), lambda a, s: 0 if a.model == "a/b" else 1) == 1

    def test_no_match_is_an_error_not_a_silent_success(self):
        d = tempfile.mkdtemp(prefix="fanout_")
        _run_file(d, 1, "a/b", "strong")
        rc = fan_out_read_mode(self._args(d, nudge="max"),
                               lambda a, s: 0)
        assert rc == 1
