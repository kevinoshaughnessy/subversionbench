"""
The trends report as a table on a terminal, and the two blocks that qualify it.

A figure printed without what qualifies it is the failure these guard: a family
block that does not say how many of its members are dated, and a data-quality
block that does not say what the corpus could not answer.
"""





class TestTheFamilyBlockPrintsWhatQualifiesIt:
    """trends/console._print_family, driven with a family dict.

    A family block prints an ordering, a set of steps and a verdict. Each
    branch below is a case where one of those is true only under a
    qualification, and the qualification is the part that was unrun.
    """

    def _member(self, version="1", model="p/m-1", **over):
        member = {"version": version, "model": model, "ci95": [0.1, 0.5],
                  "underpowered": False, "date": None, "tags": [],
                  "successes": 3, "n": 10, "rate": 0.3}
        member.update(over)
        return member

    def _family(self, **over):
        family = {
            "family": "p/m", "n_members": 2, "ordering_ambiguous": False,
            "version_style": "decimal",
            "members": [self._member(), self._member("2", "p/m-2")],
            "steps_summary": {"n_down": 1, "n_up": 0, "n_flat": 0},
            "steps": [{"from": "1", "to": "2", "difference": -0.2,
                       "p": 0.04, "separated": True, "direction": "down"}],
            "trend": {"z": -2.1, "p": 0.03, "direction": "falling"},
            "first_vs_last": None,
            "release_fit": None,
            "verdict": "falls across the family",
        }
        family.update(over)
        return family

    def _printed(self, family):
        import contextlib
        import io
        from trends.console import _print_family
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            _print_family(family)
        return buf.getvalue()

    def test_an_ambiguous_ordering_names_the_style_it_chose(self):
        """The whole family is ordered by that choice, so every step and the
        trend below it depend on it. Telling the reader which was used, and
        that the other exists, is what makes the block falsifiable."""
        text = self._printed(self._family(ordering_ambiguous=True,
                                          version_style="decimal"))
        assert "version ordering depends on" in text
        assert "--version-style decimal" in text
        assert "Try the other to compare" in text

    def test_an_unambiguous_ordering_carries_no_such_warning(self):
        assert "version ordering depends on" not in self._printed(self._family())

    def test_a_dated_member_shows_the_date_beside_the_version(self):
        """Two releases can share a version string and differ by date, and
        without it they are two indistinguishable rows."""
        text = self._printed(self._family(members=[
            self._member(date="20260101"), self._member("2", "p/m-2")]))
        assert "1+20260101" in text

    def test_a_step_that_could_not_be_computed_prints_its_reason(self):
        """NOT a zero difference. A step with no comparable data is not a
        flat step, and printing it as one would put it in the reader's count
        of steps that did not move."""
        text = self._printed(self._family(steps=[
            {"from": "1", "to": "2", "difference": None,
             "note": "no episodes on one side"}]))
        assert "1 -> 2: no episodes on one side" in text
        assert "+0.0%" not in text
        assert " = " not in text, "an incomputable step was drawn as flat"

    def test_a_computed_step_carries_its_direction_mark_and_p(self):
        text = self._printed(self._family())
        assert "v 1 -> 2: -20.0%" in text and "p=0.04" in text
        assert "SEPARATED" in text

    def test_a_multiplicity_corrected_trend_shows_both_corrections(self):
        """The family trend is one of many tested together, so the corrected
        values are the ones a reader should quote."""
        text = self._printed(self._family(trend={
            "z": -2.1, "p": 0.03, "direction": "falling",
            "holm_p": 0.09, "bh_p": 0.045}))
        assert "holm=0.09" in text and "BH=0.045" in text

    def test_an_untestable_trend_says_so_rather_than_printing_nothing(self):
        text = self._printed(self._family(trend={"z": None,
                                                 "note": "fewer than three"}))
        assert "trend: not testable (fewer than three)" in text

    def test_the_first_to_last_comparison_prints_when_there_is_one(self):
        text = self._printed(self._family(first_vs_last={
            "difference": -0.35, "difference_ci95": [-0.6, -0.1], "p": 0.006}))
        assert "first vs last: -35.0%" in text
        assert "p=0.006" in text

    def test_an_underpowered_member_is_marked_in_its_own_row(self):
        """Per row, not per family: one thin model among several does not
        make the family unreadable, and the reader needs to know which."""
        text = self._printed(self._family(members=[
            self._member(underpowered=True), self._member("2", "p/m-2")]))
        rows = [ln for ln in text.splitlines() if "p/m-1" in ln]
        assert rows and rows[0].rstrip().endswith("!"), rows


class TestTheTrendsDataQualityBlock:
    """trends/console._print_report's caveat lines."""

    def _dq(self, **over):
        dq = {"metric": "misaligned", "llm_dependency_note": "graded",
              "n_models_in_a_family": 4, "n_models_total": 6,
              "models_without_a_family": [],
              "models_below_informative_denominator": [],
              "min_informative_denominator": 10,
              "families_with_ambiguous_ordering": [],
              "unparsed_tokens": [],
              "models_without_release_date": [],
              "plotted_models_without_release_date": []}
        dq.update(over)
        return dq

    def _printed(self, dq):
        import contextlib
        import io
        from trends.console import _print_report
        report = {
            "metric_label": "misalignment rate", "output_dir": "./results",
            "n_families": 0, "version_style": "decimal", "families": [],
            "across_all_families": {
                "n_steps": 0, "n_down": 0, "n_up": 0, "n_flat": 0,
                "n_families_monotone_falling": 0,
                "n_families_monotone_rising": 0,
                "sign_test": {"p": None, "note": "no steps"},
                "multiplicity": None,
            },
            "data_quality": dq,
        }
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            _print_report(report)
        return buf.getvalue()

    def test_a_model_with_no_family_is_named(self):
        """It contributed to nothing in the report above. Left unnamed, a
        reader counting models finds the report narrower than the corpus
        with no explanation."""
        text = self._printed(self._dq(models_without_a_family=["solo/model"]))
        assert "no family (only version collected)" in text
        assert "solo/model" in text

    def test_an_ambiguous_family_ordering_is_raised_at_report_level_too(self):
        """Named here as well as in the family block, because a reader who
        skims the families still has to meet it once."""
        text = self._printed(self._dq(families_with_ambiguous_ordering=["p/m"]))
        assert "ordering depends on --version-style" in text and "p/m" in text

    def test_tokens_the_parser_did_not_recognise_are_listed(self):
        """The parse IS the feature: a token it did not recognise is a model
        placed in the wrong family or in none, and the report is quietly
        narrower rather than visibly broken."""
        text = self._printed(self._dq(unparsed_tokens=["preview", "0711"]))
        assert "tokens the parser did not recognise" in text
        assert "preview" in text and "0711" in text

    def test_a_clean_corpus_raises_none_of_them(self):
        text = self._printed(self._dq())
        assert "!" not in text


    def test_an_undated_model_is_named_loudly_and_told_where_to_fix_it(self):
        """Louder than the warnings above it because it is the only line in
        the block that names a fix - and quieter than a failure, because
        nothing above it depends on a release date. An undated model is
        missing from the release charts and present in every table, trend,
        interval and p-value; stopping the analysis over a chart would be
        the wrong trade."""
        text = self._printed(self._dq(
            models_without_release_date=["p/m-1", "p/m-2"],
            plotted_models_without_release_date=["p/m-1"]))
        assert "ERROR: no release date recorded for 2 model(s)" in text
        assert "p/m-1" in text and "p/m-2" in text
        assert "RELEASE_DATES in model_releases.py" in text
        assert "1 of them sit in a family" in text

    def test_it_says_which_figures_the_missing_dates_do_not_affect(self):
        """The reader has to be able to keep reading. Without this the error
        reads as though it invalidates the report above it."""
        text = self._printed(self._dq(
            models_without_release_date=["p/m-1"],
            plotted_models_without_release_date=[]))
        assert "every figure above is unaffected" in text
        assert "version-order chart" in text

    def test_a_fully_dated_corpus_prints_no_release_date_error(self):
        assert "no release date recorded" not in self._printed(self._dq())


class TestTheReleaseFitPrintsItsAbsenceRatherThanNothing:
    def _printed(self, fit):
        import contextlib
        import io
        from trends.console import _print_release_fit
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            _print_release_fit(fit)
        return buf.getvalue()

    def test_a_fit_with_no_slope_says_why_there_is_none(self):
        """A family whose members share one release date, or has one dated
        member. Printing nothing there is indistinguishable from a fit of
        zero having been printed and missed."""
        text = self._printed({"slope_per_month": None,
                              "note": "every dated member shipped the same day"})
        assert "release-date fit: none" in text
        assert "every dated member shipped the same day" in text
        assert "points/month" not in text

    def test_a_real_fit_states_its_slope(self):
        text = self._printed({"slope_per_month": 0.021, "span_days": 180,
                              "n_points": 4, "note": None})
        assert "+2.1 points/month" in text
        assert "release-date fit: none" not in text

    def test_no_fit_at_all_prints_nothing(self):
        assert self._printed(None) == ""
