"""
The shipped comparison, built once, for the tests that read it.

Not named `test_*`, so neither runner collects it as a suite file: pytest looks
for `test_*.py` and so does run_tests.discover_modules. It still counts as suite
rather than shipping source, because conftest.is_test_file decides that by
position - anything under a `test_*/` directory - so the project guards that
apply to tests apply here too.
"""

import unittest

import agentic_misalignment as am

def _shipped_report():
    """The report over the real corpus, built once for the whole module.

    Every build walks the entire corpus TWICE - `local_rates` and
    `local_act_rates` each call `load_episodes` - which on the r9 corpus is
    over a minute. Four tests each building their own made this module most of
    the suite's total runtime, and they were asserting on reports that could
    not differ from one another.

    READ-ONLY. Any test that mutates a report, or wants one over a different
    corpus or bundle, must build its own - this is shared state and the saving
    is not worth a test that passes because of what another one did to it.
    """
    return am.build_report("eval_results_r9")


def _require_pairs(report):
    """Skip when the corpus is absent, rather than assert on a degenerate report.

    `unittest.SkipTest` rather than `pytest.skip`, which raises a BaseException
    subclass that `run_tests.py` does not honour. Without this a CI machine with
    no corpus ran these assertions against an empty report and reported the
    result as coverage of the populated one.
    """
    if not report["n_pairs"]:
        raise unittest.SkipTest(
            "no local results overlap the external bundle in this checkout")
