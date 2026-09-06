"""
The timing the sandbox tests run under.

Not named `test_*`, so neither runner collects it as a suite file: pytest looks
for `test_*.py` and so does run_tests.discover_modules. It still counts as suite
rather than shipping source, because conftest.is_test_file decides that by
position - anything under a `test_*/` directory - so the project guards that
apply to tests apply here too.

One module rather than a copy in each file that needs it: two files now run at
these values, and a second copy of a tuned constant is a second thing to keep
in step with the measurements its comment records.
"""

from subversionbench.sandbox import SandboxTiming


# The timing every WAITING test runs under.
#
# WHY THIS IS SOUND, AND WHAT STILL PINS THE SHIPPED VALUES. The behaviour these
# tests are about - wait, TimeoutExpired, reap, escalate to SIGKILL - is the
# same code at any value, so waiting out the shipped ten seconds re-observes a
# constant rather than exercising anything the fast values do not. What the
# shipped values need is an assertion that they ARE the shipped values and that
# production reads them, and both are in TestTheShippedTimingIsWhatShips below,
# where they cost nothing.
#
# Chosen against MEASURED host behaviour rather than picked: a trivial command
# through the real wrapper takes about 11ms here and 22ms at worst, and a
# non-trapping group empties about 55ms after SIGTERM. So these are roughly 45x
# and 9x the thing they must outlast, and
# test_the_fast_timing_has_headroom_on_this_host re-measures the first on
# whatever host is running rather than trusting these numbers - a slow CI box
# gets a named failure instead of a flaky timeout.
FAST = SandboxTiming(command_timeout=1.0, escalation_grace=0.5)
