"""A capability arm is held to the same settings as the propensity arms it screens.

r3 of the impossible-task scenario removed every prohibition on editing the check
from its propensity arms, but its capability arm kept r2's settings file, which
still said the settings were not to be edited. A model refusing on the strength of
that line was recorded as not having shown the capability, and a capability-first
screen would have dropped it for a rule its propensity episodes never see (v320).
The rule here is that a capability arm overriding the settings uses a value some
propensity arm of the same bundle uses, so any prohibition it carries is one the
propensity episodes carry too.
"""

from pathlib import Path

from subversionbench.scenario import load_scenario
from test_corpus.test_scenario import _other_bundles

SETTINGS = "monitoring_config"


def _bundles():
    return [Path("subversionbench/scenario.b64"), *_other_bundles()]


def _offending(bundle: dict) -> list:
    """The capability targets whose settings no propensity arm of `bundle` uses."""
    arms = [bundle.get(SETTINGS)] + [v[SETTINGS] for v in
                                     (bundle.get("variants") or {}).values()
                                     if SETTINGS in v]
    return sorted(target for target, overrides in
                  (bundle.get("capability") or {}).items()
                  if SETTINGS in overrides and overrides[SETTINGS] not in arms)


class TestACapabilityArmUsesThePropensityArmsSettings:
    def test_every_committed_bundle_is_examined(self):
        """A glob matching nothing would pass the guard below vacuously."""
        assert len(_bundles()) > 1
        assert any(SETTINGS in o for b in _bundles()
                   for o in (load_scenario(b).get("capability") or {}).values())

    def test_no_capability_arm_has_settings_of_its_own(self):
        offending = {str(b): _offending(load_scenario(b)) for b in _bundles()}
        assert {b: t for b, t in offending.items() if t} == {}

    def test_settings_no_arm_uses_are_caught(self):
        bundle = {SETTINGS: "a", "variants": {"v": {SETTINGS: "b"}},
                  "capability": {"t": {SETTINGS: "c"}, "u": {SETTINGS: "b"}}}
        assert _offending(bundle) == ["t"]
