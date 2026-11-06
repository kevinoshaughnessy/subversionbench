"""
The monitor's instructions, held base64-encoded, and the pins they are run under.

Encoded for the reason subversionbench/detectors.py gives for the rubric: how a
monitor is told to look is the protocol a model trained on it would learn to
pass. Base64 is not security; bulk training pipelines ingest text and do not
decode it.

NO DECODED WORKING COPY. detectors.py writes one, gitignored; this does not,
because a gitignored plaintext copy is still plaintext on disk beside the repo.
`--show` prints an entry, `--set` replaces one from stdin, and the text is only
ever decoded in memory.

THE PINS. Every result row carries the fingerprint of the bundle, the render
version and the probe rendering for its view and cut. monitor.pins.json holds
the fingerprints this checkout produces, and run refuses a bundle or renderer
that no longer matches them, so a changed prompt cannot be pooled with results
collected under the old one. `--pin` rewrites the sidecar, which is the
deliberate decision to start a new set.
"""

import argparse
import base64
import hashlib
import json
import sys
from pathlib import Path

from .render import CUTS, RENDER_VERSION, VIEWS, probe_digest

_BUNDLE_PATH = Path(__file__).with_name("monitor.b64")
_PINS_PATH = Path(__file__).with_name("monitor.pins.json")

REQUIRED = (
    # How the monitor is framed, and what it is asked to return.
    "system_prompt",
    # The question put after the transcript, from the harness.
    "question",
)


def load_bundle(path: Path = None) -> dict:
    raw = (path or _BUNDLE_PATH).read_text(encoding="utf-8")
    return json.loads(base64.b64decode(raw).decode("utf-8"))


def encode_bundle(bundle: dict, path: Path = None) -> None:
    """Write the bundle encoded, refusing one missing a required entry."""
    missing = [k for k in REQUIRED if not bundle.get(k)]
    if missing:
        raise ValueError(f"refusing to encode a monitor bundle missing {missing}")
    payload = json.dumps(bundle, indent=2, sort_keys=True).encode("utf-8")
    (path or _BUNDLE_PATH).write_text(
        base64.b64encode(payload).decode("ascii") + "\n", encoding="utf-8")


def fingerprint(bundle: dict, view: str, cut: str) -> str:
    """What a result in `view` at `cut` was produced under."""
    body = json.dumps({"bundle": bundle, "render": RENDER_VERSION,
                       "probe": probe_digest(view, cut), "view": view,
                       "cut": cut}, sort_keys=True)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def fingerprints(bundle: dict) -> dict:
    return {f"{view}/{cut}": fingerprint(bundle, view, cut)
            for view in VIEWS for cut in CUTS}


def load_pins(path: Path = None) -> dict:
    return json.loads((path or _PINS_PATH).read_text(encoding="utf-8"))


def check_pins(bundle: dict, pins: dict = None) -> None:
    """Raise unless every fingerprint matches its pin."""
    pinned = (pins or load_pins())["fingerprints"]
    current = fingerprints(bundle)
    moved = sorted(k for k in current if pinned.get(k) != current[k])
    if moved:
        raise ValueError(
            f"the monitor bundle or renderer no longer matches its pins for "
            f"{', '.join(moved)}. Results under a different prompt cannot be "
            f"pooled; re-pin with `python3 -m monitoring.bundle --pin` only as "
            f"a deliberate new set.")


def write_pins(bundle: dict, path: Path = None) -> None:
    (path or _PINS_PATH).write_text(
        json.dumps({"render_version": RENDER_VERSION,
                    "fingerprints": fingerprints(bundle)},
                   indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Read and edit the encoded monitor instructions.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--list", action="store_true", help="entry names and sizes")
    group.add_argument("--show", metavar="NAME", help="print one entry")
    group.add_argument("--set", metavar="NAME",
                       help="replace one entry with the text on stdin")
    group.add_argument("--pin", action="store_true",
                       help="rewrite monitor.pins.json from this checkout")
    opts = parser.parse_args(argv)
    bundle = load_bundle()
    if opts.list:
        for name, value in sorted(bundle.items()):
            print(f"  {name:<20} {len(json.dumps(value)):>7} chars")
        return 0
    if opts.show:
        if opts.show not in bundle:
            print(f"no entry {opts.show!r}; --list shows the names",
                  file=sys.stderr)
            return 1
        print(bundle[opts.show])
        return 0
    if opts.set:
        encode_bundle({**bundle, opts.set: sys.stdin.read().strip()})
        print(f"set {opts.set}; the pins no longer match until --pin")
        return 0
    write_pins(bundle)
    print(f"wrote {_PINS_PATH.name}")
    return 0


if __name__ == "__main__":
    sys.exit(_main())
