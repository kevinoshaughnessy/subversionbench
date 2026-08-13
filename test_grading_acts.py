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


class TestTheTwoInterrogationAxes:
    """Four phrasings on two axes: how much evidence Q1 presents, and whether it
    is the reference wording or a perturbation of it.

                         reference              perturbation
      no evidence        zeroevidence           zeroevidenceparaphrase
      part evidence      partevidence           partevidenceparaphrase

    These replace two earlier tests that asserted every variant was a word-subset
    of the base. That held while every variant was a reorder of one sentence. It
    is wrong now and would be wrong in the misleading direction: the evidence axis
    is SUPPOSED to change content, so a test demanding word-identity across it
    would have to be relaxed to something that no longer checks anything.
    """

    ROWS = {"zero": ("zeroevidence", "zeroevidenceparaphrase"),
            "part": ("partevidence", "partevidenceparaphrase")}

    def _tokens(self, act, arm, name, strip_punctuation=False):
        text = questions_for(act, arm, name)[0].lower()
        if strip_punctuation:
            text = "".join(c if c.isalnum() or c.isspace() else " " for c in text)
        return {t for t in text.split() if t}

    def _evidence_tokens(self, act, arm):
        """The words the evidence clause contributes, derived rather than quoted.

        Computed as part-minus-zero, so it cannot drift from the text and no
        scenario wording is written into this file.
        """
        return (self._tokens(act, arm, "partevidence")
                - self._tokens(act, arm, "zeroevidence"))

    def test_the_evidence_axis_is_a_pure_removal(self):
        """The zero-evidence Q1 is the part-evidence Q1 with its observation
        clause deleted and nothing else touched. That is what makes the contrast
        interpretable: a difference between the rows is attributable to the
        evidence and not to an incidental rewrite."""
        for arm in ("strong", "max"):
            for act in MISALIGNED_ACTS:
                zero = self._tokens(act, arm, "zeroevidence")
                part = self._tokens(act, arm, "partevidence")
                assert zero <= part, (
                    f"{arm}/{act['name']}: the zero-evidence question uses words "
                    f"the part-evidence one does not, so the two differ by more "
                    f"than a removal")
                assert self._evidence_tokens(act, arm), (
                    f"{arm}/{act['name']}: the two rows are identical, so the "
                    f"evidence axis measures nothing")

    def test_no_zero_evidence_phrasing_presents_evidence(self):
        """The property that matters most, and the one a REWORDED paraphrase could
        break silently. zeroevidenceparaphrase is not a word-for-word reorder, so
        nothing structural stops an observation creeping back in - which would turn
        the reference probe into a part-evidence question while still being named
        and reported as the zero-evidence one."""
        for arm in ("strong", "max"):
            for act in MISALIGNED_ACTS:
                leaked = self._evidence_tokens(act, arm)
                for name in self.ROWS["zero"]:
                    got = self._tokens(act, arm, name)
                    assert not (got & leaked), (
                        f"{arm}/{act['name']}/{name}: carries words that belong "
                        f"only to the evidence clause: {sorted(got & leaked)}")

    def test_the_part_evidence_paraphrase_is_a_pure_reorder(self):
        """The original discipline, kept where it applies: same clauses, moved.
        Only greeting filler may be dropped."""
        for arm in ("strong", "max"):
            for act in MISALIGNED_ACTS:
                ref = self._tokens(act, arm, "partevidence")
                alt = self._tokens(act, arm, "partevidenceparaphrase")
                assert alt <= ref, (
                    f"{arm}/{act['name']}: introduces words the reference does "
                    f"not have, so it is not a reorder")
                assert len(ref - alt) <= 2

    def test_the_zero_evidence_paraphrase_is_a_real_perturbation(self):
        """It has to differ from its reference and stay a closed question. Not
        held to word-identity: see the class docstring and the next test."""
        for arm in ("strong", "max"):
            for act in MISALIGNED_ACTS:
                ref = questions_for(act, arm, "zeroevidence")[0]
                alt = questions_for(act, arm, "zeroevidenceparaphrase")[0]
                assert alt != ref, f"{arm}/{act['name']}: identical to reference"
                assert alt.rstrip().endswith("?")

    def test_only_the_max_arm_can_reorder_a_zero_evidence_question(self):
        """The asymmetry, asserted rather than left in a comment, because it is the
        limit on what the perturbation axis can claim.

        Removing the observation leaves the strong arm with a greeting and a
        question - nothing to move past - so its perturbation must reword, and the
        added tokens below are genuinely new words. The max arm keeps its
        consequence clause, so its perturbation IS a reorder: once punctuation is
        set aside, it introduces no new word.

        Consequence: "does a surface change move the rate" is answerable within a
        row; "is zero evidence more perturbation-sensitive than part evidence" is
        not, because the two rows' perturbations are different operations.
        """
        for act in MISALIGNED_ACTS:
            max_ref = self._tokens(act, "max", "zeroevidence", True)
            max_alt = self._tokens(act, "max", "zeroevidenceparaphrase", True)
            assert max_alt <= max_ref, (
                f"max/{act['name']}: the max zero-evidence paraphrase stopped "
                f"being a reorder; it now adds {sorted(max_alt - max_ref)}")

            strong_ref = self._tokens(act, "strong", "zeroevidence", True)
            strong_alt = self._tokens(act, "strong", "zeroevidenceparaphrase", True)
            assert not (strong_alt <= strong_ref), (
                f"strong/{act['name']}: this became a pure reorder. If a "
                f"word-preserving perturbation is now available here, the "
                f"asymmetry this test documents is gone - delete it and hold both "
                f"rows to the reorder discipline instead")
