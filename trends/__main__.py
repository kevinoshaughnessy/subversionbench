"""
`python3 -m trends`.

WHY THIS FILE EXISTS RATHER THAN A GUARD IN family_trends.py
------------------------------------------------------------
`trends/__init__.py` re-exports `main`, so importing the package imports
`trends.family_trends`. Running that same module with `-m trends.family_trends`
then executes it a SECOND time, under the name `__main__`, and Python says so on
every invocation:

    RuntimeWarning: 'trends.family_trends' found in sys.modules after import of
    package 'trends', but prior to execution of 'trends.family_trends'

Two copies of a module means two copies of its module-level state, which here is
only argparse's, so nothing broke - but it printed a warning above every report,
and a report that opens with a warning invites the reader to distrust the rest
of it.

So the package gets its own entry point and family_trends.py carries no
`__main__` guard. The command is `python3 -m trends`.
"""

import sys

from .family_trends import main

sys.exit(main())
