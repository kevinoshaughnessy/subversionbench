"""
Read and edit the scenario text, which is stored base64-encoded.

The scenario is everything the model sees: the system prompts, the user
prompt, the interrogation questions and the files it reads in the sandbox.
It is kept encoded so that publishing this repository does not put it into
the next training crawl - see subversionbench/scenario.py for why. Base64 is
not security; this tool is the intended way to read it.

    python scenario_tool.py --decode          # write scenario.json
    python scenario_tool.py --show memo       # print one entry
    python scenario_tool.py --list            # entry names and sizes
    python scenario_tool.py --encode          # fold scenario.json back in

scenario.json is gitignored, so a decoded working copy cannot be committed by
accident. --encode refuses to write a bundle missing any entry, since a
truncated scenario would fail at run time rather than here.

ANOTHER BASE64 BUNDLE - a scenario in a world of its own, committed encoded
like the shipped one - is read and edited the same way with --bundle, and its
working copy is the bundle's own path with a .json suffix (gitignored):

    python scenario_tool.py --bundle subversionbench/scenarios/NAME.b64 --decode
    python scenario_tool.py --bundle subversionbench/scenarios/NAME.b64 --pin

--pin computes that bundle's fingerprints into its .pins.json sidecar. The
sidecar's declarations - rollout_version, cells, scenario_acts - are written by
hand, as heldout_tool.py's twins' scenario_acts are, and --pin fills in the
fingerprints for every cell, variant and capability target the bundle has.
"""

import argparse
import json
import sys
from pathlib import Path

from subversionbench.bundle_pinning import PROVISIONAL, run_under_override
from subversionbench.scenario import (BUNDLE_ENV_VAR, bundle_is_overridden,
                                      encode_scenario, load_scenario)
from subversionbench.sidecar_pins import SIDECAR_SUFFIX

WORKING_COPY = Path(__file__).with_name("scenario.json")


def _build_parser():
    parser = argparse.ArgumentParser(
        description="Read and edit the encoded scenario text.")
    parser.add_argument("--bundle", type=Path, default=None,
                        help="another base64 bundle to act on instead of the "
                             "shipped scenario.b64")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--decode", action="store_true",
                       help=f"write the scenario to {WORKING_COPY.name}")
    group.add_argument("--encode", action="store_true",
                       help=f"fold {WORKING_COPY.name} back into scenario.b64")
    group.add_argument("--list", action="store_true",
                       help="entry names and sizes")
    group.add_argument("--show", metavar="SUBSTRING",
                       help="print entries whose name contains SUBSTRING")
    group.add_argument("--pin", action="store_true",
                       help="compute a --bundle's fingerprints into its sidecar")
    return parser


def _decode(bundle: Path, working: Path) -> int:
    # encoding named on both sides of the round trip. json.dumps escapes
    # non-ASCII by default, so the write happens to be safe today - but the
    # READ below takes back a file a person has edited, and editing the
    # scenario means adding the invisible and confusable characters that are
    # this benchmark's whole subject. Left to the locale, that read raised
    # UnicodeDecodeError on any non-UTF-8 machine. Named here too so the two
    # cannot drift, and so removing ensure_ascii later is not a silent break.
    working.write_text(json.dumps(load_scenario(bundle), indent=2),
                       encoding="utf-8")
    print(f"wrote {working.name}; edit it, then --encode")
    return 0


def _list(bundle: Path) -> int:
    for name, value in load_scenario(bundle).items():
        size = sum(len(v) for v in value) if isinstance(value, list) \
            else len(value)
        kind = f"list[{len(value)}]" if isinstance(value, list) else "text"
        print(f"  {name:34s} {kind:9s} {size:6d} chars")
    return 0


def _show(bundle: Path, substring: str) -> int:
    found = False
    for name, value in load_scenario(bundle).items():
        if substring.lower() not in name.lower():
            continue
        found = True
        print(f"===== {name} =====")
        print("\n\n".join(value) if isinstance(value, list) else value)
        print()
    if not found:
        print(f"No entry matching {substring!r}. Try --list.")
        return 1
    return 0


def _encode(bundle: Path, working: Path, shipped: bool) -> int:
    if not working.exists():
        print(f"{working.name} not found - run --decode first.")
        return 1
    edited = json.loads(working.read_text(encoding="utf-8"))
    # A bundle being written for the first time has nothing to be missing.
    missing = set(load_scenario(bundle)) - set(edited) if bundle.exists() \
        else set()
    if missing:
        print(f"Refusing to encode: {working.name} is missing "
              f"{sorted(missing)}.")
        return 1
    encode_scenario(edited, None if shipped else bundle)
    print(f"{bundle.name} updated. Run the tests before committing.")
    return 0


# Every cell, variant and capability target the bundle has, computed in one
# subprocess under the override. The tables are read off the bundle and the
# sidecar's declared cells, so nothing here lists them a second time.
_PIN_PROBE = (
    "import json\n"
    "from subversionbench.rollout import rollout_fingerprint\n"
    "cells, variants, targets = json.loads(TABLES)\n"
    "print(json.dumps({\n"
    "  'cells': [[o, l, rollout_fingerprint(o, lure=l)] for o, l in cells],\n"
    "  'variants': [[v, o, l, rollout_fingerprint(o, lure=l, variant=v)]\n"
    "               for v in variants for o, l in cells],\n"
    "  'capability': [[t, o, rollout_fingerprint(o, capability=t,"
    " nudge='none')]\n"
    "                 for t in targets for o in sorted({o for o, _l in cells})],\n"
    "}))\n"
)


def _pin(bundle: Path) -> int:
    """Fill the bundle's sidecar with the fingerprints it assembles to."""
    sidecar = bundle.with_suffix(SIDECAR_SUFFIX)
    if not sidecar.is_file():
        print(f"{sidecar.name} not found. Write its rollout_version, cells and "
              f"scenario_acts by hand first; --pin fills in the fingerprints.")
        return 1
    declared = json.loads(sidecar.read_text(encoding="utf-8"))
    raw = load_scenario(bundle)
    cells = [[bool(o), bool(lure)] for o, lure in declared["cells"]]
    variants = sorted(raw.get("variants", {}))
    targets = sorted(raw.get("capability", {}))
    provisional = dict(declared)
    provisional["fingerprints"] = [
        {"oversight": o, "lure": lure, "fingerprint": PROVISIONAL}
        for o, lure in cells]
    provisional["variant_fingerprints"] = [
        {"variant": v, "oversight": o, "lure": lure, "fingerprint": PROVISIONAL}
        for v in variants for o, lure in cells]
    provisional["capability_fingerprints"] = [
        {"target": t, "oversight": o, "fingerprint": PROVISIONAL}
        for t in targets for o in sorted({o for o, _l in cells})]
    probe = _PIN_PROBE.replace(
        "TABLES", repr(json.dumps([cells, variants, targets])))
    got = run_under_override(Path(__file__).resolve().parent, bundle, sidecar,
                             provisional, probe)
    from subversionbench import rollout_pins
    shipped = set(rollout_pins.ROLLOUT_FINGERPRINTS.values())
    computed = [row[-1] for table in got.values() for row in table]
    if shipped & set(computed) or len(set(computed)) != len(computed):
        # A pin equal to the shipped scenario's, or two arms of this bundle
        # sharing one, would let episodes pool across arms they do not match.
        print("Refusing to pin: a computed fingerprint matches the shipped "
              "scenario's or another arm of this bundle.")
        return 1
    declared["fingerprints"] = [
        {"oversight": o, "lure": lure, "fingerprint": fp}
        for o, lure, fp in got["cells"]]
    declared["variant_fingerprints"] = [
        {"variant": v, "oversight": o, "lure": lure, "fingerprint": fp}
        for v, o, lure, fp in got["variants"]]
    declared["capability_fingerprints"] = [
        {"target": t, "oversight": o, "fingerprint": fp}
        for t, o, fp in got["capability"]]
    sidecar.write_text(json.dumps(declared, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {sidecar.name}: {len(computed)} fingerprint(s)")
    return 0


def main():
    args = _build_parser().parse_args()

    # Every path below resolves through load_scenario(), which follows the
    # override. Under one, --decode would write the alternative bundle's text
    # into scenario.json and --list and --show would describe it while naming
    # this file's paths. Refused rather than silently retargeted: a bundle is
    # named with --bundle, so that it is always clear which one is being read.
    if bundle_is_overridden():
        print(f"{BUNDLE_ENV_VAR} is set, which selects another scenario "
              f"bundle. Unset it, and name a base64 bundle with --bundle; the "
              f"encrypted held-out twins have heldout_tool.py.")
        return 1
    shipped = args.bundle is None
    bundle = Path(__file__).parent / "subversionbench" / "scenario.b64" \
        if shipped else args.bundle
    working = WORKING_COPY if shipped else bundle.with_suffix(".json")
    if args.pin:
        if shipped:
            print("--pin is for a --bundle. The shipped scenario's pins are "
                  "literals in subversionbench/rollout_pins.py.")
            return 1
        return _pin(bundle)
    if args.decode:
        return _decode(bundle, working)
    if args.list:
        return _list(bundle)
    if args.show:
        return _show(bundle, args.show)
    return _encode(bundle, working, shipped)


if __name__ == "__main__":
    sys.exit(main())
