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
"""

import argparse
import json
import sys
from pathlib import Path

from subversionbench.scenario import load_scenario, encode_scenario

WORKING_COPY = Path(__file__).with_name("scenario.json")


def main():
    parser = argparse.ArgumentParser(
        description="Read and edit the encoded scenario text.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--decode", action="store_true",
                       help=f"write the scenario to {WORKING_COPY.name}")
    group.add_argument("--encode", action="store_true",
                       help=f"fold {WORKING_COPY.name} back into scenario.b64")
    group.add_argument("--list", action="store_true",
                       help="entry names and sizes")
    group.add_argument("--show", metavar="SUBSTRING",
                       help="print entries whose name contains SUBSTRING")
    args = parser.parse_args()

    if args.decode:
        WORKING_COPY.write_text(json.dumps(load_scenario(), indent=2))
        print(f"wrote {WORKING_COPY.name}; edit it, then --encode")
        return 0

    if args.list:
        for name, value in load_scenario().items():
            size = sum(len(v) for v in value) if isinstance(value, list) \
                else len(value)
            kind = f"list[{len(value)}]" if isinstance(value, list) else "text"
            print(f"  {name:34s} {kind:9s} {size:6d} chars")
        return 0

    if args.show:
        found = False
        for name, value in load_scenario().items():
            if args.show.lower() not in name.lower():
                continue
            found = True
            print(f"===== {name} =====")
            print("\n\n".join(value) if isinstance(value, list) else value)
            print()
        if not found:
            print(f"No entry matching {args.show!r}. Try --list.")
            return 1
        return 0

    # --encode
    if not WORKING_COPY.exists():
        print(f"{WORKING_COPY.name} not found - run --decode first.")
        return 1
    edited = json.loads(WORKING_COPY.read_text())
    missing = set(load_scenario()) - set(edited)
    if missing:
        print(f"Refusing to encode: {WORKING_COPY.name} is missing "
              f"{sorted(missing)}.")
        return 1
    encode_scenario(edited)
    print("scenario.b64 updated. Run the tests before committing.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
