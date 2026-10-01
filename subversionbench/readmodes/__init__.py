"""
The read-only modes: what can be learned from episodes already collected.

Five modes, and the thing worth knowing about them is how little they share. They
all open with the same question - which saved run files am I working on - and that
one answer lives in selection.py. Past it they diverge, and deliberately so:

    grade.py         re-runs the awareness grader          spends
    reclassify.py    re-labels saved interrogation answers  spends
    resummarise.py   re-derives everything derivable        free
    reinterrogate.py asks a differently-worded question     spends
    complete_pending.py asks what --no-grader left unasked  spends

Each writes back under a policy that protects something specific, and those
policies are not interchangeable - see each module's docstring. A shared writer
would need a policy flag per mode, which is harder to read than five explicit
versions and easier to get wrong in the direction that loses data.
"""

from .complete_pending import complete_pending_interrogations
from .grade import grade_existing_runs
from .kind_self import SELF_KIND_FIELD, self_grade_kinds
from .reclassify import reclassify_existing_runs
from .reinterrogate import reinterrogate_existing_runs
from .resummarise import REDERIVED_ANALYSIS_FIELDS, resummarise_existing_runs
from .selection import fan_out_read_mode, find_run_files_or_explain

__all__ = ["REDERIVED_ANALYSIS_FIELDS", "SELF_KIND_FIELD",
           "complete_pending_interrogations", "fan_out_read_mode",
           "find_run_files_or_explain", "grade_existing_runs",
           "reclassify_existing_runs", "reinterrogate_existing_runs",
           "resummarise_existing_runs", "self_grade_kinds"]
