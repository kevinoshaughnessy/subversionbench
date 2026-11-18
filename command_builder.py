#!/usr/bin/env python3
"""
Open the run-command builder in a browser: a form for the model, provider,
reasoning level, grader, scenario and the other collection settings, which
assembles the run_all_arms.sh or run_eval command to copy. It builds commands
and runs none, and reads no credential.

    python3 command_builder.py
    python3 command_builder.py --port 9000 --no-browser
"""

import argparse

from model_releases import RELEASE_DATES
from subversionbench.command_builder_server import serve


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--port", type=int, default=8765,
                        help="loopback port; 0 picks a free one (default: %(default)s)")
    parser.add_argument("--no-browser", action="store_true",
                        help="print the address and do not open it")
    args = parser.parse_args(argv)
    serve(RELEASE_DATES, args.port, not args.no_browser)


if __name__ == "__main__":
    main()
