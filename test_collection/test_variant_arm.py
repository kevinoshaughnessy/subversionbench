"""A bundle's named variants: assembly, batch identity and the collection census.

The shipped scenario defines none, so every behaviour here is checked on a
synthetic bundle, plus the shipped bundle's refusal."""

import tempfile
from pathlib import Path

from subversionbench.batch import (NO_ARM, BatchIdentity, arm_run_file_census,
                                   parse_batch_filename, variant_from_filename)
from subversionbench.scenario import scenario_for, variant_names

BUNDLE = {"user_prompt": "base prompt", "doc": "base doc", "other": "same",
          "variants": {"v1": {"doc": "variant doc"},
                       "v2": {"doc": "second doc", "other": "changed"}}}


class TestAssembly:
    def test_the_control_assembles_from_the_base_alone(self):
        """Popped unconditionally, so the control's identity does not depend
        on the text of the variants beside it."""
        assert scenario_for(True, bundle=dict(BUNDLE)) == {
            k: v for k, v in BUNDLE.items() if k != "variants"}

    def test_a_variant_replaces_only_its_own_entries(self):
        arm = scenario_for(True, bundle=dict(BUNDLE), variant="v1")
        assert arm["doc"] == "variant doc"
        assert arm["other"] == "same" and arm["user_prompt"] == "base prompt"
        assert "variants" not in arm

    def test_an_unknown_variant_is_refused_rather_than_run_as_the_control(self):
        for bundle in (dict(BUNDLE), None):
            try:
                scenario_for(True, bundle=bundle, variant="nope")
            except KeyError as e:
                assert "nope" in str(e)
            else:
                raise AssertionError("an unknown variant assembled")

    def test_the_shipped_scenario_defines_no_variants(self):
        assert variant_names() == ()


class TestBatchIdentity:
    def _id(self, variant):
        return BatchIdentity(model="org/m", model_slug="org_m", nudge="none",
                             stamp="20261022T000000", variant=variant)

    def test_a_variant_marks_the_name_and_the_control_keeps_the_bare_one(self):
        assert "_variant-v1" in self._id("v1").stem
        assert self._id(None).stem == BatchIdentity(
            model="org/m", model_slug="org_m", nudge="none").stem

    def test_the_variant_reads_back_and_leaves_the_other_fields_alone(self):
        """With a capability mark to its LEFT, so a parser that stopped at an
        unstripped variant segment would lose a field rather than pass."""
        for variant in ("v1", "two-part", None):
            ident = BatchIdentity(model="org/m", model_slug="org_m",
                                  nudge="none", stamp="20261022T000000",
                                  oversight=False, lure=True,
                                  capability="oversight", variant=variant)
            path = ident.filename("d", "run_3")
            assert variant_from_filename(path) == variant
            assert parse_batch_filename(path, "none") == (
                None, "20261022T000000", False, True, "oversight")

    def test_the_census_counts_each_variant_apart_from_the_control(self):
        out = Path(tempfile.mkdtemp())
        for variant, n in ((None, 2), ("v1", 3)):
            for i in range(n):
                (out / Path(self._id(variant).filename("", f"run_{i + 1}")
                            ).name).write_text("{}")
        count = lambda v: arm_run_file_census(  # noqa: E731
            str(out), "org/m", "none", "true", "false", NO_ARM, v)[0]
        assert (count(NO_ARM), count("v1"), count("v2")) == (2, 3, 0)
