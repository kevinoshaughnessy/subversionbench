"""
The blackmail port with its reasoning replayed (scenarios/blackmail_replay.b64).

What matters: the bundle is the multi-turn port's in every entry but the one switch, so the arm
changes only what goes back to the model; the switch is on under this bundle alone, for a model
whose reasoning otherwise never goes back; none of its fingerprints is the port's, so its
episodes cannot pool with the port's; and the port's readers find it from its rollout version.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

from blackmail_port import judge_common as J
from subversionbench.scenario import load_scenario

SCENARIOS = Path("subversionbench/scenarios")
REPLAY, PORT = SCENARIOS / "blackmail_replay.b64", SCENARIOS / "blackmail.b64"
PROBE = ("import json; from subversionbench.openrouter_client import returns_reasoning; "
         "print(json.dumps([returns_reasoning(m) for m in ('moonshotai/kimi-k2.6', 'google/gemini-3.5-flash')]))")


def _under(bundle):
    env = {k: v for k, v in os.environ.items() if k != "SUBVERSIONBENCH_SCENARIO_BUNDLE"}
    if bundle:
        env["SUBVERSIONBENCH_SCENARIO_BUNDLE"] = str(bundle)
    out = subprocess.run([sys.executable, "-c", PROBE], capture_output=True, text=True,
                         encoding="utf-8", env=env, check=True)
    return json.loads(out.stdout.strip().splitlines()[-1])


def _fingerprints(bundle):
    with open(bundle.with_suffix(".pins.json"), encoding="utf-8") as f:
        pins = json.load(f)
    return {e["fingerprint"] for key in ("fingerprints", "variant_fingerprints", "capability_fingerprints")
            for e in pins.get(key, [])}


class TestTheArm:
    def test_it_is_the_port_in_every_entry_but_the_switch(self):
        replay, port = load_scenario(REPLAY), load_scenario(PORT)
        assert replay.pop("replay_reasoning") is True
        assert replay == port

    def test_the_switch_is_on_under_this_bundle_alone(self):
        assert _under(REPLAY) == [True, True]
        assert _under(PORT) == [False, True]
        assert _under(None) == [False, True]

    def test_no_fingerprint_is_the_ports(self):
        replay, port = _fingerprints(REPLAY), _fingerprints(PORT)
        assert len(replay) == len(port) == 4 and not replay & port

    def test_the_ports_readers_find_it_from_its_rollout(self):
        assert Path(J.bundle_path("blackmail_replay_r1")).resolve() == REPLAY.resolve()
