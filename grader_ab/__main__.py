"""
`python3 -m grader_ab`.

Its own file rather than a guard in cli.py, for the reason report/,
trends/ and agentic_misalignment/ have the same file: `__init__.py`
re-exports `main`, so importing the package imports `grader_ab.cli`, and
running that module with `-m grader_ab.cli` would execute it a SECOND
time under the name `__main__` - which Python reports as a RuntimeWarning
above every report.
"""

import sys

from .cli import main

sys.exit(main())
