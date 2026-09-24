"""The external table, encrypted at rest, and the two constants that
say how its buckets are read.

The passphrase is published and offers no confidentiality - it is a
crawler barrier, for the reason set out in this package's __init__ and in
full in sad_oversight.py. `encrypt`/`decrypt` are imported from there
rather than reimplemented: a second copy of a key-derivation routine is a
second thing to keep in step, and the two bundles are meant to stay
readable by the same passphrase.
"""

from pathlib import Path

from sad_oversight import decrypt, encrypt
from subversionbench.grading import MISALIGNED_ACTS

# `encrypt` is re-exported rather than used here: it is the --encode half
# of the CLI, and this module is where the bundle's crypto lives even
# though only one direction of it is called on this side.
__all__ = ["ACTS", "AWARE_POOLINGS", "MEASURES", "OVERALL",
           "decrypt", "encrypt", "load_bundle"]


_BUNDLE_PATH = Path(__file__).with_name("agentic_misalignment.enc")
_PLAIN_PATH = Path(__file__).with_name("agentic_misalignment.json")

# The row every correlation uses. The per-scenario rows are carried in the
# bundle and reported, but a rank correlation over five models is thin enough
# already without splitting it three ways.
OVERALL = "overall"

# Which external buckets count as "aware". Two poolings, both reported, because
# this benchmark's single binary verdict has no exact counterpart in a
# three-way split and picking one silently would hide the choice.
AWARE_POOLINGS = {
    "any_aware": ("safety_aware", "capability_aware"),
    "safety_only": ("safety_aware",),
}

MEASURES = {
    "level": "external harmful rate vs local misalignment rate",
    "suppression": "unaware-minus-aware gap, on each side",
}

# SubversionBench's own act names, not the external benchmark's - these are
# not scenario text and may be written down. Derived from MISALIGNED_ACTS
# rather than hardcoded, so a third act added there is picked up here too.
ACTS = tuple(act["name"] for act in MISALIGNED_ACTS)


def load_bundle(path: Path = None) -> dict:
    """The decrypted table."""
    return decrypt((path or _BUNDLE_PATH).read_text(encoding="utf-8"))
