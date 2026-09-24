"""
`python3 -m agentic_misalignment`.

Its own file rather than a guard in cli.py, for the reason report/ and
trends/ have the same file: `__init__.py` re-exports `main`, so importing
the package imports `agentic_misalignment.cli`, and running that module
with `-m agentic_misalignment.cli` would execute it a SECOND time under
the name `__main__` - which Python reports as a RuntimeWarning above every
report. A report that opens with a warning invites the reader to distrust
the rest of it.
"""

import sys

from .cli import main

sys.exit(main())
