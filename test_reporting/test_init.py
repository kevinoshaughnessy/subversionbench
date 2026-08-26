"""
The reporting package's surface: what the rest of the codebase may reach for.

The three layers behind it are computation (facts/), formatting (console.py) and
persistence (summary.py), and the boundary between them is the reason the split
exists. This file pins the surface so a caller cannot reach past it into a layer
that is meant to be private - which is how the figures ended up interleaved with
the printing in the first place.
"""

import subversionbench.reporting as reporting


class TestTheSurfaceIsExactlyWhatIsDeclared:
    def test_every_name_in_all_is_importable(self):
        for name in reporting.__all__:
            assert hasattr(reporting, name), name

    def test_all_is_sorted_and_unique(self):
        """A list that has to be read to be extended stays readable only if it is
        ordered. Duplicates hide a name that was added twice and removed once."""
        assert reporting.__all__ == sorted(reporting.__all__)
        assert len(reporting.__all__) == len(set(reporting.__all__))

    def test_it_exports_one_name_per_layer_and_no_more(self):
        """Computation, formatting, persistence. A fourth kind of thing appearing
        here means the package grew a responsibility."""
        assert "batch_facts" in reporting.__all__
        assert "render_report" in reporting.__all__
        assert "summarise_batch" in reporting.__all__

    def test_the_internal_construct_modules_are_not_re_exported(self):
        """facts/ is split by construct - misalignment, scheming, awareness - and
        those are composed by batch_facts. A caller importing one directly through
        this package would be assembling its own subset of the figures."""
        for private in ("misalignment_facts", "scheming_facts", "awareness_facts",
                        "quality_facts", "timing_facts", "rate_table"):
            assert private not in reporting.__all__, (
                f"{private} is an internal step of batch_facts; exporting it "
                f"invites a second, partial assembly of the figures")


class TestTheLayersStayApart:
    def test_the_console_is_not_reachable_as_a_computation(self):
        """render_report takes finished figures. If it were exported alongside a
        way to build partial ones, the two could be combined into a report over
        figures no summary was ever written from."""
        import inspect
        params = list(inspect.signature(reporting.render_report).parameters)
        assert params[0] == "facts"

    def test_normalise_runs_before_facts_are_computed(self):
        """Both are exported, and the order matters: batch_facts reads settled
        analyses. Exported together so a caller cannot get one without seeing the
        other exists."""
        assert "normalise_analyses" in reporting.__all__
        assert "batch_facts" in reporting.__all__
