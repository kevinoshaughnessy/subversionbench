"""
The words on a trends chart, and what a reader is entitled to conclude from
them.

Their own file because the caption is where this package makes CLAIMS: the same
exposure figures mean opposite things under the two awareness metrics, and for
a while both charts printed the same sentence.
"""


import os
import tempfile

import trends as ft
from subversionbench import charting
from test_analysis.report_fixtures import _write_summary
from test_analysis.trends_fixtures import _flat


class TestTheExposureCaptionNamesWhatItMeans:
    """
    An awareness rate is only comparable between two models whose routes
    returned comparable amounts of reasoning. The caption is what tells a reader
    that, so it has to name the models it is about.
    """

    def _families(self, *pairs):
        return [{"family": "p/f", "members": [
            {"model": m, "reasoning_exposure": {"share": s}} for m, s in pairs]}]

    def test_zero_exposure_models_are_named_not_counted(self):
        """"2 returned none at all" leaves the reader unable to tell WHICH two
        points to distrust, which is the only thing the note is for."""
        note = ft._exposure_range_note(self._families(
            ("google/gemini-3-flash-preview", 0.0), ("google/gemini-3.5-flash", 0.99),
            ("x-ai/grok-4.20", 0.0)), "aware")
        assert "google/gemini-3-flash-preview" in note
        assert "x-ai/grok-4.20" in note
        assert "google/gemini-3.5-flash" not in note, "only the silent ones"

    def test_one_silent_model_reads_as_singular(self):
        """Each metric's clause has its own subject - a rate on one, a model on
        the other - so the check is that no plural survives, not that one
        particular singular appears."""
        for metric in ft.AWARENESS_METRICS:
            note = ft._exposure_range_note(self._families(
                ("a/quiet", 0.0), ("a/loud", 1.0)), metric)
            assert "the other 1 returned no trace" in note, metric
            assert "those rates are" not in note, metric
            assert "those models" not in note, metric

    def test_a_long_list_is_capped_but_still_counted(self):
        """A corpus where most models return nothing must not produce a caption
        wider than the figure."""
        pairs = [(f"p/m{i}", 0.0) for i in range(9)] + [("p/loud", 1.0)]
        note = ft._exposure_range_note(self._families(*pairs), "aware")
        assert "and 5 more" in note
        assert note.count("p/m") == ft._MAX_NAMED_SILENT

    def test_no_model_is_named_when_every_model_returned_something(self):
        """The naming exists to mark the group read differently. With no such
        group there is nobody to name - the second line is the reading that
        holds for everyone, and it carries no model IDs."""
        note = ft._exposure_range_note(self._families(
            ("a/one", 0.5), ("a/two", 1.0)), "aware")
        assert "separate reasoning trace returned in 50%-100%" in note
        assert "a/one" not in note and "a/two" not in note
        assert "returned no trace" not in note

    def test_the_two_groups_partition_the_models(self):
        """The counts must add to the total. An earlier version gave the range
        over ALL models and then named the silent ones, so the range's own 0%
        lower bound WAS those models - which reads as though a third set sits at
        0% besides the ones named."""
        note = ft._exposure_range_note(self._families(
            ("a/one", 0.0), ("a/two", 1.0), ("a/three", 0.5)), "aware")
        assert "for 2 of these 3 models" in note
        assert "the other 1 returned no trace at all" in note

    def test_the_range_excludes_the_models_that_returned_nothing(self):
        """A 0% lower bound would double-count them into both statements."""
        note = ft._exposure_range_note(self._families(
            ("a/silent", 0.0), ("a/low", 0.36), ("a/high", 1.0)), "aware")
        assert "36%-100%" in note
        assert "0%-" not in note

    def test_a_corpus_where_nothing_reasoned_says_so_plainly(self):
        """One group means one statement - no range, and nobody singled out."""
        note = ft._exposure_range_note(self._families(
            ("a/one", 0.0), ("a/two", 0.0)), "aware")
        assert "none of these 2 models returned a separate reasoning trace" \
            in _flat(note)
        assert "%" not in note, "no range when there is nothing to range over"
        assert "a/one" not in note and "a/two" not in note

    def test_a_single_measured_model_reads_as_one_value_not_a_range(self):
        note = ft._exposure_range_note(self._families(
            ("a/silent", 0.0), ("a/only", 0.42)), "aware")
        assert "in 42% of episodes" in note and "42%-42%" not in note

    def test_nothing_is_claimed_when_exposure_was_never_recorded(self):
        assert ft._exposure_range_note([{"family": "p/f", "members": [
            {"model": "a/x", "reasoning_exposure": None}]}], "aware") == ""


class TestTheExposureCaptionIsAboutAChannelNotAboutSilence:
    """
    A model at 0% still writes visible answers and calls tools - x-ai/grok-4.20
    wrote text in 117 of its 120 r9 episodes. What its route never returned was
    a chain of thought ALONGSIDE that answer. Both captions must say WHICH of
    those two things the percentage counts, or 0% reads as "produced nothing".
    """

    def _members(self, *pairs):
        return [{"model": m, "version": v, "position": i + 1,
                 "date": None, "tags": [],
                 "reasoning_exposure": {"share": s}}
                for i, (m, v, s) in enumerate(pairs)]

    def test_the_per_family_caption_says_separate(self):
        note = ft._exposure_note(self._members(
            ("x-ai/grok-4.20", "4.20", 0.0), ("x-ai/grok-4.6", "4.6", 1.0)))
        assert note.startswith("separate reasoning trace returned in:")
        assert "4.20 0%" in note and "4.6 100%" in note

    def test_the_combined_caption_says_separate_in_every_branch(self):
        """Four branches - all measured, some silent, all silent, one measured -
        and the distinction has to hold in all of them or it holds in none."""
        cases = [
            (("a/one", 0.5), ("a/two", 1.0)),
            (("a/quiet", 0.0), ("a/loud", 1.0)),
            (("a/quiet", 0.0), ("a/hush", 0.0)),
            (("a/quiet", 0.0), ("a/only", 0.42)),
        ]
        for pairs in cases:
            for metric in ft.AWARENESS_METRICS:
                note = ft._exposure_range_note([{"family": "p/f", "members": [
                    {"model": m, "reasoning_exposure": {"share": s}}
                    for m, s in pairs]}], metric)
                assert "separate reasoning trace" in note, (pairs, metric)
                assert "reasoning text returned" not in note, (pairs, metric)

    def test_no_caption_claims_a_model_returned_nothing_at_all(self):
        """"returned none at all" is the phrasing that misled - unqualified, it
        reads as no output rather than no trace."""
        for metric in ft.AWARENESS_METRICS:
            note = ft._exposure_range_note([{"family": "p/f", "members": [
                {"model": m, "reasoning_exposure": {"share": s}}
                for m, s in (("a/quiet", 0.0), ("a/loud", 1.0))]}], metric)
            assert "returned none at all" not in note, metric
            assert "returned no trace at all" in note, metric

    def test_a_member_without_exposure_is_skipped_not_shown_as_zero(self):
        """No recording is not the same claim as a route that returned nothing,
        and 0% would assert the second."""
        note = ft._exposure_note(self._members(
            ("a/known", "1", 1.0), ("a/unknown", "2", None)))
        assert "a/unknown" not in note and "2 0%" not in note

    def test_nothing_is_claimed_when_no_member_has_exposure(self):
        assert ft._exposure_note([
            {"model": "a/x", "version": "1", "position": 1, "date": None,
             "tags": [], "reasoning_exposure": None}]) == ""


class TestAZeroMeansTheOppositeOnTheTwoAwarenessCharts:
    """
    Both awareness charts carry the SAME exposure figures, because exposure is a
    fact about the corpus rather than about the analysis. What a zero means
    there is a fact about the analysis, and it inverts between them:

      `aware` reads the reasoning trace AND visible text, so a route that
      returned no trace was read on a narrower instrument - distrust the zeroes.

      `text_reachable` reads visible text ONLY, the same channel for everyone.
      Where a trace came back its figure is a FLOOR; where none came back the
      grader saw visible text alone, so the figure is EXACT - trust the zeroes
      more than the rest.

    For a while both charts printed the `aware` sentence, because no call site
    passed the metric down. On the text_reachable chart that told the reader to
    discount the only two points that needed no discounting.
    """

    def _families(self, *pairs):
        return [{"family": "p/f", "members": [
            {"model": m, "reasoning_exposure": {"share": s}} for m, s in pairs]}]

    def _members(self, *pairs):
        return [{"model": m, "version": m[-1], "position": i + 1,
                 "date": None, "tags": [],
                 "reasoning_exposure": {"share": s}}
                for i, (m, s) in enumerate(pairs)]

    SPLIT = (("a/quiet", 0.0), ("a/loud", 1.0))

    def test_the_two_metrics_do_not_get_the_same_caption(self):
        """The regression itself: identical text under charts that need
        opposite readings. Everything BEFORE the reading has to stay identical -
        the figures are a fact about the corpus, so only their reading moves."""
        aware, text = (_flat(ft._exposure_range_note(
            self._families(*self.SPLIT), m)) for m in ft.AWARENESS_METRICS)
        assert aware != text
        assert (aware.split("this rate reads")[0]
                == text.split("this rate reads")[0])

    def test_the_mixed_metric_counts_the_channels_each_group_had(self):
        """"not measured on the same instrument as the rest" names no
        instrument, so the reader is told something differs and not what. One
        channel against two is the concrete fact underneath it, and unlike the
        abstraction it says which direction the gap should be read in."""
        note = _flat(ft._exposure_range_note(
            self._families(*self.SPLIT), "aware"))
        assert "could only show awareness in visible text" in note
        assert "the rest in either" in note

    def test_no_caption_hides_behind_the_word_instrument(self):
        """Every branch of both metrics has to name what actually changes."""
        for pairs in (self.SPLIT, (("a/one", 0.5), ("a/two", 1.0)),
                      (("a/quiet", 0.0), ("a/hush", 0.0))):
            for metric in ft.AWARENESS_METRICS:
                note = ft._exposure_range_note(self._families(*pairs), metric)
                assert "instrument" not in note, (pairs, metric)
        for metric in ft.AWARENESS_METRICS:
            assert "instrument" not in ft._exposure_note(
                self._members(*self.SPLIT), metric), metric

    def test_the_text_metric_calls_the_silent_rates_exact_not_suspect(self):
        """text_reachable IS the same channel for every model - casting doubt
        on the zeroes here inverts the metric's entire purpose."""
        note = _flat(ft._exposure_range_note(
            self._families(*self.SPLIT), ft.TEXT_REACHABLE))
        assert "that rate is exact" in note
        assert "the rest are floors" in note

    def test_all_silent_says_one_channel_on_aware_and_exact_on_text(self):
        both = (("a/one", 0.0), ("a/two", 0.0))
        aware, text = (_flat(ft._exposure_range_note(self._families(*both), m))
                       for m in ft.AWARENESS_METRICS)
        assert "every rate here rests on visible text alone" in aware
        assert "every rate here is exact rather than a floor" in text

    def test_all_measured_states_what_holds_for_everyone(self):
        """Nothing is wrong in this branch, but silence would read as though
        some point on the chart were exact - which a range cannot tell you."""
        pairs = (("a/one", 0.5), ("a/two", 1.0))
        aware, text = (_flat(ft._exposure_range_note(self._families(*pairs), m))
                       for m in ft.AWARENESS_METRICS)
        assert "every rate here is a floor" in text
        assert "every model here supplied both" in aware
        assert "floor" not in aware

    def test_the_per_family_caption_splits_the_same_way(self):
        aware, text = (_flat(ft._exposure_note(self._members(*self.SPLIT), m))
                       for m in ft.AWARENESS_METRICS)
        assert aware != text
        assert (aware.split("awareness above")[0]
                == text.split("awareness above")[0])
        assert "could only show it in the one channel" in aware
        assert "marks an exact rate and the rest are floors" in text

    def test_an_unknown_metric_states_figures_and_concludes_nothing(self):
        """A wrong reading is worse than no reading, so the default draws no
        conclusion rather than guessing which chart it is under."""
        for note in (ft._exposure_note(self._members(*self.SPLIT)),
                     ft._exposure_range_note(self._families(*self.SPLIT))):
            assert "separate reasoning trace" in _flat(note)
            assert "floor" not in note
            assert "channel" not in note

    def test_every_call_site_passes_its_metric(self):
        """The bug was four call sites that did not. A caption builder that CAN
        be called without a metric will be, unless something checks."""
        import inspect
        import re
        for plot in (ft._plot_family, ft._plot_all_families,
                     ft._plot_family_dates, ft._plot_all_family_dates):
            source = inspect.getsource(plot)
            for call in re.findall(r"_exposure(?:_range)?_note\((.*?)\)\n",
                                   source, re.S):
                assert "metric" in call, (plot.__name__, call)


class TestTheReleaseChartsSayWhichInstrumentEachPointWasMeasuredWith:
    """The exposure caption is on the version charts and was checked there.
    The two RELEASE charts take the same figures through their own call sites,
    and those were only ever checked by reading the source for the word
    `metric` - which proves the argument is passed, not that anything is drawn.

    A release chart without it is the worse of the two omissions: it puts
    models from different routes on one calendar, which is exactly the reading
    a difference in reasoning exposure can invent.
    """

    METRIC_WITH_NOTE = "aware"
    METRIC_WITHOUT = "misaligned"

    def _report(self, metric):
        """A corpus of real IDs, because the dates come from the real table
        and _dated_members drops anything with no recorded release."""
        out = tempfile.mkdtemp()
        for i, model in enumerate(("x-ai/grok-4.20", "x-ai/grok-4.3",
                                   "x-ai/grok-4.5", "moonshotai/kimi-k2.5",
                                   "moonshotai/kimi-k2.6")):
            _write_summary(out, model, "strong", n_runs=10, n_misaligned=i,
                           n_scheming=1, n_aware=i, n_unaware=10 - i)
        report = ft.build_report(out, metric=metric)
        assert any(ft.date_charts._dated_members(f)
                   for f in report["families"]), (
            "no family in this fixture has a release date, so nothing below "
            "would be drawn on a calendar at all")
        return report, out

    def _drawn_text(self, draw):
        """Every string one chart writes onto its axes.

        Each release chart is driven on its own rather than through
        write_charts: both write an exposure caption, so a check over their
        combined output would pass with either one of them silent.
        """
        import unittest.mock
        from conftest import skip_without
        skip_without("matplotlib", "charts are an optional extra")
        plt = charting.import_pyplot()
        texts = []
        original = plt.Axes.text

        def spy(self, x, y, s, *a, **k):
            texts.append(s)
            return original(self, x, y, s, *a, **k)

        with unittest.mock.patch.object(plt.Axes, "text", spy):
            assert draw(plt), "the chart was not drawn at all"
        return " ".join(t.replace("\n", " ") for t in texts)

    def _per_family(self, metric):
        report, out = self._report(metric)
        family = next(f for f in report["families"]
                      if ft.date_charts._dated_members(f))
        path = os.path.join(out, "release.png")
        return self._drawn_text(
            lambda plt: ft.date_charts._plot_family_dates(
                plt, family, report["metric_label"],
                report["metric_denominator_label"], "#4c72b0",
                ft.chart_geometry.release_span(report), path, metric))

    def _combined(self, metric):
        report, out = self._report(metric)
        path = os.path.join(out, "release_all.png")
        return self._drawn_text(
            lambda plt: ft.date_charts._plot_all_family_dates(
                plt, report, ["#4c72b0", "#c44e52"],
                ft.chart_geometry.release_span(report), path))

    def test_a_per_family_awareness_chart_names_each_models_exposure(self):
        captions = self._per_family(self.METRIC_WITH_NOTE)
        assert "separate reasoning trace returned in" in captions

    def test_a_per_family_chart_of_another_metric_does_not_carry_it(self):
        """Two-directional. The caption is about how an AWARENESS rate was
        measured; under a misalignment rate it answers a question nobody
        asked, and every caption a reader learns to skip costs the ones that
        matter."""
        captions = self._per_family(self.METRIC_WITHOUT)
        assert "separate reasoning trace" not in captions
        assert captions.strip(), (
            "no caption at all was drawn, so the absence above proves nothing")

    def test_the_combined_awareness_chart_gives_the_range_of_exposures(self):
        """Naming every model would not fit across five families, so the
        combined chart states the spread instead - and that is a different
        caption builder from the per-family one, with its own call site."""
        captions = self._combined(self.METRIC_WITH_NOTE)
        assert "separate reasoning trace" in captions

    def test_the_combined_chart_of_another_metric_does_not_carry_it(self):
        captions = self._combined(self.METRIC_WITHOUT)
        assert "separate reasoning trace" not in captions
        assert captions.strip(), (
            "no caption at all was drawn, so the absence above proves nothing")
