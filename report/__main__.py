"""
`python3 -m report`.

Its own file rather than a guard in run_report.py, for the reason trends has the
same file: `report/__init__.py` re-exports `main`, so importing the package
imports `report.run_report`, and running that module with `-m
report.run_report` would execute it a SECOND time under the name `__main__` -
which Python reports as a RuntimeWarning above every report. A report that opens
with a warning invites the reader to distrust the rest of it.
"""

import sys

from .run_report import main

sys.exit(main())
