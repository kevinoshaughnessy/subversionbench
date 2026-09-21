"""
Human verdicts on disagreements, and scoring both graders against them.

The point of the file under test is that agreement with an LLM grader is a
proxy that becomes the target if nothing else is measured. These guards are
about the arithmetic not quietly restoring that: an unjudged case must not
count for anyone, and an ambiguous one must stay ambiguous.
"""

import json
import tempfile
import unittest

from grader_ab import jev_gold as g


def _case(run, key, jev, stored):
    """A disagreement record of the shape jev_tune.disagreements emits."""
    return {"run": run, "key": key, "jev": jev, "stored": stored}


class TestLabelsRoundTrip(unittest.TestCase):

    def test_an_absent_file_is_empty_not_an_error(self):
        with tempfile.TemporaryDirectory() as out:
            assert g.load_gold(out) == {}

    def test_a_label_survives_a_save_and_load(self):
        with tempfile.TemporaryDirectory() as out:
            labels = g.add_label({}, "r1.json", "mentioned_test", True, "why")
            g.save_gold(out, labels)
            back = g.load_gold(out)
        assert back[("r1.json", "mentioned_test")]["answer"] is True
        assert back[("r1.json", "mentioned_test")]["note"] == "why"

    def test_a_label_is_per_question_not_per_episode(self):
        """The same transcript can be a clear yes on one rubric question and
        a clear no on another."""
        labels = g.add_label({}, "r1.json", "mentioned_test", True)
        g.add_label(labels, "r1.json", "referenced_system_prompt", False)
        assert len(labels) == 2
        assert labels[("r1.json", "mentioned_test")]["answer"] is True
        assert labels[("r1.json", "referenced_system_prompt")]["answer"] is False

    def test_a_second_verdict_replaces_the_first(self):
        labels = g.add_label({}, "r1.json", "mentioned_test", True, "first")
        g.add_label(labels, "r1.json", "mentioned_test", False, "reconsidered")
        assert len(labels) == 1
        assert labels[("r1.json", "mentioned_test")]["answer"] is False

    def test_the_file_is_written_sorted_so_it_diffs(self):
        with tempfile.TemporaryDirectory() as out:
            labels = {}
            for run in ("r3.json", "r1.json", "r2.json"):
                g.add_label(labels, run, "mentioned_test", True)
            path = g.save_gold(out, labels)
            runs = [e["run"] for e in
                    json.load(open(path, encoding="utf-8"))["labels"]]
        assert runs == sorted(runs)

    def test_the_labels_live_beside_the_corpus(self):
        """Not in git: a rationale is a note about what an agent said, and
        agent text quotes the scenario freely."""
        assert g.gold_path("eval_results_rX").startswith("eval_results_rX")


class TestScoringOnlyCountsWhatWasSettled(unittest.TestCase):

    def test_an_unjudged_case_counts_for_nobody(self):
        """Otherwise the backlog silently scores as a win for whichever
        grader the code happens to check first."""
        score = g.score_against_gold({}, [_case("r1.json", "k", True, False)])
        assert score == {"jev_right": 0, "llm_right": 0, "settled": 0,
                         "unsettled": 0, "unlabelled": 1}

    def test_an_ambiguous_case_stays_ambiguous(self):
        """Read and not settled is a real outcome, and a different one from
        not yet read - guessing it would invent evidence."""
        labels = g.add_label({}, "r1.json", "k", g.UNSETTLED, "genuinely 50/50")
        score = g.score_against_gold(labels, [_case("r1.json", "k", True, False)])
        assert score["settled"] == 0
        assert score["unsettled"] == 1

    def test_the_human_siding_with_jev_scores_jev(self):
        labels = g.add_label({}, "r1.json", "k", True)
        score = g.score_against_gold(labels,
                                     [_case("r1.json", "k", True, False)])
        assert (score["jev_right"], score["llm_right"]) == (1, 0)

    def test_the_human_siding_with_the_llm_scores_the_llm(self):
        labels = g.add_label({}, "r1.json", "k", False)
        score = g.score_against_gold(labels,
                                     [_case("r1.json", "k", True, False)])
        assert (score["jev_right"], score["llm_right"]) == (0, 1)

    def test_exactly_one_side_wins_each_settled_disagreement(self):
        """These are by construction episodes the two answered differently,
        so a tally crediting both or neither means the join is wrong."""
        labels = {}
        cases = []
        for i, truth in enumerate((True, False, True, False)):
            run = f"r{i}.json"
            g.add_label(labels, run, "k", truth)
            cases.append(_case(run, "k", jev=truth, stored=not truth))
        score = g.score_against_gold(labels, cases)
        assert score["jev_right"] + score["llm_right"] == len(cases)
        assert score["settled"] == len(cases)

    def test_a_label_for_another_question_does_not_settle_this_one(self):
        labels = g.add_label({}, "r1.json", "other_key", True)
        score = g.score_against_gold(labels,
                                     [_case("r1.json", "k", True, False)])
        assert score["unlabelled"] == 1
        assert score["settled"] == 0


class TestTheScoreboardIsHonestAboutWhatItMeasures(unittest.TestCase):

    def _printed(self, score):
        import contextlib
        import io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            g.print_scoreboard(score)
        return buf.getvalue()

    def test_nothing_settled_says_so_rather_than_printing_zeroes(self):
        out = self._printed({"jev_right": 0, "llm_right": 0, "settled": 0,
                             "unsettled": 2, "unlabelled": 5})
        assert "Nothing settled yet" in out
        assert "5" in out and "2" in out

    def test_it_states_that_this_is_only_the_disagreements(self):
        """A reader who takes 1/3 for jev's accuracy has the wrong number by
        a very large factor - these are the arguments, not the corpus."""
        out = self._printed({"jev_right": 1, "llm_right": 2, "settled": 3,
                             "unsettled": 1, "unlabelled": 3})
        assert "not how accurate either is" in out

    def test_it_reports_the_backlog_alongside_the_score(self):
        out = self._printed({"jev_right": 1, "llm_right": 2, "settled": 3,
                             "unsettled": 1, "unlabelled": 3})
        assert "not yet judged" in out
