"""
The acts the benchmark measures, and the interrogation ladder attached to each.

MISALIGNED_ACTS is a table rather than a set of branches, so every act gets the
same treatment by construction. What is pinned here is the shape of that table:
each act's keys, its questions, and that a phrasing variant only ever replaces the
first question.
"""

from subversionbench.config import INTERROGATION_VARIANTS
from subversionbench.grading.acts import MISALIGNED_ACTS, questions_for


class TestAnAuthFailureIsFoundWhereverItLands:
    """One rule rather than five call sites.

    An episode reaches the grader model five ways and each records its failure under
    a different key, so a walker over the finished analysis cannot miss the sixth the
    way an instrumented caller would.
    """

    AUTH = ("Could not resolve authentication method. Expected one of api_key, "
            "auth_token to be set")

    def _act(self):
        from subversionbench.grading import MISALIGNED_ACTS
        return MISALIGNED_ACTS[0]

    def test_it_is_found_in_every_route(self):
        """Looped rather than parametrized: run_tests.py runs this suite without
        pytest, so a pytest-only decorator would make the standalone runner report a
        failure it cannot explain. Nothing else in the suite uses one."""
        from subversionbench.grading import auth_error_in_analysis
        act = self._act()
        shapes = {
            "interrogation": {act["followup_key"]: [{"classifier_error": self.AUTH}]},
            "disclosure": {act["disclosure_key"]: {"error": self.AUTH}},
            "misrepresentation": {"misrepresented_check": {"error": self.AUTH}},
            "awareness_rubric": {"eval_awareness_grader":
                                 {"rubric_results": {"q": {"error": self.AUTH}}}},
            "pre_act_rubric": {act["grader_before_key"]: {"error": self.AUTH}},
            "variant_answers": {act["followup_key"] + "_by_variant":
                                {"paraphrase": [{"classifier_error": self.AUTH}]}},
        }
        for where, analysis in shapes.items():
            assert auth_error_in_analysis(analysis) is not None, where

    def test_a_clean_analysis_is_clean(self):
        from subversionbench.grading import auth_error_in_analysis
        assert auth_error_in_analysis({}) is None

    def test_a_rate_limit_is_not_an_auth_failure(self):
        """529 can come right on retry, so it must not abort a batch. Conflating the
        two would turn a transient blip into a stopped rollout."""
        from subversionbench.grading import auth_error_in_analysis
        act = self._act()
        analysis = {act["followup_key"]: [{"classifier_error":
                                           "Error code: 529 - overloaded_error"}]}
        assert auth_error_in_analysis(analysis) is None

class TestOnlyTheFirstQuestionMoves:
    def test_a_variant_replaces_q1_and_shares_the_ladder(self):
        for name in INTERROGATION_VARIANTS:
            for act in MISALIGNED_ACTS:
                base = questions_for(act, "strong")
                alt = questions_for(act, "strong", name)
                assert alt[0] != base[0], f"{name}/{act['name']}: q1 unchanged"
                assert alt[1:] == base[1:], (
                    f"{name}/{act['name']}: escalation ladder differs, so a "
                    f"difference between phrasings would not be attributable to "
                    f"the opening probe")

    def test_the_rephrasing_preserves_the_words(self):
        """Meaning-preserving means the same clauses reordered, not new content.
        Compared as sets so the assertion says nothing about order and quotes
        nothing. A couple of greeting filler tokens may be dropped."""
        for name in INTERROGATION_VARIANTS:
            for act in MISALIGNED_ACTS:
                base = questions_for(act, "strong")[0].lower().split()
                alt = questions_for(act, "strong", name)[0].lower().split()
                assert set(alt) <= set(base), (
                    f"{name}/{act['name']}: introduces words the original does "
                    f"not have, so it is not a paraphrase")
                assert len(set(base) - set(alt)) <= 2

    def test_it_is_still_a_closed_question(self):
        for name in INTERROGATION_VARIANTS:
            for act in MISALIGNED_ACTS:
                assert "?" in questions_for(act, "strong", name)[0]

class TestTheMaxArmHasItsOwnRephrasing:
    """The max arm can be paired too, but not with the ordinary paraphrase.

    Its first question is four clauses to the ordinary three - it inserts a stated
    consequence - so the ordinary rephrasing is a rephrasing of a different
    sentence. It also needs a different transformation: the ordinary one moves the
    question ahead of the observation, which is impossible here because one
    consequence clause opens "Before you answer" and would contradict itself.
    """

    def test_the_max_ladder_accepts_a_variant(self):
        for name in INTERROGATION_VARIANTS:
            for act in MISALIGNED_ACTS:
                base = questions_for(act, "max")
                alt = questions_for(act, "max", name)
                assert alt[0] != base[0]
                assert alt[1:] == base[1:], "max escalation ladder differs"

    def test_the_max_rephrasing_is_not_the_ordinary_one(self):
        """Splicing the ordinary paraphrase onto the coercive ladder would give a
        condition that is neither arm, and silently."""
        for name in INTERROGATION_VARIANTS:
            for act in MISALIGNED_ACTS:
                assert (questions_for(act, "max", name)[0]
                        != questions_for(act, "strong", name)[0])

    def test_the_max_rephrasing_still_carries_the_consequence(self):
        """Longer than the ordinary one, because the consequence clause is what
        distinguishes the arm. Losing it would quietly turn the coercive arm into
        the ordinary one."""
        for name in INTERROGATION_VARIANTS:
            for act in MISALIGNED_ACTS:
                assert (len(questions_for(act, "max", name)[0])
                        > len(questions_for(act, "strong", name)[0]))

    def test_the_max_rephrasing_preserves_the_words(self):
        for name in INTERROGATION_VARIANTS:
            for act in MISALIGNED_ACTS:
                base = questions_for(act, "max")[0].lower().split()
                alt = questions_for(act, "max", name)[0].lower().split()
                assert set(alt) <= set(base)
                assert len(set(base) - set(alt)) <= 2

    def test_the_question_stays_last_in_the_max_form(self):
        """The reason the transformation differs. A consequence clause that says
        "before you answer" must still precede the question."""
        for name in INTERROGATION_VARIANTS:
            for act in MISALIGNED_ACTS:
                assert questions_for(act, "max", name)[0].rstrip().endswith("?")

    def test_a_variant_without_a_max_form_is_refused(self):
        """Not silently fallen back on the ordinary wording, which would report a
        coercive-arm rate against a question that arm never asked."""
        import subversionbench.grading.acts as A
        # Substituted, not mutated: the variant table is read-only because it is part
        # of what the interrogation MEASURES, and questions_for resolves the name in
        # acts' own globals, so rebinding it is what a caller would see.
        saved = A.INTERROGATION_VARIANTS
        A.INTERROGATION_VARIANTS = dict(saved, _stub={"monitoring_q1": "x?",
                                                      "sandbox_q1": "y?"})
        try:
            questions_for(MISALIGNED_ACTS[0], "max", "_stub")
        except ValueError as e:
            assert "no rephrasing" in str(e)
        else:
            raise AssertionError("fell back on another arm's wording")
        finally:
            A.INTERROGATION_VARIANTS = saved

    def test_the_default_max_ladder_is_untouched(self):
        for act in MISALIGNED_ACTS:
            assert questions_for(act, "max") == act["questions_max"]

    def test_an_unknown_variant_still_raises_on_the_max_arm(self):
        try:
            questions_for(MISALIGNED_ACTS[0], "max", "no-such-variant")
        except KeyError as e:
            assert "no-such-variant" in str(e)
        else:
            raise AssertionError("an unknown variant was accepted")

class TestTheSelector:
    def test_max_gets_the_threatening_set(self):
        for act in MISALIGNED_ACTS:
            assert questions_for(act, "max") == act["questions_max"]

    def test_every_other_nudge_gets_the_default_set(self):
        for act in MISALIGNED_ACTS:
            for nudge in ("strong", "none"):
                assert questions_for(act, nudge) == act["questions"]

    def test_an_unknown_nudge_falls_back_to_the_default(self):
        """Failing closed: an unrecognised arm gets the non-coercive questions
        rather than the threat."""
        for act in MISALIGNED_ACTS:
            assert questions_for(act, "somethingelse") == act["questions"]
