"""
The root scripts an operator runs, and the helpers inside them nothing called.

Eighteen functions in this repository were never executed by the suite, found
by reading coverage rather than by grepping for call sites - a name can appear
in a comment, and an indirect call appears nowhere. Most of them were in these
scripts: the tools are the part of the codebase that ships without a test file
of its own, because each is "just a CLI" until it stops working.

WHAT A SMOKE TEST OVER --help IS ACTUALLY WORTH HERE. It runs the module's
imports, builds its parser, and exits. That catches the failures these scripts
really have - an import removed in a refactor, an argparse call with a bad
default, a helper renamed at one of two call sites - none of which the rest of
the suite can see, and all of which surface as a traceback in front of an
operator who is part-way through something expensive.

Derived from the directory rather than from a list, so a script added later
inherits the check instead of escaping it.

WHAT --help CANNOT REACH, AND WHY THE REST OF THIS FILE EXISTS. A smoke test
over --help executes the parser and stops, so the body of every main() and
every helper it calls stays unrun. Coverage shows this plainly: the four
main() functions here were the largest never-executed spans in the codebase.
The tests below take the two routes that need no key and no corpus - the
guard paths that refuse and return non-zero, and the pure helpers underneath
- because those are the parts an operator meets at the worst moment, having
already decided to spend something.
"""

import contextlib
import io
import json
import os
import pathlib
import string
import subprocess
import sys
import tempfile

import conftest


def _root_scripts() -> list:
    """Every root script with a __main__ guard, as repo-relative paths."""
    found = []
    for path in sorted(conftest.PROJECT_ROOT.glob("*.py")):
        if path.name.startswith("test_") or path.name in ("conftest.py",
                                                          "run_tests.py"):
            continue
        source = path.read_text(encoding="utf-8")
        if 'if __name__ == "__main__"' in source and "argparse" in source:
            found.append(path)
    return found


class TestEveryRootScriptStillStarts:
    """The cheapest check that a tool is not broken, run over all of them."""

    def test_the_script_list_is_not_empty(self):
        """A glob that matches nothing empties the scope and every check built
        on it passes. This suite has been bitten by exactly that."""
        assert len(_root_scripts()) >= 8, [p.name for p in _root_scripts()]

    def test_each_one_answers_help_without_a_traceback(self):
        """--help imports the module and builds its parser, which is where a
        broken tool breaks. It spends nothing and reaches no model."""
        failures = []
        for path in _root_scripts():
            done = subprocess.run(
                [sys.executable, str(path), "--help"],
                cwd=str(conftest.PROJECT_ROOT), capture_output=True,
                text=True, timeout=120)
            if done.returncode != 0 or "Traceback" in done.stderr:
                failures.append(
                    f"{path.name}: exit={done.returncode} "
                    f"{done.stderr.strip().splitlines()[-1] if done.stderr else ''}")
        assert not failures, "\n".join(failures)

    def test_each_one_describes_itself(self):
        """A --help with no description is a tool whose purpose lives only in
        whoever wrote it. Checked because these scripts have no README entry
        beyond a one-line table row in docs/Layout.md."""
        thin = []
        for path in _root_scripts():
            done = subprocess.run(
                [sys.executable, str(path), "--help"],
                cwd=str(conftest.PROJECT_ROOT), capture_output=True,
                text=True, timeout=120)
            body = done.stdout.split("options:")[0]
            if len(body.split()) < 12:
                thin.append(path.name)
        assert not thin, f"these print a --help that explains nothing: {thin}"


class TestContaminationCheckHelpers:
    """contamination_check.py's two pure helpers, neither previously run."""

    def test_tracked_files_lists_what_git_would_ship(self):
        import contamination_check as cc
        files = cc.tracked_files()
        assert files, "no tracked files - the crawler's view cannot be empty"
        assert "AGENTS.md" in files and "pyproject.toml" in files
        assert all(not p.startswith("/") for p in files), "expected repo-relative"

    def test_tracked_files_is_empty_rather_than_fatal_without_git(self):
        """It answers "what would a crawler see". Outside a checkout the honest
        answer is nothing, and a traceback there would stop the whole check
        over a question that has a sensible answer."""
        import contamination_check as cc
        real = cc.subprocess.run
        try:
            def _missing(*a, **k):
                raise FileNotFoundError("git")
            cc.subprocess.run = _missing
            assert cc.tracked_files() == []
        finally:
            cc.subprocess.run = real

    def _summary(self, **over):
        base = {
            "verdict": "clean",
            "signals": [],
            "forced_choice": {
                "scenario": {"hits": 1, "n": 4, "rate": 0.25},
                "control": {"hits": 1, "n": 4, "rate": 0.25},
                "chance_rate": 0.25, "p_vs_control": 0.5,
            },
            "continuation": {"scenario_overlap": None, "control_overlap": None},
        }
        base.update(over)
        return base

    def test_print_verdict_names_the_model_and_the_verdict(self):
        import contamination_check as cc
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            cc.print_verdict("some/model", self._summary())
        text = out.getvalue()
        assert "some/model" in text and "CLEAN" in text

    def test_print_verdict_shows_every_signal_it_was_given(self):
        """The signals are the finding. One dropped in formatting is a
        contamination indicator that was computed and never seen."""
        import contamination_check as cc
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            cc.print_verdict("m", self._summary(
                verdict="suspect", signals=["recalled the memo", "named it"]))
        text = out.getvalue()
        assert "recalled the memo" in text and "named it" in text

    def test_print_verdict_survives_a_run_with_no_forced_choice(self):
        """n=0 is the shape a --quick run produces, and dividing by it or
        formatting None would end the report part-way through."""
        import contamination_check as cc
        summary = self._summary()
        summary["forced_choice"]["scenario"]["n"] = 0
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            cc.print_verdict("m", summary)
        assert "m" in out.getvalue()


class _Block:
    def __init__(self, kind, text=""):
        self.type, self.text = kind, text


class _Reply:
    def __init__(self, *blocks):
        self.content = list(blocks)


class _RecordingClient:
    """A stand-in that records the kwargs it was called with. No call leaves
    the process; conftest's placeholder credentials are never read."""

    def __init__(self, reply=None, raises=None):
        self.calls = []
        self._reply, self._raises = reply, raises
        self.messages = self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self._raises is not None:
            raise self._raises
        return self._reply


class TestContaminationCheckAsk:
    """The one call every probe family goes through.

    Its whole job is to turn an API call into `(text, error)` without ever
    raising, because a single badly-phrased reply used to take a model's
    remaining probes down with it - see the comment in probe_model.
    """

    def test_the_answer_is_the_text_block_not_the_thinking_that_precedes_it(self):
        """A thinking model returns its reasoning first. Reading content[0]
        would record the reasoning as the answer and score it."""
        import contamination_check as cc
        client = _RecordingClient(_Reply(_Block("thinking", "let me see"),
                                         _Block("text", '{"choice": 2}')))
        text, error = cc.ask(client, "claude-opus-5", "prompt")
        assert (text, error) == ('{"choice": 2}', None)

    def test_a_reply_that_is_all_thinking_is_empty_rather_than_an_error(self):
        """The failure FORCED_CHOICE_TOKENS was raised for: the model spent
        its ceiling reasoning and emitted no text. That is an empty answer,
        not a failed call, and the two are not the same downstream - "" is
        scored, None leaves the item out of both the numerator and the
        denominator."""
        import contamination_check as cc
        client = _RecordingClient(_Reply(_Block("thinking", "still going")))
        assert cc.ask(client, "claude-opus-5", "p") == ("", None)

    def test_a_failed_call_returns_the_error_rather_than_raising(self):
        import contamination_check as cc
        client = _RecordingClient(raises=RuntimeError("overloaded_error"))
        text, error = cc.ask(client, "claude-opus-5", "p")
        assert text is None and "overloaded_error" in error

    def test_thinking_is_turned_off_where_the_model_allows_it(self):
        import contamination_check as cc
        client = _RecordingClient(_Reply(_Block("text", "ok")))
        cc.ask(client, "claude-opus-5", "p")
        assert client.calls[0]["thinking"] == {"type": "disabled"}

    def test_a_model_that_cannot_be_told_to_stop_thinking_is_given_room(self):
        """The ceiling sent is the RESOLVED one. Passing the requested 400
        to a model whose thinking cannot be disabled spends the whole budget
        on reasoning and returns nothing - which arrives here as an
        unparseable reply rather than as an obvious configuration error."""
        import contamination_check as cc
        from subversionbench.reasoning import MIN_TOKENS_WHEN_THINKING_FORCED
        client = _RecordingClient(_Reply(_Block("text", "ok")))
        cc.ask(client, "claude-fable-5", "p", max_tokens=400)
        assert client.calls[0]["max_tokens"] == MIN_TOKENS_WHEN_THINKING_FORCED

    def test_a_model_that_needs_no_room_is_given_exactly_what_was_asked(self):
        """The other direction of the same rule: raising every ceiling would
        make the floor above a spend rather than a headroom allowance."""
        import contamination_check as cc
        client = _RecordingClient(_Reply(_Block("text", "ok")))
        cc.ask(client, "claude-opus-5", "p", max_tokens=400)
        assert client.calls[0]["max_tokens"] == 400


class TestContaminationCheckAuditRunsOffline:
    """--audit is the mode the docstring tells you to run first, and the only
    one that costs nothing. It has to work without a key."""

    def test_a_clean_file_audits_to_a_report_and_a_zero_exit(self):
        import contamination_check as cc
        with tempfile.TemporaryDirectory() as d:
            clean = f"{d}/notes.txt"
            with open(clean, "w", encoding="utf-8") as f:
                f.write("The quick brown fox jumps over the lazy dog.\n" * 20)
            with conftest.env_without("ANTHROPIC_API_KEY", "OPENROUTER_API_KEY",
                                      "OPENAI_API_KEY"):
                code, text = conftest.run_tool_main(cc, ["--audit", "--audit-paths", clean,
                                             "--output-dir", d])
            assert code == 0, text
            assert "No scenario text found in the clear" in text
            written = [p for p in os.listdir(d)
                       if p.startswith("contamination_")]
            assert written, "the audit reported nothing to disk"

    def test_auditing_nothing_is_a_refusal_rather_than_a_clean_verdict(self):
        """An empty file list audits zero files and finds zero leaks. Calling
        that "clean" is the silent pass this project keeps finding bugs
        behind."""
        import contamination_check as cc
        real = cc.tracked_files
        try:
            cc.tracked_files = list
            with tempfile.TemporaryDirectory() as d:
                code, text = conftest.run_tool_main(cc, ["--audit", "--output-dir", d])
        finally:
            cc.tracked_files = real
        assert code == 1
        assert "No files to audit" in text

    def test_a_run_that_was_asked_for_nothing_says_so(self):
        import contamination_check as cc
        try:
            conftest.run_tool_main(cc, [])
        except SystemExit as exit_code:
            assert exit_code.code == 2
        else:
            raise AssertionError("neither --audit nor --models must not run")


class TestRubricABCells:
    """The grid rubric_ab fans out over."""

    def test_every_grader_is_paired_with_every_wording(self):
        import rubric_ab
        graders = ("a", "b")
        wordings = (("w1", "q1"), ("w2", "q2"))
        got = list(rubric_ab.cells("k", graders, wordings))
        assert got == [("a", "w1", "q1"), ("a", "w2", "q2"),
                       ("b", "w1", "q1"), ("b", "w2", "q2")]

    def test_an_empty_axis_yields_no_work(self):
        """A missing wording list must produce no cells rather than one cell
        with a missing question - the A/B is meaningless without both axes."""
        import rubric_ab
        assert list(rubric_ab.cells("k", ("a",), ())) == []
        assert list(rubric_ab.cells("k", (), (("w", "q"),))) == []


class _StubbedRubricAB:
    """rubric_ab with its grader call, grounding check and sleep replaced.

    A context manager rather than a fixture because run_tests.py cannot
    interpret one - see AGENTS.md. Restores every attribute it took.
    """

    def __init__(self, answers, grounded=True):
        self.answers = list(answers)
        self.grounded = grounded
        self.asked = []
        self.grounding_calls = []
        self.sleeps = []
        self.clients_built = []

    def __enter__(self):
        import rubric_ab
        self.module = rubric_ab
        self.saved = {name: getattr(rubric_ab, name) for name in
                      ("ask_rubric_question", "check_quote_grounding",
                       "_normalise_quote", "time")}

        def _ask(question, corpus, grader, client):
            self.asked.append((question, corpus, grader, client))
            return {"answer": self.answers[len(self.asked) - 1],
                    "quote": "q"}

        def _grounding(quote, corpus, scenario):
            self.grounding_calls.append((quote, corpus, scenario))
            return self.grounded

        rubric_ab.ask_rubric_question = _ask
        rubric_ab.check_quote_grounding = _grounding
        rubric_ab._normalise_quote = lambda corpus: corpus
        rubric_ab.time = type("_Clock", (), {
            "sleep": staticmethod(lambda s: self.sleeps.append(s))})
        return self

    def __exit__(self, *exc):
        for name, value in self.saved.items():
            setattr(self.module, name, value)
        return False

    def client_for(self, grader):
        self.clients_built.append(grader)
        return f"client-for-{grader}"

    def run(self, episodes, delay=0, question="Q", grader="g"):
        with contextlib.redirect_stdout(io.StringIO()):
            return self.module.run_cell(episodes, question, grader, delay,
                                        self.client_for)


def _episodes(n):
    return [(f"{i}", f"corpus {i}", f"scenario {i}") for i in range(n)]


class TestRubricABRunCell:
    """One cell of the A/B: one question, one grader, every episode.

    Nothing here reaches a model - the grader call is stubbed - because what
    is worth guarding is the loop's bookkeeping, and a real call would make
    these tests both expensive and non-deterministic.
    """

    def test_every_episode_comes_back_keyed_by_its_run_label(self):
        """The labels are what the report joins on when it compares which
        episodes one wording drops and the other keeps. A dropped or
        re-keyed entry silently changes that comparison."""
        with _StubbedRubricAB([True, False, True]) as stub:
            out = stub.run(_episodes(3))
        assert sorted(out) == ["0", "1", "2"]
        assert [out[k]["answer"] for k in sorted(out)] == [True, False, True]

    def test_an_answer_of_no_has_no_quote_to_ground(self):
        """quote_grounded is None, not False, when the question did not fire.
        There is no quote to check, and recording that as a failed grounding
        would put a confident negative into a rate that counts them."""
        with _StubbedRubricAB([False]) as stub:
            out = stub.run(_episodes(1))
        assert out["0"]["quote_grounded"] is None
        assert stub.grounding_calls == [], "nothing to ground on a 'no'"

    def test_a_grader_error_is_not_grounded_either(self):
        """An answer of None is an unanswered question, which is a third
        state and not a 'no'."""
        with _StubbedRubricAB([None]) as stub:
            out = stub.run(_episodes(1))
        assert out["0"]["quote_grounded"] is None
        assert stub.grounding_calls == []

    def test_a_fired_question_has_its_quote_checked_against_the_episode(self):
        with _StubbedRubricAB([True]) as stub:
            out = stub.run(_episodes(1))
        assert out["0"]["quote_grounded"] is True
        assert stub.grounding_calls == [("q", "corpus 0", "scenario 0")]

    def test_the_client_is_built_once_for_the_cell_not_once_per_episode(self):
        """client_for memoises per grader in main(), so a per-episode call
        would be harmless there and expensive anywhere else it is reused.
        The cell asks for its client once because that is what it needs."""
        with _StubbedRubricAB([True] * 20) as stub:
            stub.run(_episodes(20))
        assert stub.clients_built == ["g"]

    def test_the_client_it_built_is_the_one_every_call_receives(self):
        with _StubbedRubricAB([True, True]) as stub:
            stub.run(_episodes(2), grader="haiku")
        assert {call[3] for call in stub.asked} == {"client-for-haiku"}

    def test_the_delay_falls_between_episodes_and_not_after_the_last(self):
        """A rate-limit delay is a gap between calls. Sleeping after the
        final one buys nothing and pays for it once per cell, which over a
        2x2 grid is four idle delays per run."""
        with _StubbedRubricAB([True] * 4) as stub:
            stub.run(_episodes(4), delay=0.25)
        assert stub.sleeps == [0.25, 0.25, 0.25]

    def test_no_delay_means_no_sleeping(self):
        with _StubbedRubricAB([True] * 3) as stub:
            stub.run(_episodes(3), delay=0)
        assert stub.sleeps == []

    def test_no_episodes_asks_nothing(self):
        with _StubbedRubricAB([]) as stub:
            assert stub.run([]) == {}
        assert stub.asked == []


class TestRubricABRefusesBeforeItSpends:
    """Both of main()'s guard paths return 1 without making a call.

    Each is reached before the grid runs, which matters because the grid is
    one call per episode per cell - a 20-episode pilot over a 2x2 is 80.
    """

    def test_a_directory_with_no_matching_runs_is_a_refusal(self):
        import rubric_ab
        with tempfile.TemporaryDirectory() as d:
            code, text = conftest.run_tool_main(rubric_ab, [
                "--model", "x-ai/grok-4.5", "--output-dir", d])
        assert code == 1
        assert "No run files" in text

    def test_a_question_with_no_superseded_wording_is_a_refusal(self):
        """Comparing the shipped wording against itself would report a
        Fisher p of 1 and prove nothing, having paid for every call."""
        import rubric_ab
        from subversionbench.config import RUBRIC_QUESTIONS
        unrecorded = sorted(set(RUBRIC_QUESTIONS) - set(rubric_ab.PREVIOUS_WORDINGS))
        assert unrecorded, "every question has a previous wording - pick another guard"
        with tempfile.TemporaryDirectory() as d:
            conftest.write_run_file(d, 1, "x-ai/grok-4.5", "strong")
            code, text = conftest.run_tool_main(rubric_ab, [
                "--model", "x-ai/grok-4.5", "--output-dir", d,
                "--question", unrecorded[0]])
        assert code == 1
        assert "PREVIOUS_WORDINGS" in text


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


class TestHeldoutToolFingerprints:
    """Computing a held-out bundle's four arm fingerprints.

    The awkward shape here is load-bearing and the docstring on the function
    says why: pinning has to run UNDER the bundle override, and rollout_pins
    refuses to import under the override without the very sidecar the pin is
    about to write. A provisional sidecar breaks that cycle, and the whole
    risk of the arrangement is that one is left behind - which would leave
    the bundle pinned to a value nothing produced, and the drift guard would
    then refuse every arm of the next batch.
    """

    def _tool(self, tmpdir):
        import heldout_tool
        heldout_tool.PINS_PATH = pathlib.Path(tmpdir) / "heldout.pins.json"
        return heldout_tool

    def _restoring(self, tmpdir):
        """heldout_tool with PINS_PATH redirected, put back afterwards."""
        import heldout_tool
        real = heldout_tool.PINS_PATH

        @contextlib.contextmanager
        def _ctx():
            try:
                yield self._tool(tmpdir)
            finally:
                heldout_tool.PINS_PATH = real
        return _ctx()

    def test_the_probe_runs_under_the_bundle_it_was_asked_about(self):
        """Not the shipped one. Fingerprinting an un-overridden process was
        the original defect: the fingerprint covers the sandbox display path
        and the task file's name as well as the text, so all four came back
        disagreeing with what any run reproduces."""
        with tempfile.TemporaryDirectory() as d:
            with self._restoring(d) as tool:
                bundle = pathlib.Path(d) / "twin.json"
                bundle.write_text("{}", encoding="utf-8")
                with _ProbeSpy(tool) as spy:
                    tool._fingerprints(bundle)
        assert spy.env_at_probe_time["SUBVERSIONBENCH_SCENARIO_BUNDLE"] == str(bundle)

    def test_the_probe_sees_a_sidecar_so_the_harness_will_import(self):
        with tempfile.TemporaryDirectory() as d:
            with self._restoring(d) as tool:
                with _ProbeSpy(tool) as spy:
                    tool._fingerprints(pathlib.Path(d) / "twin.json")
        assert spy.sidecar_at_probe_time is not None, \
            "without a sidecar rollout_pins refuses to import under the override"
        assert len(spy.sidecar_at_probe_time["fingerprints"]) == 4

    def test_the_provisional_value_can_never_be_read_as_a_real_fingerprint(self):
        """If a --pin is interrupted and one survives, the drift guard must
        refuse to start rather than accept it. Real fingerprints are hex."""
        with tempfile.TemporaryDirectory() as d:
            with self._restoring(d) as tool:
                with _ProbeSpy(tool) as spy:
                    tool._fingerprints(pathlib.Path(d) / "twin.json")
        provisional = {e["fingerprint"]
                       for e in spy.sidecar_at_probe_time["fingerprints"]}
        assert len(provisional) == 1
        value = provisional.pop()
        assert not all(c in string.hexdigits for c in value), \
            f"{value!r} could be mistaken for a fingerprint"

    def test_a_sidecar_that_was_not_there_is_not_there_afterwards(self):
        """Restores on EVERY exit, not only on failure. Leaving the
        provisional behind on success made the accept step implicit."""
        with tempfile.TemporaryDirectory() as d:
            with self._restoring(d) as tool:
                with _ProbeSpy(tool):
                    tool._fingerprints(pathlib.Path(d) / "twin.json")
                assert not tool.PINS_PATH.exists()

    def test_an_existing_sidecar_comes_back_byte_for_byte(self):
        with tempfile.TemporaryDirectory() as d:
            with self._restoring(d) as tool:
                before = b'{"rollout_version": "heldout1", "fingerprints": []}'
                tool.PINS_PATH.write_bytes(before)
                with _ProbeSpy(tool):
                    tool._fingerprints(pathlib.Path(d) / "twin.json")
                assert tool.PINS_PATH.read_bytes() == before

    def test_a_failed_probe_restores_the_sidecar_and_says_what_broke(self):
        with tempfile.TemporaryDirectory() as d:
            with self._restoring(d) as tool:
                before = b'{"rollout_version": "heldout1", "fingerprints": []}'
                tool.PINS_PATH.write_bytes(before)
                with _ProbeSpy(tool, returncode=1):
                    try:
                        tool._fingerprints(pathlib.Path(d) / "twin.json")
                    except RuntimeError as failure:
                        assert "probe failed" in str(failure)
                    else:
                        raise AssertionError("a failed probe must not return pins")
                assert tool.PINS_PATH.read_bytes() == before

    def test_each_arm_keeps_the_fingerprint_the_probe_reported_for_it(self):
        """JSON has no tuple key, so the probe reports a list of triples and
        this rebuilds the mapping. A pair rebuilt the wrong way round pins
        each arm to its neighbour's identity - four plausible-looking
        fingerprints, none of which that arm reproduces, and the drift guard
        then refuses every arm of the next batch."""
        with tempfile.TemporaryDirectory() as d:
            with self._restoring(d) as tool:
                with _ProbeSpy(tool):
                    pins = tool._fingerprints(pathlib.Path(d) / "twin.json")
        assert pins == {(o, lure): f"fp-o{o}-l{lure}"
                        for o in (True, False) for lure in (True, False)}


class TestHeldoutToolRefusesWithoutItsBundle:
    """The bundle is gitignored and exists only where it was authored, so
    every mode has to say that rather than traceback on a missing file."""

    def test_a_missing_bundle_is_a_refusal_that_explains_itself(self):
        import heldout_tool
        real = heldout_tool.BUNDLE_PATH
        try:
            # Under ROOT, because the message reports the path relative to it.
            # A temp directory is not, and asking for that relation raises.
            heldout_tool.BUNDLE_PATH = heldout_tool.HELDOUT_DIR / "absent.enc"
            assert not heldout_tool.BUNDLE_PATH.exists()
            code, text = conftest.run_tool_main(heldout_tool, ["--list"])
        finally:
            heldout_tool.BUNDLE_PATH = real
        assert code == 1
        assert "not found" in text and "gitignored" in text
