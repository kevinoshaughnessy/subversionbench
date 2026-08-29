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
