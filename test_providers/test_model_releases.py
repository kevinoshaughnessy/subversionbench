"""
The release-date table, and the one claim it is there to support.

A table of hand-entered constants does not need testing for its own sake - the
values are either transcribed right or they are not, and no assertion here can
tell. What is worth pinning is the SHAPE the lookups assume (keys carry a
provider, dates are date objects, the stem fallback is not ambiguous) and the
cross-check against the trends package, because that is the only place the two
files can contradict each other.
"""

from datetime import date

import model_releases as mr
import trends as ft


class TestTheTableIsWellFormed:
    def test_no_two_keys_share_a_stem(self):
        """The invariant the stem fallback actually needs.

        This replaced "every key carries a provider", which was a PROXY for it
        and forbade something legitimate: `claude-haiku-4-5-20251001` is the
        real ID for the Anthropic API, which is how this corpus reached that
        model. The `anthropic/` prefix is an OpenRouter convention, and keying
        it that way would have recorded a route that was never used.

        A bare key is safe on its own. What is not safe is the same model under
        two keys - a bare one and a prefixed one - because release_date() would
        then find two dates for one stem and have no way to choose. That is the
        case this holds, and it is the real content of the old rule."""
        stems = [k.rpartition("/")[2].lower() for k in mr.RELEASE_DATES]
        dupes = sorted({s for s in stems if stems.count(s) > 1})
        assert not dupes, f"these stems appear under more than one key: {dupes}"

    def test_every_key_is_stripped(self):
        """Surrounding whitespace would break the exact-match path silently:
        release_date() strips its ARGUMENT, not the table's keys."""
        bad = [k for k in mr.RELEASE_DATES if k != k.strip()]
        assert not bad, f"these keys carry surrounding whitespace: {bad}"

    def test_every_value_is_a_date_object(self):
        """Not an ISO string. Callers sort and compare these directly, and a
        string would sort correctly right up until one was written without a
        zero-padded month."""
        bad = [k for k, v in mr.RELEASE_DATES.items() if not isinstance(v, date)]
        assert not bad, f"these values are not date objects: {bad}"

    def test_no_two_ids_differ_only_in_case(self):
        """The stem fallback lowercases, so a table holding both cases would
        make the fallback ambiguous for a reason no reader would guess."""
        lowered = [k.lower() for k in mr.RELEASE_DATES]
        assert len(set(lowered)) == len(lowered)


class TestLookup:
    def test_an_exact_id_returns_its_date(self):
        assert mr.release_date("x-ai/grok-4.5") == date(2026, 7, 8)

    def test_an_unqualified_id_falls_back_to_the_stem(self):
        """gpt-5.6-luna is in this corpus twice, once natively and once through
        OpenRouter. The route does not change when it was released."""
        assert mr.release_date("gpt-5.6-luna") == date(2026, 7, 9)

    def test_an_unknown_id_returns_none_rather_than_a_guess(self):
        assert mr.release_date("x-ai/grok-9") is None

    def test_an_ambiguous_stem_returns_none(self):
        """Two providers shipping the same stem is the case the fallback must
        refuse, not resolve. Constructed rather than taken from the table,
        because the real table has no such pair - which is precisely why this
        would otherwise go untested until the day one appeared."""
        table = dict(mr.RELEASE_DATES)
        table["a/twin-1"] = date(2026, 1, 1)
        table["b/twin-1"] = date(2026, 6, 1)
        original, mr.RELEASE_DATES = mr.RELEASE_DATES, table
        try:
            assert mr.release_date("twin-1") is None
            assert mr.release_date("a/twin-1") == date(2026, 1, 1)
        finally:
            mr.RELEASE_DATES = original


class TestOrdering:
    def test_the_whole_table_comes_back_oldest_first(self):
        ordered = mr.by_release_date()
        dates = [mr.RELEASE_DATES[m] for m in ordered]
        assert dates == sorted(dates)
        assert len(ordered) == len(mr.RELEASE_DATES)

    def test_a_tie_keeps_the_order_it_was_given(self):
        """The three gpt-5.6 variants share a release date. An arbitrary
        tie-break would reorder them between runs and make a chart's x-axis
        unstable for no reason."""
        ordered = mr.by_release_date(
            ["openai/gpt-5.6-sol", "openai/gpt-5.6-terra", "openai/gpt-5.6-luna"])
        assert ordered == ["openai/gpt-5.6-sol", "openai/gpt-5.6-terra",
                           "openai/gpt-5.6-luna"]

    def test_undated_models_are_dropped_not_sorted_to_the_front(self):
        ordered = mr.by_release_date(["x-ai/grok-4.5", "x-ai/grok-9"])
        assert ordered == ["x-ai/grok-4.5"]


class TestMissingDates:
    def test_it_names_what_the_table_has_not_been_told_about(self):
        """The guard that makes a hand-maintained table safe: the gap is
        reported rather than discovered."""
        assert mr.missing_dates(
            ["x-ai/grok-4.5", "openai/gpt-9", "a/b"]) == ["a/b", "openai/gpt-9"]

    def test_a_fully_covered_corpus_reports_nothing(self):
        assert mr.missing_dates(mr.RELEASE_DATES) == []


class TestAgainstTheVersionOrder:
    """
    Where the parsed version order and the recorded dates disagree, one of them
    is wrong about the world. These pin which.
    """

    def _families(self):
        return ft.group_families(list(mr.RELEASE_DATES), "decimal")

    def test_the_kimi_thinking_snapshot_is_the_one_known_inversion(self):
        """kimi-k2-thinking has no date stamp, so the parser sorts it with the
        undated k2 members - ahead of k2-0905. It was released two months
        AFTER. The parse is what is wrong here, not the dates, and it is
        recorded rather than silently corrected because reordering a family on
        a date would change what `--metric` trends report."""
        found = mr.disagreements(self._families())
        assert list(found) == ["moonshotai/kimi-k"]
        assert [(a, b) for a, _, b, _ in found["moonshotai/kimi-k"]] == [
            ("moonshotai/kimi-k2-thinking", "moonshotai/kimi-k2-0905")]

    def test_grok_420_agrees_with_its_release_date(self):
        """The decimal reading of 4.20 was a correction to an earlier
        package-manager reading that put it at the END of its family. The dates
        are the independent evidence that the correction was right."""
        families = self._families()
        grok = [m.raw for m in families["x-ai/grok"]]
        assert grok == ["x-ai/grok-4.20", "x-ai/grok-4.3", "x-ai/grok-4.5",
                        "x-ai/grok-4.6"]
        assert "x-ai/grok" not in mr.disagreements(families)

    def test_the_dated_deepseek_snapshots_sort_after_their_undated_siblings(self):
        """The undated-before-dated rule is a guess about naming. For both
        deepseek lines the dates confirm it."""
        assert not {k: v for k, v in mr.disagreements(self._families()).items()
                    if k.startswith("deepseek/")}

    def test_a_family_with_no_recorded_dates_reports_nothing(self):
        """Missing dates must not read as an inversion - that would turn a gap
        in this table into a false claim about someone's version numbering."""
        Fake = ft.ModelId
        members = [Fake(raw=f"x/unknown-{i}", provider="x", stem="unknown",
                        version=(i,), date=None, tags=(), unparsed=())
                   for i in (1, 2)]
        assert mr.disagreements({"x/unknown": members}) == {}


class TestTheScript:
    def test_it_prints_every_model_and_exits_clean(self):
        """Runnable as well as importable, since a date table is most often
        wanted as a quick look rather than as an import."""
        assert mr.main([]) == 0

    def test_it_rejects_arguments_rather_than_ignoring_them(self):
        assert mr.main(["--metric", "aware"]) == 2
