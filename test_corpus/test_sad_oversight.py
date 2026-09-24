"""
The external situational-awareness leaderboard, and its correlation with the
awareness rates measured here.

Two things are worth testing and neither is the arithmetic.

THE BARRIER: the shipped bundle must not contain readable text, and no
plaintext file in the repository may reproduce what it holds. That is the whole
reason the file exists in this form, and it is the property most easily lost by
accident - one debug print, one comment naming a row.

THE PAIRING: eight points is few enough that a single wrong match changes the
sign of the answer, and two of the near-misses in this corpus are one date
stamp away from a leaderboard row while scoring three times the awareness rate.
So the mapping is asserted to be explicit, guarded, and free of the specific
mistakes that would be easy to make.
"""


import contextlib
import json
import os
import subprocess
import tempfile
from pathlib import Path

import pytest

import conftest
import sad_oversight as so
from test_analysis.report_fixtures import write_awareness_episode
from test_corpus.sad_fixtures import (_awareness, _bundle)


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
