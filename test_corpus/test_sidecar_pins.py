"""The sidecar rules a bundle in a world of its own adds: declared cells, variant
pins and capability pins. The held-out twins' rules - every cell or none, no
shared version, the act set - are in test_heldout_scenario.py."""

import json
import tempfile
from pathlib import Path
from unittest import mock

from subversionbench import rollout_pins, sidecar_pins
from test_corpus.heldout_fixtures import overridden

SHIPPED = (rollout_pins.ROLLOUT_VERSION, rollout_pins.ROLLOUT_FINGERPRINTS,
           rollout_pins.SCENARIO_ACTS)


def _staged(declared: dict) -> Path:
    """A bundle path with `declared` as its sidecar."""
    bundle = Path(tempfile.mkdtemp()) / "alt.b64"
    bundle.write_text("", encoding="utf-8")
    bundle.with_suffix(".pins.json").write_text(json.dumps(declared),
                                                encoding="utf-8")
    return bundle


def _raises(exc, fn, *args):
    try:
        fn(*args)
    except exc as e:
        return str(e)
    raise AssertionError(f"{fn.__name__} accepted what it should refuse")


ONE_CELL = {"rollout_version": "world-test", "cells": [[True, False]],
            "fingerprints": [{"oversight": True, "lure": False,
                              "fingerprint": "a" * 12}]}


class TestDeclaredCells:
    def test_a_bundle_may_pin_only_the_cells_it_declares(self):
        with overridden(_staged(ONE_CELL)):
            _version, pins, _acts = sidecar_pins.alternative_pins(*SHIPPED)
        assert set(pins) == {(True, False)}

    def test_without_cells_every_shipped_cell_is_still_required(self):
        """The twins' rule is the default, so no sidecar written before the
        field existed is read any differently."""
        declared = {k: v for k, v in ONE_CELL.items() if k != "cells"}
        with overridden(_staged(declared)):
            msg = _raises(ValueError, sidecar_pins.alternative_pins, *SHIPPED)
        assert "unpinned" in msg

    def test_a_declared_cell_left_unpinned_is_refused(self):
        declared = dict(ONE_CELL, cells=[[True, False], [False, False]])
        with overridden(_staged(declared)):
            assert "unpinned" in _raises(
                ValueError, sidecar_pins.alternative_pins, *SHIPPED)

    def test_a_pin_for_an_undeclared_cell_is_refused(self):
        declared = dict(ONE_CELL, fingerprints=ONE_CELL["fingerprints"] + [
            {"oversight": False, "lure": False, "fingerprint": "b" * 12}])
        with overridden(_staged(declared)):
            assert "does not declare" in _raises(
                ValueError, sidecar_pins.alternative_pins, *SHIPPED)

    def test_no_cells_and_unknown_cells_are_refused(self):
        for cells in ([], [[True, False], ["sideways", 3]]):
            with overridden(_staged(dict(ONE_CELL, cells=cells))):
                _raises(ValueError, sidecar_pins.alternative_pins, *SHIPPED)


class TestVariantAndCapabilityPins:
    def test_every_variant_the_bundle_defines_must_be_pinned(self):
        declared = dict(ONE_CELL, variant_fingerprints=[
            {"variant": "v1", "oversight": True, "lure": False,
             "fingerprint": "c" * 12}])
        names = "subversionbench.scenario.variant_names"
        with overridden(_staged(declared)):
            with mock.patch(names, return_value=("v1",)):
                pins = sidecar_pins.alternative_variant_pins()
            assert pins == {("v1", True, False): "c" * 12}
            with mock.patch(names, return_value=("v1", "v2")):
                assert "v2" in _raises(
                    ValueError, sidecar_pins.alternative_variant_pins)

    def test_the_shipped_bundle_has_no_variant_or_capability_pins(self):
        with overridden(None):
            assert sidecar_pins.alternative_variant_pins() == {}
            assert sidecar_pins.alternative_capability_pins() is None
        assert rollout_pins.VARIANT_FINGERPRINTS == {}
        _raises(KeyError, rollout_pins.variant_fingerprint_for, "any", True)

    def test_a_twin_without_capability_pins_reads_as_none(self):
        """None, not {}: capability_fingerprint_for refuses a twin rather than
        stamping the shipped scenario's capability identity on it."""
        with overridden(_staged(ONE_CELL)):
            assert sidecar_pins.alternative_capability_pins() is None
        declared = dict(ONE_CELL, capability_fingerprints=[
            {"target": "oversight", "oversight": True, "fingerprint": "d" * 12}])
        with overridden(_staged(declared)):
            assert sidecar_pins.alternative_capability_pins() == {
                ("oversight", True): "d" * 12}
