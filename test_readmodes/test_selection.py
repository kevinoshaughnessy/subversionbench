"""
Choosing which saved runs a read mode acts on, and fanning out over batches.
Every read mode reaches its run files through this one helper, so an empty
selection is explained the same way whichever mode the operator asked for. What
each mode then does with them is deliberately NOT shared: the write-back policies
differ, and a common default would hide that.
"""

import argparse
import contextlib
import io
import tempfile
import types

from pathlib import Path
from subversionbench.batch import ALL, BatchSelection
from subversionbench.run_eval import fan_out_read_mode
import subversionbench.run_eval as ev_run
from conftest import write_run_file


MODES = ("grade_existing_runs", "reclassify_existing_runs",
         "resummarise_existing_runs", "reinterrogate_existing_runs")

def _args(out, **over):
    base = {"output_dir": out, "model": "m", "nudge": "strong", "effort": None,
                "batch_stamp": None, "grader_model": "g", "write_back": False,
                "max_turns": 40, "max_tokens": 8192, "no_power": True, "runs": 1,
                "oversight": True, "lure": False, "delay": 0,
                "interrogations": ["default", ev_run.INTERROGATION_CHOICES[-1]],
                "interrogation": "default"}
    base.update(over)
    return types.SimpleNamespace(**base)

def _run_mode(name, args):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = getattr(ev_run, name)(args, BatchSelection.typed(args))
    return code, buf.getvalue()

class TestFanOut:
    def _args(self, d, **kw):
        base = {"output_dir": d, "model": ALL, "nudge": ALL, "effort": None,
                    "oversight": "true", "lure": "false", "write_back": False}
        base.update(kw)
        return argparse.Namespace(**base)

    def test_calls_the_mode_once_per_batch(self):
        d = tempfile.mkdtemp(prefix="fanout_")
        write_run_file(d, 1, "a/b", "strong")
        write_run_file(d, 2, "c/d", "none")
        seen = []

        def fake(args, sel):
            seen.append((sel.model, sel.nudge, sel.model_slug))
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
        write_run_file(d, 1, "a/b", "strong", effort="medium")
        write_run_file(d, 2, "c/d", "strong")
        write_run_file(d, 3, "e/f", "strong")
        seen = []

        def fake(args, sel):
            seen.append((args.effort, args.oversight, args.lure))
            return 0

        fan_out_read_mode(self._args(d, effort=None), fake)
        assert seen == [(None, "true", "false")] * 3, (
            f"the operator's filters did not survive the fan out: {seen}")

    def test_a_typed_effort_is_preserved_for_every_batch(self):
        d = tempfile.mkdtemp(prefix="fanout_")
        write_run_file(d, 1, "a/b", "strong", effort="high")
        write_run_file(d, 2, "c/d", "strong", effort="high")
        efforts = []

        def fake(args, sel):
            efforts.append(args.effort)
            return 0

        fan_out_read_mode(self._args(d, effort="high"), fake)
        assert efforts == ["high", "high"]

    def test_the_fan_out_does_not_touch_the_caller_s_args(self):
        """BEHAVIOURAL, where this used to be a source scan.

        `args` is shared across every batch in a fan out, so writing the arm onto
        it poisons every batch after. This asserted it by parsing run_eval.py for
        assignments to five named filter fields - which caught the shape it knew
        about, in one module, and could say nothing about whether the object the
        caller handed in actually came back unchanged.

        The equivalent source scan now lives in test_project/test_args_bag.py and
        covers every source file rather than one, so repeating it here would be
        the same rule guarded twice - the defect class this repository keeps
        finding. What that scan cannot express is this: the caller's own object,
        compared field by field, before and after.
        """
        d = tempfile.mkdtemp(prefix="fanout_")
        for i, m in enumerate(("a/b", "c/d"), 1):
            write_run_file(d, i, m, "none")
        args = self._args(d)
        before = dict(vars(args))

        seen = []

        def fake(a, sel):
            seen.append((sel.model, sel.nudge))
            return 0

        assert fan_out_read_mode(args, fake) == 0
        assert len(seen) == 2, seen

        after = dict(vars(args))
        changed = {k: (before[k], after[k]) for k in before
                   if before[k] != after[k]}
        assert not changed, (
            f"fan_out_read_mode modified the caller's args: {changed}. It is "
            f"shared, so every batch after this one would see it.")
        assert set(after) == set(before), (
            f"fields were added or removed: "
            f"{set(after) ^ set(before)}")

    def test_each_batch_still_sees_its_own_model_and_nudge(self):
        """The other half. Not writing to the caller's args would be easy to
        achieve by not passing the arm along at all, which would send every batch
        to whatever the operator typed."""
        d = tempfile.mkdtemp(prefix="fanout_")
        for i, m in enumerate(("a/b", "c/d"), 1):
            write_run_file(d, i, m, "none")
        seen = []

        def fake(a, sel):
            seen.append((sel.model, sel.nudge, sel.model_slug))
            return 0

        fan_out_read_mode(self._args(d), fake)
        assert sorted(seen) == [("a/b", "none", "a_b"),
                                ("c/d", "none", "c_d")], seen

    def test_one_failing_batch_does_not_abandon_the_rest(self):
        d = tempfile.mkdtemp(prefix="fanout_")
        for i, m in enumerate(("a/b", "c/d", "e/f"), 1):
            write_run_file(d, i, m, "strong")
        seen = []

        def fake(args, sel):
            seen.append(sel.model)
            if sel.model == "c/d":
                raise RuntimeError("unreadable")
            return 0

        rc = fan_out_read_mode(self._args(d), fake)
        assert len(seen) == 3, "a raise stopped the fan out"
        assert rc == 1, "a failed batch must surface in the exit code"

    def test_worst_exit_code_wins(self):
        d = tempfile.mkdtemp(prefix="fanout_")
        write_run_file(d, 1, "a/b", "strong")
        write_run_file(d, 2, "c/d", "strong")
        assert fan_out_read_mode(
            self._args(d), lambda a, s: 0 if s.model == "a/b" else 1) == 1

    def test_no_match_is_an_error_not_a_silent_success(self):
        d = tempfile.mkdtemp(prefix="fanout_")
        write_run_file(d, 1, "a/b", "strong")
        rc = fan_out_read_mode(self._args(d, nudge="max"),
                               lambda a, s: 0)
        assert rc == 1

class TestTheHelperDelegatesRatherThanReimplements:
    def test_it_returns_exactly_what_find_run_files_returns(self):
        """The filters are subtle - a model slug must be the whole segment, an arm
        suffix sits between slug and stamp - and a second implementation of them
        would be a bare-substring defect waiting to happen."""
        out = tempfile.mkdtemp()
        for name in ("run_1_m_strong_20260101T000000.json",
                     "run_2_m_strong_20260101T000000.json",
                     "run_1_m_max_20260101T000000.json",
                     "run_1_other_m_strong_20260101T000000.json"):
            Path(out, name).write_text("{}")
        args = _args(out)
        with contextlib.redirect_stdout(io.StringIO()):
            got = ev_run.find_run_files_or_explain(args, BatchSelection.typed(args))
        expected = ev_run.find_run_files(out, "m", "strong", None, None)
        assert got == expected
        assert len(got) == 2, [Path(p).name for p in got]

    def test_it_returns_none_not_an_empty_list(self):
        """A caller that treated the empty case as a value would loop over nothing
        and report success on a batch it never found."""
        out = tempfile.mkdtemp()
        args = _args(out)
        with contextlib.redirect_stdout(io.StringIO()):
            assert ev_run.find_run_files_or_explain(args, BatchSelection.typed(args)) is None

class TestTheyAllExplainAnEmptySelectionTheSameWay:
    def test_every_mode_gives_the_same_diagnostic(self):
        """THE inconsistency. Three modes printed one line; --grade-existing named
        the stamp it filtered on and listed what the directory held. Nothing made
        that a decision, and an operator hitting the short version has to go to
        `ls` to learn what the long one would have told them."""
        out = tempfile.mkdtemp()
        Path(out, "run_1_other_strong_20260101T000000.json").write_text("{}")
        seen = {}
        for name in MODES:
            code, text = _run_mode(name, _args(out))
            assert code == 1, f"{name} did not report failure"
            seen[name] = text
        assert len(set(seen.values())) == 1, (
            "the modes still explain an empty selection differently:\n"
            + "\n".join(f"  {k}: {v!r}" for k, v in seen.items()))

    def test_it_lists_what_the_directory_does_hold(self):
        """The useful half. An empty selection almost always means a filter that
        does not match, and the listing is what shows which."""
        out = tempfile.mkdtemp()
        Path(out, "run_1_other_max_20260101T000000.json").write_text("{}")
        _, text = _run_mode("resummarise_existing_runs", _args(out))
        assert "Available run files:" in text
        assert "run_1_other_max_20260101T000000.json" in text

    def test_it_names_the_filters_that_could_be_wrong(self):
        """A stamp or an effort that matches nothing is the usual cause, so the
        message repeats them back rather than leaving the operator to recall what
        they typed."""
        out = tempfile.mkdtemp()
        _, text = _run_mode("resummarise_existing_runs",
                            _args(out, batch_stamp="20990101T000000",
                                  effort="xhigh"))
        assert "batch 20990101T000000" in text
        assert "effort xhigh" in text

    def test_an_empty_directory_says_none_rather_than_nothing(self):
        out = tempfile.mkdtemp()
        _, text = _run_mode("reclassify_existing_runs", _args(out))
        assert "(none)" in text

class TestWhatIsDeliberatelyNotShared:
    def test_the_write_back_policies_are_deliberately_different(self):
        """Why there is no single spine past the opening question.

        Each mode protects something different, and a common writer would need a
        policy flag per mode - which is harder to read than four explicit
        implementations and easier to get wrong:

          --grade-existing   writes per episode, and skips an episode whose every
                             rubric question failed rather than overwriting a real
                             verdict with a failed call.
          --reclassify       defers every write to the end of the pass and abandons
                             all of them if too many classifier calls fell back to
                             keywords, because writing those over good verdicts
                             destroys work and looks like a result.
          --resummarise      writes only the allowlisted re-derived fields, and only
                             those that actually differ, because it must never
                             touch a sampled judgement.
          --reinterrogate    adds answers under a phrasing key and leaves the
                             headline fields alone.
        """
        import inspect
        policies = {}
        for name in MODES:
            src = inspect.getsource(getattr(ev_run, name))
            policies[name] = {
                "defers_to_end_of_pass": "pending" in src,
                "field_allowlist": "REDERIVED_ANALYSIS_FIELDS" in src,
                "aborts_the_whole_pass": "MAX_CLASSIFIER_FALLBACK_RATE" in src,
            }
        # Distinct on purpose: if these ever collapse to one shape, a shared
        # writer becomes worth revisiting - and until then it is not.
        shapes = {tuple(sorted(v.items())) for v in policies.values()}
        assert len(shapes) > 1, (
            "the write-back policies have converged; a shared writer may now be "
            "the simpler option, so this test should be reconsidered rather than "
            "deleted")
        assert policies["resummarise_existing_runs"]["field_allowlist"], (
            "--resummarise must write only re-derived fields")
        assert policies["reclassify_existing_runs"]["aborts_the_whole_pass"], (
            "--reclassify must be able to abandon a bad pass wholesale")
