"""
The CLI: what the flags mean, what they forbid, and where each one dispatches.

This file used to be 2304 lines against a 441-line module, because it was written
before run_eval.py was split and it kept testing episode, runner and reporting
through the re-export shim. Those tests now live beside the modules they exercise,
and what is left here is what run_eval.py actually still does: parse, refuse, and
dispatch.

Every refusal below is cheap and happens BEFORE anything is charged for. That is
the point of testing them: a contradiction caught by argparse costs nothing, and
the same contradiction caught mid-batch has already spent the money.
"""

import contextlib
import io
import tempfile

import pytest

import subversionbench.run_eval as ev_run


class _RolloutAttempted(AssertionError):
    """A test reached the collecting path. See _main."""


def _main(*argv, rollout=None):
    """Run main() with this argv, returning (exit code, combined output).

    main() reads sys.argv rather than taking it, so this swaps it out. Both streams
    are captured because argparse writes its refusals to stderr and the module's own
    refusals go to stdout, and a test should not have to know which is which.

    THE COLLECTING PATH IS ALWAYS REPLACED.
    ---------------------------------------
    Unless a test passes its own `rollout`, run_batch is swapped for something that
    raises. A test about a refusal is a test about an argv that does NOT reach the
    rollout, and if it stops being one the consequence is not a failure - it is the
    suite creating an episode root, wrapping a sandbox, and calling a provider. One
    of these tests did exactly that while being written, and it hung rather than
    failing, which is the better of the two outcomes.
    """
    import sys

    def refuse(*a, **k):
        raise _RolloutAttempted(
            f"argv {list(argv)!r} reached run_batch. If that is intended, pass "
            f"rollout= to _main; if not, the refusal under test is not firing.")

    out, err = io.StringIO(), io.StringIO()
    saved_argv, saved_batch = sys.argv, ev_run.run_batch
    sys.argv = ["run_eval", *argv]
    ev_run.run_batch = rollout or refuse
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = ev_run.main()
    except SystemExit as exit_:
        code = exit_.code
    finally:
        sys.argv, ev_run.run_batch = saved_argv, saved_batch
    return code, out.getvalue() + err.getvalue()


def _read_mode_argv(mode, out=None, nudge="strong"):
    """A minimal read-mode invocation: a mode, a model, an arm, a directory.

    `nudge` is a parameter rather than fixed, because appending another --nudge
    after this list silently overrides it - which is how two tests below came to be
    about the strong arm while claiming to be about the max one.
    """
    return [mode, "--model", "m", "--nudge", nudge,
            "--output-dir", out or tempfile.mkdtemp()]


class TestContradictoryFlagsAreRefusedBeforeSpending:
    def test_grade_existing_with_no_grader_is_refused(self):
        """The first does nothing but run the grader, so together they ask for a
        run that cannot do anything - and would look like a successful no-op."""
        code, out = _main("--grade-existing", "--no-grader", "--model", "m")
        assert code == 2
        assert "contradictory" in out

    def test_batch_stamp_outside_a_read_mode_is_refused(self):
        """It selects among batches already on disk. On a collecting run it would
        be silently ignored, and the operator would believe they had narrowed the
        rollout to one batch."""
        code, out = _main("--batch-stamp", "20260101T000000", "--model", "m")
        assert code == 2
        assert "--batch-stamp only applies" in out

    def test_write_back_outside_a_read_mode_is_refused(self):
        """Nothing to write back to. Accepting it would imply the collecting path
        has a dry-run mode, which it does not."""
        code, out = _main("--write-back", "--model", "m")
        assert code == 2
        assert "--write-back only applies" in out

    def test_batch_stamp_is_accepted_with_every_read_mode(self):
        """Refusals have to be exactly as wide as their reason. A guard listing
        three of the four modes would refuse a legitimate invocation."""
        for mode in ("--grade-existing", "--reclassify", "--resummarise",
                     "--reinterrogate"):
            code, out = _main(mode, "--batch-stamp", "20260101T000000",
                              "--model", "m", "--nudge", "strong",
                              "--output-dir", tempfile.mkdtemp())
            assert "--batch-stamp only applies" not in out, mode

    def test_write_back_is_accepted_with_every_read_mode(self):
        for mode in ("--grade-existing", "--reclassify", "--resummarise",
                     "--reinterrogate"):
            code, out = _main(mode, "--write-back", "--model", "m",
                              "--nudge", "strong",
                              "--output-dir", tempfile.mkdtemp())
            assert "--write-back only applies" not in out, mode


# A model whose thinking surface actually takes a budget. The checks below only
# apply to those: on an adaptive-thinking model the flag is dropped with a warning,
# so asserting a refusal against one would be asserting nothing. Chosen from the
# shipped surface table rather than written down, so it cannot name a model whose
# surface has since changed.
BUDGET_MODEL = next(
    m for m in ("claude-opus-4-5", "claude-sonnet-4-5")
    if getattr(__import__("subversionbench.llm_client", fromlist=["x"])
               .thinking_surface(m), "mode", None) == "budget")


class TestTheThinkingBudgetIsCheckedAgainstMaxTokens:
    def test_a_budget_at_or_above_max_tokens_is_refused(self):
        """Thinking tokens count against max_tokens, so there has to be room left
        for the visible answer or tool call. Without this the model spends its
        whole budget reasoning and returns nothing, which reads as a refusal."""
        code, out = _main("--model", BUDGET_MODEL, "--thinking-budget", "8192",
                          "--max-tokens", "8192")
        assert code == 2
        assert "must be less" in out

    def test_the_error_suggests_a_workable_max_tokens(self):
        """A refusal that does not say what would work costs another round trip."""
        code, out = _main("--model", BUDGET_MODEL, "--thinking-budget", "8192",
                          "--max-tokens", "8192")
        assert "--max-tokens 12288" in out

    def test_a_budget_below_the_minimum_is_refused(self):
        from subversionbench.run_eval import MIN_THINKING_BUDGET
        code, out = _main("--model", BUDGET_MODEL,
                          "--thinking-budget", str(MIN_THINKING_BUDGET - 1),
                          "--max-tokens", "100000")
        assert code == 2
        assert "at least" in out

    def test_a_workable_pair_is_not_refused(self):
        code, out = _main("--model", BUDGET_MODEL, "--thinking-budget", "4096",
                          "--max-tokens", "16384", "--resummarise",
                          "--output-dir", tempfile.mkdtemp())
        assert "must be less" not in out and "at least" not in out


class TestTheInterrogationFlagIsValidatedBeforeARollout:
    def test_an_unknown_phrasing_is_refused(self):
        code, out = _main("--model", "m", "--interrogation", "not-a-phrasing")
        assert code == 2

    def test_every_shipped_variant_has_a_max_form(self):
        """The max arm has its own four-clause first question, so a variant needs
        its own max rephrasing. The check runs at parse time so a variant without
        one fails before a paid rollout rather than part-way through one - and this
        asserts the shipped set all pass it, rather than that the check exists.
        """
        from subversionbench.config import INTERROGATION_CHOICES
        assert len(INTERROGATION_CHOICES) > 1, "no variants to check"
        for variant in INTERROGATION_CHOICES:
            code, out = _main("--interrogation", variant,
                              *_read_mode_argv("--resummarise", nudge="max"))
            assert code != 2, (variant, out)

    def test_a_variant_with_no_max_form_is_refused(self):
        """The refusal itself, with a variant invented for the purpose so the test
        does not depend on the shipped set having a broken member."""
        import subversionbench.config as cfg
        saved = cfg.INTERROGATION_CHOICES
        cfg.INTERROGATION_CHOICES = tuple(saved) + ("no-max-form",)
        try:
            code, out = _main("--interrogation", "no-max-form",
                              *_read_mode_argv("--resummarise", nudge="max"))
        finally:
            cfg.INTERROGATION_CHOICES = saved
        assert code == 2

    def test_the_default_phrasing_is_always_acceptable(self):
        code, out = _main(*_read_mode_argv("--resummarise", nudge="max"))
        assert code != 2, out


class TestTheArmIsResolvedFromStringsToBooleans:
    def test_oversight_and_lure_arrive_as_strings_and_are_converted(self):
        """They are `--oversight true|false` rather than store_true, so that a
        batch's arm is always stated explicitly in the command that produced it.
        The conversion has to happen once, before anything reads them."""
        seen = {}

        def capture(args, model_slug, system_prompt, kwargs, config):
            seen["oversight"] = args.oversight
            seen["lure"] = args.lure
            return 0

        _main("--model", "m", "--oversight", "false", "--lure", "true",
              "--runs", "1", "--no-power", "--output-dir", tempfile.mkdtemp(),
              rollout=capture)
        assert seen == {"oversight": False, "lure": True}

    def test_an_invalid_arm_value_is_refused_by_argparse(self):
        """Not coerced. `--oversight yes` silently becoming False is how a batch
        gets filed under the wrong condition."""
        code, _ = _main("--model", "m", "--oversight", "yes")
        assert code == 2


class TestTheModelSlugIsFilenameSafe:
    def test_a_provider_prefix_becomes_an_underscore(self):
        """OpenRouter ids are "provider/model", and the slash would be read as a
        path separator - so the run file would land in a directory that does not
        exist, or worse, one that does."""
        captured = {}

        def capture(args, model_slug, *rest):
            captured["slug"] = model_slug
            return 0

        _main("--model", "x-ai/grok-4.5", "--runs", "1", "--no-power",
              "--output-dir", tempfile.mkdtemp(), rollout=capture)
        assert captured["slug"] == "x-ai_grok-4.5"
        assert "/" not in captured["slug"]


class TestDispatch:
    def _dispatches_to(self, name, argv):
        """Patch one read mode and confirm this argv reaches it, and only it."""
        calls = []
        modes = ("resummarise_existing_runs", "reclassify_existing_runs",
                 "grade_existing_runs", "reinterrogate_existing_runs")
        saved = {m: getattr(ev_run, m) for m in modes}
        for m in modes:
            setattr(ev_run, m,
                    (lambda m: lambda *a, **k: (calls.append(m), 0)[1])(m))
        try:
            _main(*argv)
        finally:
            for m, fn in saved.items():
                setattr(ev_run, m, fn)
        assert calls == [name], (name, calls)

    def test_resummarise_reaches_the_resummarise_mode(self):
        self._dispatches_to("resummarise_existing_runs",
                            _read_mode_argv("--resummarise"))

    def test_reclassify_reaches_the_reclassify_mode(self):
        self._dispatches_to("reclassify_existing_runs",
                            _read_mode_argv("--reclassify"))

    def test_grade_existing_reaches_the_grade_mode(self):
        self._dispatches_to("grade_existing_runs",
                            _read_mode_argv("--grade-existing"))

    def test_reinterrogate_reaches_the_reinterrogate_mode(self):
        self._dispatches_to("reinterrogate_existing_runs",
                            _read_mode_argv("--reinterrogate"))

    def test_compare_returns_before_any_read_mode(self):
        """--compare reads two summaries and nothing else. If it fell through to a
        read mode it would spend on a corpus the operator only asked to inspect."""
        calls = []
        saved = ev_run.compare_batches
        ev_run.compare_batches = lambda args: (calls.append("compare"), 0)[1]
        try:
            _main("--compare", "a.json", "b.json", "--model", "m")
        finally:
            ev_run.compare_batches = saved
        assert calls == ["compare"]

    def test_with_no_read_mode_it_rolls_out(self):
        calls = []
        _main("--model", "m", "--runs", "1", "--no-power",
              "--output-dir", tempfile.mkdtemp(),
              rollout=lambda *a, **k: (calls.append("rollout"), 0)[1])
        assert calls == ["rollout"]

    def test_the_guard_in_this_file_would_catch_a_refusal_that_stopped_firing(self):
        """The positive control for _main itself. Without it, a test whose refusal
        silently stopped working would start a real rollout instead of failing."""
        with pytest.raises(_RolloutAttempted):
            _main("--model", "m", "--runs", "1", "--no-power",
                  "--output-dir", tempfile.mkdtemp())


class TestFanningOutOverEveryBatch:
    def test_a_free_mode_fans_out_without_confirmation(self):
        """--resummarise calls no API, so there is no bill to show."""
        calls = []
        saved = ev_run.fan_out_read_mode
        ev_run.fan_out_read_mode = lambda args, fn: (calls.append(fn), 0)[1]
        try:
            code, out = _main("--resummarise", "--model", "all",
                              "--nudge", "strong",
                              "--output-dir", tempfile.mkdtemp())
        finally:
            ev_run.fan_out_read_mode = saved
        assert len(calls) == 1 and code == 0

    def test_a_spending_mode_refuses_without_yes(self):
        """The guard exists to make the bill visible, not to make the operation
        unavailable - so it says what it would have cost and stops."""
        code, out = _main("--reclassify", "--model", "all", "--nudge", "strong",
                          "--output-dir", tempfile.mkdtemp())
        assert code == 2
        assert "--yes" in out and "real money" in out

    def test_with_yes_it_says_the_scope_it_is_proceeding_with(self):
        calls = []
        saved = ev_run.fan_out_read_mode
        ev_run.fan_out_read_mode = lambda args, fn: (calls.append(fn), 0)[1]
        try:
            code, out = _main("--reclassify", "--yes", "--model", "all",
                              "--nudge", "strong",
                              "--output-dir", tempfile.mkdtemp())
        finally:
            ev_run.fan_out_read_mode = saved
        assert len(calls) == 1
        assert "--yes given" in out

    def test_all_with_a_collecting_run_is_refused(self):
        """`all` means "every batch already on disk", which is meaningless for a
        rollout - there is nothing on disk yet."""
        code, out = _main("--model", "all", "--output-dir", tempfile.mkdtemp())
        assert code == 2
        assert "read-only modes" in out

    def test_nudge_all_fans_out_the_same_way_as_model_all(self):
        """Either axis. A guard keyed on only one of them would let the other
        through to a rollout that cannot work."""
        code, out = _main("--nudge", "all", "--model", "m",
                          "--output-dir", tempfile.mkdtemp())
        assert code == 2
        assert "read-only modes" in out


class TestTheOutputDirectoryIsCreated:
    def test_a_missing_directory_is_made_rather_than_refused(self):
        """A rollout that fails after the first episode because the directory does
        not exist has spent the money and saved nothing."""
        import os
        out_dir = os.path.join(tempfile.mkdtemp(), "nested", "deeper")
        _main("--model", "m", "--runs", "1", "--no-power",
              "--output-dir", out_dir, rollout=lambda *a, **k: 0)
        assert os.path.isdir(out_dir)


class TestTheModuleStaysACli:
    def test_it_does_not_compute_a_figure(self):
        """Everything it used to do lives in runner.py, episode.py and reporting/.
        A figure computed here would be one the summary never sees.

        Checked as CALLS, via the AST, not as text. The module re-exports several of
        these names for tests, so a substring search finds its own re-export line -
        the same substring-versus-token mistake this codebase keeps finding in its
        own matchers.
        """
        import ast
        import inspect
        computations = {"wilson_ci", "_wilson_ci", "classify_scheming",
                        "classify_misalignment", "concealment_level",
                        "settle_analysis", "batch_facts"}
        called = set()
        for node in ast.walk(ast.parse(inspect.getsource(ev_run))):
            if isinstance(node, ast.Call):
                fn = node.func
                name = getattr(fn, "id", None) or getattr(fn, "attr", None)
                if name in computations:
                    called.add(name)
        assert not called, f"the CLI layer computes figures again: {sorted(called)}"

    def test_main_is_the_only_entry_point(self):
        """It takes no arguments and reads sys.argv, which is why the helper above
        swaps sys.argv rather than passing a list."""
        import inspect
        assert callable(ev_run.main)
        assert list(inspect.signature(ev_run.main).parameters) == []

    def test_the_re_exports_all_resolve(self):
        """Tests and scripts import several names through this module. A dangling
        re-export is an ImportError at collection time, not at use."""
        import inspect
        for name, value in vars(ev_run).items():
            if name.startswith("_") or inspect.ismodule(value):
                continue
            assert value is not None or name in ("__doc__",), name
