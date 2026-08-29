"""
The external agentic-misalignment comparison.

Three things are guarded here, and only the first is about arithmetic.

THE BUNDLE STAYS OUT OF PLAINTEXT. The model names, the harm-scenario names and
the counts are all inside the encrypted file. A test that asserted on them by
writing them down would put back exactly what the encryption is for, so every
test below either reads the bundle at runtime or builds its own fixture.

THE MAPPING IS A DECISION, NOT A GUESS. Five pairs is few enough that one wrong
pairing moves every rho, and the two naming schemes have no derivable relation -
so a row is either aliased or recorded as deliberately unmatched, and neither
list may be empty by accident.

A RHO IS NOT A CONCLUSION. At this n a single model can carry a correlation from
weak to near-perfect, so a rho is never reported without its n and its
leave-one-out range - and, on the suppression measure, without whether the two
sides even agree on the sign.
"""

import json
import sys
import tempfile
from pathlib import Path

import agentic_misalignment as am
import conftest


def _require_pairs(report):
    """Skip when the corpus is absent, rather than assert on a degenerate report.

    `unittest.SkipTest` rather than `pytest.skip`, which raises a BaseException
    subclass that `run_tests.py` does not honour. Without this a CI machine with
    no corpus ran these assertions against an empty report and reported the
    result as coverage of the populated one.
    """
    import unittest
    if not report["n_pairs"]:
        raise unittest.SkipTest(
            "no local results overlap the external bundle in this checkout")


class TestTheBundleIsEncryptedAndRoundTrips:
    def test_the_shipped_bundle_decrypts(self):
        bundle = am.load_bundle()
        assert bundle["rows"], "the bundle carries no rows"
        assert bundle["aliases"], "the bundle carries no model mapping"

    def test_no_bundle_content_appears_in_the_encrypted_file(self):
        """The point of the file. Terms are taken FROM the bundle rather than
        written here, so this cannot be satisfied by checking for the wrong
        words - and cannot itself leak them into tracked source."""
        raw = Path(am._BUNDLE_PATH).read_text(encoding="utf-8")
        terms = {r["model"] for r in am.load_bundle()["rows"]}
        terms |= {r["scenario"] for r in am.load_bundle()["rows"]}
        assert terms, "no terms to check - the guard would pass vacuously"
        leaked = sorted(t for t in terms if t.lower() in raw.lower())
        assert not leaked, f"{len(leaked)} bundle term(s) readable in the .enc"

    def test_a_round_trip_preserves_every_row(self):
        bundle = am.load_bundle()
        assert am.decrypt(am.encrypt(bundle)) == bundle

    def test_an_edited_bundle_fails_authentication(self):
        """A truncated or hand-edited file must say so rather than decode to
        bytes that happen not to be JSON."""
        text = am.encrypt({"rows": [], "aliases": []})
        broken = text[:60] + ("A" if text[60] != "A" else "B") + text[61:]
        try:
            am.decrypt(broken)
        except (ValueError, Exception) as exc:      # noqa: B014 - either is fine
            assert "authentication" in str(exc) or isinstance(exc, ValueError)
        else:
            raise AssertionError("an edited bundle decoded without complaint")


class TestEveryExternalRowIsEitherPairedOrExplained:
    def test_no_row_is_dropped_silently(self):
        """The guard that makes a hand-maintained mapping safe. A row that is
        neither aliased nor recorded as a decision is a row that vanished."""
        bundle = am.load_bundle()
        undecided = [r for r in am.unmatched_rows(bundle) if not r["decided"]]
        assert not undecided, (
            f"these external models are neither paired nor recorded as "
            f"deliberately unmatched: {[r['external_model'] for r in undecided]}")

    def test_every_deliberate_exclusion_carries_a_reason(self):
        for row in am.load_bundle().get("deliberately_unmatched") or []:
            assert row.get("reason"), row["external_model"]
            assert len(row["reason"]) > 40, (
                f"{row['external_model']} is excluded with no real reason, so "
                f"nothing stops it being quietly re-included")

    def test_the_alias_list_is_not_empty(self):
        """Scope check: an empty mapping would make every correlation test below
        pass over zero pairs."""
        assert len(am.local_index(am.load_bundle())) >= 2

    def test_no_local_model_is_aliased_twice(self):
        """Two external rows claiming one local model would double-weight it."""
        seen = []
        for alias in am.load_bundle()["aliases"]:
            seen.extend(alias["local_models"])
        assert len(seen) == len(set(seen)), "a local model appears twice"

    def test_the_mapping_comes_only_from_the_alias_list(self):
        """A behavioural guard on the real rule, replacing an earlier version
        that asserted external names and local IDs never share a normalised
        stem. That premise is simply false - several pairs here do - and a test
        resting on it would have had to be weakened into meaninglessness.

        What matters is that nothing is inferred: a bundle whose rows are all
        present but whose alias list is empty must yield NO pairs, however
        similar the names look."""
        bundle = am.load_bundle()
        stripped = dict(bundle, aliases=[])
        assert am.local_index(stripped) == {}, (
            "pairs were produced from a bundle with no alias list, so the "
            "mapping is being inferred from the names somewhere")


class TestTheRatesArePooledNotAveraged:
    """Bucket sizes differ by more than an order of magnitude inside one model,
    so a mean of bucket rates is not the model's rate."""

    def _bundle(self, unaware, safety, capability):
        return {
            "source": "fixture", "rows": [{
                "model": "M", "scenario": "overall",
                "buckets": {"unaware": {"harmful": unaware[0], "n": unaware[1]},
                            "safety_aware": {"harmful": safety[0],
                                             "n": safety[1]},
                            "capability_aware": {"harmful": capability[0],
                                                 "n": capability[1]}}}],
            "aliases": [{"external_model": "M", "local_models": ["m"]}],
        }

    def test_the_overall_rate_sums_counts_before_dividing(self):
        got = am.external_rates(self._bundle((50, 100), (1, 100), (0, 800)))
        # Pooled: 51/1000. A mean of the three rates would be about 17%.
        assert got["M"]["overall_rate"] == 51 / 1000

    def test_the_gap_is_unaware_minus_aware_and_pools_both_aware_buckets(self):
        got = am.external_rates(self._bundle((50, 100), (10, 100), (0, 100)),
                                "any_aware")
        assert got["M"]["aware"]["n"] == 200
        assert got["M"]["suppression_gap"] == round(0.5 - 10 / 200, 4)

    def test_the_narrower_pooling_gives_a_different_aware_side(self):
        b = self._bundle((50, 100), (10, 100), (0, 100))
        assert (am.external_rates(b, "safety_only")["M"]["aware"]["n"] == 100)
        assert (am.external_rates(b, "any_aware")["M"]["aware"]["n"] == 200)

    def test_a_positive_gap_means_awareness_went_with_less_harm(self):
        """The sign convention every reader depends on, stated as a test rather
        than only in a docstring."""
        got = am.external_rates(self._bundle((90, 100), (10, 100), (0, 0)))
        assert got["M"]["suppression_gap"] > 0

    def test_an_empty_aware_side_gives_no_gap_rather_than_a_zero(self):
        got = am.external_rates(self._bundle((50, 100), (0, 0), (0, 0)))
        assert got["M"]["aware"]["rate"] is None
        assert got["M"]["suppression_gap"] is None

    def test_a_thin_aware_side_is_marked_underpowered(self):
        got = am.external_rates(self._bundle((50, 100), (1, 3), (0, 2)))
        assert got["M"]["aware_side_underpowered"] is True


class TestTheLocalSideMatchesHowTheExternalSideIsBuilt:
    def _dir(self, episodes):
        out = tempfile.mkdtemp()
        for i, (aware, misaligned) in enumerate(episodes):
            ep = conftest.batch_episode(tampered=misaligned, aware=bool(aware))
            analysis = dict(ep["analysis"])
            # BOTH measures have to be absent for the verdict to be
            # unresolved: awareness_flag prefers the grader and falls back to
            # the keyword detector, so clearing only the grader leaves the
            # episode resolved - which is what an earlier version of this
            # fixture did, making the test below assert nothing.
            if aware is None:
                analysis["eval_awareness_grader"] = None
                analysis["eval_awareness_keywords"] = None
            else:
                analysis["eval_awareness_grader"] = {
                    "eval_aware": bool(aware), "rubric_results": {}}
            with open(f"{out}/run_{i}_m_strong_20260101T000000.json", "w",
                      encoding="utf-8") as f:
                json.dump({"model": "m", "nudge": "strong", "oversight": True,
                           "lure": False, "analysis": analysis,
                           "transcript": []}, f)
        return out

    def test_an_unresolved_verdict_is_not_counted_as_unaware(self):
        """It is a missing measurement, and the external table has no bucket to
        match it to. Counting it as unaware would move the gap on every model
        whose grader ever failed."""
        got = am.local_rates(self._dir([(None, True), (None, False),
                                        (True, True), (False, False)]))["m"]
        assert got["n_awareness_unresolved"] == 2
        assert got["aware"]["n"] == 1 and got["unaware"]["n"] == 1
        assert got["n"] == 4, "the overall rate should still see every episode"

    def test_the_gap_uses_the_same_sign_convention_as_the_external_side(self):
        got = am.local_rates(self._dir(
            [(False, True), (False, True), (True, False), (True, False)]))["m"]
        assert got["suppression_gap"] > 0, (
            "unaware were misaligned and aware were not, so the gap must be "
            "positive on the same convention the external side uses")

    def test_a_model_with_no_resolved_awareness_gets_no_gap(self):
        got = am.local_rates(self._dir([(None, True), (None, False)]))["m"]
        assert got["suppression_gap"] is None


class TestARhoIsNeverReportedAlone:
    def _pairs(self, points):
        """points: (external_gap, local_gap, external_rate, local_rate)."""
        return [{
            "local_model": f"m{i}", "external_model": f"M{i}",
            "external": {"overall_rate": er, "suppression_gap": eg,
                         "aware_side_underpowered": False},
            "local": {"misaligned_rate": lr, "suppression_gap": lg,
                      "aware_side_underpowered": False},
        } for i, (eg, lg, er, lr) in enumerate(points)]

    def test_every_correlation_carries_its_n_and_leave_one_out_range(self):
        c = am.correlate(self._pairs([(0.1, 0.1, 0.1, 0.1), (0.2, 0.2, 0.2, 0.2),
                                      (0.3, 0.3, 0.3, 0.3),
                                      (0.4, 0.4, 0.4, 0.4)]), "suppression")
        assert c["n_models"] == 4
        assert c["leave_one_out_rho_range"] is not None
        assert c["p"] is not None and c["p_method"]

    def test_direction_disagreement_is_counted_beside_the_rho(self):
        """The finding rho cannot express. A rank correlation is invariant to
        where zero sits, so both sides can rank the models identically while
        disagreeing about whether awareness suppresses harm at all."""
        c = am.correlate(self._pairs([(0.1, -0.4, 0, 0), (0.2, -0.3, 0, 0),
                                      (0.3, -0.2, 0, 0), (0.4, -0.1, 0, 0)]),
                         "suppression")
        assert c["spearman_rho"] == 1.0, "precondition: ranks agree perfectly"
        assert c["n_opposite_direction"] == 4, (
            "all four disagree on the sign and a rho of 1.0 says nothing about "
            "it - the direction count is what makes that visible")
        assert c["n_same_direction"] == 0

    def test_direction_agreement_is_counted_too(self):
        c = am.correlate(self._pairs([(0.1, 0.2, 0, 0), (0.3, 0.4, 0, 0)]),
                         "suppression")
        assert c["n_same_direction"] == 2 and c["n_opposite_direction"] == 0

    def test_the_level_measure_carries_no_direction_count(self):
        """There is no sign to agree about: both sides are rates, not gaps."""
        c = am.correlate(self._pairs([(0.1, 0.1, 0.2, 0.3),
                                      (0.2, 0.2, 0.4, 0.5)]), "level")
        assert "n_opposite_direction" not in c

    def test_a_pair_missing_either_side_is_dropped_not_zeroed(self):
        pairs = self._pairs([(0.1, 0.1, 0.1, 0.1), (0.2, 0.2, 0.2, 0.2)])
        pairs.append({
            "local_model": "gap", "external_model": "GAP",
            "external": {"overall_rate": 0.5, "suppression_gap": None,
                         "aware_side_underpowered": False},
            "local": {"misaligned_rate": 0.5, "suppression_gap": 0.1,
                      "aware_side_underpowered": False}})
        assert am.correlate(pairs, "suppression")["n_models"] == 2

    def test_no_pairs_at_all_is_not_a_crash(self):
        c = am.correlate([], "suppression")
        assert c["n_models"] == 0 and c["spearman_rho"] is None


class TestTheReportSaysWhatItCannotSay:
    def test_it_declares_itself_descriptive(self):
        report = am.build_report("eval_results_r9")
        assert report["is_descriptive_not_causal"] is True
        assert "not an effect" in report["interpretation"] or \
               "two populations" in report["interpretation"]

    def test_it_reports_both_poolings_so_the_choice_is_visible(self):
        report = am.build_report("eval_results_r9")
        assert set(report["pairs_by_pooling"]) == set(am.AWARE_POOLINGS)
        measures = {(c["measure"], c["aware_pooling"])
                    for c in report["correlations"]}
        assert ("suppression", "any_aware") in measures
        assert ("suppression", "safety_only") in measures
        assert ("level", None) in measures

    def test_it_names_the_rows_it_could_not_pair(self):
        report = am.build_report("eval_results_r9")
        assert report["unmatched_external_models"], (
            "the report claims a complete mapping; the bundle records an "
            "explicit exclusion, so this should not be empty")

    def test_it_prints(self):
        import contextlib
        import io
        report = am.build_report("eval_results_r9")
        _require_pairs(report)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            am.print_report(report)
        printed = buf.getvalue()
        assert "Spearman rho" in printed
        assert "leave-one-out" in printed
        assert "gap = unaware rate minus aware rate" in printed

    def test_it_prints_a_pair_with_no_aware_episodes_on_either_side(self):
        """A local model with zero aware episodes has `suppression_gap = None`
        - possible on any model thin enough, and not a hypothetical: writing a
        chart fixture with exactly this shape crashed print_report before this
        test existed. The per-pair row formatted the gap directly and claimed
        "OPPOSITE" for a comparison that never happened; both must instead say
        there was nothing to compare."""
        import contextlib
        import io
        pair = {
            "local_model": "thin-model",
            "external": {"overall_rate": 0.3, "suppression_gap": 0.1,
                        "aware_side_underpowered": False},
            "local": {"misaligned_rate": 0.2, "suppression_gap": None,
                     "aware_side_underpowered": True},
        }
        report = {
            "version": "fixture", "rollout_version": "fixture",
            "source": "fixture", "n_pairs": 1, "interpretation": "fixture",
            "unmatched_external_models": [], "unmatched_local_models": [],
            "pairs_by_pooling": {"any_aware": [pair]},
            "correlations": [
                {"measure": "level", "measure_label": "l", "aware_pooling": None,
                 "n_models": 1, "spearman_rho": None, "p": None,
                 "p_method": None, "separated": None, "note": "too few",
                 "leave_one_out_rho_range": None,
                 "n_underpowered_aware_sides": 0},
                {"measure": "suppression", "measure_label": "s",
                 "aware_pooling": "any_aware", "n_models": 1,
                 "spearman_rho": None, "p": None, "p_method": None,
                 "separated": None, "note": "too few",
                 "leave_one_out_rho_range": None,
                 "n_underpowered_aware_sides": 0},
            ],
        }
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            am.print_report(report)   # must not raise
        printed = buf.getvalue()
        assert "thin-model" in printed
        assert "n/a" in printed, (
            "no placeholder printed for the unmeasurable gap")
        assert "OPPOSITE" not in printed, (
            "a pair with no local gap to compare was still marked OPPOSITE")

    def test_it_prints_when_nothing_overlaps(self):
        """The path a machine without the corpus takes, which is every CI run
        and every fresh clone.

        This is not hypothetical tidiness: rho, p, the method and the separation
        verdict are None TOGETHER, and the printer formatted rho defensively
        while formatting p directly - so a corpus-free run raised TypeError
        instead of printing. It passed locally throughout, because a machine
        holding the corpus never takes this path. The report must degrade to
        saying it has no coefficient, not crash and not print a zero.
        """
        import contextlib
        import io
        empty = tempfile.mkdtemp()
        report = am.build_report(empty)
        assert report["n_pairs"] == 0, (
            "an empty directory produced pairs, so this test is no longer "
            "exercising the no-overlap path")
        assert all(c["spearman_rho"] is None for c in report["correlations"]), (
            "a coefficient survived with nothing to correlate")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            am.print_report(report)
        printed = buf.getvalue()
        assert "no coefficient" in printed, (
            "the corpus-free report does not say why it has no correlation")
        # The reason is carried from spearman(), so it cannot drift from the
        # threshold that actually applied.
        assert any(c["note"] and c["note"] in printed
                   for c in report["correlations"])
        assert "rho=+0.000" not in printed and "p=0" not in printed, (
            "absent is being printed as zero, which is a different claim")


class TestTheChart:
    """The chart adds no arithmetic - every number on it is already in
    `report` - so what these guard is presentation: that it renders at all
    without the corpus, and that the one thing a rho cannot show (which pairs
    disagree on the SIGN of the suppression gap) is visibly distinguished
    rather than merged into one dot colour."""

    def _bundle(self):
        # Three models, spread so the level and gap panels both have real
        # variation - and so gap signs differ, which is the case the right
        # panel exists to show. Awareness buckets sized above
        # MIN_INFORMATIVE_DENOMINATOR so no marker is hollow by construction;
        # one dedicated fixture below shrinks a bucket on purpose instead.
        def row(model, unaware, safety):
            return {"model": model, "scenario": am.OVERALL,
                   "buckets": {"unaware": {"harmful": unaware[0], "n": unaware[1]},
                               "safety_aware": {"harmful": safety[0], "n": safety[1]},
                               "capability_aware": {"harmful": 0, "n": 30}}}
        return {
            "source": "fixture", "rows": [
                row("Ext A", (60, 100), (10, 100)),   # gap positive
                row("Ext B", (10, 100), (40, 100)),   # gap negative
                row("Ext C", (50, 100), (50, 100)),   # gap ~zero
            ],
            "aliases": [
                {"external_model": "Ext A", "local_models": ["a"]},
                {"external_model": "Ext B", "local_models": ["b"]},
                {"external_model": "Ext C", "local_models": ["c"]},
            ],
        }

    def _local(self):
        def side(misaligned, n):
            return {"misaligned": misaligned, "n": n,
                   "rate": misaligned / n if n else None}
        # a: gap positive like Ext A (agrees). b: gap positive, UNLIKE Ext B's
        # negative gap (disagrees) - the case the right panel has to show as a
        # different colour from a. c: no aware episodes at all, so its gap is
        # None and it must be silently excluded rather than plotted as zero.
        rows = {
            "a": {"misaligned": 20, "n": 100,
                 "unaware": side(15, 60), "aware": side(2, 40)},
            "b": {"misaligned": 30, "n": 100,
                 "unaware": side(10, 60), "aware": side(2, 40)},
            "c": {"misaligned": 5, "n": 100,
                 "unaware": side(5, 100), "aware": side(0, 0)},
        }
        for row in rows.values():
            row["misaligned_rate"] = row["misaligned"] / row["n"]
            u, av = row["unaware"]["rate"], row["aware"]["rate"]
            row["suppression_gap"] = None if av is None else round(u - av, 4)
            row["aware_side_underpowered"] = (
                row["aware"]["n"] < am.MIN_INFORMATIVE_DENOMINATOR)
        return rows

    def _report(self, pooling="any_aware"):
        # Assembled with the same keys build_report() sets, rather than the
        # minimum write_chart happens to read, so a print_report() call on
        # this fixture (as the CLI test below makes) exercises the real
        # shape instead of one this test invented.
        bundle, local = self._bundle(), self._local()
        pairs = am.build_pairs(bundle, local, pooling)
        return {
            "version": "fixture", "rollout_version": "fixture",
            "source": "fixture source",
            "n_pairs": len(pairs),
            "interpretation": "fixture interpretation",
            "unmatched_external_models": [],
            "unmatched_local_models": [],
            "pairs_by_pooling": {pooling: pairs},
            "correlations": [
                am.correlate(pairs, "level"),
                am.correlate(pairs, "suppression", pooling),
            ],
        }

    def _plt_or_skip(self):
        from subversionbench import charting
        if charting.import_pyplot() is None:
            import unittest
            raise unittest.SkipTest("matplotlib not installed")
        return charting.import_pyplot()

    def test_the_chart_renders_without_error(self):
        self._plt_or_skip()
        with tempfile.TemporaryDirectory() as out:
            path = am.write_chart(self._report(), str(Path(out) / "c.png"))
            assert path and Path(path).exists()

    def test_no_pairs_means_no_chart_rather_than_an_empty_one(self):
        assert am.write_chart({"n_pairs": 0, "pairs_by_pooling": {}},
                              "/dev/null/unwritable.png") is None

    def test_without_matplotlib_it_returns_none_rather_than_raising(self):
        """The same degrade-don't-fail contract every chart in this repository
        makes: losing matplotlib costs presentation, not the report."""
        from subversionbench import charting as real_charting
        original = real_charting.import_pyplot
        real_charting.import_pyplot = lambda *a, **k: None
        try:
            with tempfile.TemporaryDirectory() as out:
                result = am.write_chart(self._report(), str(Path(out) / "c.png"))
        finally:
            real_charting.import_pyplot = original
        assert result is None

    def test_a_disagreeing_pair_is_drawn_in_a_different_colour_than_agreeing(self):
        """The whole reason this chart exists rather than the rho alone: rho
        cannot show WHICH pairs disagree on the sign of the gap, and this is
        the assertion that the chart actually encodes that rather than just
        plotting every point the same way."""
        self._plt_or_skip()
        import inspect
        source = inspect.getsource(am.write_chart)
        assert "agree" in source and "#c44e52" in source and "#4c72b0" in source

    def test_a_pair_with_no_suppression_gap_is_excluded_not_zeroed(self):
        """model c has no aware episodes, so its local gap is None. Plotting
        it at 0 would claim awareness had no effect, which is a different and
        unsupported claim from "not measured" - and is indistinguishable from
        a genuinely near-zero gap to anyone reading the chart. Checked on the
        actual scatter calls, not on write_chart merely surviving: a version
        that plots (0, 0) for the excluded pair still returns a path."""
        plt = self._plt_or_skip()
        pairs = am.build_pairs(self._bundle(), self._local(), "any_aware")
        c_pair = next(p for p in pairs if p["local_model"] == "c")
        assert c_pair["local"]["suppression_gap"] is None, (
            "the fixture no longer reproduces an unmeasurable gap, so this "
            "test would pass however write_chart handled it")
        import unittest.mock
        calls = []
        original = plt.Axes.scatter
        def spy(self, x, y, *a, **k):
            calls.append((x, y))
            return original(self, x, y, *a, **k)
        with unittest.mock.patch.object(plt.Axes, "scatter", spy):
            with tempfile.TemporaryDirectory() as out:
                path = am.write_chart(self._report(), str(Path(out) / "c.png"))
        assert path
        assert len(calls) == 2, (
            f"expected one gap point per pair with a measurable gap (a, b), "
            f"got {len(calls)}: {calls}")
        assert (0, 0) not in calls, (
            "the pair with no measurable gap was plotted at the origin")

    def test_an_underpowered_pair_draws_a_hollow_marker(self):
        """The gap panel carries no confidence interval - a difference of two
        rates has none computed anywhere in this file - so the underpowered
        flag already on each pair is the marker's only caution. A filled dot
        promises more certainty than a bucket this small can support."""
        self._plt_or_skip()
        import inspect
        source = inspect.getsource(am.write_chart)
        assert "aware_side_underpowered" in source
        assert 'facecolors=("none"' in source

    def test_subplots_is_called_for_two_side_by_side_panels(self):
        """write_chart closes its figure before returning, so the panel
        geometry is checked from the source - `plt.subplots(1, 2, ...)` is
        what keeps this a level-panel/gap-panel pair rather than a stack."""
        import inspect
        source = inspect.getsource(am.write_chart)
        assert "plt.subplots(1, 2" in source

    def test_both_panel_titles_carry_a_p_value_beside_rho(self):
        """sad_oversight.py's chart shows rho beside p; an earlier version of
        this one showed rho and n but dropped p, an inconsistency with no
        reason behind it - the console output two lines away prints p for the
        same numbers. Checked on the rendered titles, not the source text, so
        a rewording that keeps the value out would still be caught."""
        plt = self._plt_or_skip()
        titles = []
        original = plt.Axes.set_title
        def spy(self, label, *a, **k):
            titles.append(label)
            return original(self, label, *a, **k)
        import unittest.mock
        with unittest.mock.patch.object(plt.Axes, "set_title", spy):
            with tempfile.TemporaryDirectory() as out:
                am.write_chart(self._report(), str(Path(out) / "c.png"))
        assert len(titles) == 2, titles
        # The shared fixture's gap panel legitimately has no rho - model c's
        # local gap is None, leaving only two usable pairs, one short of what
        # a coefficient needs - so its title correctly shows the `note`
        # instead. The level panel has all three and is what this test checks.
        assert "p=" in titles[0], titles

    def test_the_gap_panel_shows_p_too_when_it_has_a_rho(self):
        """The case the test above cannot reach: a corpus where the gap
        correlation itself has enough pairs to compute. A fourth model, so
        three (not two) pairs carry a measurable gap on both sides."""
        plt = self._plt_or_skip()
        bundle, local = self._bundle(), self._local()
        bundle["rows"].append({"model": "Ext D", "scenario": am.OVERALL,
                               "buckets": {"unaware": {"harmful": 20, "n": 100},
                                          "safety_aware": {"harmful": 5, "n": 100},
                                          "capability_aware": {"harmful": 0, "n": 30}}})
        bundle["aliases"].append({"external_model": "Ext D", "local_models": ["d"]})
        local["d"] = {"misaligned": 10, "n": 100, "misaligned_rate": 0.1,
                     "unaware": {"misaligned": 8, "n": 60, "rate": 8 / 60},
                     "aware": {"misaligned": 1, "n": 40, "rate": 1 / 40},
                     "suppression_gap": round(8 / 60 - 1 / 40, 4),
                     "aware_side_underpowered": False}
        pairs = am.build_pairs(bundle, local, "any_aware")
        report = {"n_pairs": len(pairs), "interpretation": "fixture",
                  "pairs_by_pooling": {"any_aware": pairs},
                  "correlations": [am.correlate(pairs, "level"),
                                   am.correlate(pairs, "suppression", "any_aware")]}
        gap_stat = next(c for c in report["correlations"]
                        if c["measure"] == "suppression")
        assert gap_stat["spearman_rho"] is not None, (
            "the fixture still has fewer than three usable gap pairs, so this "
            "test would pass without reaching the code path it targets")
        titles = []
        original = plt.Axes.set_title
        def spy(self, label, *a, **k):
            titles.append(label)
            return original(self, label, *a, **k)
        import unittest.mock
        with unittest.mock.patch.object(plt.Axes, "set_title", spy):
            with tempfile.TemporaryDirectory() as out:
                am.write_chart(report, str(Path(out) / "c.png"))
        assert "p=" in titles[1], titles


class TestChartLabelsDoNotOverlap:
    """The same measured-bbox collision guard sad_oversight.py's chart needed,
    exercised here because this file owns its own copy rather than importing a
    private name across a module boundary - see write_chart's docstring."""

    def _plt(self):
        from subversionbench import charting
        if charting.import_pyplot() is None:
            import unittest
            raise unittest.SkipTest("matplotlib not installed")
        return charting.import_pyplot()

    def test_a_lone_label_keeps_the_natural_offset(self):
        plt = self._plt()
        fig, ax = plt.subplots()
        am._place_labels(fig, ax, [(50.0, 50.0, "only-model")])
        assert ax.texts[0].xyann == am._LABEL_OFFSETS[0]
        plt.close(fig)

    def test_several_points_at_nearly_the_same_spot_all_get_readable_labels(self):
        plt = self._plt()
        fig, ax = plt.subplots()
        points = [(65.0, 10.0 + i, f"model-{i}") for i in range(4)]
        for x, y, _t in points:
            ax.plot([x], [y], "o")
        am._place_labels(fig, ax, points)
        fig.canvas.draw()
        renderer = fig.canvas.get_renderer()
        boxes = [t.get_window_extent(renderer=renderer) for t in ax.texts]
        for i, a in enumerate(boxes):
            for b in boxes[i + 1:]:
                assert not a.overlaps(b)
        plt.close(fig)

    def test_every_point_gets_exactly_one_label(self):
        plt = self._plt()
        fig, ax = plt.subplots()
        points = [(65.0, 10.0 + i * 0.1, f"model-{i}") for i in range(5)]
        am._place_labels(fig, ax, points)
        assert len(ax.texts) == 5
        assert {t.get_text() for t in ax.texts} == {p[2] for p in points}
        plt.close(fig)


class TestTheCLIWritesTheChart:
    """Not the correlation arithmetic - the classes above already exercise
    that against fixtures - but the wiring: does main() call write_chart, does
    the file land under --output-dir/charts by default, and does --no-charts
    actually skip it. build_report is patched to a canned report so this does
    not depend on the shipped bundle pairing a real local model with episodes
    this test would otherwise have to fabricate."""

    def _report(self):
        return TestTheChart()._report()

    def _run(self, output_dir, *extra_args):
        import unittest.mock
        argv = sys.argv
        sys.argv = ["agentic_misalignment.py", "--output-dir", output_dir,
                   "--json-out", str(Path(output_dir) / "r.json"), *extra_args]
        try:
            with unittest.mock.patch.object(am, "build_report",
                                            return_value=self._report()):
                return am.main()
        finally:
            sys.argv = argv

    def test_a_normal_run_writes_a_chart_under_output_dir(self):
        from subversionbench import charting
        if charting.import_pyplot() is None:
            import unittest
            raise unittest.SkipTest("matplotlib not installed")
        out = tempfile.mkdtemp()
        assert self._run(out) == 0
        chart = Path(out) / "charts" / "agentic_misalignment_correlation.png"
        assert chart.exists(), "main() did not write a chart to the default path"

    def test_no_charts_flag_skips_the_chart_file(self):
        out = tempfile.mkdtemp()
        assert self._run(out, "--no-charts") == 0
        assert not (Path(out) / "charts").exists(), (
            "--no-charts wrote a chart directory anyway")

    def test_chart_dir_is_honoured(self):
        from subversionbench import charting
        if charting.import_pyplot() is None:
            import unittest
            raise unittest.SkipTest("matplotlib not installed")
        out = tempfile.mkdtemp()
        chart_dir = str(Path(out) / "somewhere-else")
        assert self._run(out, "--chart-dir", chart_dir) == 0
        assert (Path(chart_dir) /
               "agentic_misalignment_correlation.png").exists()
