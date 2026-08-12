"""
What the four read-only modes have in common, which is less than it looks.

--grade-existing, --reclassify, --resummarise and --reinterrogate all begin by
asking the same question with the same filters: which saved run files am I working
on? They used to answer it four different ways, and three of the four told the
operator less than the fourth.

They do NOT share the rest. Each spends differently, each may abort for its own
reason, and each writes back under its own policy - see
test_the_write_back_policies_are_deliberately_different. Only the question they
open with is shared, so only that is shared code.
"""

import contextlib
import io
import json
import tempfile
import types
from pathlib import Path

import subversionbench.run_eval as ev_run

MODES = ("grade_existing_runs", "reclassify_existing_runs",
         "resummarise_existing_runs", "reinterrogate_existing_runs")


def _args(out, **over):
    base = dict(output_dir=out, model="m", nudge="strong", effort=None,
                batch_stamp=None, grader_model="g", write_back=False,
                max_turns=40, max_tokens=8192, no_power=True, runs=1,
                oversight=True, lure=False, delay=0,
                interrogations=["default", ev_run.INTERROGATION_CHOICES[-1]],
                interrogation="default")
    base.update(over)
    return types.SimpleNamespace(**base)


def _run_mode(name, args):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = getattr(ev_run, name)(args, "m")
    return code, buf.getvalue()


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
            got = ev_run.find_run_files_or_explain(args, "m")
        expected = ev_run.find_run_files(out, "m", "strong", None, None)
        assert got == expected
        assert len(got) == 2, [Path(p).name for p in got]

    def test_it_returns_none_not_an_empty_list(self):
        """A caller that treated the empty case as a value would loop over nothing
        and report success on a batch it never found."""
        out = tempfile.mkdtemp()
        args = _args(out)
        with contextlib.redirect_stdout(io.StringIO()):
            assert ev_run.find_run_files_or_explain(args, "m") is None


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
        import ast
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
