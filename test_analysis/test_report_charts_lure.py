"""
The lure arm's two charts, and the arm-exclusion rules every chart obeys.

Together because they are the same subject from two sides: the lure charts are
the only ones split by oversight stratum, which is what makes an exclusion
apply to a PANEL here rather than to a whole figure.
"""


import os
import tempfile

import report_charts as rc
from subversionbench.power import MIN_INFORMATIVE_DENOMINATOR
from test_analysis.chart_fixtures import (
    _epr_profile, _epr_row, _excluded_stamp,
    _lure_model_row, _plt, _section)


class TestTheLureForestFoldsOnlyTheModelsWithNothingToMove:
    """The fold is narrowly "zero misaligned on BOTH sides", not "difference of
    zero". Those are different findings and one of them belongs on the chart."""

    def test_a_model_with_no_misalignment_either_side_is_folded(self):
        rows = rc._lure_effect_rows(
            {"by_model": [_lure_model_row("p/quiet", 30, 30, 0, 0)]},
            "oversight")
        assert [r.label for r in rows] == ["(1 models omitted)"]
        assert rows[0].diff is None, (
            "a folded group must not be drawn as a marker at zero - it is not "
            "a data point")

    def test_a_high_base_rate_null_is_KEPT(self):
        """24/30 in both arms is a genuine null at a high base rate, and the
        most informative null in the set. Folding it away with the models that
        never did anything would hide it."""
        rows = rc._lure_effect_rows(
            {"by_model": [_lure_model_row("p/busy", 30, 30, 24, 24)]},
            "oversight")
        assert [r.label for r in rows] == ["p/busy"]
        assert rows[0].diff == 0

    def test_the_two_are_distinguished_in_one_chart(self):
        rows = rc._lure_effect_rows(
            {"by_model": [_lure_model_row("p/quiet", 30, 30, 0, 0),
                          _lure_model_row("p/busy", 30, 30, 24, 24)]},
            "oversight")
        labels = [r.label for r in rows]
        assert "p/busy" in labels and "p/quiet" not in labels
        assert "(1 models omitted)" in labels

    def test_the_floor_applies_to_the_thinner_arm(self):
        """A difference is only as informative as its thinner side, so a model
        with plenty of lure episodes and almost none without is not plotted."""
        thin = _lure_model_row("p/lopsided", 200, MIN_INFORMATIVE_DENOMINATOR - 1,
                               10, 1)
        assert rc._lure_effect_rows({"by_model": [thin]},
                                               "oversight") == []
        fat = _lure_model_row("p/balanced", 200, MIN_INFORMATIVE_DENOMINATOR,
                              10, 1)
        assert [r.label for r in rc._lure_effect_rows(
            {"by_model": [fat]}, "oversight")] == ["p/balanced"]

    def test_a_marker_is_filled_only_when_its_interval_excludes_zero(self):
        moved = _lure_model_row("p/moved", 40, 40, 20, 0)
        flat = _lure_model_row("p/flat", 40, 40, 4, 3)
        rows = {r.label: r for r in rc._lure_effect_rows(
            {"by_model": [moved, flat]}, "oversight")}
        assert rows["p/moved"].marked
        assert not rows["p/flat"].marked

    def test_rows_are_sorted_by_the_difference(self):
        rows = rc._lure_effect_rows(
            {"by_model": [_lure_model_row("p/down", 40, 40, 2, 12),
                          _lure_model_row("p/up", 40, 40, 12, 2)]},
            "oversight")
        assert [r.label for r in rows] == ["p/up", "p/down"]


class TestTheHoneypotChartShowsOnlyWhatHappened:
    def _profile(self):
        rows = [_lure_model_row(f"p/m{i}", 30, 30, 1, 1) for i in range(5)]
        rows[0]["n_discovered"], rows[0]["n_read"] = 7, 3
        rows[1]["n_discovered"], rows[1]["n_read"] = 2, 0
        rows[2]["n_discovered"], rows[2]["n_read"] = 0, 1
        return {"by_model": rows,
                "pooled": {"n_lure_resolved": 150, "n_discovered": 9,
                           "n_read": 4}}

    def test_only_models_that_reached_it_are_rowed(self):
        rows = rc._honeypot_rows(self._profile())
        assert [r["model"] for r in rows] == ["p/m0", "p/m1", "p/m2"]

    def test_a_read_without_a_discovery_still_appears(self):
        """Measured on the corpus: an episode can glob the contents without the
        filename ever being listed, so a row must not be gated on discovery."""
        rows = rc._honeypot_rows(self._profile())
        assert any(r["model"] == "p/m2" and r["n_read"] for r in rows)

    def test_it_renders_and_states_how_many_models_are_not_drawn(self):
        plt = _plt()
        out = os.path.join(tempfile.mkdtemp(), "honeypot.png")
        assert rc.plot_honeypot_access(
            plt, {"characteristics": {"lure_effect": self._profile()}}, out)
        assert os.path.getsize(out) > 1000

    def test_nothing_is_drawn_when_no_model_reached_it(self):
        """An empty chart claiming a measure was taken is worse than no chart."""
        plt = _plt()
        profile = self._profile()
        for r in profile["by_model"]:
            r["n_discovered"] = r["n_read"] = 0
        out = os.path.join(tempfile.mkdtemp(), "honeypot.png")
        assert rc.plot_honeypot_access(
            plt, {"characteristics": {"lure_effect": profile}}, out) is None

    def test_the_misalignment_chart_writes_one_file_per_stratum(self):
        plt = _plt()
        rows = [_lure_model_row(f"p/m{i}", 40, 40, i + 1, 1) for i in range(4)]
        out = os.path.join(tempfile.mkdtemp(), "lure_misalignment.png")
        assert rc.plot_lure_misalignment(
            plt, {"characteristics": {"lure_effect": {"by_model": rows,
                  "pooled": {"oversight": rows[0]["oversight"],
                             "no_oversight": rows[0]["no_oversight"]}}}}, out)
        assert os.path.exists(out)
        assert os.path.exists(out.replace(".png", "_no_oversight.png")), (
            "the no-oversight stratum must get its own file - the two strata "
            "carry opposite signs and cannot share a panel")


class TestEveryChartSaysWhichArmsItCovers:
    def _plot_functions(self):
        """Every chart entry point this module offers, from the module itself.

        DERIVED, AND ASSERTED NON-EMPTY. A hand-written list of the charts is
        the defect class this repository keeps re-fixing: the grading package's
        guards enumerated their own submodules in a tuple, fell two behind the
        directory, and four guards silently stopped covering two modules. A glob
        that matches nothing empties the scope and every guard built on it
        passes, so the count is checked before it is used.
        """
        import inspect
        # `startswith`, not `==`: the charts live in submodules of the
        # package and the facade re-exports them, so a function's __module__ is
        # `report_charts.questions` rather than `report_charts`. Comparing for
        # equality emptied this scope the moment the file became a package,
        # which is the failure this assertion's own docstring warns about.
        found = {name: obj for name, obj in vars(rc).items()
                 if name.startswith("plot_") and inspect.isfunction(obj)
                 and obj.__module__.startswith(rc.__name__)}
        assert len(found) >= 7, (
            f"only found {sorted(found)} - the enumeration is broken, and an "
            f"empty scope makes every assertion below vacuous")
        return found

    def test_every_chart_names_the_exclusion_in_its_title_and_captions(self):
        """The rule, not a path. Any chart added later inherits this: it is
        enumerated from the module rather than listed here, so a new plot_
        function that forgets the words fails this test rather than shipping a
        figure indistinguishable from the full-corpus one of the same name."""
        import inspect
        for name, func in self._plot_functions().items():
            source = inspect.getsource(func)
            assert "_exclusion_title_suffix" in source, (
                f"{name} does not put the exclusion in its title, so the "
                f"figure cannot be told from the full-corpus chart of the "
                f"same filename once it leaves its directory")
            assert "_exclusion_captions" in source, (
                f"{name} draws no caption naming the excluded arm")

    def test_nothing_is_said_when_no_arm_was_excluded(self):
        """The ordinary report must not grow a banner reading "nothing
        excluded": a reader trained to skip that block skips it on the one
        chart where it matters."""
        for report in ({}, {"arm_exclusion": None},
                       {"arm_exclusion": {"axis": None, "words": ""}}):
            assert rc._exclusion_title_suffix(report) == ""
            assert rc._exclusion_captions(report) == []

    def test_the_words_and_the_counts_reach_the_reader(self):
        report = {"arm_exclusion": _excluded_stamp(kept=120, before=240)}
        assert "no-oversight arm excluded" in rc._exclusion_title_suffix(report)
        text = " ".join(c for c, _ in rc._exclusion_captions(report))
        assert "no-oversight arm excluded" in text
        # The counts, so a reader can see how much of the corpus is behind the
        # figure without opening the JSON.
        assert "120 of 240" in text
        # And that this is not a repaired estimate.
        assert "sensitivity" in text.lower()
        assert "not a correction" in text.lower()

    def test_the_caption_is_drawn_in_the_warning_colour(self):
        """Same colour this module already reserves for the crude-vs-stratified
        divergence, because it is the same class of statement: something a
        reader who stops at the markers would take the chart to mean."""
        captions = rc._exclusion_captions(
            {"arm_exclusion": _excluded_stamp()})
        assert captions[0][1] == "#b00020"

    def test_a_question_the_exclusion_collapsed_draws_no_chart(self):
        """A forest of thirty "no data on one side" rows under the question's
        own title reads as a measured null rather than an absent comparison."""
        plt = _plt()
        section = _section()
        section["collapsed_by_exclusion"] = "not estimable with the arm excluded"
        out = os.path.join(tempfile.mkdtemp(), "q.png")
        assert rc.plot_question(plt, 1, section, out,
                                {"arm_exclusion": _excluded_stamp()}) is None
        assert not os.path.exists(out)

    def test_the_same_question_still_draws_when_nothing_collapsed(self):
        """The positive control: without the mark the chart renders, so the
        test above is about the mark and not about the fixture."""
        plt = _plt()
        out = os.path.join(tempfile.mkdtemp(), "q.png")
        assert rc.plot_question(plt, 1, _section(), out,
                                {"arm_exclusion": _excluded_stamp()})
        assert os.path.getsize(out) > 1000

    def test_the_overview_keeps_a_row_for_a_collapsed_question(self):
        """Dropped rather than marked, this chart would show nine questions
        while its own caption calls it all twelve - and a reader would conclude
        the three were never asked."""
        plt = _plt()
        collapsed = _section(id="oversight_vs_scheming")
        collapsed["collapsed_by_exclusion"] = "no comparator"
        report = {"questions": [collapsed,
                                _section(id="awareness_vs_scheming")],
                  "arm_exclusion": _excluded_stamp()}
        captured = {}
        original = rc.draw._draw_forest

        def capture(plt_, rows, title, captions, path, *a, **kw):
            captured["rows"] = rows
            captured["title"] = title
            return path

        rc.draw._draw_forest = capture
        try:
            rc.plot_overview(plt, report, os.path.join(tempfile.mkdtemp(), "o.png"))
        finally:
            rc.draw._draw_forest = original
        labels = [r.label for r in captured["rows"]]
        assert len(labels) == 2, labels
        gap = [r for r in captured["rows"] if r.diff is None]
        assert len(gap) == 1 and "excluded arm" in gap[0].missing
        assert "no-oversight arm excluded" in captured["title"]

    def test_the_excluded_arms_own_lure_panel_is_not_drawn(self):
        """`lure_effect` is already split on oversight, so the excluded panel
        normally has no rows and falls out. This is the other case: a stratum
        left with rows from an arm the report says it dropped, which would draw
        a panel titled "no oversight" inside an oversight-only reading."""
        plt = _plt()
        rows = [_lure_model_row(f"p/m{i}", 40, 40, i + 1, 1) for i in range(4)]
        profile = {"by_model": rows,
                   "pooled": {"oversight": rows[0]["oversight"],
                              "no_oversight": rows[0]["no_oversight"]}}
        out = os.path.join(tempfile.mkdtemp(), "lure_misalignment.png")
        assert rc.plot_lure_misalignment(
            plt, {"characteristics": {"lure_effect": profile},
                  "arm_exclusion": _excluded_stamp()}, out)
        assert os.path.exists(out)
        assert not os.path.exists(out.replace(".png", "_no_oversight.png")), (
            "the no-oversight panel was drawn inside a report whose every "
            "other figure says that arm was excluded")

    def test_the_stratum_match_is_by_name_against_the_excluded_level(self):
        """Both directions, so the helper cannot pass by always answering one
        way: with the no-oversight arm dropped it is the `no_oversight` panel
        that goes, and with the oversight arm dropped it is the other."""
        drop_no_oversight = {"arm_exclusion": _excluded_stamp()}
        assert rc._excluded_stratum(drop_no_oversight, "no_oversight")
        assert not rc._excluded_stratum(drop_no_oversight, "oversight")
        flipped = {"arm_exclusion": dict(_excluded_stamp(),
                                         excluded_level=True)}
        assert rc._excluded_stratum(flipped, "oversight")
        assert not rc._excluded_stratum(flipped, "no_oversight")
        assert not rc._excluded_stratum({}, "no_oversight")


class TestWriteChartsCollectsEveryFileItActuallyWrote:
    """write_charts returns the list the report then names in its JSON and the
    console prints. A chart drawn and left out of that list is a file nobody
    is told about; a name in the list with no file behind it sends a reader to
    a path that does not exist. Both are silent, so each chart the collector
    handles is asserted against the control that must NOT produce it.

    The lure entry is the one with a rule rather than a name: it writes one
    file per oversight stratum and returns only the first, so the second is
    collected by asking the filesystem. Testing it means running it with two
    strata and with one.
    """

    def _characteristics(self):
        rows = [_lure_model_row("p/busy", 30, 30, 24, 24),
                _lure_model_row("p/moved", 40, 40, 20, 0)]
        rows[0]["n_discovered"], rows[0]["n_read"] = 7, 3
        return {
            "encoded_payload_rate": _epr_profile(
                [_epr_row("p/a", 61, 1, underpowered=False),
                 _epr_row("p/b", 60, 12, underpowered=False)]),
            "lure_effect": {
                "by_model": rows,
                "pooled": {"n_lure_resolved": 70, "n_discovered": 7,
                           "n_read": 3,
                           "oversight": {"diff": 0.01},
                           "no_oversight": {"diff": 0.02}},
            },
        }

    def _written(self, report):
        _plt()
        with tempfile.TemporaryDirectory() as out:
            written = rc.write_charts(report, out)
            on_disk = set(os.listdir(out))
        names = [os.path.basename(p) for p in written]
        assert len(names) == len(set(names)), f"a chart was listed twice: {names}"
        for name in names:
            assert name in on_disk, (
                f"{name} was returned but never written to disk")
        return names

    def test_the_encoded_payload_chart_is_collected(self):
        names = self._written({"questions": [],
                               "characteristics": self._characteristics()})
        assert "encoded_payload_rate.png" in names

    def test_the_honeypot_chart_is_collected(self):
        names = self._written({"questions": [],
                               "characteristics": self._characteristics()})
        assert "honeypot_access.png" in names

    def test_both_lure_strata_are_collected_not_just_the_returned_one(self):
        """plot_lure_misalignment writes a file per stratum and returns the
        first. The second exists on disk either way - the failure this catches
        is it going unmentioned, so the report's own list of charts is short
        by a figure a reader is meant to read alongside the other."""
        names = self._written({"questions": [],
                               "characteristics": self._characteristics()})
        assert "lure_misalignment.png" in names
        assert "lure_misalignment_no_oversight.png" in names

    def test_an_excluded_stratum_contributes_no_second_file(self):
        """Two-directional against the test above: the second file is
        collected because it was written, not because its name was assumed."""
        names = self._written({
            "questions": [], "characteristics": self._characteristics(),
            "arm_exclusion": _excluded_stamp()})
        assert "lure_misalignment.png" in names
        assert "lure_misalignment_no_oversight.png" not in names

    def test_none_of_them_appear_without_the_characteristics_behind_them(self):
        """The control for all four. Without it every assertion above would
        pass against a write_charts that returned every name unconditionally."""
        names = self._written({"questions": [_section()]})
        for absent in ("encoded_payload_rate.png", "honeypot_access.png",
                       "lure_misalignment.png",
                       "lure_misalignment_no_oversight.png"):
            assert absent not in names
