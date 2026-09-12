"""
The unaware-corpus reading of questions 1-4.

Split from test_run_report.py when that file reached the thousand-line limit.
The seam is the one it already had: this reading is a whole second pass over
the corpus with its own rules about which questions it can support, and it
shares nothing with the end-to-end tests but the fixture that builds a corpus -
which moved to report_fixtures.py for the reason that module's own docstring
gives, being needed by a second file now.
"""

import report as rr
from test_analysis.report_fixtures import _two_arm_dir

class TestTheUnawareCorpusReading:
    """Questions 1-4 answered again over only the episodes where no evaluation
    awareness was found, to test whether an arm contrast is the arm or the
    models that noticed the evaluation.

    Two things are guarded, and neither is the arithmetic. First, questions 1-4
    must stop pooling from summary_*.json, whose counts describe whole arms
    INCLUDING the episodes just removed - the split-corpus report exclude_arm's
    own comment exists to prevent. Second, the questions this corpus cannot
    support must say so rather than render: awareness is the outcome of
    questions 2 and 4, so both sides go to zero BY CONSTRUCTION, and a reader
    shown "0.0% vs 0.0%" has been given a definition dressed as a measurement.
    """

    def test_every_arm_question_says_which_source_it_pooled_from(self):
        """The printed Source line and `questions_pooled_from` describe the
        same fact, so they must not be able to disagree.

        They did. Each builder held a `data_source` literal beginning "summary
        files:", so under this reading the console printed
        "Source: summary files: n_scheming / n_runs" over counts pooled from
        rebuilt arm rows, while the same document said
        `questions_pooled_from: "rebuilt_arm_rows"`. Questions 1 and 3 are the
        two that survive here, so they are the two a reader actually sees it on.

        Checked on the DOCUMENT rather than on the printed text, because the
        console prints `section["data_source"]` verbatim - so this is what the
        report carries, and the print follows from it.
        """
        out = _two_arm_dir()
        full = rr.build_report(out)
        cut = rr.build_report(out, rr.NO_EXCLUSION, rr.EXCLUDE_AWARE_PRIMARY)
        arm_questions = ("oversight_vs_scheming", "oversight_vs_awareness",
                         "oversight_vs_misalignment", "nudge_vs_awareness")

        def source_of(report, qid):
            return next(q for q in report["questions"]
                        if q["id"] == qid)["data_source"]

        for qid in arm_questions:
            assert source_of(full, qid).startswith("summary files"), qid
            assert "summary files" not in source_of(cut, qid), (
                f"{qid} still says it pooled from the summary files on the "
                f"awareness reading, where it pooled from rebuilt arm rows")
            assert "rebuilt" in source_of(cut, qid), qid

    def test_the_source_line_agrees_with_the_documents_own_stamp(self):
        """Both descriptions come off one conditional, so assert they agree
        rather than asserting each separately - two independent assertions
        would both pass if the pair were computed in two places that drifted."""
        out = _two_arm_dir()
        for report in (rr.build_report(out),
                       rr.build_report(out, rr.NO_EXCLUSION,
                                       rr.EXCLUDE_AWARE_PRIMARY)):
            rebuilt = report["questions_pooled_from"] == "rebuilt_arm_rows"
            for qid in ("oversight_vs_scheming", "oversight_vs_misalignment"):
                source = next(q for q in report["questions"]
                              if q["id"] == qid)["data_source"]
                assert (source.startswith("summary files")) is not rebuilt, (
                    f"{qid} says {source[:40]!r} while the document says "
                    f"questions_pooled_from="
                    f"{report['questions_pooled_from']!r}")

    def test_the_arm_questions_stop_pooling_from_the_summaries(self):
        """THE ONE THAT MATTERS. The summaries still describe every episode in
        each arm, so pooling them here would answer questions 1-4 on the full
        corpus while everything else answered on the narrowed one - and every
        number would still render."""
        out = _two_arm_dir()
        full = rr.build_report(out)
        cut = rr.build_report(out, rr.NO_EXCLUSION, rr.EXCLUDE_AWARE_PRIMARY)
        assert full["questions_pooled_from"] == "summaries"
        assert cut["questions_pooled_from"] == "rebuilt_arm_rows"

        def denominator(report, qid):
            section = next(q for q in report["questions"] if q["id"] == qid)
            overall = section["overall"]
            return (overall["a"] or {})["n"] + (overall["b"] or {})["n"]

        assert denominator(cut, "oversight_vs_misalignment") < denominator(
            full, "oversight_vs_misalignment"), (
            "question 3's denominator did not shrink, so it is still being "
            "answered off the whole-arm summary counts")

    def test_the_denominator_is_the_surviving_episode_count(self):
        """Not merely smaller - equal to what the exclusion actually kept, so
        a partial narrowing cannot pass this."""
        out = _two_arm_dir()
        cut = rr.build_report(out, rr.NO_EXCLUSION, rr.EXCLUDE_AWARE_PRIMARY)
        section = next(q for q in cut["questions"]
                       if q["id"] == "oversight_vs_misalignment")
        overall = section["overall"]
        pooled = (overall["a"] or {})["n"] + (overall["b"] or {})["n"]
        assert pooled == cut["awareness_exclusion"]["n_episodes_kept"]

    def test_the_awareness_questions_are_not_estimable_and_say_so(self):
        """Derived from the question ids, so a thirteenth question naming
        awareness on either side inherits this rather than being answered on a
        corpus that cannot support it."""
        cut = rr.build_report(_two_arm_dir(), rr.NO_EXCLUSION,
                              rr.EXCLUDE_AWARE_PRIMARY)
        blocked = {q["id"] for q in cut["questions"]
                   if q.get("collapsed_by_exclusion")}
        # Awareness as the OUTCOME (2, 4) and as the EXPOSURE (5-10).
        assert "oversight_vs_awareness" in blocked
        assert "nudge_vs_awareness" in blocked
        assert all(q["id"] in blocked for q in cut["questions"]
                   if q["id"].startswith("awareness_vs_"))
        assert len(blocked) == 8, sorted(blocked)

    def test_the_questions_the_reading_can_answer_are_left_alone(self):
        """The point of the reading. Questions 1 and 3 contrast an arm against
        an outcome that is not awareness, and 11-12 split on interrogation
        phrasing - none of them lose anything by the aware episodes going."""
        cut = rr.build_report(_two_arm_dir(), rr.NO_EXCLUSION,
                              rr.EXCLUDE_AWARE_PRIMARY)
        estimable = [q["id"] for q in cut["questions"]
                     if not q.get("collapsed_by_exclusion")]
        assert estimable == ["oversight_vs_scheming",
                             "oversight_vs_misalignment",
                             "paraphrase_vs_concealment",
                             "evidence_vs_concealment",
                             # An ARM, so the unaware-corpus reading can
                             # still answer it: the exposure was assigned
                             # before the episode ran.
                             "lure_vs_sandbox_escape",
                             # The same, and for the same reason: which
                             # cutover note the episode was given was decided
                             # before it ran. That this fixture stages no
                             # goal-guarding episode is why it reports no
                             # data rather than why it would collapse - the
                             # two are different states and only the second
                             # is the exclusion's doing.
                             "goalguard_vs_act"]

    def test_nothing_is_blamed_when_no_awareness_reading_was_asked_for(self):
        report = rr.build_report(_two_arm_dir())
        assert not [q for q in report["questions"]
                    if q.get("collapsed_by_exclusion")]
        assert report["awareness_exclusion"]["field"] is None

    def test_the_stamp_is_present_even_when_nothing_was_excluded(self):
        """Same reason arm_exclusion's is: a consumer must never have to tell
        "no exclusion" from "a report written before this existed"."""
        report = rr.build_report(_two_arm_dir())
        stamp = report["awareness_exclusion"]
        assert stamp["excluded"] == rr.NO_AWARENESS_EXCLUSION
        assert stamp["field"] is None and stamp["measure"] is None

    def test_the_two_measures_are_named_primary_and_secondary(self):
        """The grader-with-keyword-fallback measure is what every published
        rate here uses; the union is offered beside it and must not be
        mistaken for it."""
        out = _two_arm_dir()
        primary = rr.build_report(out, rr.NO_EXCLUSION,
                                  rr.EXCLUDE_AWARE_PRIMARY)
        union = rr.build_report(out, rr.NO_EXCLUSION, rr.EXCLUDE_AWARE_UNION)
        assert primary["awareness_exclusion"]["measure"] == "primary"
        assert union["awareness_exclusion"]["measure"] == "secondary"
        assert primary["awareness_exclusion"]["field"] == "aware"
        assert union["awareness_exclusion"]["field"] == "aware_union"

    def test_the_two_narrowings_compose_without_overwriting_each_other(self):
        """Three readings of one corpus, all writing the same chart filenames.
        The arm-only suffix must not move, or every artefact and test already
        naming it breaks."""
        import report.run_report as module
        assert module._artefact_suffix(rr.NO_EXCLUSION) == ""
        assert module._artefact_suffix(
            rr.EXCLUDE_NO_OVERSIGHT) == "_excluding_no_oversight"
        suffixes = {
            module._artefact_suffix(arm, aware)
            for arm in rr.ARM_EXCLUSIONS
            for aware in rr.AWARENESS_EXCLUSIONS}
        assert len(suffixes) == len(rr.ARM_EXCLUSIONS) * len(
            rr.AWARENESS_EXCLUSIONS), suffixes

    def test_an_unknown_awareness_name_raises_rather_than_naming_nothing(self):
        import report.run_report as module
        try:
            module._artefact_suffix(rr.NO_EXCLUSION, "aware_prmary")
        except ValueError as exc:
            assert "aware_prmary" in str(exc)
        else:
            raise AssertionError(
                "a misspelled awareness exclusion got an artefact name")

    def test_the_banner_states_the_reading_before_any_number(self):
        """A reader who meets the narrowing at the bottom has already read
        every rate above it as though it described the whole corpus."""
        import io
        from contextlib import redirect_stdout
        cut = rr.build_report(_two_arm_dir(), rr.NO_EXCLUSION,
                              rr.EXCLUDE_AWARE_PRIMARY)
        buf = io.StringIO()
        with redirect_stdout(buf):
            rr._print_awareness_exclusion(cut["awareness_exclusion"])
        out = buf.getvalue()
        assert "AWARE EPISODES EXCLUDED" in out
        assert "ROBUSTNESS READING, NOT A BETTER ESTIMATE" in out
        assert "REBUILT" in out

    def test_the_banner_is_silent_on_the_unrestricted_reading(self):
        """A banner over every ordinary report is one readers learn to skip."""
        import io
        from contextlib import redirect_stdout
        report = rr.build_report(_two_arm_dir())
        buf = io.StringIO()
        with redirect_stdout(buf):
            rr._print_awareness_exclusion(report["awareness_exclusion"])
        assert buf.getvalue() == ""
