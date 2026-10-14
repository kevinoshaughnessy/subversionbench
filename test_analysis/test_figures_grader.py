"""Whose counts a batch summary holds - see report/loading.py:_figures_grader."""


class TestASummaryNamesOnlyAGraderThatReadIt:
    """A --no-grader batch was labelled with the default grader, and grading
    it later left the summary as it was - so the label claimed counts the
    file never held, and the report would pool them under that grader."""

    def test_an_unlabelled_summary_is_the_legacy_default(self):
        from report.loading import _figures_grader
        from subversionbench.config import LEGACY_DEFAULT_GRADER_MODEL
        assert _figures_grader({}) == LEGACY_DEFAULT_GRADER_MODEL

    def test_a_label_whose_grader_read_nothing_names_no_grader(self):
        from report.loading import _figures_grader, summaries_describe
        d = {"figures_grader_model": "gpt-6-sol", "grader_models": []}
        assert _figures_grader(d) is None
        assert not summaries_describe([{"figures_grader": None}], "gpt-6-sol")

    def test_a_label_whose_grader_read_the_batch_stands(self):
        from report.loading import _figures_grader
        d = {"figures_grader_model": "gpt-6-sol",
             "grader_models": ["claude-opus-5", "gpt-6-sol"]}
        assert _figures_grader(d) == "gpt-6-sol"
