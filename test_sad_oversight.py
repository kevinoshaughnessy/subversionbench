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
import sys
import tempfile
from pathlib import Path

import pytest

import sad_oversight as so
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
            cwd=Path(__file__).parent).stdout.split()
        offenders = []
        for name in tracked:
            path = Path(__file__).parent / name
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
        ignored = (Path(__file__).parent / ".gitignore").read_text()
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

    def test_a_family_variant_is_not_matched_to_a_row_naming_no_size(self):
        """The specific mistake above, pinned so it cannot come back."""
        index = so.local_index(_bundle())
        assert "thinkingmachines/inkling-small" not in index


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
        if so._import_matplotlib() is None:
            pytest.skip("matplotlib not installed")
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
