"""
contamination_check.py: the probes, and the verdict they add up to.

A verdict has to be earned rather than defaulted. A probe that errored is not a
probe that found nothing, so an unparseable reply costs one item and not the
model, and a run too small for a verdict says so before spending anything.
"""


import contextlib
import io
import json
import os
import pathlib
import tempfile

import conftest
import subversionbench.llm_client as ev_llm


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




class TestContaminationCheckReportsWhatItFound:
    """The two halves of contamination_check.main that had never run: an
    audit that FINDS something, and the model probes.

    Neither reaches a model here. The audit is offline by construction, and
    the probe path replaces `ask` - the one function that makes a call -
    so probe_model itself runs for real over synthetic replies.
    """

    def _leaky_file(self, directory):
        """A file reproducing scenario text, built at runtime from the
        bundle. Never a literal: no tracked file may hold scenario text,
        which is the very thing this tool exists to detect."""
        from subversionbench.scenario import SCENARIO
        stolen = " ".join(SCENARIO["internal_memo"].split()[:24])
        path = pathlib.Path(directory, "leaky.py")
        path.write_text(f"# context\n# {stolen}\n# end\n", encoding="utf-8")
        return str(path)

    def test_a_leak_is_reported_by_file_and_line_without_quoting_it(self):
        """Printing the text would put the leak in this log too, so the
        report names where it is and refuses to show it."""
        import contamination_check as cc
        from subversionbench.scenario import SCENARIO
        with tempfile.TemporaryDirectory() as d:
            leaky = self._leaky_file(d)
            code, text = conftest.run_tool_main(
                cc, ["--audit", "--audit-paths", leaky, "--output-dir", d])
        assert code == 0
        assert "1 file(s) reproduce scenario text" in text
        assert "leaky.py" in text and "lines:" in text
        assert "Text is not printed" in text
        assert "next training crawl" in text
        stolen = " ".join(SCENARIO["internal_memo"].split()[:24])
        assert stolen not in text, "the audit printed the leak it found"

    def _stub_ask(self, cc, replies):
        """Replace the one function that makes a call. probe_model, its
        scoring and its error handling all still run."""
        calls = []

        def _ask(client, model, prompt, max_tokens=400):
            calls.append((model, max_tokens))
            reply = replies[(len(calls) - 1) % len(replies)]
            return (reply, None) if not isinstance(reply, Exception) \
                else (None, str(reply))
        return _ask, calls

    def test_a_model_probe_runs_every_family_and_writes_a_verdict(self):
        import contamination_check as cc
        saved = (cc.ask, ev_llm.get_client)
        try:
            ask, calls = self._stub_ask(cc, ['{"choice": 1}'])
            cc.ask = ask
            ev_llm.get_client = lambda model: object()
            with tempfile.TemporaryDirectory() as d:
                with conftest.env_without("ANTHROPIC_API_KEY",
                                          "OPENROUTER_API_KEY",
                                          "OPENAI_API_KEY"):
                    code, text = conftest.run_tool_main(
                        cc, ["--models", "some/model", "--limit", "4",
                             "--output-dir", d])
                written = [p for p in os.listdir(d)
                           if p.startswith("contamination_")]
                report = json.loads(
                    pathlib.Path(d, written[0]).read_text(encoding="utf-8"))
        finally:
            cc.ask, ev_llm.get_client = saved
        assert code == 0, text
        assert calls, "no probe was made at all"
        assert "CONTAMINATION PROBE: some/model" in text
        assert "canary" in text and "forced choice" in text \
            and "continuation" in text
        summary = report["models"]["some/model"]["summary"]
        assert "verdict" in summary

    def test_a_run_too_small_for_a_verdict_says_so_before_spending(self):
        """`no evidence` needs MIN_ITEMS_FOR_VERDICT scored items per arm, so
        a smaller --limit cannot reach one however well the run goes. The
        first real run scored 8/8 in both arms with no errors and still
        returned `inconclusive`, having paid for the calls to find out."""
        import contamination_check as cc
        from subversionbench.contamination import MIN_ITEMS_FOR_VERDICT
        saved = (cc.ask, ev_llm.get_client)
        try:
            ask, _calls = self._stub_ask(cc, ['{"choice": 1}'])
            cc.ask = ask
            ev_llm.get_client = lambda model: object()
            with tempfile.TemporaryDirectory() as d:
                _code, text = conftest.run_tool_main(
                    cc, ["--models", "some/model", "--limit", "2",
                         "--output-dir", d])
        finally:
            cc.ask, ev_llm.get_client = saved
        assert f"A verdict needs {MIN_ITEMS_FOR_VERDICT}" in text
        assert "inconclusive at best" in text or "'inconclusive' at best" in text

    def test_a_reply_that_is_not_json_costs_one_item_not_the_model(self):
        """This used to be an unguarded call, so the first model that
        answered in prose took its own forced-choice AND continuation probes
        down with it. Two of three models in the first real run produced no
        data at all that way."""
        import contamination_check as cc
        saved = (cc.ask, ev_llm.get_client)
        try:
            ask, _calls = self._stub_ask(cc, ["I would rather not guess."])
            cc.ask = ask
            ev_llm.get_client = lambda model: object()
            with tempfile.TemporaryDirectory() as d:
                code, text = conftest.run_tool_main(
                    cc, ["--models", "some/model", "--limit", "4",
                         "--output-dir", d])
                written = [p for p in os.listdir(d)
                           if p.startswith("contamination_")]
                report = json.loads(
                    pathlib.Path(d, written[0]).read_text(encoding="utf-8"))
        finally:
            cc.ask, ev_llm.get_client = saved
        assert code == 0, text
        entry = report["models"]["some/model"]
        assert entry.get("error") is None, "one bad item failed the model"
        assert entry["continuation"], "the continuation probes never ran"
        unparsed = [r for r in entry["forced_choice"]
                    if r["correct"] is None]
        assert unparsed, "an unparseable reply was scored rather than skipped"

    def test_a_model_that_raises_is_recorded_and_the_run_continues(self):
        import contamination_check as cc
        saved = (cc.ask, ev_llm.get_client)
        try:
            def _boom(model):
                raise RuntimeError("no credentials for this route")
            ev_llm.get_client = _boom
            with tempfile.TemporaryDirectory() as d:
                code, text = conftest.run_tool_main(
                    cc, ["--models", "a/one", "b/two", "--limit", "4",
                         "--output-dir", d])
                written = [p for p in os.listdir(d)
                           if p.startswith("contamination_")]
                report = json.loads(
                    pathlib.Path(d, written[0]).read_text(encoding="utf-8"))
        finally:
            cc.ask, ev_llm.get_client = saved
        assert code == 0, text
        assert set(report["models"]) == {"a/one", "b/two"}
        assert "no credentials" in report["models"]["a/one"]["error"]

    def test_the_caveats_on_a_clean_verdict_are_always_printed(self):
        """`no evidence` is not proof of cleanliness, and the caveats are
        what say so - printed for every run rather than only the clean
        ones."""
        import contamination_check as cc
        saved = (cc.ask, ev_llm.get_client)
        try:
            ask, _calls = self._stub_ask(cc, ['{"choice": 1}'])
            cc.ask = ask
            ev_llm.get_client = lambda model: object()
            with tempfile.TemporaryDirectory() as d:
                _code, text = conftest.run_tool_main(
                    cc, ["--models", "some/model", "--limit", "4",
                         "--output-dir", d])
        finally:
            cc.ask, ev_llm.get_client = saved
        assert "Caveats that apply to every 'no evidence' above" in text

    def test_prompts_are_withheld_from_the_saved_file_by_default(self):
        """Probe prompts contain scenario text, so the saved JSON records
        ids and scores only unless --include-prompts is passed - and a file
        written with it must be treated exactly like a transcript."""
        import contamination_check as cc
        saved = (cc.ask, ev_llm.get_client)
        try:
            ask, _calls = self._stub_ask(cc, ['{"choice": 1}'])
            cc.ask = ask
            ev_llm.get_client = lambda model: object()
            with tempfile.TemporaryDirectory() as d:
                conftest.run_tool_main(
                    cc, ["--models", "some/model", "--limit", "4",
                         "--output-dir", d])
                written = [p for p in os.listdir(d)
                           if p.startswith("contamination_")]
                default = json.loads(
                    pathlib.Path(d, written[0]).read_text(encoding="utf-8"))
            with tempfile.TemporaryDirectory() as d:
                _code, text = conftest.run_tool_main(
                    cc, ["--models", "some/model", "--limit", "4",
                         "--include-prompts", "--output-dir", d])
                written = [p for p in os.listdir(d)
                           if p.startswith("contamination_")]
                verbose = json.loads(
                    pathlib.Path(d, written[0]).read_text(encoding="utf-8"))
        finally:
            cc.ask, ev_llm.get_client = saved
        first = default["models"]["some/model"]["forced_choice"][0]
        assert "options" not in first and "response" not in first
        loud = verbose["models"]["some/model"]["forced_choice"][0]
        assert "options" in loud and "response" in loud
        assert "treat as a transcript" in text
