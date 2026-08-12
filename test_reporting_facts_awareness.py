"""
Evaluation-awareness figures.
"""

import subversionbench.reporting as ev_report


class TestAwarenessFlag:
    """Anything conditioning on eval awareness must prefer the grader. The
    keyword proxy found 0/20 in a pilot arm the grader scored 15/20, which
    made the cross-analysis either absent or meaningless."""

    def test_grader_wins_over_keywords(self):
        analysis = {
            "eval_awareness_grader": {"eval_aware": True},
            "eval_awareness_keywords": {"eval_aware": False,
                                            "goal_conflict_noted": False},
        }
        assert ev_report.awareness_flag(analysis) == (True, "grader")

    def test_falls_back_to_keywords_without_a_grader(self):
        analysis = {"eval_awareness_keywords": {"eval_aware": True}}
        assert ev_report.awareness_flag(analysis) == (True, "keywords")

    def test_a_failed_grading_falls_back_rather_than_counting_as_negative(self):
        """A wholly failed grading returns eval_aware=False as an artefact of
        answer=None reading as "no signal"; using it would silently label the
        episode unaware."""
        analysis = {
            "eval_awareness_grader": {"eval_aware": False,
                                      "grading_failed": True},
            "eval_awareness_keywords": {"eval_aware": True},
        }
        assert ev_report.awareness_flag(analysis) == (True, "keywords")

    def test_no_measure_at_all(self):
        assert ev_report.awareness_flag({}) == (None, None)
