"""
Read, edit and pin the held-out scenario, which is stored encrypted.

The held-out scenario is a reworded twin of the shipped one: same acts, same
arms, same mechanism, different surface text. It exists to ask whether a rate
this benchmark reports survives a change that carries no semantic content - so
its value depends entirely on it never having been published. The bundle, the
decrypted copy the harness reads, its rollout pins and its transcripts are all
gitignored.

Encrypted rather than base64, which is the one place it departs from
scenario.b64. That bundle is committed encoded because it has to stay readable
by anyone auditing the benchmark and the encoding is an honest speed bump for a
training crawler. This one is the control and is never published at all, so the
authentication is what earns its place: a truncated or hand-edited bundle says
so, instead of decoding to bytes that happen not to be JSON hours into a batch.
The passphrase is sad_oversight.py's published barrier phrase - a crawler
barrier, not a secret, and deliberately not a new credential to manage.

    python heldout_tool.py --decode     # write the editable working copy
    python heldout_tool.py --show memo  # print one entry
    python heldout_tool.py --list       # entry names and sizes
    python heldout_tool.py --encode     # fold the working copy back in
    python heldout_tool.py --check      # run the bundle's invariants
    python heldout_tool.py --pin        # compute its rollout fingerprints
    python heldout_tool.py --export     # decrypt for a run, and print the path

--encode refuses a bundle missing any entry the shipped one has, and refuses
one that fails the invariants, restoring what was there. Either would fail at
run time rather than here.

TO COLLECT UNDER IT, see run_heldout.sh, which does --export, points
SUBVERSIONBENCH_SCENARIO_BUNDLE at the result, and removes the plaintext after.
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from sad_oversight import encrypt, decrypt          # noqa: E402
from subversionbench.rollout_pins import _PINS_SIDECAR_SUFFIX  # noqa: E402
from subversionbench.scenario import load_scenario  # noqa: E402

HELDOUT_DIR = ROOT / "heldout"
BUNDLE_PATH = HELDOUT_DIR / "scenario_heldout.enc"
WORKING_COPY = HELDOUT_DIR / "scenario_heldout.json"
PINS_PATH = BUNDLE_PATH.with_suffix(_PINS_SIDECAR_SUFFIX)
TESTS = ROOT / "test_corpus" / "test_heldout_scenario.py"

# What the held-out rollout calls itself. NOT "r9", and rollout_pins refuses a
# sidecar that claims to be: sharing a rollout version is what makes two
# rollouts indistinguishable. Numbered so a later reword is a later rollout
# rather than a silent redefinition of this one.
ROLLOUT_VERSION = "heldout1"


def load_heldout(path: Path = None) -> dict:
    """The decrypted held-out bundle."""
    return decrypt((path or BUNDLE_PATH).read_text(encoding="utf-8"))


def _invariants_hold() -> bool:
    """The tracked test, as a subprocess, so the assertions live in one file.

    Deliberately not a second implementation of the invariants. The previous
    arrangement had a standalone checker beside the bundle, which meant the
    rules existed twice and could disagree about which was authoritative.
    """
    result = subprocess.run(
        [sys.executable, "-m", "pytest", str(TESTS), "-q"],
        cwd=ROOT, capture_output=True, text=True)
    print(result.stdout.strip().splitlines()[-1] if result.stdout.strip()
          else "(no output from pytest)")
    if result.returncode:
        print(result.stdout.rstrip())
    return result.returncode == 0


# Fingerprints for the provisional sidecar that breaks the pinning cycle
# below. Not hex, so they can never equal a real fingerprint: if --pin is
# interrupted and one is left behind, the drift guard refuses to start rather
# than letting a batch collect against pins nothing produced.
_PROVISIONAL = "PROVISIONAL-"

_FINGERPRINT_PROBE = (
    "import json\n"
    "from subversionbench.rollout import rollout_fingerprint\n"
    "print(json.dumps([[o, lure, rollout_fingerprint(o, lure=lure)]\n"
    "                  for o in (True, False) for lure in (True, False)]))\n"
)


def _fingerprints(bundle_for_run: Path) -> dict:
    """
    The four arm fingerprints this bundle produces, computed UNDER the override.

    NOT by patching rollout.scenario_for in an un-overridden process. That was
    the first implementation and it was wrong: the fingerprint covers the
    sandbox display path and the task file's name as well as the scenario text,
    and both are derived from the bundle at import - so patching only
    scenario_for mixed the held-out documents with the shipped scenario's paths
    and produced four fingerprints no run would ever reproduce. Measured rather
    than reasoned about: all four disagreed with the real ones, and the drift
    guard refused every arm.

    So pinning has to run with SUBVERSIONBENCH_SCENARIO_BUNDLE set - and
    rollout_pins refuses to import under it without the very sidecar this
    writes. A provisional sidecar breaks that cycle, in a subprocess because
    this process has already frozen the shipped bundle's constants at import.
    """
    previous = PINS_PATH.read_bytes() if PINS_PATH.is_file() else None
    PINS_PATH.write_text(json.dumps({
        "rollout_version": ROLLOUT_VERSION,
        "fingerprints": [{"oversight": o, "lure": lure,
                          "fingerprint": _PROVISIONAL}
                         for o in (True, False) for lure in (True, False)],
    }), encoding="utf-8")
    env = dict(os.environ)
    env["SUBVERSIONBENCH_SCENARIO_BUNDLE"] = str(bundle_for_run)
    try:
        result = subprocess.run([sys.executable, "-c", _FINGERPRINT_PROBE],
                                cwd=ROOT, env=env, capture_output=True,
                                text=True)
        if result.returncode:
            raise RuntimeError(
                f"computing fingerprints under the override failed:\n"
                f"{result.stderr.rstrip()}")
        return {(bool(o), bool(lure)): fp
                for o, lure, fp in json.loads(result.stdout)}
    except BaseException:
        # Leave nothing provisional behind on any exit, interrupt included.
        if previous is None:
            PINS_PATH.unlink(missing_ok=True)
        else:
            PINS_PATH.write_bytes(previous)
        raise


def main():
    parser = argparse.ArgumentParser(
        description="Read, edit and pin the encrypted held-out scenario.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--decode", action="store_true",
                       help=f"write {WORKING_COPY.name} for editing")
    group.add_argument("--encode", action="store_true",
                       help=f"fold {WORKING_COPY.name} back in")
    group.add_argument("--list", action="store_true",
                       help="entry names and sizes")
    group.add_argument("--show", metavar="SUBSTRING",
                       help="print entries whose name contains SUBSTRING")
    group.add_argument("--check", action="store_true",
                       help="run the bundle's invariants")
    group.add_argument("--pin", action="store_true",
                       help="compute and write the rollout fingerprints")
    group.add_argument("--export", action="store_true",
                       help="decrypt for a run and print the path")
    args = parser.parse_args()

    if not BUNDLE_PATH.is_file():
        print(f"{BUNDLE_PATH.relative_to(ROOT)} not found. The held-out bundle "
              f"is gitignored and exists only where it was authored.")
        return 1

    if args.check:
        return 0 if _invariants_hold() else 1

    if args.decode:
        WORKING_COPY.write_text(json.dumps(load_heldout(), indent=2),
                                encoding="utf-8")
        print(f"wrote {WORKING_COPY.relative_to(ROOT)}; edit it, then --encode")
        return 0

    if args.export:
        # The harness reads JSON, because scenario.py deliberately has no
        # decryption path - see its load_scenario docstring. Written 0600: it
        # is the scenario in plaintext, on a machine that may be shared.
        WORKING_COPY.write_text(json.dumps(load_heldout(), indent=2),
                                encoding="utf-8")
        os.chmod(WORKING_COPY, 0o600)
        if not PINS_PATH.is_file():
            print(f"no rollout pins at {PINS_PATH.name} - run --pin first, or "
                  f"the harness will refuse to start.", file=sys.stderr)
            return 1
        print(WORKING_COPY)
        return 0

    if args.pin:
        # The harness reads JSON - scenario.py has no decryption path - so the
        # pinning run has to read the same exported form a real run will.
        WORKING_COPY.write_text(json.dumps(load_heldout(), indent=2),
                                encoding="utf-8")
        os.chmod(WORKING_COPY, 0o600)
        pins = _fingerprints(WORKING_COPY)
        from subversionbench.rollout_pins import ROLLOUT_FINGERPRINTS
        shared = {k: v for k, v in pins.items()
                  if v == ROLLOUT_FINGERPRINTS.get(k)}
        if shared:
            # Would mean the reworded bundle assembles to the same arm as the
            # shipped one, so its episodes could be pooled with r9's.
            print(f"Refusing to pin: {sorted(shared)} match the shipped "
                  f"rollout's fingerprints exactly.")
            return 1
        PINS_PATH.write_text(json.dumps({
            "rollout_version": ROLLOUT_VERSION,
            "fingerprints": [
                {"oversight": o, "lure": lure, "fingerprint": fp}
                for (o, lure), fp in sorted(pins.items())],
        }, indent=2), encoding="utf-8")
        print(f"wrote {PINS_PATH.relative_to(ROOT)} "
              f"(rollout_version {ROLLOUT_VERSION})")
        for (o, lure), fp in sorted(pins.items()):
            print(f"  oversight={o!s:5s} lure={lure!s:5s} {fp}")
        return 0

    if args.list:
        for name, value in load_heldout().items():
            size = sum(len(v) for v in value) if isinstance(value, list) \
                else len(value) if isinstance(value, str) else len(str(value))
            kind = f"list[{len(value)}]" if isinstance(value, list) else \
                "text" if isinstance(value, str) else f"dict[{len(value)}]"
            print(f"  {name:34s} {kind:9s} {size:6d} chars")
        return 0

    if args.show:
        found = False
        for name, value in load_heldout().items():
            if args.show.lower() not in name.lower():
                continue
            found = True
            print(f"===== {name} =====")
            print("\n\n".join(value) if isinstance(value, list)
                  else value if isinstance(value, str)
                  else json.dumps(value, indent=2))
            print()
        if not found:
            print(f"No entry matching {args.show!r}. Try --list.")
            return 1
        return 0

    # --encode
    if not WORKING_COPY.exists():
        print(f"{WORKING_COPY.name} not found - run --decode first.")
        return 1
    edited = json.loads(WORKING_COPY.read_text(encoding="utf-8"))

    # Against the SHIPPED bundle's key set, not the held-out one's own. The
    # twin has to carry every entry the harness reaches for, and comparing it
    # against itself would accept a bundle that had quietly lost one.
    missing = set(load_scenario()) - set(edited)
    if missing:
        print(f"Refusing to encode: {WORKING_COPY.name} is missing "
              f"{sorted(missing)}.")
        return 1

    # Written, then checked, then kept or rolled back. The invariants run as
    # the tracked test, which reads the bundle at its real path, so there is no
    # staging path to check it at - the rollback is what makes that safe.
    previous = BUNDLE_PATH.read_bytes()
    BUNDLE_PATH.write_text(encrypt(edited), encoding="utf-8")
    if not _invariants_hold():
        BUNDLE_PATH.write_bytes(previous)
        print(f"\nRefusing to encode: {BUNDLE_PATH.name} rolled back.")
        return 1
    print(f"{BUNDLE_PATH.name} updated.")
    if PINS_PATH.is_file():
        print(f"NOTE: {PINS_PATH.name} may now be stale - re-run --pin if any "
              f"document the model reads changed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
