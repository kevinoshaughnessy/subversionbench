"""
Deriving a model family and a version order from an ID.

The families are never enumerated, so the parse IS the feature - a rule that is
wrong about one ID puts a model in the wrong family, or in none, and the report
is quietly narrower than the corpus rather than visibly broken. These pin every
real ID in the r9 corpus and the shapes a future one is likely to take.
"""



import trends as ft


class TestParsingRealModelIds:
    """Every ID below is one the corpus actually holds."""

    def test_a_dotted_version_splits_from_its_stem(self):
        parsed = ft.parse_model_id("x-ai/grok-4.5")
        assert parsed.provider == "x-ai"
        assert parsed.stem == "grok"
        assert parsed.version == (4, 5)

    def test_a_version_glued_to_the_stem_is_split(self):
        """qwen3.8-27b and hy3 carry the version inside the word."""
        assert ft.parse_model_id("tencent/hy3").version == (3,)
        assert ft.parse_model_id("tencent/hy3").stem == "hy"
        parsed = ft.parse_model_id("qwen/qwen3.8-27b")
        assert parsed.version == (3, 8)
        # A parameter count is family identity, not a version.
        assert parsed.stem == "qwen-27b"

    def test_a_leading_v_is_not_part_of_the_stem(self):
        """Otherwise deepseek-v4-pro and a future deepseek-5-pro are two
        families that never get compared."""
        assert ft.parse_model_id("deepseek/deepseek-v4-pro").stem == (
            "deepseek-pro")
        assert ft.parse_model_id("deepseek/deepseek-v4-pro").version == (4,)

    def test_dash_separated_version_components_merge(self):
        """Anthropic writes with dashes what everyone else writes with dots, so
        claude-haiku-4-5 is version (4, 5) and not two versions."""
        parsed = ft.parse_model_id("claude-haiku-4-5-20251001")
        assert parsed.version == (4, 5)
        assert parsed.stem == "claude-haiku"

    def test_a_date_stamp_is_not_a_version_component(self):
        """The regression: the version pattern matches a run of digits, so
        checking it first parsed deepseek-v4-pro-0813 as version (4, 813) -
        sorting it after a hypothetical v4.99 - and claude-haiku-4-5-20251001
        as version (4, 5, 20251001)."""
        parsed = ft.parse_model_id("deepseek/deepseek-v4-pro-0813")
        assert parsed.version == (4,), "0813 must not become a version part"
        assert parsed.date == "0813"
        assert ft.parse_model_id("claude-haiku-4-5-20251001").date == "20251001"
        assert ft.parse_model_id(
            "mistralai/mistral-small-2603").date == "2603"

    def test_a_single_digit_is_a_version_not_a_date(self):
        assert ft.parse_model_id("google/gemini-3-flash-preview").version == (3,)
        assert ft.parse_model_id("google/gemini-3-flash-preview").date is None

    def test_a_release_stage_word_becomes_a_tag(self):
        for model, tag in (("google/gemini-3-flash-preview", "preview"),
                           ("moonshotai/kimi-k2-thinking", "thinking")):
            parsed = ft.parse_model_id(model)
            assert parsed.tags == (tag,), model
            assert tag not in parsed.stem, model

    def test_an_id_with_no_version_parses_without_one(self):
        parsed = ft.parse_model_id("thinkingmachines/inkling-small")
        assert parsed.version == ()
        assert parsed.stem == "inkling-small"


class TestWhichModelsShareAFamily:
    def test_the_four_families_the_corpus_holds(self):
        expected = {
            "x-ai/grok": {"x-ai/grok-4.20", "x-ai/grok-4.3", "x-ai/grok-4.5",
                          "x-ai/grok-4.6"},
            "moonshotai/kimi-k": {"moonshotai/kimi-k2-thinking",
                                  "moonshotai/kimi-k2.5",
                                  "moonshotai/kimi-k2.6"},
            "deepseek/deepseek-pro": {"deepseek/deepseek-v4-pro",
                                      "deepseek/deepseek-v4-pro-0813"},
            "google/gemini-flash": {"google/gemini-3-flash-preview",
                                    "google/gemini-3.5-flash",
                                    "google/gemini-3.6-flash",
                                    "google/gemini-3.7-flash"},
        }
        for model in sorted({m for ms in expected.values() for m in ms}):
            key = ft.family_key(ft.parse_model_id(model))
            assert model in expected[key], f"{model} landed in {key}"

    def test_a_tier_word_does_split_a_family(self):
        """gemini-3.1-flash-lite is not a version of gemini-3.5-flash, and
        pooling them would compare two product lines and call it a trend."""
        lite = ft.family_key(ft.parse_model_id("google/gemini-3.1-flash-lite"))
        flash = ft.family_key(ft.parse_model_id("google/gemini-3.5-flash"))
        assert lite != flash
        pro = ft.family_key(ft.parse_model_id("deepseek/deepseek-v4-pro"))
        dsflash = ft.family_key(
            ft.parse_model_id("deepseek/deepseek-v4-flash-0731"))
        assert pro != dsflash

    def test_the_route_does_not_get_pooled_with_the_model(self):
        """gpt-5.6-luna and openai/gpt-5.6-luna are one model on two routes,
        which differ in how much reasoning they return - pooling them would
        compare instruments."""
        assert (ft.family_key(ft.parse_model_id("gpt-5.6-luna"))
                != ft.family_key(ft.parse_model_id("openai/gpt-5.6-luna")))

    def test_a_future_version_needs_no_change_here(self):
        """The whole point of deriving rather than listing."""
        models = ["google/gemini-3.5-flash", "google/gemini-3.6-flash",
                  "google/gemini-3.7-flash", "google/gemini-3.8-flash"]
        families = ft.group_families(models, "component")
        assert list(families) == ["google/gemini-flash"]
        assert [m.raw for m in families["google/gemini-flash"]] == models

    def test_a_lone_model_is_not_a_family(self):
        assert ft.group_families(["a/x-1", "b/y-2"], "component") == {}


class TestVersionOrdering:
    def test_a_minor_sorts_numerically(self):
        models = ["google/gemini-3.7-flash", "google/gemini-3-flash-preview",
                  "google/gemini-3.5-flash", "google/gemini-3.6-flash"]
        order = [m.raw for m in ft.group_families(
            models, "component")["google/gemini-flash"]]
        assert order == ["google/gemini-3-flash-preview",
                         "google/gemini-3.5-flash",
                         "google/gemini-3.6-flash",
                         "google/gemini-3.7-flash"]

    def test_a_dated_snapshot_follows_the_undated_one(self):
        models = ["deepseek/deepseek-v4-pro-0813", "deepseek/deepseek-v4-pro"]
        order = [m.raw for m in ft.group_families(
            models, "component")["deepseek/deepseek-pro"]]
        assert order == ["deepseek/deepseek-v4-pro",
                         "deepseek/deepseek-v4-pro-0813"]

    def test_an_incoming_dated_pair_needs_no_change(self):
        """deepseek-v4-flash is being collected as the earlier version of
        deepseek-v4-flash-0731. It joins its family and orders correctly with no
        edit, which is the whole point of deriving families rather than listing
        them - the same shape deepseek-pro already has."""
        models = ["deepseek/deepseek-v4-flash-0731", "deepseek/deepseek-v4-flash"]
        families = ft.group_families(models, "decimal")
        assert list(families) == ["deepseek/deepseek-flash"]
        assert [m.raw for m in families["deepseek/deepseek-flash"]] == [
            "deepseek/deepseek-v4-flash", "deepseek/deepseek-v4-flash-0731"]

    def test_the_flash_and_pro_lines_stay_separate(self):
        """Both are v4 with a dated snapshot. Pooling them would compare two
        product lines and report the difference as a version trend."""
        models = ["deepseek/deepseek-v4-flash", "deepseek/deepseek-v4-flash-0731",
                  "deepseek/deepseek-v4-pro", "deepseek/deepseek-v4-pro-0813"]
        families = ft.group_families(models, "decimal")
        assert sorted(families) == ["deepseek/deepseek-flash",
                                    "deepseek/deepseek-pro"]
        assert all(len(m) == 2 for m in families.values())

    def test_the_two_styles_disagree_only_on_a_trailing_zero(self):
        """4.20 is major 4 minor 20 under `component`, so after 4.6; and 4.2
        under `decimal`, so before 4.3. Both are defensible."""
        models = ["x-ai/grok-4.20", "x-ai/grok-4.3", "x-ai/grok-4.5",
                  "x-ai/grok-4.6"]
        component = [m.raw for m in ft.group_families(
            models, "component")["x-ai/grok"]]
        decimal = [m.raw for m in ft.group_families(
            models, "decimal")["x-ai/grok"]]
        assert component[-1] == "x-ai/grok-4.20"
        assert decimal[0] == "x-ai/grok-4.20"

    def test_the_default_reads_a_version_as_a_decimal(self):
        """grok-4.20 is an OLDER release than grok-4.3, so 4.20 means 4.2 and
        not major-4-minor-20. The package-manager reading was the original
        default; it put 4.20 at the end of its family and reversed the sign of
        the family's trend, from falling to rising."""
        models = ["x-ai/grok-4.5", "x-ai/grok-4.20", "x-ai/grok-4.6",
                  "x-ai/grok-4.3"]
        expected = ["x-ai/grok-4.20", "x-ai/grok-4.3", "x-ai/grok-4.5",
                    "x-ai/grok-4.6"]
        assert [m.raw for m in ft.group_families(
            models, "decimal")["x-ai/grok"]] == expected
        # And by the default, reached without naming a style at all.
        assert [m.raw for m in sorted(
            [ft.parse_model_id(m) for m in models],
            key=ft.version_sort_key)] == expected

    def test_the_default_still_puts_a_future_minor_last(self):
        """The reason `component` was the original default: 3.8 must land after
        3.7, not between 3.1 and 3.5. Reading as a decimal does that too."""
        models = ["google/gemini-3.1-flash", "google/gemini-3.7-flash",
                  "google/gemini-3.8-flash", "google/gemini-3.5-flash"]
        assert [m.raw for m in sorted(
            [ft.parse_model_id(m) for m in models],
            key=ft.version_sort_key)] == [
                "google/gemini-3.1-flash", "google/gemini-3.5-flash",
                "google/gemini-3.7-flash", "google/gemini-3.8-flash"]

    def test_the_build_and_the_cli_agree_on_the_default(self):
        """A default that differs between the library call and the flag would
        make the JSON disagree with the chart beside it."""
        import inspect
        assert inspect.signature(
            ft.build_report).parameters["style"].default == "decimal"
        assert 'default="decimal"' in inspect.getsource(ft.main)

    def test_the_disagreement_is_detected(self):
        grok = [ft.parse_model_id(m) for m in
                ("x-ai/grok-4.20", "x-ai/grok-4.3", "x-ai/grok-4.6")]
        assert ft.ordering_is_ambiguous(grok) is True

    def test_an_unambiguous_family_is_not_flagged(self):
        gemini = [ft.parse_model_id(m) for m in
                  ("google/gemini-3.5-flash", "google/gemini-3.6-flash",
                   "google/gemini-3.7-flash")]
        assert ft.ordering_is_ambiguous(gemini) is False


class TestATokenTheParserCannotReadIsRecordedNotDiscarded:
    """The family is derived from the ID, so a token nobody anticipated has
    two wrong answers available: drop it and two different models collapse
    into one family, or guess it is a version and order them wrongly. It joins
    the stem - which keeps IDs that share it together - and is listed in
    `unparsed`, which is what lets the parse be audited rather than trusted.
    """

    def test_an_unreadable_token_joins_the_stem_and_is_listed(self):
        parsed = ft.parse_model_id("vendor/model-Beta9X")
        assert "beta9x" in parsed.stem, (
            "the token was dropped, so this ID now shares a family with "
            "vendor/model")
        assert parsed.unparsed == ("beta9x",)
        assert parsed.version == (), "an unreadable token was read as a version"

    def test_an_ordinary_token_is_not_listed_as_unparsed(self):
        """Two-directional: a parser that listed everything would satisfy the
        test above and tell a reader nothing."""
        parsed = ft.parse_model_id("vendor/model-ABC")
        assert parsed.unparsed == ()
        assert "abc" in parsed.stem
