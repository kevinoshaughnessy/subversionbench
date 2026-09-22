#!/usr/bin/env python3
"""
Read and edit the detector text - the rubric and the keyword lists.

Sibling of scenario_tool.py, and it exists for the same reason: the values are
held base64-encoded so that publishing this repository does not put them into
the next training crawl, and this is the intended way to read them.

    python detector_tool.py --list              # entry names and sizes
    python detector_tool.py --show rubric_questions
    python detector_tool.py --show rationale    # why each phrase is in or out
    python detector_tool.py --decode            # write detectors.json
    python detector_tool.py --encode            # fold detectors.json back in

detectors.json is gitignored, so a decoded working copy cannot be committed by
accident.

A ROOT SCRIPT RATHER THAN `python -m subversionbench.detectors`, which works
but warns: config.py imports the module at package import, so running it as
__main__ re-executes a module already in sys.modules and Python says so. A
documented command that prints a RuntimeWarning teaches the reader to ignore
warnings, which is the opposite of what the rest of this repository asks for.
"""

import sys

from subversionbench.detectors import _main

if __name__ == "__main__":
    sys.exit(_main())
