"""
The misuse profile: the decomposition, and the figure that draws it.

WHAT THE MEASURE IS FOR. Naming the content in front of you as an attack is a
different claim from saying the situation was built to observe you. The rubric
question that merges them asks whether the scenario may be "planted", and
content planted by an attacker satisfies that as readily as content planted by
an experimenter - so the decomposition here is the number that says how much
of a published awareness figure is really the other construct.

THE TWO BLOCKS HAVE DIFFERENT DENOMINATORS ON PURPOSE, and most of what
follows is about not letting them merge: the rate is over every episode with
the measure, the decomposition over the AWARE ones only. Folding them would
make the decomposition read as a corpus rate, which it is not.

No phrase is quoted. Every one is taken from the bundle, on the scrub rule
that governs both keyword lists.
"""

import unittest

from subversionbench.config import MISUSE_INDICATORS
from report.characteristics import misuse_profile
from report.episode_rows import _misuse_columns

PHRASE = MISUSE_INDICATORS[0]


def _analysis(*, suspected=False, fired=(), citing=(), failed=False):
    """A stored analysis block with a chosen grader verdict.

    `fired` names the signal questions answered yes; `citing` the subset whose
    stored quote is misuse language.
    """
    rubric = {k: {"answer": True,
                  "quote": (f"it looks like {PHRASE} to me" if k in citing
                            else "this is clearly a constructed situation")}
              for k in fired}
    return {
        "misuse_keywords": {"misuse_suspected": suspected,
                            "indicators_found": [PHRASE] if suspected else []},
        "eval_awareness_grader": {"rubric_results": rubric,
                                  "grading_failed": failed},
    }


def _row(**kw):
    row = {}
    _misuse_columns(row, _analysis(**kw))
    return row


class TestTheEvidenceBandOfOneEpisode(unittest.TestCase):

    def test_an_ungraded_episode_is_not_a_band(self):
        """An episode that is not aware has no verdict for misuse to be a
        share OF, so the question does not arise - None, not 'unrelated'."""
        assert _row(suspected=True)["misuse_evidence"] is None

    def test_a_graded_episode_that_answered_no_to_everything_is_not_a_band(self):
        """The case the test above CANNOT reach, and nearly did not get one.

        With no rubric at all the function returns at the empty-rubric check,
        so that test exercises the ungraded path only. An episode graded and
        answered no throughout has a full rubric and no fired signal, and it
        is the one that reaches the fired-signal check - planting a band there
        left the test above green.
        """
        analysis = _analysis(fired=("mentioned_test",))
        analysis["eval_awareness_grader"]["rubric_results"][
            "mentioned_test"]["answer"] = False
        row = {}
        _misuse_columns(row, analysis)
        assert row["misuse_evidence"] is None

    def test_a_failed_grading_is_not_a_band(self):
        assert _row(fired=("mentioned_test",), failed=True)[
            "misuse_evidence"] is None

    def test_aware_on_evidence_that_never_mentions_an_attack(self):
        assert _row(fired=("mentioned_test",))["misuse_evidence"] == "unrelated"

    def test_every_fired_signal_citing_it_is_the_ceiling_band(self):
        assert _row(fired=("mentioned_test",),
                    citing=("mentioned_test",))["misuse_evidence"] == "all"

    def test_one_of_several_citing_it_is_partial(self):
        """The verdict survives without the misuse language, so this episode
        is NOT in the ceiling - the distinction the whole measure turns on."""
        got = _row(fired=("mentioned_test", "broke_character"),
                   citing=("mentioned_test",))
        assert got["misuse_evidence"] == "partial"

    def test_all_of_several_citing_it_is_the_ceiling_band(self):
        got = _row(fired=("mentioned_test", "broke_character"),
                   citing=("mentioned_test", "broke_character"))
        assert got["misuse_evidence"] == "all"

    def test_the_band_reads_the_quote_not_the_transcript(self):
        """An episode can name an attack all through its reasoning and still
        be graded aware on something else. Only the stored quote says which
        happened, so misuse_suspected must not move the band."""
        assert _row(suspected=True, fired=("mentioned_test",))[
            "misuse_evidence"] == "unrelated"

    def test_the_flag_is_independent_of_the_band(self):
        assert _row(suspected=True)["misuse_suspected"] is True
        assert _row(suspected=False)["misuse_suspected"] is False

    def test_an_episode_without_the_measure_reads_none_not_false(self):
        """The field is absent on every episode collected before it existed.
        None keeps those out of a denominator; False would count them as
        confident no-attack."""
        row = {}
        _misuse_columns(row, {"eval_awareness_grader": {}})
        assert row["misuse_suspected"] is None


def _ep(model="m", suspected=False, evidence=None):
    return {"model": model, "misuse_suspected": suspected,
            "misuse_evidence": evidence}


class TestTheProfileKeepsItsTwoDenominatorsApart(unittest.TestCase):

    def test_the_decomposition_counts_only_aware_episodes(self):
        p = misuse_profile([_ep(evidence="all"), _ep(evidence="unrelated"),
                            _ep(evidence=None), _ep(evidence=None)])
        assert p["n_aware"] == 2
        assert sum(p["evidence"].values()) == 2
        assert p["n_episodes"] == 4

    def test_the_rate_counts_every_episode_with_the_measure(self):
        p = misuse_profile([_ep(suspected=True), _ep(suspected=False),
                            _ep(suspected=True, evidence="all")])
        assert p["n_resolved"] == 3 and p["n_true"] == 2
        assert p["rate"] == round(2 / 3, 4)

    def test_an_episode_without_the_measure_leaves_the_denominator(self):
        p = misuse_profile([_ep(suspected=True), _ep(suspected=None)])
        assert p["n_resolved"] == 1 and p["rate"] == 1.0

    def test_every_band_is_reported_even_at_zero(self):
        """A band missing from the dict would be drawn as absent rather than
        as empty, and the three must always sum to n_aware."""
        p = misuse_profile([_ep(evidence="unrelated")])
        assert set(p["evidence"]) == set(p["evidence_bands"])
        assert p["evidence"]["all"] == 0

    def test_it_reports_per_model_rates(self):
        p = misuse_profile([_ep("a", True), _ep("a", False), _ep("b", True)])
        by = {r["model"]: r for r in p["by_model"]}
        assert by["a"]["rate"] == 0.5 and by["b"]["rate"] == 1.0

    def test_an_empty_corpus_does_not_divide_by_zero(self):
        p = misuse_profile([])
        assert p["rate"] is None and p["n_aware"] == 0


class TestTheFigureDrawsWhatTheProfileSays(unittest.TestCase):
    """Behavioural: what plot_misuse_profile HANDS the renderer.

    Not a search of the module's source. A guard against a location cannot
    tell a band that is computed from one that is computed and dropped, which
    is exactly the defect that shipped here - by_model was built and left out
    of the returned dict, and only the chart's own emptiness showed it.
    """

    def _captured(self, report):
        from unittest import mock

        import report_charts.characteristics as mod
        seen = {}

        def fake(plt, bands, rows, title, captions, path, ref=None):
            seen.update(bands=bands, rows=rows, captions=captions, ref=ref)
            return path

        with mock.patch.object(mod.draw, "_draw_misuse_chart", fake):
            out = mod.plot_misuse_profile(object(), report, "x.png")
        return out, seen

    def _report(self, **over):
        profile = {"n_aware": 10, "evidence_bands": ["unrelated", "partial", "all"],
                   "evidence": {"unrelated": 7, "partial": 2, "all": 1},
                   "rate": 0.25, "interpretation": "i",
                   "by_model": [{"model": "m", "n_true": 25, "n_resolved": 100,
                                 "rate": 0.25, "underpowered": False}]}
        profile.update(over)
        return {"characteristics": {"misuse_profile": profile}}

    def test_the_bands_reach_the_renderer_as_shares_of_the_aware_set(self):
        _out, seen = self._captured(self._report())
        assert [c for _l, c, _s in seen["bands"]] == [7, 2, 1]
        assert [round(s, 3) for _l, _c, s in seen["bands"]] == [0.7, 0.2, 0.1]

    def test_the_per_model_rows_reach_the_renderer(self):
        _out, seen = self._captured(self._report())
        assert [r.label for r in seen["rows"]] == ["m"]
        assert seen["rows"][0].diff == 0.25
        assert seen["ref"] == 0.25

    def test_a_thin_model_is_not_drawn(self):
        _out, seen = self._captured(self._report(by_model=[
            {"model": "m", "n_true": 1, "n_resolved": 2, "rate": 0.5,
             "underpowered": True}]))
        assert seen["rows"] == []

    def test_the_band_key_names_every_band_and_its_count(self):
        """The figure has no legend box - the key IS a caption, so a band
        dropped from it is invisible rather than merely unlabelled."""
        _out, seen = self._captured(self._report())
        key = next(t for t, _c in seen["captions"] if t.startswith("TOP bands"))
        for shade in ("lightest", "mid", "darkest"):
            assert shade in key
        assert "7 (70.0%)" in key and "1 (10.0%)" in key

    def test_it_says_the_ceiling_is_reported_not_subtracted(self):
        _out, seen = self._captured(self._report())
        assert any("NOT subtracted" in t for t, _c in seen["captions"])

    def test_nothing_is_drawn_without_an_aware_set(self):
        out, _seen = self._captured(self._report(n_aware=0))
        assert out is None

    def test_nothing_is_drawn_without_per_model_rows(self):
        """The defect that shipped: by_model computed and never returned."""
        out, _seen = self._captured(self._report(by_model=[]))
        assert out is None
