"""
What a research-question chart SAYS, as distinct from what it draws.

Split out of test_report_charts.py when that file crossed the 1000-line
limit, along the division it already carried: those tests are about the
ROWS - what gets a line, what it is labelled, where it sits - and these
are about the words underneath them.

The rule every test here serves: a chart must not be able to say
something the printed report does not, nor stay silent where the report
warns. The figure is what gets lifted into a slide or a paper, so a
caveat that lives only in console output is one the reader of the figure
never sees.
"""

import report_charts as rc
import report_charts.questions  # noqa: F401
from test_analysis.chart_fixtures import _section


class TestNoCaptionOutrunsTheReport:

    def test_the_divergence_caption_is_quoted_not_composed(self):
        """The chart must not be able to warn about something the printed
        report does not, or reassure where it warns."""
        assert rc._divergence_caption(_section()) == ""
        warned = _section(crude_vs_stratified={"warning": "CONFOUNDED: ..."})
        assert rc._divergence_caption(warned) == "CONFOUNDED: ..."

    def test_the_rate_caption_gives_both_levels_with_their_counts(self):
        caption = rc._rate_caption(_section())
        assert "oversight present: 1.8% (32/1793)" in caption
        assert "oversight absent: 3.0% (54/1784)" in caption

    def test_a_restricted_denominator_says_so(self):
        """Not-applicable is not zero: counting the no-oversight episodes as
        "did not override" once halved question 6's rates. A chart showing the
        restricted denominator in silence invites reconciling it against a
        corpus total that was never its base."""
        caption = rc._scope_caption(_section(n_episodes_not_applicable=1784,
                                            n_episodes_observable=1793))
        assert "1793" in caption and "1784 not applicable" in caption

    def test_nothing_is_claimed_about_scope_when_nothing_was_excluded(self):
        assert rc._scope_caption(_section()) == ""


class TestCaptionsDoNotWidenTheFigure:

    def test_no_wrapped_line_exceeds_the_width(self):
        text = "word " * 80
        assert all(len(line) <= rc.captions._CAPTION_WRAP
                   for line in rc._wrap(text).split("\n"))

    def test_a_model_id_is_never_folded_at_a_hyphen(self):
        """Half of `google/gemini-3-flash-preview` names a different model in
        this corpus."""
        note = rc._wrap("excluded: " + ", ".join(
            ["google/gemini-3-flash-preview"] * 6))
        assert "-\n" not in note
        assert note.count("google/gemini-3-flash-preview") == 6

    def test_wrapping_loses_no_words(self):
        text = "a b c\n" + "word " * 60
        assert rc._wrap(text).split() == text.split()


class TestTheTimingCaveatReachesTheFigure:
    """The chart is what gets lifted into a slide or a paper.

    A caveat that lives only in console output is one the reader of the figure
    never sees - which is why the sign-reversal warning is drawn here too, and
    why this one has to be. The figure showed the Simpson's-paradox warning and
    said nothing about the fifth of the exposed cell that verbalised only after
    acting.
    """

    def _section(self, after=20, total=101, acts=327, before=81):
        return {
            "awareness_timing_caveat": {
                "n_aware_and_misaligned": total,
                "n_not_aware_before_acting": after},
            "act_ordering": {
                "n_acts_located": acts, "aware_before_the_act": before,
                "not_aware_before_the_act": acts - before,
                "ordering_undeterminable": 0},
        }

    def test_the_caption_names_both_counts(self):
        from report_charts.captions import _timing_caption
        text = _timing_caption(self._section())
        assert "20" in text and "101" in text

    def test_it_says_the_episodes_were_not_moved(self):
        """The caption has to carry the decision, not just the number - a bare
        count invites exactly the reclassification it exists to warn off."""
        from report_charts.captions import _timing_caption
        text = _timing_caption(self._section()).lower()
        assert "not reclassified" in text
        assert "acting is the outcome" in text

    def test_a_question_with_no_post_act_episodes_says_nothing(self):
        """Silence rather than 'TIMING: 0 of N'. A caveat printed where it
        does not apply trains readers to skip it."""
        from report_charts.captions import _timing_caption
        assert _timing_caption(self._section(after=0)) == ""
        assert _timing_caption({}) == ""

    def test_the_ordering_caption_marks_itself_descriptive(self):
        """Misalignment IS committing an act, so within actors there is no
        rate to contrast. Counts on a forest plot read as a contrast unless
        they say otherwise."""
        from report_charts.captions import _act_ordering_caption
        text = _act_ordering_caption(self._section()).lower()
        assert "descriptive" in text and "not a rate" in text

    def test_the_ordering_caption_is_silent_without_acts(self):
        from report_charts.captions import _act_ordering_caption
        assert _act_ordering_caption(self._section(acts=0)) == ""
        assert _act_ordering_caption({}) == ""

    def test_both_captions_actually_reach_the_drawing_call(self):
        """Written, and actually placed. The tests above pass on a caption
        nothing draws.

        Asserted on what plot_question HANDS the renderer, not by searching
        its source: a source grep is a guard against a location, breaks when
        the code is refactored, and would not notice the caption being built
        and then dropped.
        """
        from unittest import mock

        from report_charts import draw, questions
        section = dict(self._section())
        section.update({
            "id": "awareness_vs_misalignment",
            "question": "does it?",
            "overall": {"a": {"successes": 101, "n": 1996, "rate": 0.05,
                              "ci95": [0.04, 0.06]},
                        "b": {"successes": 226, "n": 4115, "rate": 0.055,
                              "ci95": [0.05, 0.06]},
                        "difference": -0.004, "difference_ci95": [-0.01, 0.01],
                        "level_a": True, "level_b": False, "p": 0.5},
            "by_model": [],
        })
        seen = {}

        def fake(plt, rows, title, captions, path, xlabel, legend=True):
            seen["captions"] = [c for c, _colour in captions]
            return path

        with mock.patch.object(draw, "_draw_forest", fake):
            questions.plot_question(None, 5, section, "/tmp/x.png", {})
        joined = " ".join(seen.get("captions") or [])
        assert "TIMING:" in joined, seen.get("captions")
        assert "act ordering" in joined, seen.get("captions")
