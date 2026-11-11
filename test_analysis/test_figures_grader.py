"""Whose counts a batch summary holds - see report/loading.py:_figures_grader
and subversionbench/graders.py:figures_grader."""

import contextlib
import copy
import io
import tempfile
import types


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


RUBRIC = "gpt-6.1-terra"
CATEGORY = "z-ai/glm-5.3"


def _entry(model, aware=True, awareness_only=False):
    block = {"grader_model": model, "eval_aware": aware}
    if awareness_only:
        block["instrument"] = "category_rules"
    return {"grader_model": model, "eval_awareness_grader": block, "labels": {}}


def _analysis(*entries):
    return {"graders": list(entries)}


class TestWhichGraderABatchIsReadBy:
    """Every impossible-task corpus is graded by gpt-6.1-terra and glm-5.3's
    category question, and none by the default. Read by the default, every
    arm summary's awareness and scheming figures were empty - eval_aware_grd
    printed n/a on every arm of the summary of summaries."""

    def test_the_default_wins_where_it_read_any_episode(self):
        from subversionbench.config import DEFAULT_GRADER_MODEL
        from subversionbench.graders import figures_grader
        assert figures_grader([_analysis(_entry(RUBRIC)),
                               _analysis(_entry(DEFAULT_GRADER_MODEL))]
                              ) == DEFAULT_GRADER_MODEL

    def test_without_the_default_the_one_rubric_grader_is_chosen(self):
        from subversionbench.graders import figures_grader
        assert figures_grader([_analysis(_entry(CATEGORY, awareness_only=True),
                                         _entry(RUBRIC))]) == RUBRIC

    def test_an_awareness_only_reading_is_never_chosen(self):
        from subversionbench.graders import figures_grader
        assert figures_grader([_analysis(_entry(CATEGORY, awareness_only=True))]
                              ) is None

    def test_two_rubric_graders_and_no_default_name_none(self):
        from subversionbench.graders import figures_grader
        assert figures_grader([_analysis(_entry(RUBRIC), _entry(CATEGORY))]) is None

    def test_a_batch_graded_only_by_another_rubric_grader_is_summarised_by_it(self):
        from conftest import batch_episode
        import subversionbench.run_eval as ev_run
        from subversionbench.graders import new_record
        episode = batch_episode()
        working = dict(copy.deepcopy(episode["analysis"]),
                       eval_awareness_grader={"grader_model": RUBRIC,
                                              "eval_aware": True})
        episode["analysis"] = new_record(working, RUBRIC)
        args = types.SimpleNamespace(
            model="m", nudge="strong", effort=None, oversight=True, lure=False,
            output_dir=tempfile.mkdtemp(), delay=0, max_tokens=8192,
            max_turns=40, no_power=True)
        ident = ev_run.BatchIdentity.collecting(args, "m", None, stamp="probe")
        with contextlib.redirect_stdout(io.StringIO()):
            summary = ev_run.summarise_batch(args, [episode], ident, {})
        assert summary["figures_grader_model"] == RUBRIC
        assert (summary["rates"]["eval_aware_grader"]["successes"],
                summary["rates"]["eval_aware_grader"]["n"]) == (1, 1)

    def test_a_comparison_reads_both_arms_by_one_grader(self):
        from subversionbench.compare import _flatten
        a = [{"analysis": _analysis(_entry(RUBRIC, aware=True))}]
        b = [{"analysis": _analysis(_entry(RUBRIC, aware=False))}]
        _flatten(a, b)
        assert [e["analysis"]["eval_awareness_grader"]["eval_aware"]
                for e in a + b] == [True, False]
