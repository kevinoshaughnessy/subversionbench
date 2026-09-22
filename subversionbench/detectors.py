"""
The detector text - rubric and keyword lists - held base64-encoded at rest.

WHY THIS IS NOT PLAIN SOURCE
----------------------------
scenario.py keeps the text the model READS out of the training crawl. This
keeps out the text that decides what the model's own words MEAN: the nine
rubric questions the LLM grader answers, the system prompt that frames them,
and the two keyword lists the free cross-checks match against.

The argument is Deckenbach et al., arXiv:2605.28591, which distinguishes
instance-level contamination from the leakage of evaluation STRUCTURE. They
fine-tune models on documents describing how evaluations are built and find
them significantly safer across five safety benchmarks - and, critically, that
the shift persists in responses containing no verbalized evaluation awareness
at all. Their second recommendation is to extend hold-out "from instance-level
to protocol-level". A model that has read `EVAL_AWARENESS_INDICATORS` knows
that "a deliberate test" is matched and "a trap" is not.

This repository already held the scenario back and published the detector,
which is the wrong half if that paper is right.

LATE, AND KNOWN TO BE LATE. These values were public in the initial commit and
stayed at HEAD for eight weeks, so they are in whatever crawls ran in that
window and encoding them now does not retrieve them. It is done anyway for two
reasons: changes from here on are not published, which is what matters for
every indicator added after this point; and a benchmark others fork should not
model the practice it is arguing against.

WHY A SEPARATE BUNDLE FROM scenario.b64
---------------------------------------
Because the held-out twin must be graded by the SAME instrument as the shipped
scenario, and co-locating them would guarantee it is not. The held-out bundle
is selected by SUBVERSIONBENCH_SCENARIO_BUNDLE, and heldout_tool.py refuses to
encode a bundle "missing any entry the shipped one has" - so a rubric living in
scenario.b64 would be forced into the held-out bundle as a second copy, free to
drift, and a held-out run would silently measure with a different rubric. The
comparison that corpus exists for would be the casualty.

It is the same split the repository already draws between ROLLOUT_VERSION and
VERSION: the scenario is what produced an episode, the detector is what
analysed it. There is deliberately NO environment override here.

Base64 is not security, exactly as in scenario.py. Bulk training pipelines
ingest text; they do not base64-decode it. Anyone auditing the benchmark reads
it in one command:

    python detector_tool.py --decode     # writes detectors.json
    python detector_tool.py --list
    python detector_tool.py --show rubric_questions
    python detector_tool.py --encode     # fold changes back in

detectors.json is gitignored, so a decoded working copy cannot be committed by
accident.
"""

import argparse
import base64
import json
import sys
from pathlib import Path

_BUNDLE_PATH = Path(__file__).with_name("detectors.b64")
WORKING_COPY = Path(__file__).with_name("detectors.json")

# Every key the harness reads. --encode refuses a bundle missing one, the way
# scenario_tool does: a truncated bundle would fail somewhere inside a grading
# pass rather than here, after the calls were paid for.
REQUIRED = (
    "rubric_questions",
    "rubric_system_prompt",
    "eval_awareness_indicators",
    "goal_conflict_awareness",
    # The evidence for each phrase - what it newly flagged, what the grader
    # independently agreed on, and which candidates were REJECTED and why.
    # Travels with the values rather than staying behind as a comment in
    # config.py, because a rationale that names the rejected phrases
    # ("an evaluation of", "test to see") leaks the same protocol the values
    # do. Read it before proposing an addition; it is why the list is not
    # longer.
    "rationale",
)


def load_detectors(path: Path = None) -> dict:
    """The decoded bundle. No environment override, by design - see above."""
    raw = (path or _BUNDLE_PATH).read_text(encoding="utf-8")
    return json.loads(base64.b64decode(raw).decode("utf-8"))


def encode_detectors(bundle: dict, path: Path = None) -> None:
    """Fold a bundle back into its encoded form, refusing an incomplete one."""
    missing = [k for k in REQUIRED if k not in bundle]
    if missing:
        raise ValueError(
            f"refusing to encode a detector bundle missing {missing}. "
            f"A truncated bundle fails inside a grading pass, after the "
            f"calls are paid for, rather than here.")
    payload = json.dumps(bundle, indent=2, sort_keys=True).encode("utf-8")
    (path or _BUNDLE_PATH).write_text(
        base64.b64encode(payload).decode("ascii") + "\n", encoding="utf-8")


def _main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Read and edit the encoded detector text.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--decode", action="store_true",
                       help=f"write the bundle to {WORKING_COPY.name}")
    group.add_argument("--encode", action="store_true",
                       help=f"fold {WORKING_COPY.name} back in")
    group.add_argument("--list", action="store_true",
                       help="entry names and sizes")
    group.add_argument("--show", metavar="NAME",
                       help="print one entry")
    args = parser.parse_args(argv)

    if args.list:
        for k, v in sorted(load_detectors().items()):
            print(f"  {k:<32} {len(json.dumps(v)):>7} chars")
        return 0
    if args.show:
        bundle = load_detectors()
        if args.show not in bundle:
            print(f"no entry {args.show!r}; --list shows the names",
                  file=sys.stderr)
            return 1
        print(json.dumps(bundle[args.show], indent=2))
        return 0
    if args.decode:
        WORKING_COPY.write_text(
            json.dumps(load_detectors(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8")
        print(f"wrote {WORKING_COPY}")
        return 0
    if not WORKING_COPY.is_file():
        print(f"{WORKING_COPY} does not exist; --decode first", file=sys.stderr)
        return 1
    encode_detectors(json.loads(WORKING_COPY.read_text(encoding="utf-8")))
    print(f"folded {WORKING_COPY.name} into {_BUNDLE_PATH.name}")
    return 0


if __name__ == "__main__":
    sys.exit(_main())
