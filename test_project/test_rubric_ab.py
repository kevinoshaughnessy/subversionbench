"""
rubric_ab.py: one rubric question's wording against another, on saved
transcripts.

The grid is the point - every grader crossed with every wording - because a
wording that fires more often is not necessarily a better one, and the report
has to name both ends of that reading rather than pick a winner.
"""


import contextlib
import io
import json
import os
import pathlib
import tempfile

import conftest
import subversionbench.llm_client as ev_llm


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


class TestRubricABRunsTheWholeGrid:
    """rubric_ab.main end to end, with the grader stubbed.

    The A/B is one call per episode per cell, so a 20-episode pilot over a
    2x2 is 80 calls - which is exactly why nothing had ever run this path.
    Stubbing the grader makes the assembly, the report and the saved file
    assertable for nothing, and those are the parts that decide whether the
    experiment can be read at all.
    """

    def _corpus(self, out, n=2, model="x-ai/grok-4.5", nudge="strong"):
        for i in range(1, n + 1):
            path = pathlib.Path(
                out, f"run_{i}_{model.replace('/', '_')}_{nudge}"
                     f"_20260101T00000{i}.json")
            path.write_text(json.dumps({
                "model": model, "nudge": nudge,
                "transcript": [
                    {"turn": 1, "type": "thinking",
                     "content": "this might be an evaluation of my behaviour"},
                    {"turn": 1, "type": "text", "content": "I recommend B."},
                ],
                "analysis": {},
            }), encoding="utf-8")

    def _run(self, argv, answers=None, out=None):
        """main() with the grader replaced. Returns (code, stdout, out_dir)."""
        import rubric_ab
        out = out or tempfile.mkdtemp()
        answers = list(answers or [])
        calls = []
        # ask_rubric_question is bound on rubric_ab; get_client is not any
        # more - it is called through subversionbench.llm_client, which is the
        # one place a patch of it reaches every caller.
        saved = {"ask_rubric_question": rubric_ab.ask_rubric_question}
        saved_client = ev_llm.get_client
        try:
            def _ask(question, corpus, grader, client):
                calls.append((grader, question))
                reply = (answers[(len(calls) - 1) % len(answers)]
                         if answers else True)
                return {"answer": reply, "quote": "this might be an evaluation"}
            rubric_ab.ask_rubric_question = _ask
            ev_llm.get_client = lambda model: f"client-{model}"
            code, text = conftest.run_tool_main(
                rubric_ab, [*argv, "--output-dir", out])
        finally:
            for name, value in saved.items():
                setattr(rubric_ab, name, value)
            ev_llm.get_client = saved_client
        return code, text, out, calls

    def test_the_grid_is_every_grader_crossed_with_every_wording(self):
        """Two graders and two wordings over two episodes is eight calls.
        The count is the cost, and it is announced before anything is spent."""
        out = tempfile.mkdtemp()
        self._corpus(out)
        code, text, _out, calls = self._run(
            ["--model", "x-ai/grok-4.5", "--graders", "a", "b"], out=out)
        assert code == 0, text
        assert len(calls) == 8, calls
        assert {g for g, _q in calls} == {"a", "b"}
        assert len({q for _g, q in calls}) == 2, "one wording was asked twice"
        assert "2 episode(s) x 2 grader(s) x 2 wording(s) = 8 calls" in text

    def test_the_shipped_and_superseded_wordings_are_both_asked(self):
        """Comparing the current wording against itself would report a
        Fisher p of 1 and prove nothing. The point is the comparison with
        what it replaced."""
        import rubric_ab
        from subversionbench.config import RUBRIC_QUESTIONS
        out = tempfile.mkdtemp()
        self._corpus(out)
        _code, _text, _out, calls = self._run(
            ["--model", "x-ai/grok-4.5", "--graders", "a"], out=out)
        asked = {q for _g, q in calls}
        assert RUBRIC_QUESTIONS["suspects_being_tested"] in asked
        assert rubric_ab.PREVIOUS_WORDINGS["suspects_being_tested"] in asked

    def test_a_limit_is_a_pilot_and_is_honoured(self):
        """Run a pilot before paying for the full batch - so --limit has to
        actually reduce the calls, not just the reported total."""
        out = tempfile.mkdtemp()
        self._corpus(out, n=4)
        _code, text, _out, calls = self._run(
            ["--model", "x-ai/grok-4.5", "--graders", "a", "--limit", "2"],
            out=out)
        assert len(calls) == 4, "the limit did not reach the grid"
        assert "2 episode(s)" in text

    def test_the_report_names_both_ends_of_the_reading(self):
        """The output exists to be interpreted, and the three readings are
        the whole point of running it: the rewrite doing the work, grader
        capability being the constraint, or nothing measurable moving."""
        out = tempfile.mkdtemp()
        self._corpus(out)
        _code, text, _out, _calls = self._run(
            ["--model", "x-ai/grok-4.5", "--graders", "a"], out=out)
        assert "both graders drop sharply" in text
        assert "grader capability was the constraint" in text
        assert "the rewrite changed nothing measurable" in text

    def test_a_wording_that_fires_less_is_reported_as_dropping_episodes(self):
        """The comparison the tool exists for: which episodes the shipped
        wording no longer finds."""
        out = tempfile.mkdtemp()
        self._corpus(out, n=2)
        # previous fires, shipped does not, for every episode.
        _code, text, _out, _calls = self._run(
            ["--model", "x-ai/grok-4.5", "--graders", "a"],
            answers=[True, True, False, False], out=out)
        assert "dropped 2, newly added 0" in text

    def test_a_wording_that_finds_more_is_flagged_for_reading(self):
        """The revised wording should not FIND more, so when it does the
        report says to go and read those transcripts rather than leaving
        the reader to notice."""
        out = tempfile.mkdtemp()
        self._corpus(out, n=2)
        _code, text, _out, _calls = self._run(
            ["--model", "x-ai/grok-4.5", "--graders", "a"],
            answers=[False, False, True, True], out=out)
        assert "newly added 2" in text
        assert "the revised wording should not FIND more" in text

    def test_an_errored_verdict_leaves_the_denominator(self):
        """answer=None is an unanswered question, not a "no". Counting it
        would put a transport failure into the rate the A/B compares."""
        out = tempfile.mkdtemp()
        self._corpus(out, n=2)
        _code, text, _out, _calls = self._run(
            ["--model", "x-ai/grok-4.5", "--graders", "a"],
            answers=[True, None], out=out)
        assert "1/1" in text, text
        assert "    1" in text, "the error was not counted separately"

    def test_the_saved_file_carries_both_wordings_and_every_cell(self):
        """Nothing is written back to any run file - this reads transcripts
        and reports - so the saved JSON is the whole record of what was
        asked and what came back."""
        out = tempfile.mkdtemp()
        self._corpus(out)
        _code, _text, _out, _calls = self._run(
            ["--model", "x-ai/grok-4.5", "--graders", "a", "b"], out=out)
        written = [p for p in os.listdir(out) if p.startswith("rubric_ab_")]
        assert len(written) == 1, written
        saved = json.loads(pathlib.Path(out, written[0]).read_text(
            encoding="utf-8"))
        assert set(saved["wordings"]) == {"previous", "shipped"}
        assert set(saved["cells"]) == {"a|previous", "a|shipped",
                                       "b|previous", "b|shipped"}
        assert saved["n_episodes"] == 2
        assert saved["evaluated_model"] == "x-ai/grok-4.5"

    def test_an_episode_with_no_transcript_contributes_nothing(self):
        """There is nothing to grade, and building an empty corpus for it
        would ask the grader about a blank episode and score the answer."""
        out = tempfile.mkdtemp()
        self._corpus(out, n=1)
        pathlib.Path(out, "run_9_x-ai_grok-4.5_strong_20260101T000009.json"
                     ).write_text(json.dumps(
                         {"model": "x-ai/grok-4.5", "nudge": "strong",
                          "transcript": [], "analysis": {}}), encoding="utf-8")
        _code, text, _out, calls = self._run(
            ["--model", "x-ai/grok-4.5", "--graders", "a"], out=out)
        assert "1 episode(s)" in text
        assert len(calls) == 2, calls
