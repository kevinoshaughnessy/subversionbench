"""
Tests for sad_oversight.py - the external leaderboard and its correlation.

Two things are worth testing here and they are not the arithmetic.

The first is the BARRIER: the shipped bundle must not contain readable text, and
no plaintext file in the repository may reproduce what it holds. That is the
whole reason the file exists in this form, and it is the property most easily
lost by accident - one debug print, one comment naming a row.

The second is the PAIRING. Eight points is few enough that a single wrong match
changes the sign of the answer, and two of the near-misses in this corpus are
one date stamp away from a leaderboard row while scoring three times the
awareness rate. So the mapping is asserted to be explicit, guarded, and free of
the specific mistakes that would be easy to make.
"""

import json
import os
import subprocess
import tempfile
import conftest
from pathlib import Path

import pytest

import sad_oversight as so
from test_analysis.report_fixtures import write_awareness_episode
from subversionbench import charting
from subversionbench.power import spearman, spearman_leave_one_out


def _bundle():
    return so.load_bundle()


# ---------------------------------------------------------------------------
# The barrier
# ---------------------------------------------------------------------------

class TestTheBundleIsNotReadableAtRest:
    """
    Publishing somebody else's benchmark as plain text feeds the next training
    crawl and destroys the leaderboard's own validity. The passphrase is
    published, so this is a crawler barrier and not confidentiality - but a
    barrier that leaks the text anyway is no barrier.
    """

    def test_the_shipped_bundle_holds_no_readable_words(self):
        raw = so._BUNDLE_PATH.read_bytes()
        for word in (b"kimi", b"gemini", b"grok", b"claude", b"deepseek",
                     b"Oversight", b"score", b"rank"):
            assert word.lower() not in raw.lower(), word

    def test_it_round_trips(self):
        payload = {"rows": [{"model": "m", "effort": "high"}], "aliases": []}
        assert so.decrypt(so.encrypt(payload)) == payload

    def test_an_edited_bundle_says_so_rather_than_decoding_to_noise(self):
        """Authenticated on purpose: silent garbage is the failure that wastes
        an afternoon. One flipped character, length untouched, so this reaches
        the tag check rather than stopping at base64."""
        text = so.encrypt({"rows": [{"model": "m"}], "aliases": []})
        blob = "".join(text.split())
        middle = len(blob) // 2
        swapped = "A" if blob[middle] != "A" else "B"
        with pytest.raises(ValueError, match="authentication"):
            so.decrypt(blob[:middle] + swapped + blob[middle + 1:])

    def test_a_truncated_bundle_is_also_refused(self):
        """A different path - base64 gives up before the tag does - and both
        have to fail loudly."""
        text = so.encrypt({"rows": [{"model": "m"}], "aliases": []})
        with pytest.raises(ValueError):
            so.decrypt("".join(text.split())[:-7])

    def test_an_empty_bundle_is_rejected_not_indexed(self):
        with pytest.raises(ValueError, match="too short"):
            so.decrypt("")

    def test_each_write_uses_a_fresh_salt(self):
        """Otherwise two bundles differing in one row would be byte-identical
        over their shared prefix, which leaks structure for free."""
        payload = {"rows": [], "aliases": []}
        assert so.encrypt(payload) != so.encrypt(payload)

    def test_no_tracked_plaintext_file_reproduces_a_leaderboard_score(self):
        """
        The audit that keeps the barrier honest as the code grows, in the same
        spirit as test_contamination's scenario audit.

        IT LOOKS FOR SCORES, NOT FOR MODEL NAMES
        ----------------------------------------
        An earlier version audited the row names and failed on the CHANGELOG,
        correctly. Most of these models were evaluated here too, so their names
        are all over the repository and have to be - they are what the local
        results are keyed by. A name is not the leaderboard.

        What the leaderboard IS, and what a crawl must not find, is the mapping
        from a model to a score. So the needles are the scores: two-decimal
        figures distinctive enough that a coincidental match in source or prose
        is unlikely, and the thing a debug print or a worked example in a
        comment would actually spill.
        """
        bundle = _bundle()
        needles = sorted({f"{row[variant]['score']:.2f}"
                          for row in bundle["rows"]
                          for variant in so.VARIANTS})
        tracked = subprocess.run(
            ["git", "ls-files"], capture_output=True, text=True,
            cwd=conftest.PROJECT_ROOT).stdout.split()
        offenders = []
        for name in tracked:
            path = conftest.PROJECT_ROOT / name
            if path.suffix not in (".py", ".md", ".sh", ".txt", ".toml"):
                continue
            # This file names the audit's own subject in order to look for it.
            if path.name == Path(__file__).name:
                continue
            try:
                text = path.read_text(errors="ignore")
            except OSError:
                continue
            for needle in needles:
                if needle in text:
                    offenders.append(f"{name}: {needle}")
        assert not offenders, (
            "these tracked plaintext files reproduce leaderboard scores: "
            + ", ".join(sorted(offenders)[:8]))


class TestTheBundleCanStillBeEdited:
    """A barrier nobody can get through is a barrier nobody can maintain."""

    def test_decode_then_encode_preserves_the_data(self):
        original = _bundle()
        with tempfile.TemporaryDirectory() as out:
            plain = Path(out) / "plain.json"
            plain.write_text(json.dumps(original))
            bundle = Path(out) / "b.enc"
            bundle.write_text(so.encrypt(json.loads(plain.read_text())))
            assert so.load_bundle(bundle) == original

    def test_the_decoded_working_copy_is_gitignored(self):
        """It would otherwise be one `git add .` from undoing all of this."""
        ignored = (conftest.PROJECT_ROOT / ".gitignore").read_text()
        assert so._PLAIN_PATH.name in ignored


# ---------------------------------------------------------------------------
# The data
# ---------------------------------------------------------------------------

class TestTheTableIsComplete:

    def test_every_row_carries_every_variant(self):
        for row in _bundle()["rows"]:
            for variant in so.VARIANTS:
                cell = row[variant]
                assert set(cell) == {"rank", "score", "se", "invalid"}, row
                assert 0 <= cell["score"] <= 100, row
                assert cell["se"] > 0, row

    def test_a_model_may_appear_more_than_once_at_different_efforts(self):
        """Effort is part of the key, not a label: the same model at two efforts
        is two rows with different scores."""
        keys = [(r["model"], r["effort"]) for r in _bundle()["rows"]]
        assert len(keys) == len(set(keys))
        assert len({m for m, _e in keys}) < len(keys)

    def test_tied_scores_share_a_rank(self):
        """As the source table states. A test rather than a comment because it
        is the one transcription error that would not look like one."""
        for variant in so.VARIANTS:
            by_score = {}
            for row in _bundle()["rows"]:
                by_score.setdefault(row[variant]["score"], set()).add(
                    row[variant]["rank"])
            for score, ranks in by_score.items():
                assert len(ranks) == 1, (variant, score, ranks)

    def test_the_bundle_says_what_the_two_benchmarks_measure(self):
        """Carried with the data so it reaches the JSON output. A weak
        correlation between two different constructs is not evidence that either
        is wrong, and the output has to say so without the reader knowing it."""
        assert len(_bundle()["construct_note"]) > 200


class TestTheMappingIsExplicitAndGuarded:

    def test_every_alias_points_at_a_row_that_exists(self):
        index = so.local_index(_bundle())
        assert index
        for entry in index.values():
            assert entry["row"]["model"] == entry["alias"]["sad_model"]

    def test_unmatched_rows_are_named_rather_than_dropped(self):
        """The guard that makes a hand-kept mapping safe, the same role
        model_releases.missing_dates plays."""
        bundle = _bundle()
        left = so.unmatched_rows(bundle)
        assert len(left) == len(bundle["rows"]) - len(bundle["aliases"])

    def test_a_dated_snapshot_is_not_matched_to_its_undated_row(self):
        """The mistake that would invert the answer: the -0813 checkpoint is at
        100% awareness where the model the row names is at 31%."""
        index = so.local_index(_bundle())
        assert "deepseek/deepseek-v4-pro" in index
        assert "deepseek/deepseek-v4-pro-0813" not in index

    def test_every_deliberate_non_match_carries_a_reason(self):
        excluded = _bundle()["deliberately_unmatched"]
        assert excluded
        index = so.local_index(_bundle())
        for item in excluded:
            assert len(item["reason"]) > 30, item
            assert item["local_model"] not in index, item

    def test_every_shipped_alias_is_an_exact_match(self):
        """
        The bundle once carried a pair matched on a shared name stem, and it was
        a different model: the row named no size, and the local ID is the small
        variant. It sat at one end of the range at a 0% awareness rate, so it
        had leverage over a correlation it did not belong in.

        Nothing less than exact ships now. The `confidence` mechanism stays -
        see the test below - so a future soft match is labelled and set aside
        rather than blended in.
        """
        for alias in _bundle()["aliases"]:
            assert alias.get("confidence", "exact") == "exact", alias

    def test_a_soft_match_would_be_excluded_from_the_sensitivity_pass(self):
        """The mechanism, tested on a synthetic bundle rather than on shipped
        data, so it stays working while no shipped alias needs it."""
        bundle = _bundle()
        alias = dict(bundle["aliases"][0], confidence="stem")
        pairs = so.build_pairs(
            dict(bundle, aliases=[alias]),
            _awareness(**{alias["local_models"][0].replace("/", "__"):
                          (3, 1, 60)}))
        assert pairs and pairs[0]["confidence"] == "stem"
        assert [p for p in pairs if p["confidence"] == "exact"] == []

    def test_a_family_variant_is_matched_only_once_its_own_row_exists(self):
        """
        thinkingmachines/inkling-small was excluded above because the
        leaderboard's 'inkling' row named no size, so pairing it there was a
        guess dressed as a match. It is matched now because a SEPARATE row
        named 'inkling-small' was added - a different fact, not a reversal of
        the one above: the guess is still wrong, and is still excluded.
        """
        index = so.local_index(_bundle())
        assert index["thinkingmachines/inkling-small"]["row"]["model"] \
            == "inkling-small"
        unmatched = so.unmatched_rows(_bundle())
        assert any(r.startswith("inkling (") for r in unmatched), unmatched


# ---------------------------------------------------------------------------
# Pairing
# ---------------------------------------------------------------------------

def _awareness(**models):
    out = {}
    for model, (aware, text, n) in models.items():
        out[model.replace("__", "/")] = {
            "n_aware": aware, "n_aware_text": text, "n": n,
            "n_episodes": n, "episodes_with_reasoning": n}
    return out


class TestOneModelCountsOnce:
    """
    A correlation over eight points cannot afford a duplicate. Two local IDs in
    this corpus are the same model over different routes; counted separately
    they would put two near-identical points at one end and move both rho and
    its p-value, and neither movement is evidence.
    """

    def _routes(self):
        alias = next(a for a in _bundle()["aliases"]
                     if len(a["local_models"]) > 1)
        return alias["local_models"]

    def test_two_routes_of_one_model_become_one_pair(self):
        a, b = self._routes()
        pairs = so.build_pairs(_bundle(), _awareness(**{
            a.replace("/", "__"): (7, 3, 120),
            b.replace("/", "__"): (11, 0, 120)}))
        assert len(pairs) == 1
        assert pairs[0]["pooled_routes"] is True

    def test_the_pooled_pair_adds_the_counts_rather_than_averaging_rates(self):
        """Averaging two rates over unequal denominators is a different number,
        and these two routes are not guaranteed equal n."""
        a, b = self._routes()
        pairs = so.build_pairs(_bundle(), _awareness(**{
            a.replace("/", "__"): (7, 3, 120),
            b.replace("/", "__"): (11, 0, 240)}))
        assert pairs[0]["n"] == 360
        assert pairs[0]["n_aware"] == 18
        assert pairs[0]["aware_rate"] == round(18 / 360, 4)

    def test_a_model_with_no_resolved_episodes_is_not_a_pair(self):
        """A rate over zero episodes is not a low rate."""
        alias = next(a for a in _bundle()["aliases"]
                     if len(a["local_models"]) == 1)
        local = alias["local_models"][0]
        pairs = so.build_pairs(_bundle(),
                               _awareness(**{local.replace("/", "__"): (0, 0, 0)}))
        assert pairs == []

    def test_a_local_model_with_no_row_is_skipped_silently_here(self):
        """And reported by unmatched_models, not by omission."""
        assert so.build_pairs(_bundle(), _awareness(nothing__here=(1, 1, 10))) == []
        assert so.unmatched_models(_bundle(), ["nothing/here"]) == ["nothing/here"]


# ---------------------------------------------------------------------------
# Correlating
# ---------------------------------------------------------------------------

class TestTheCorrelationQualifiesItself:

    def _pairs(self, values):
        """One synthetic pair per (score, rate), bypassing the alias table."""
        return [{"sad_model": f"m{i}", "sad_effort": "high",
                 "confidence": "exact",
                 "scores": {v: {"rank": i, "score": s, "se": 3.0, "invalid": 0}
                            for v in so.VARIANTS},
                 "aware_rate": r, "text_rate": r, "n": 120, "n_aware": 0,
                 "n_aware_text": 0, "local_models": [f"p/m{i}"],
                 "pooled_routes": False}
                for i, (s, r) in enumerate(values)]

    def test_a_perfect_ordering_is_found(self):
        pairs = self._pairs([(50, 0.1), (60, 0.2), (70, 0.3), (80, 0.4)])
        out = so.correlate(pairs, "plain", "aware")
        assert out["spearman_rho"] == 1.0
        assert out["p_method"] == "exact_permutation"

    def test_the_leave_one_out_range_travels_with_every_rho(self):
        """At this n it is the headline, not a refinement: a rho that halves
        when one model is dropped is a statement about that model."""
        pairs = self._pairs([(50, 0.1), (60, 0.2), (70, 0.3), (80, 0.0)])
        out = so.correlate(pairs, "plain", "aware")
        lo, hi = out["leave_one_out_rho_range"]
        assert lo < out["spearman_rho"] < hi or lo <= out["spearman_rho"] <= hi
        assert out["most_influential_model"]

    def test_a_flat_measure_gives_no_rho_rather_than_zero(self):
        """Every model at the same rate is a variable that never varies, which
        is not a correlation of zero."""
        pairs = self._pairs([(50, 0.2), (60, 0.2), (70, 0.2), (80, 0.2)])
        out = so.correlate(pairs, "plain", "aware")
        assert out["spearman_rho"] is None
        assert "no spread" in out["note"]

    def test_the_n_is_reported_beside_the_rho(self):
        out = so.correlate(self._pairs([(50, 0.1), (60, 0.2), (70, 0.3)]),
                           "plain", "aware")
        assert out["n_models"] == 3

    def test_both_awareness_measures_are_correlated(self):
        """A correlation that holds on the mixed measure and not on the
        text-only one is a fact about the instrument, not about the models."""
        assert set(so.MEASURES) == {"aware", "text_reachable"}


class TestSpearmanItself:

    def test_the_p_value_is_exact_at_small_n(self):
        out = spearman([1, 2, 3, 4, 5], [1, 2, 3, 4, 5])
        assert out["method"] == "exact_permutation"
        # Two of the 120 orderings reach |rho| = 1.
        assert out["p"] == pytest.approx(2 / 120)

    def test_ties_share_a_rank_so_input_order_cannot_matter(self):
        a = spearman([1, 2, 2, 3, 4], [1, 2, 3, 4, 5])["rho"]
        b = spearman([1, 2, 2, 3, 4], [1, 3, 2, 4, 5])["rho"]
        assert a == b

    def test_reversal_flips_the_sign_and_keeps_the_p(self):
        up = spearman([1, 2, 3, 4, 5], [2, 1, 4, 3, 5])
        down = spearman([1, 2, 3, 4, 5], [4, 5, 2, 3, 1])
        assert up["rho"] == pytest.approx(-down["rho"])
        assert up["p"] == pytest.approx(down["p"])

    def test_too_few_pairs_is_said_not_computed(self):
        out = spearman([1, 2], [1, 2])
        assert out["rho"] is None and "three" in out["note"]

    def test_mismatched_lengths_raise(self):
        with pytest.raises(ValueError):
            spearman([1, 2, 3], [1, 2])

    def test_leave_one_out_needs_something_to_drop(self):
        out = spearman_leave_one_out([1, 2, 3], [1, 2, 3])
        assert out["min_rho"] is None and "too few" in out["note"]

    def test_leave_one_out_finds_the_point_that_carries_the_fit(self):
        xs = [1, 2, 3, 4, 5, 6]
        ys = [1, 2, 3, 4, 5, 0]
        out = spearman_leave_one_out(xs, ys)
        assert out["most_influential_index"] == 5
        assert out["max_rho"] == 1.0


class TestSpearmanOnceThereAreTooManyModelsToEnumerate:
    """The sampled-permutation branch, taken above _EXACT_PERMUTATION_MAX_N.

    Every p-value this benchmark reports for a rank correlation comes from
    the exact branch today, because the model set is small. The moment it
    grows past the threshold the sampled branch produces all of them
    instead - so it is worth having run before that happens rather than
    after, which is what "n=9" means in these tests.
    """

    def test_the_threshold_is_where_the_method_changes(self):
        """8! is 40,320 orderings and enumerable; 9! is 362,880 and not.
        Asserted at the boundary rather than at a comfortable distance from
        it, because a threshold is exactly where an off-by-one lives."""
        from subversionbench.power import _EXACT_PERMUTATION_MAX_N
        assert _EXACT_PERMUTATION_MAX_N == 8
        exact = spearman(list(range(8)), list(range(8)))
        sampled = spearman(list(range(9)), list(range(9)))
        assert exact["method"] == "exact_permutation"
        assert sampled["method"] == "sampled_permutation"

    def test_the_sampled_p_is_never_zero(self):
        """(hits + 1) / (draws + 1), not hits / draws. A perfect correlation
        over nine points draws no counter-example, and reporting p = 0 for
        that claims more than a sample can support - it says the null was
        excluded rather than never observed."""
        from subversionbench.power import _PERMUTATION_DRAWS
        out = spearman(list(range(9)), list(range(9)))
        assert out["rho"] == 1.0
        assert out["p"] == pytest.approx(1 / (_PERMUTATION_DRAWS + 1))
        assert out["p"] > 0

    def test_it_reports_how_many_draws_stand_behind_the_p(self):
        """The exact branch reports the orderings it enumerated. This one
        has to report the draws instead, or a reader cannot tell a p that
        was counted from one that was sampled."""
        from subversionbench.power import _PERMUTATION_DRAWS
        out = spearman(list(range(9)), list(range(9)))
        assert out["n_permutations"] == _PERMUTATION_DRAWS

    def test_the_same_pairing_gives_the_same_p_every_time(self):
        """Seeded deliberately. A p-value that moved between two runs of the
        same analysis would make a reported figure irreproducible, which
        matters more here than the sampling error does."""
        xs, ys = list(range(9)), [3, 1, 4, 1, 5, 9, 2, 6, 5]
        assert spearman(xs, ys)["p"] == spearman(xs, ys)["p"]

    def test_an_arbitrary_pairing_is_not_separated_from_chance(self):
        """The other end of the range: the sampled branch has to be able to
        return a large p, not only a small one. A near-zero rho over nine
        points is what any pairing looks like."""
        out = spearman(list(range(9)), [5, 1, 8, 2, 9, 3, 7, 4, 6])
        assert out["method"] == "sampled_permutation"
        assert out["p"] > 0.05
        assert out["separated"] is False

    def test_a_constant_side_is_declined_before_any_sampling(self):
        """A variable that never varies is not a correlation of zero, and
        the check has to come first - permuting a constant column would
        otherwise spend 100,000 draws to discover the same thing."""
        out = spearman(list(range(9)), [7] * 9)
        assert out["rho"] is None and out["p"] is None
        assert out["method"] is None


class TestChartLabelsDoNotOverlap:
    """
    At seven or eight well-spread points a fixed offset above-right of each
    marker never collided. At eleven - once kimi-k3 joined the comparison at
    the same score range as three other models - four labels in the
    low-awareness cluster started overlapping each other on exactly the panels
    a reader most needs to tell grok-4.6 apart from gemini-3.5-flash apart from
    llama 4 maverick.
    """

    def _plt(self):
        if charting.import_pyplot() is None:
            from conftest import skip_without
            skip_without("matplotlib", "charts are an optional extra")
        return charting.import_pyplot()

    def test_a_lone_label_keeps_the_natural_offset(self):
        """No collision, no reason to move it."""
        plt = self._plt()
        fig, ax = plt.subplots()
        so._place_labels(fig, ax, [(50.0, 50.0, "only-model")])
        assert ax.texts[0].xyann == so._LABEL_OFFSETS[0]
        plt.close(fig)

    def test_four_points_at_nearly_the_same_spot_all_get_readable_labels(self):
        """The exact shape of the defect: several models within a couple of
        points of each other on both axes. Every label must end up somewhere,
        and no two may occupy the same pixels."""
        plt = self._plt()
        fig, ax = plt.subplots()
        points = [(65.0, 10.0 + i, f"model-{i}") for i in range(4)]
        for x, y, _t in points:
            ax.plot([x], [y], "o")
        so._place_labels(fig, ax, points)
        fig.canvas.draw()
        renderer = fig.canvas.get_renderer()
        boxes = [t.get_window_extent(renderer=renderer) for t in ax.texts]
        for i, a in enumerate(boxes):
            for b in boxes[i + 1:]:
                assert not a.overlaps(b)
        plt.close(fig)

    def test_widely_spaced_points_are_untouched(self):
        """The mechanism must not go looking for a collision that is not
        there - every point here is far enough apart to keep offset zero."""
        plt = self._plt()
        fig, ax = plt.subplots()
        points = [(x, x, f"model-{x}") for x in (10.0, 40.0, 70.0)]
        # Markers plotted first, same as write_chart: with none, the axes sit
        # at their default 0-1 view and every point maps off it, which put
        # spurious overlaps into an earlier version of this test.
        for x, y, _t in points:
            ax.plot([x], [y], "o")
        so._place_labels(fig, ax, points)
        assert all(t.xyann == so._LABEL_OFFSETS[0] for t in ax.texts)
        plt.close(fig)

    def test_every_point_gets_exactly_one_label(self):
        plt = self._plt()
        fig, ax = plt.subplots()
        points = [(65.0, 10.0 + i * 0.1, f"model-{i}") for i in range(6)]
        so._place_labels(fig, ax, points)
        assert len(ax.texts) == 6
        assert {t.get_text() for t in ax.texts} == {p[2] for p in points}
        plt.close(fig)


class TestTheChartIsLaidOutInThreeStackedPanels:
    """The three prompt variants read top to bottom - plain, then SP, then SP
    (large) - which is VARIANTS' own order, so a reader compares one model
    down a column rather than across a row."""

    def _report(self):
        return {
            "n_pairs": 3, "effort_agreement": {"note": "note"},
            "pairs": [
                {"sad_model": "a", "confidence": "exact",
                 "scores": {v: {"score": 50.0, "se": 2.0} for v in so.VARIANTS},
                 "aware_rate": 0.3, "aware_ci95": [0.2, 0.4]},
                {"sad_model": "b", "confidence": "exact",
                 "scores": {v: {"score": 60.0, "se": 2.0} for v in so.VARIANTS},
                 "aware_rate": 0.5, "aware_ci95": [0.4, 0.6]},
                {"sad_model": "c", "confidence": "exact",
                 "scores": {v: {"score": 70.0, "se": 2.0} for v in so.VARIANTS},
                 "aware_rate": 0.7, "aware_ci95": [0.6, 0.8]},
            ],
            "correlations": [
                {"measure": m, "variant": v, "spearman_rho": 0.5, "p": 0.5,
                 "note": None}
                for m in so.MEASURES for v in so.VARIANTS],
        }

    def test_the_chart_renders_without_error(self):
        if charting.import_pyplot() is None:
            from conftest import skip_without
            skip_without("matplotlib", "charts are an optional extra")
        with tempfile.TemporaryDirectory() as out:
            path = so.write_chart(self._report(), os.path.join(out, "c.png"))
            assert path and os.path.exists(path)

    def test_subplots_is_called_for_a_single_column_of_three_rows(self):
        """write_chart closes its figure before returning, so the geometry is
        checked from the source rather than from a live Axes object - the
        `plt.subplots(len(VARIANTS), 1, ...)` call is what fixes rows-not-
        columns, and a stray transpose back to (1, len(VARIANTS)) would not
        otherwise be caught by anything that inspects the saved image."""
        import inspect
        source = inspect.getsource(so.write_chart)
        assert "plt.subplots(len(VARIANTS), 1" in source

    def test_the_panel_order_is_plain_then_sp_then_sp_large(self):
        """Pinned on the constant the plotting loop actually iterates, since
        that is what determines top-to-bottom order for subplots(3, 1, ...)."""
        assert so.VARIANTS == ("plain", "sp", "sp_large")


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

class TestTheRunWritesWhatItSays:

    def _corpus(self, out, model):
        for oversight in ("oversight", "nooversight"):
            name = f"summary_{model.replace('/', '_')}_strong_{oversight}_20260101T000000.json"
            with open(os.path.join(out, name), "w") as f:
                json.dump({"model": model, "nudge": "strong", "n_runs": 10,
                           "n_scheming": 1, "n_misaligned": 2,
                           "awareness_subgroups": {"aware": 3, "unaware": 7}}, f)

    def test_the_json_lands_in_the_rollout_directory(self, monkeypatch):
        bundle = _bundle()
        locals_ = [m for a in bundle["aliases"] for m in a["local_models"]]
        with tempfile.TemporaryDirectory() as out:
            for model in locals_[:4]:
                self._corpus(out, model)
            monkeypatch.setattr("sys.argv",
                                ["sad_oversight.py", "--output-dir", out,
                                 "--no-charts"])
            assert so.main() == 0
            written = [f for f in os.listdir(out)
                       if f.startswith("sad_oversight_correlation")]
            assert len(written) == 1
            with open(os.path.join(out, written[0])) as f:
                report = json.load(f)
        assert report["rollout_version"]
        assert report["n_pairs"] >= 3
        assert report["correlations"]
        assert report["effort_agreement"]["note"]

    def test_a_corpus_with_no_overlap_exits_nonzero(self, monkeypatch):
        """Rather than writing a report whose every correlation is None."""
        with tempfile.TemporaryDirectory() as out:
            self._corpus(out, "nobody/nothing-1")
            monkeypatch.setattr("sys.argv",
                                ["sad_oversight.py", "--output-dir", out,
                                 "--no-charts"])
            assert so.main() == 1

    def test_the_chart_is_written_and_is_optional(self, monkeypatch):
        if charting.import_pyplot() is None:
            from conftest import skip_without
            skip_without("matplotlib", "charts are an optional extra")
        bundle = _bundle()
        locals_ = [m for a in bundle["aliases"] for m in a["local_models"]]
        with tempfile.TemporaryDirectory() as out:
            for model in locals_[:4]:
                self._corpus(out, model)
            monkeypatch.setattr("sys.argv",
                                ["sad_oversight.py", "--output-dir", out])
            assert so.main() == 0
            chart = os.path.join(out, "charts",
                                 "sad_oversight_correlation.png")
            assert os.path.exists(chart)

    def test_the_rollout_version_is_not_touched_by_any_of_this(self):
        """This is analysis over data already collected. Nothing here changes
        what a model saw, so no episode may fail to pool because of it."""
        source = Path(so.__file__).read_text()
        assert "ROLLOUT_VERSION =" not in source


class TestBothAwarenessRatesArePooledPerModel:
    """awareness_by_model reads two different measures from two different
    places, and the join between them was unrun.

    `aware` comes from the summaries and covers reasoning AND visible
    output; `text_reachable` exists per EPISODE only, so the arms are
    rebuilt from run files for it. The two are carried side by side because
    the first is not comparable across models whose routes return different
    amounts of reasoning - and the models on this leaderboard differ there.
    A correlation holding on one and not the other is a fact about the
    instrument rather than about the models.
    """

    def _corpus(self, out, model="p/m", n_aware=3, n_runs=10, text_aware=2):
        from test_analysis.report_fixtures import _write_summary
        _write_summary(out, model, "strong", n_runs=n_runs, n_aware=n_aware,
                       n_unaware=n_runs - n_aware)
        for i in range(1, n_runs + 1):
            write_awareness_episode(out, i, model, "strong",
                                    where="text", aware=i <= text_aware,
                                    stamp=f"2026010{i % 10}T00000{i % 10}")

    def test_the_text_only_numerator_is_rebuilt_from_the_episodes(self):
        """The summaries do not carry it. Without this pass the text rate
        would be a flat zero for every model and the second measure would
        silently be no measure at all."""
        with tempfile.TemporaryDirectory() as out:
            self._corpus(out, text_aware=2)
            pooled = so.awareness_by_model(out)
        entry = pooled["p/m"]
        assert entry["n_aware_text"] == 2, entry
        assert entry["text_rate"] is not None and entry["text_rate"] > 0

    def test_the_two_measures_are_kept_apart(self):
        """Same denominator, different numerators. Collapsing them would
        make the comparison the tool exists for impossible."""
        with tempfile.TemporaryDirectory() as out:
            self._corpus(out, n_aware=3, text_aware=1)
            entry = so.awareness_by_model(out)["p/m"]
        assert entry["n_aware"] == 3 and entry["n_aware_text"] == 1
        assert entry["aware_rate"] != entry["text_rate"]

    def test_an_episode_for_a_model_with_no_summary_is_ignored(self):
        """The pooled map is keyed off the SUMMARIES. An episode whose model
        never got one has no denominator to join to, and adding a numerator
        without one would produce a rate over nothing."""
        with tempfile.TemporaryDirectory() as out:
            self._corpus(out, model="p/m")
            write_awareness_episode(out, 99, "p/other", "strong",
                                    where="text", aware=True,
                                    stamp="20260202T000000")
            pooled = so.awareness_by_model(out)
        assert set(pooled) == {"p/m"}, "an episode created a model row"
        assert pooled["p/m"]["n_aware_text"] == 2, "the stray episode counted"

    def test_a_model_with_no_resolved_awareness_reports_no_rate(self):
        """Not a rate of zero: nothing was measured. n=0 is what says so."""
        from test_analysis.report_fixtures import _write_summary
        with tempfile.TemporaryDirectory() as out:
            _write_summary(out, "p/m", "strong", n_runs=4, n_aware=0,
                           n_unaware=0)
            entry = so.awareness_by_model(out)["p/m"]
        assert entry["n"] == 0
        assert entry["aware_rate"] is None and entry["text_rate"] is None
        assert entry["aware_ci95"] is None


class TestTheBundleEditingModes:
    """--decode and --encode, the only way to maintain the barrier.

    A barrier nobody can get through is a barrier nobody can maintain, so
    these two modes exist and had never run. Both paths are redirected at a
    temporary copy: --encode WRITES the tracked bundle, and a test that ran
    against the real one would rewrite the published artefact.
    """

    def _redirected(self, tmpdir):
        import contextlib
        from pathlib import Path

        @contextlib.contextmanager
        def _ctx():
            saved = (so._BUNDLE_PATH, so._PLAIN_PATH)
            try:
                copy = Path(tmpdir) / "sad_oversight.enc"
                copy.write_text(saved[0].read_text(encoding="utf-8"),
                                encoding="utf-8")
                so._BUNDLE_PATH = copy
                so._PLAIN_PATH = Path(tmpdir) / "sad_oversight.json"
                yield so
            finally:
                so._BUNDLE_PATH, so._PLAIN_PATH = saved
        return _ctx()

    def test_decode_writes_the_editable_copy(self):
        with tempfile.TemporaryDirectory() as d:
            with self._redirected(d) as tool:
                code, text = conftest.run_tool_main(tool, ["--decode"])
                assert code == 0, text
                assert json.loads(tool._PLAIN_PATH.read_text(
                    encoding="utf-8")) == tool.load_bundle(tool._BUNDLE_PATH)
        assert "then --encode" in text

    def test_encode_without_a_decoded_copy_says_to_decode_first(self):
        with tempfile.TemporaryDirectory() as d:
            with self._redirected(d) as tool:
                before = tool._BUNDLE_PATH.read_text(encoding="utf-8")
                code, text = conftest.run_tool_main(tool, ["--encode"])
                assert tool._BUNDLE_PATH.read_text(encoding="utf-8") == before
        assert code == 1
        assert "run --decode first" in text

    def test_an_edit_round_trips_and_the_bundle_stays_unreadable(self):
        """The round trip is the point, and so is what it produces: a
        re-encoded bundle that still holds no readable score."""
        with tempfile.TemporaryDirectory() as d:
            with self._redirected(d) as tool:
                conftest.run_tool_main(tool, ["--decode"])
                edited = json.loads(tool._PLAIN_PATH.read_text(
                    encoding="utf-8"))
                edited["rows"][0]["effort"] = "edited-marker"
                tool._PLAIN_PATH.write_text(json.dumps(edited),
                                            encoding="utf-8")
                code, text = conftest.run_tool_main(tool, ["--encode"])
                assert code == 0, text
                assert tool.load_bundle(tool._BUNDLE_PATH)["rows"][0][
                    "effort"] == "edited-marker"
                raw = tool._BUNDLE_PATH.read_bytes()
        assert b"edited-marker" not in raw, "the edit is readable at rest"

    def test_a_missing_results_directory_is_refused_by_the_parser(self):
        """The parser validates it, so main's own isdir check below is not
        reachable through the CLI - asserted where the refusal actually
        happens rather than where it is written."""
        with tempfile.TemporaryDirectory() as d:
            with self._redirected(d) as tool:
                try:
                    conftest.run_tool_main(
                        tool, ["--output-dir", os.path.join(d, "absent")])
                except SystemExit as exit_code:
                    assert exit_code.code == 2
                else:
                    raise AssertionError("a missing directory was accepted")


# ---------------------------------------------------------------------------
# What the printed report says about the matches it made
# ---------------------------------------------------------------------------

def _synthetic_report(pairs=None, correlations=None, sensitivity=None,
                      deliberately_unmatched=None, unmatched_rows=None):
    """A report shaped like build_report's, assembled here rather than run off
    the shipped bundle: what that bundle happens to carry today (which rows are
    unmatched, which matches are inexact) is a fact about the corpus that moves
    as models are evaluated, and pinning it in a test would make the printer's
    guards untestable in whichever direction the bundle currently sits."""
    return {
        "n_pairs": len(pairs or []), "n_leaderboard_rows": 12,
        "n_local_models": 9, "pairs": pairs or [],
        "correlations": correlations or [],
        "correlations_exact_matches_only": sensitivity or [],
        "effort_agreement": {"n_pairs": 0, "n_local_effort_unset": 0,
                             "note": "fixture effort note"},
        "unmatched_leaderboard_rows": unmatched_rows or [],
        "unmatched_local_models": [],
        "deliberately_unmatched": deliberately_unmatched or [],
    }


def _synthetic_pair(sad_model="Ext A", confidence="exact", local_models=("a",),
                    n_aware=6, n_aware_text=3, n=60, score=41.5):
    return {
        "sad_model": sad_model, "sad_effort": "high",
        "confidence": confidence, "match_note": None,
        "scores": {v: {"rank": 1, "score": score, "se": 2.0, "invalid": 0}
                   for v in so.VARIANTS},
        "local_models": list(local_models),
        "n_aware": n_aware, "n_aware_text": n_aware_text, "n": n,
        "n_episodes": n, "episodes_with_reasoning": n,
        "aware_rate": round(n_aware / n, 4),
        "text_rate": round(n_aware_text / n, 4),
        "pooled_routes": len(local_models) > 1,
    }


def _print(report):
    import contextlib
    import io
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        so.print_report(report)
    return buf.getvalue()


class TestAPairThatIsNotOneCleanMatchSaysSo:
    """Eight points is few enough that one wrong match changes the sign of the
    answer, so the two ways a row can be less than a clean match - two local
    routes pooled into one point, and a name matched on a stem rather than
    exactly - are flagged on the row itself rather than left in the JSON."""

    def test_a_pooled_pair_says_how_many_routes_went_into_it(self):
        printed = _print(_synthetic_report(
            [_synthetic_pair(local_models=("a", "b"))]))
        assert "2 routes pooled" in printed

    def test_an_inexactly_matched_pair_says_so(self):
        printed = _print(_synthetic_report(
            [_synthetic_pair(confidence="name stem")]))
        assert "name stem match" in printed

    def test_a_clean_exact_pair_carries_no_flags(self):
        """Two-directional against both tests above: a flag on every row is a
        flag on none, since the reader stops seeing it."""
        printed = _print(_synthetic_report([_synthetic_pair()]))
        assert "Ext A" in printed, "the fixture printed no row at all"
        assert "pooled" not in printed
        assert "match]" not in printed and "[" not in printed


class TestACorrelationRowCarriesItsOwnFragility:
    """rho over eight models is one model away from a different answer, so the
    leave-one-out range is not decoration - it is the number that says how
    much of the coefficient rests on any single point."""

    def _correlation(self, rho=0.71, loo=(0.44, 0.88), note=None):
        return {"measure": "aware", "variant": "plain", "n_models": 8,
                "spearman_rho": rho, "p": 0.0312,
                "leave_one_out_rho_range": list(loo) if loo else None,
                "note": note}

    def test_a_coefficient_is_printed_with_its_leave_one_out_range(self):
        printed = _print(_synthetic_report(
            correlations=[self._correlation()]))
        assert "rho=+0.710" in printed
        assert "p=0.0312" in printed
        assert "n=8" in printed
        assert "leave-one-out +0.440..+0.880" in printed

    def test_a_coefficient_with_no_range_still_prints_its_rho(self):
        printed = _print(_synthetic_report(
            correlations=[self._correlation(loo=None)]))
        assert "rho=+0.710" in printed
        assert "leave-one-out" not in printed

    def test_the_sensitivity_block_is_titled_apart_from_the_main_one(self):
        """Exact matches only is a different population from all pairs, and a
        reader comparing two rhos has to be able to tell which is which."""
        printed = _print(_synthetic_report(
            correlations=[self._correlation()],
            sensitivity=[self._correlation(rho=0.55, loo=None)]))
        assert "CORRELATIONS" in printed
        assert "EXACT MATCHES ONLY" in printed
        assert "rho=+0.550" in printed

    def test_an_absent_block_is_not_given_an_empty_heading(self):
        printed = _print(_synthetic_report(
            correlations=[self._correlation()]))
        assert "EXACT MATCHES ONLY" not in printed


class TestTheReportNamesWhatItDidNotCompare:
    def test_a_deliberate_non_match_is_printed_with_its_reason(self):
        printed = _print(_synthetic_report(deliberately_unmatched=[
            {"local_model": "vendor/small", "reason": "not the row's model"}]))
        assert "NOT matched, on purpose" in printed
        assert "vendor/small: not the row's model" in printed

    def test_nothing_deliberately_unmatched_prints_no_heading(self):
        printed = _print(_synthetic_report())
        assert "NOT matched, on purpose" not in printed

    def test_leaderboard_rows_with_no_local_run_are_listed(self):
        printed = _print(_synthetic_report(
            unmatched_rows=[f"Row {i}" for i in range(1, 4)]))
        assert "3 leaderboard row(s) not evaluated here" in printed
        assert "Row 1, Row 2, Row 3" in printed
        assert "more" not in printed

    def test_a_long_list_is_truncated_and_says_how_many_it_hid(self):
        printed = _print(_synthetic_report(
            unmatched_rows=[f"Row {i}" for i in range(1, 11)]))
        assert "Row 6" in printed
        assert "Row 7" not in printed
        assert "and 4 more" in printed

    def test_no_unmatched_rows_prints_no_line_about_them(self):
        printed = _print(_synthetic_report())
        assert "not evaluated here" not in printed


class TestAnAliasWithNoLeaderboardRowIsNotAMatch:
    """The alias table is written by hand against a bundle that is edited
    separately. An alias naming a row that is not there must drop out, not
    index its local models onto whatever row happens to sort nearby."""

    def _bundle(self, alias_effort):
        return {
            "rows": [{"model": "Ext A", "effort": "high",
                      **{v: {"rank": 1, "score": 40.0, "se": 2.0, "invalid": 0}
                         for v in so.VARIANTS}}],
            "aliases": [
                {"sad_model": "Ext A", "sad_effort": "high",
                 "local_models": ["vendor/a"]},
                {"sad_model": "Ext A", "sad_effort": alias_effort,
                 "local_models": ["vendor/ghost"]},
            ],
        }

    def test_the_alias_is_dropped_rather_than_matched_to_another_row(self):
        index = so.local_index(self._bundle("low"))
        assert set(index) == {"vendor/a"}, (
            "an alias naming an effort level no row carries was still indexed")

    def test_the_same_alias_indexes_once_its_row_exists(self):
        """The control - without it the test above would pass against a
        local_index that indexed nothing at all."""
        index = so.local_index(self._bundle("high"))
        assert set(index) == {"vendor/a", "vendor/ghost"}


class TestTheChartDegradesRatherThanFailing:
    def test_without_matplotlib_it_returns_none(self):
        original = charting.import_pyplot
        charting.import_pyplot = lambda *a, **k: None
        try:
            result = so.write_chart(_synthetic_report([_synthetic_pair()]),
                                    "/dev/null/unwritable.png")
        finally:
            charting.import_pyplot = original
        assert result is None

    def test_no_pairs_means_no_chart_rather_than_an_empty_one(self):
        """An empty three-panel figure is worse than no file: it reads as a
        correlation that was measured and found to be nothing."""
        if charting.import_pyplot() is None:
            from conftest import skip_without
            skip_without("matplotlib", "charts are an optional extra")
        assert so.write_chart(_synthetic_report([]),
                              "/dev/null/unwritable.png") is None

    def test_a_run_whose_chart_was_not_drawn_announces_no_file(self):
        """main asks for a chart and gets None back on a machine without
        matplotlib. It must still exit zero and write the JSON, without
        naming a png that is not there."""
        import contextlib
        import io
        import sys as _sys
        import unittest.mock
        bundle = _bundle()
        locals_ = [m for a in bundle["aliases"] for m in a["local_models"]]
        buf = io.StringIO()
        saved = _sys.argv
        with tempfile.TemporaryDirectory() as out:
            for model in locals_[:4]:
                TestTheRunWritesWhatItSays()._corpus(out, model)
            _sys.argv = ["sad_oversight.py", "--output-dir", out]
            try:
                with contextlib.redirect_stdout(buf), \
                        unittest.mock.patch.object(so, "write_chart",
                                                   return_value=None):
                    code = so.main()
            finally:
                _sys.argv = saved
            written = [f for f in os.listdir(out)
                       if f.startswith("sad_oversight_correlation")]
        assert code == 0, buf.getvalue()
        assert written, "the JSON report was not written"
        assert "Chart written to" not in buf.getvalue()
