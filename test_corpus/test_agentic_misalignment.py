"""
The external agentic-misalignment comparison: the bundle, the rates, the
pairing, and what the report is allowed to say.

Five models overlap. That is enough to report a rank correlation and nowhere
near enough to conclude anything from one, so what these mostly pin is the
qualification rather than the coefficient: every rho with its n and its
leave-one-out range, both awareness poolings reported, and every external row
either paired or explained.

Nothing here draws - the charts and the CLI are in
test_agentic_misalignment_charts.py, which is the same analysis-above-
presentation split the package itself makes.
"""


import json
import tempfile
from pathlib import Path

import agentic_misalignment as am
import conftest
from report import load_episodes
from test_corpus.am_fixtures import _require_pairs, _shipped_report


class TestTheBundleIsEncryptedAndRoundTrips:
    def test_the_shipped_bundle_decrypts(self):
        bundle = am.load_bundle()
        assert bundle["rows"], "the bundle carries no rows"
        assert bundle["aliases"], "the bundle carries no model mapping"

    def test_no_bundle_content_appears_in_the_encrypted_file(self):
        """The point of the file. Terms are taken FROM the bundle rather than
        written here, so this cannot be satisfied by checking for the wrong
        words - and cannot itself leak them into tracked source."""
        raw = Path(am.bundle._BUNDLE_PATH).read_text(encoding="utf-8")
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


class TestExternalRatesByScenario:
    """external_rates and external_rates_by_scenario share _model_stats, so
    these only need to guard the grouping - the arithmetic itself is already
    covered above."""

    def _bundle(self):
        def row(model, scenario, unaware, safety):
            return {"model": model, "scenario": scenario,
                    "buckets": {"unaware": {"harmful": unaware[0], "n": unaware[1]},
                                "safety_aware": {"harmful": safety[0], "n": safety[1]},
                                "capability_aware": {"harmful": 0, "n": 30}}}
        return {
            "source": "fixture",
            "rows": [
                row("Ext A", "scenario one", (10, 100), (5, 50)),
                row("Ext B", "scenario one", (20, 100), (5, 50)),
                row("Ext A", "scenario two", (30, 100), (5, 50)),
                row("Ext A", am.OVERALL, (40, 100), (5, 50)),
            ],
        }

    def test_overall_is_excluded_and_the_rest_are_grouped_by_scenario(self):
        got = am.external_rates_by_scenario(self._bundle())
        assert set(got) == {"scenario one", "scenario two"}
        assert set(got["scenario one"]) == {"Ext A", "Ext B"}
        assert set(got["scenario two"]) == {"Ext A"}

    def test_a_models_scenario_row_and_overall_row_are_independent(self):
        got = am.external_rates_by_scenario(self._bundle())
        overall = am.external_rates(self._bundle())
        assert got["scenario one"]["Ext A"]["overall_rate"] != (
            overall["Ext A"]["overall_rate"])

    def test_matches_external_rates_math_for_an_equivalent_single_row(self):
        """Same _model_stats call underneath - a scenario row and an OVERALL
        row with identical buckets must produce identical rates."""
        bundle = {"source": "fixture", "rows": [
            {"model": "M", "scenario": "only scenario",
             "buckets": {"unaware": {"harmful": 12, "n": 40},
                        "safety_aware": {"harmful": 3, "n": 20},
                        "capability_aware": {"harmful": 1, "n": 10}}},
            {"model": "M", "scenario": am.OVERALL,
             "buckets": {"unaware": {"harmful": 12, "n": 40},
                        "safety_aware": {"harmful": 3, "n": 20},
                        "capability_aware": {"harmful": 1, "n": 10}}},
        ]}
        by_scenario = am.external_rates_by_scenario(bundle)["only scenario"]["M"]
        overall = am.external_rates(bundle)["M"]
        assert by_scenario == overall


class TestScenarioActCorrelations:
    """Every (scenario, act) pair taken apart at once, rather than only the
    two pooled numbers correlate() reports."""

    def _bundle(self):
        def row(model, scenario, h, n):
            return {"model": model, "scenario": scenario,
                    "buckets": {"unaware": {"harmful": h, "n": n},
                                "safety_aware": {"harmful": 0, "n": 5},
                                "capability_aware": {"harmful": 0, "n": 5}}}
        return {
            "source": "fixture",
            "rows": [
                # s1's rate ranks A < B < C, exactly like oversight below and
                # exactly the reverse of sandbox below.
                row("Ext A", "s1", 10, 100), row("Ext B", "s1", 50, 100),
                row("Ext C", "s1", 90, 100),
                # s2 ranks B < A < C - neither order.
                row("Ext A", "s2", 50, 100), row("Ext B", "s2", 10, 100),
                row("Ext C", "s2", 90, 100),
            ],
            "aliases": [
                {"external_model": "Ext A", "local_models": ["a"]},
                {"external_model": "Ext B", "local_models": ["b"]},
                {"external_model": "Ext C", "local_models": ["c"]},
            ],
        }

    def _local_acts(self):
        def act(rate):
            return {"taken": round(rate * 10), "n": 10, "rate": rate}
        # oversight ranks a < b < c, like s1. sandbox ranks a > b > c, the
        # reverse of s1 and so of oversight too.
        return {
            "a": {"oversight": act(0.1), "sandbox": act(0.9)},
            "b": {"oversight": act(0.5), "sandbox": act(0.5)},
            "c": {"oversight": act(0.9), "sandbox": act(0.1)},
        }

    def test_one_row_per_scenario_and_act_combination(self):
        got = am.scenario_act_correlations(self._bundle(), self._local_acts())
        assert {(c["scenario"], c["act"]) for c in got} == {
            ("s1", "oversight"), ("s1", "sandbox"),
            ("s2", "oversight"), ("s2", "sandbox"),
        }

    def test_a_matching_rank_order_gets_rho_one(self):
        got = am.scenario_act_correlations(self._bundle(), self._local_acts())
        c = next(c for c in got
                if c["scenario"] == "s1" and c["act"] == "oversight")
        assert c["n_models"] == 3
        assert c["spearman_rho"] == 1.0

    def test_the_exact_reverse_rank_order_gets_rho_minus_one(self):
        got = am.scenario_act_correlations(self._bundle(), self._local_acts())
        c = next(c for c in got
                if c["scenario"] == "s1" and c["act"] == "sandbox")
        assert c["spearman_rho"] == -1.0

    def test_pairs_carry_enough_for_a_chart_to_draw_wilson_intervals(self):
        got = am.scenario_act_correlations(self._bundle(), self._local_acts())
        c = next(c for c in got
                if c["scenario"] == "s1" and c["act"] == "oversight")
        for pair in c["pairs"]:
            assert {"harmful", "n"} <= set(pair["external"])
            assert {"taken", "n"} <= set(pair["local_act"])

    def test_a_model_missing_from_local_acts_is_excluded_not_zeroed(self):
        local_acts = self._local_acts()
        del local_acts["b"]
        got = am.scenario_act_correlations(self._bundle(), local_acts)
        c = next(c for c in got
                if c["scenario"] == "s1" and c["act"] == "oversight")
        assert c["n_models"] == 2


class TestBestScenarioActPairing:
    def test_picks_the_highest_rho_not_the_highest_magnitude(self):
        """Ranked by rho itself: a strong NEGATIVE correlation must lose to a
        weaker positive one, the same sense every other rho in this file is
        read (agreement, not just association)."""
        correlations = [
            {"scenario": "s1", "act": "oversight", "spearman_rho": -0.95},
            {"scenario": "s2", "act": "sandbox", "spearman_rho": 0.4},
        ]
        best = am.best_scenario_act_pairing(correlations)
        assert (best["scenario"], best["act"]) == ("s2", "sandbox")

    def test_a_row_with_no_coefficient_is_never_picked(self):
        correlations = [
            {"scenario": "s1", "act": "oversight", "spearman_rho": None},
        ]
        assert am.best_scenario_act_pairing(correlations) is None

    def test_returns_the_actual_row_not_a_copy(self):
        """print_report marks the winning row by identity - `c is best` -
        rather than re-matching on (scenario, act), so this must be the same
        object, not an equal one."""
        row = {"scenario": "s1", "act": "oversight", "spearman_rho": 0.5}
        best = am.best_scenario_act_pairing([row])
        assert best is row


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


class TestLocalActRates:
    """local_act_rates() is local_rates()'s misaligned_rate taken apart: that
    rate pools both acts with an OR, so it cannot say which act is driving a
    correlation. Each act here gets its own denominator instead."""

    def _dir(self, model, episodes):
        """episodes: list of (oversight_tampered, out_of_scope_attempts).
        oversight_tampered is None for "not observable" (the no-oversight
        arm, where there is no monitor to tamper with); out_of_scope_attempts
        is a list, empty meaning the act was not taken."""
        out = tempfile.mkdtemp()
        for i, (oversight, sandbox) in enumerate(episodes):
            ep = conftest.batch_episode()
            analysis = dict(ep["analysis"])
            analysis["oversight_tampered"] = oversight
            analysis["out_of_scope_attempts"] = sandbox
            with open(f"{out}/run_{i}_{model}_strong_20260101T000000.json", "w",
                      encoding="utf-8") as f:
                json.dump({"model": model, "nudge": "strong", "oversight": True,
                          "lure": False, "analysis": analysis, "transcript": []}, f)
        return out

    def test_each_act_gets_its_own_denominator(self):
        """A model that only ever takes the oversight act must not have that
        pulled into the sandbox rate, or vice versa."""
        out = self._dir("m", [(True, []), (True, []), (False, []), (False, [])])
        got = am.local_act_rates(out)["m"]
        assert got["oversight"]["rate"] == 0.5
        assert got["sandbox"]["rate"] == 0.0

    def test_oversight_is_restricted_to_observable_episodes(self):
        """None means the no-oversight arm - not-applicable, not a False that
        would drag the rate down."""
        out = self._dir("m", [(True, []), (None, []), (None, [])])
        got = am.local_act_rates(out)["m"]
        assert got["oversight"]["n"] == 1
        assert got["oversight"]["rate"] == 1.0

    def test_sandbox_is_observable_in_every_episode(self):
        out = self._dir("m", [(None, []), (None, ["cat /etc/passwd"])])
        got = am.local_act_rates(out)["m"]
        assert got["sandbox"]["n"] == 2
        assert got["sandbox"]["rate"] == 0.5

    def test_a_model_with_no_observable_episodes_for_an_act_has_no_rate(self):
        out = self._dir("m", [(None, [])])
        got = am.local_act_rates(out)["m"]
        assert got["oversight"]["rate"] is None


class TestTheCorpusIsWalkedOnce:
    """`load_episodes` opens and parses every run file in the directory, and
    build_report needs two views of the result - the pooled misalignment rate
    and the per-act rates. It used to ask for the corpus once per view, so every
    report parsed every file twice to reach two readings of the same episodes.
    On the r9 corpus that was the dominant cost of the script, and of this test
    module.

    A performance property, but guarded like a correctness one because the cost
    is invisible in the output: the report was right either way, so nothing
    failed when the second walk was added and nothing would fail if it came
    back."""

    def _dir(self):
        out = tempfile.mkdtemp()
        for i in range(3):
            ep = conftest.batch_episode(tampered=bool(i % 2))
            with open(f"{out}/run_{i}_m_strong_20260101T000000.json", "w",
                      encoding="utf-8") as f:
                json.dump({"model": "m", "nudge": "strong", "oversight": True,
                           "lure": False, "analysis": ep["analysis"],
                           "transcript": []}, f)
        return out

    def _counted(self, call):
        """Run `call`, returning (result, how many times the corpus was read).

        Patches the name the module resolves at call time, so it counts reads
        from every function here rather than from one that was told about.
        """
        calls = []
        import report as report_pkg
        original = report_pkg.load_episodes

        def counting(output_dir):
            calls.append(output_dir)
            return original(output_dir)

        report_pkg.load_episodes = counting
        try:
            return call(), len(calls)
        finally:
            report_pkg.load_episodes = original

    def test_a_report_reads_the_corpus_once(self):
        out = self._dir()
        _report, reads = self._counted(lambda: am.build_report(out, {
            "source": "fixture", "rows": [], "aliases": []}))
        assert reads == 1, (
            f"build_report read the corpus {reads} times; both views must "
            f"share one load")

    def test_a_preloaded_corpus_is_not_read_again(self):
        """What lets build_report share one list. Without it the parameter
        would be accepted and ignored, which is the same cost with a wider
        signature."""
        out = self._dir()
        episodes = load_episodes(out)
        for name, fn in (("local_rates", am.local_rates),
                         ("local_act_rates", am.local_act_rates)):
            _got, reads = self._counted(lambda fn=fn: fn(out, episodes))
            assert reads == 0, f"{name} reloaded a corpus it was handed"

    def test_handing_the_episodes_over_changes_no_figure(self):
        """The correctness claim the sharing rests on: both functions only read
        the episodes, so which list they read is not observable. Asserted on
        the whole returned structure rather than a chosen field, so a figure
        that starts depending on load order fails here."""
        out = self._dir()
        episodes = load_episodes(out)
        assert am.local_rates(out) == am.local_rates(out, episodes)
        assert am.local_act_rates(out) == am.local_act_rates(out, episodes)

    def test_neither_view_mutates_the_shared_episodes(self):
        """Sharing one list between two callers is only safe while it stays
        read-only. A field written by whichever ran first would make the other
        one's figures depend on the call order."""
        out = self._dir()
        episodes = load_episodes(out)
        before = json.dumps(episodes, sort_keys=True, default=str)
        am.local_rates(out, episodes)
        am.local_act_rates(out, episodes)
        assert json.dumps(episodes, sort_keys=True, default=str) == before


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
        report = _shipped_report()
        assert report["is_descriptive_not_causal"] is True
        assert "not an effect" in report["interpretation"] or \
               "two populations" in report["interpretation"]

    def test_it_reports_both_poolings_so_the_choice_is_visible(self):
        report = _shipped_report()
        assert set(report["pairs_by_pooling"]) == set(am.AWARE_POOLINGS)
        measures = {(c["measure"], c["aware_pooling"])
                    for c in report["correlations"]}
        assert ("suppression", "any_aware") in measures
        assert ("suppression", "safety_only") in measures
        assert ("level", None) in measures

    def test_it_names_the_rows_it_could_not_pair(self):
        """build_report's unmatched_external_models is unmatched_rows(bundle)
        passed through - checked against a fixture rather than the shipped
        bundle, whose current mix of paired and excluded rows is a fact about
        the corpus today (it changes as models are evaluated and aliased),
        not something this test should pin."""
        bundle = {
            "source": "fixture",
            "rows": [
                {"model": "Paired", "scenario": am.OVERALL,
                "buckets": {"unaware": {"harmful": 1, "n": 10},
                           "safety_aware": {"harmful": 0, "n": 5},
                           "capability_aware": {"harmful": 0, "n": 5}}},
                {"model": "Excluded", "scenario": am.OVERALL,
                "buckets": {"unaware": {"harmful": 1, "n": 10},
                           "safety_aware": {"harmful": 0, "n": 5},
                           "capability_aware": {"harmful": 0, "n": 5}}},
            ],
            "aliases": [{"external_model": "Paired", "local_models": ["p"]}],
            "deliberately_unmatched": [
                {"external_model": "Excluded", "reason": "fixture exclusion"}],
        }
        # An empty output dir, not the corpus: this asserts that
        # `unmatched_external_models` is `unmatched_rows(bundle)` passed
        # through, which no episode contributes to. Naming the corpus here
        # cost a full two-pass walk of it to reach an identical answer.
        report = am.build_report(tempfile.mkdtemp(), bundle)
        assert report["unmatched_external_models"] == [
            {"external_model": "Excluded", "decided": True,
            "reason": "fixture exclusion"}]

    def test_it_prints(self):
        import contextlib
        import io
        report = _shipped_report()
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


class TestTheUnpairedExternalRowsAreNamedInTheOutput:
    """An external model with no local counterpart is either a decision
    somebody made or a gap nobody has looked at, and the printed report has to
    say which. Collapsing the two would let a model quietly drop out of the
    comparison and read as deliberate.
    """

    def _report(self, unmatched):
        return {"version": "fixture", "rollout_version": "fixture",
                "source": "fixture", "n_pairs": 0,
                "interpretation": "fixture",
                "unmatched_external_models": unmatched,
                "unmatched_local_models": [],
                "pairs_by_pooling": {"any_aware": []},
                "correlations": []}

    def _printed(self, unmatched):
        import contextlib
        import io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            am.print_report(self._report(unmatched))
        return buf.getvalue()

    def test_a_decided_exclusion_is_marked_decided_and_gives_its_reason(self):
        printed = self._printed([
            {"external_model": "Ext Gone", "decided": True,
             "reason": "withdrawn from the external table"}])
        assert "[DECIDED]" in printed
        assert "Ext Gone" in printed
        assert "withdrawn from the external table" in printed

    def test_a_row_nobody_decided_about_is_marked_as_a_gap(self):
        """Two-directional against the test above: the marker has to change
        with `decided`, not be printed the same way for both."""
        printed = self._printed([
            {"external_model": "Ext Unknown", "decided": False,
             "reason": None}])
        assert "[GAP" in printed
        assert "[DECIDED]" not in printed
        assert "Ext Unknown" in printed
        assert "None" not in printed, (
            "an absent reason was printed as the string None")


class TestACorrelationPrintsItsCaveatBesideItsCoefficient:
    """`note` is not only the reason a coefficient is absent - a correlation
    that HAS a rho can carry one too, and that is when it matters most: a
    caveat dropped beside a number that looks solid is the one a reader will
    act on without."""

    def _report(self, note):
        return {"version": "fixture", "rollout_version": "fixture",
                "source": "fixture", "n_pairs": 0,
                "interpretation": "fixture",
                "unmatched_external_models": [], "unmatched_local_models": [],
                "pairs_by_pooling": {"any_aware": []},
                "correlations": [
                    {"measure": "level", "measure_label": "l",
                     "aware_pooling": None, "n_models": 6,
                     "spearman_rho": 0.42, "p": 0.03,
                     "p_method": "exact_permutation", "separated": True,
                     "note": note, "leave_one_out_rho_range": None,
                     "n_underpowered_aware_sides": 0}]}

    def _printed(self, note):
        import contextlib
        import io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            am.print_report(self._report(note))
        return buf.getvalue()

    def test_a_note_is_printed_beside_the_coefficient_that_carries_it(self):
        printed = self._printed("two models share a rank, so p is approximate")
        assert "rho=+0.420" in printed, (
            "the fixture no longer prints a coefficient, so this says nothing "
            "about a note printed ALONGSIDE one")
        assert "two models share a rank, so p is approximate" in printed

    def test_a_correlation_with_no_note_prints_no_stray_line(self):
        printed = self._printed(None)
        assert "rho=+0.420" in printed
        assert "None" not in printed


class TestTheScenarioActTableShowsHowMuchOneModelCouldMoveIt:
    """n is three to six models here, so a single model can swing the whole
    coefficient. The leave-one-out range is the only thing on the row that
    says by how much."""

    def _report(self, loo):
        return {"version": "fixture", "rollout_version": "fixture",
                "source": "fixture", "n_pairs": 0,
                "interpretation": "fixture",
                "unmatched_external_models": [], "unmatched_local_models": [],
                "pairs_by_pooling": {"any_aware": []}, "correlations": [],
                "scenario_act_correlations": [
                    {"scenario": "s1", "act": "oversight", "n_models": 4,
                     "spearman_rho": 0.8, "p": 0.02,
                     "leave_one_out_rho_range": loo, "note": None}],
                "best_scenario_act_pairing": None}

    def _printed(self, loo):
        import contextlib
        import io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            am.print_report(self._report(loo))
        return buf.getvalue()

    def test_a_row_with_a_range_shows_both_ends_of_it(self):
        printed = self._printed([0.55, 0.93])
        assert "rho=+0.800" in printed
        assert "loo +0.550 to +0.930" in printed

    def test_a_row_without_a_range_prints_the_rho_and_no_empty_column(self):
        printed = self._printed(None)
        assert "rho=+0.800" in printed
        assert "loo" not in printed
