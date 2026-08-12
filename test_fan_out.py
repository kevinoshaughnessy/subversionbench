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

from subversionbench.batch import ALL, discover_batches
from subversionbench.run_eval import fan_out_read_mode


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

    def test_the_typed_filters_reach_every_batch(self):
        """THE bug, from the other end.

        The filters the operator typed have to mean the same thing on the last
        batch as on the first. This used to fail because the callee assigned the
        batch's own arm onto args.effort/oversight/lure: the first batch, collected
        at effort "medium", filtered every later model to "medium", and two of four
        groups silently reported "no run files" while the run reported success.

        fan_out no longer restores anything between iterations, because there is no
        longer anything to restore - the arm travels in a BatchIdentity. What keeps
        that true is test_no_read_mode_writes_to_the_operators_filters below, not a
        snapshot here: a guard that fails loudly beats one that silently repairs.
        """
        d = tempfile.mkdtemp(prefix="fanout_")
        _run_file(d, 1, "a/b", "strong", effort="medium")
        _run_file(d, 2, "c/d", "strong")
        _run_file(d, 3, "e/f", "strong")
        seen = []

        def fake(args, slug):
            seen.append((args.effort, args.oversight, args.lure))
            return 0

        fan_out_read_mode(self._args(d, effort=None), fake)
        assert seen == [(None, "true", "false")] * 3, (
            f"the operator's filters did not survive the fan out: {seen}")

    def test_a_typed_effort_is_preserved_for_every_batch(self):
        d = tempfile.mkdtemp(prefix="fanout_")
        _run_file(d, 1, "a/b", "strong", effort="high")
        _run_file(d, 2, "c/d", "strong", effort="high")
        efforts = []

        def fake(args, slug):
            efforts.append(args.effort)
            return 0

        fan_out_read_mode(self._args(d, effort="high"), fake)
        assert efforts == ["high", "high"]

    def test_no_read_mode_writes_to_the_operators_filters(self):
        """The guard that replaces the snapshot fan_out used to keep.

        `args` is shared across every batch in a fan out, so a read mode that
        assigns to one of the filter fields poisons every batch after it. The arm a
        batch was collected under now travels in a BatchIdentity, so no mode needs
        to; this makes needing to a test failure rather than a silent half-done
        backfill.

        main is exempt for model/nudge-adjacent normalisation of its OWN freshly
        parsed namespace, and fan_out itself sets model and nudge as its iteration
        variables - written afresh every time round.
        """
        import ast
        import inspect
        import subversionbench.run_eval as ev
        FILTERS = {"effort", "oversight", "lure", "model", "nudge"}
        ALLOWED = {"main", "fan_out_read_mode"}
        tree = ast.parse(inspect.getsource(ev))
        offenders = []
        for fn in tree.body:
            if not isinstance(fn, ast.FunctionDef) or fn.name in ALLOWED:
                continue
            for node in ast.walk(fn):
                if (isinstance(node, ast.Attribute)
                        and isinstance(node.ctx, ast.Store)
                        and getattr(node.value, "id", "") == "args"
                        and node.attr in FILTERS):
                    offenders.append(f"{fn.name} assigns args.{node.attr}")
                if (isinstance(node, ast.Call)
                        and getattr(node.func, "id", "") == "setattr"
                        and node.args and getattr(node.args[0], "id", "") == "args"):
                    offenders.append(f"{fn.name} setattrs onto args")
        assert not offenders, (
            f"these would leak across a fan out: {sorted(set(offenders))}")

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


class TestModelSlugIsDelimited:
    """A shorter model slug must not sweep in a longer model's files.

    find_run_files globs `run_*_<slug>_<nudge>`, and the `*` standing in for the
    run index matches across underscores - so `gpt-5.4` also matched
    `run_10_openai_gpt-5.4_strong`. Two live consequences: summarising the short
    spelling covered 20 files instead of 10, which is where a primary-arm
    denominator of 630 came from against a true 610; and fanning a paid regrade
    out over a directory would have graded those files twice.
    """

    def _dir(self):
        d = tempfile.mkdtemp(prefix="slug_")
        for i in (1, 2):
            _run_file(d, i, "gpt-5.4", "strong")
            _run_file(d, i, "openai/gpt-5.4", "strong")
        return d

    def test_the_short_spelling_does_not_match_the_prefixed_one(self):
        from subversionbench.batch import find_run_files
        d = self._dir()
        short = find_run_files(d, "gpt-5.4", "strong")
        assert len(short) == 2, [os.path.basename(p) for p in short]
        assert not any("openai" in os.path.basename(p) for p in short)

    def test_the_prefixed_spelling_matches_only_its_own(self):
        from subversionbench.batch import find_run_files
        d = self._dir()
        got = find_run_files(d, "openai_gpt-5.4", "strong")
        assert len(got) == 2
        assert all("openai" in os.path.basename(p) for p in got)

    def test_the_two_spellings_are_disjoint(self):
        from subversionbench.batch import find_run_files
        d = self._dir()
        a = set(find_run_files(d, "gpt-5.4", "strong"))
        b = set(find_run_files(d, "openai_gpt-5.4", "strong"))
        assert not (a & b), "a file matched by both spellings would be graded twice"

    def test_no_file_is_matched_by_two_batch_pairs(self):
        """The property that matters for fanning out: every run file belongs to
        exactly one (model, nudge) group."""
        from subversionbench.batch import find_run_files
        d = self._dir()
        _run_file(d, 3, "gpt-5.4", "none")
        counts = {}
        for m, n in discover_batches(d):
            for f in find_run_files(d, m.replace("/", "_"), n):
                counts[f] = counts.get(f, 0) + 1
        assert all(c == 1 for c in counts.values()), counts

    def test_the_arm_and_effort_suffixes_still_match(self):
        """The delimiter rule must not exclude the legitimate name shapes."""
        from subversionbench.batch import find_run_files
        d = tempfile.mkdtemp(prefix="slug_")
        _run_file(d, 1, "a/b", "strong")                      # plain
        _run_file(d, 2, "a/b", "strong", effort="high")       # with effort
        Path(d, "run_3_a_b_strong.json").write_text(
            json.dumps({"model": "a/b", "nudge": "strong"}))  # no stamp at all
        Path(d, "run_4_a_b_strong_nooversight_20260101T000000.json").write_text(
            json.dumps({"model": "a/b", "nudge": "strong"}))  # counterfactual
        assert len(find_run_files(d, "a_b", "strong")) == 4
