#!/usr/bin/env python3
"""
Is misalignment falling as a model family advances?

Groups every model in a results directory into families by parsing its ID, orders
each family by version, and asks whether the rate moves monotonically along that
order. Answers one question per family and one across all of them.

WHY THIS IS NOT A LIST OF FAMILIES
----------------------------------
The families are DERIVED, never enumerated. A hand-written list is wrong the day
after the next model is collected, and it is wrong silently - a new ID simply
fails to appear in any family and the report is quietly narrower than the
corpus. So `gemini-3.8-flash` joins the gemini-flash family with no edit here,
and any model whose family gains a second member starts being reported.

The cost of deriving is that the parse has to be right about things a list would
never have to state, and those are the two constants below: which trailing words
are release-stage qualifiers rather than family identity, and how a version
string is ordered. Both are wrong for some future ID, so both are reported in
the output rather than applied silently.

WHAT "CONSISTENTLY FALLING" MEANS HERE
--------------------------------------
Two different claims, reported separately because a family can satisfy one and
not the other:

  the TREND falls   - Cochran-Armitage across the ordered versions, one degree
                      of freedom, position as the score. Four steps down and one
                      large step up can still fit a falling trend.
  every STEP falls  - the monotone claim, counted from consecutive differences.
                      This is what "consistently" says, and it is the stricter
                      reading.

Neither is a causal claim about model development. Version order is not a
randomised assignment, families differ in how many versions were collected, and
nothing here knows what changed between two releases.

WHY THE METRIC IS A FLAG
------------------------
Misalignment is derived from the ACT keys, so it does not depend on any LLM
verdict and is safe to read off a batch whose grading failed. Scheming is the
act plus concealment, and concealment comes from a sampled classifier - so
`--metric scheming` is only as good as the classifier calls that batch made.
The data-quality block says when that matters rather than leaving it implied.

TWO X AXES, TWO DIFFERENT QUESTIONS
-----------------------------------
Version POSITION spaces every release equally, which is the axis the trend tests
run on and the one the question is about. It also hides the calendar: four grok
releases over four months and four gemini releases over eight draw the same
shape on it. So each chart is drawn a second time against the release dates in
model_releases.py, with no connecting lines - a segment between two releases
would invite reading a slope off months in which nothing was measured. Each
family gets one straight dotted least-squares fit there instead, which says how
fast in time and carries no p-value: the test stays on version position, and
refitting on the calendar with an interval would be a second test of one
hypothesis on one dataset.

A release date cannot be derived from a model ID, so it has to be recorded, and
a model that has not been recorded is reported as an error and then dropped from
the release charts alone. Nothing else here depends on a date: every rate,
interval, trend and p-value is computed from version order.

Reads the same `summary_*.json` fields as run_report.py, through the same
loader, so a family's rate here and its per-model rate there cannot disagree.

WHERE THE REST OF THE CODE IS
-----------------------------
This file is the command line and nothing else: the arguments, and the loop that
runs one report per metric. Everything it calls lives in the sibling modules,
and `trends/__init__.py` says which module holds what and why the package is
split where it is.
"""
import argparse
import json
import os
import time

from subversionbench import charting
from report import load_episodes, report_graders
from subversionbench.config import ROLLOUT_VERSION
from subversionbench.redaction import redact_paths

# From the siblings directly rather than through the package, which would be a
# cycle: `trends/__init__.py` imports this module in order to re-export main().
from .charts import write_charts
from .console import _print_overall, _print_report
from .metrics import METRIC_ALL, METRICS
from .model_ids import VERSION_STYLES
from .overall import build_overall_report
from .overall_charts import write_overall_charts
from .report import build_report


def main() -> int:
    parser = argparse.ArgumentParser(
        # Named, because argparse otherwise takes it from argv[0] - which under
        # `-m` is `__main__.py`, a name that appears nowhere a reader could act
        # on. This is the command the README and docs/trends.md give.
        prog="python3 -m trends",
        description="Whether a rate falls as a model family advances. "
                    "Families and their version order are derived from the "
                    "model IDs, so a newly collected version needs no change "
                    "here.")
    parser.add_argument("--output-dir",
                        default=f"./eval_results_{ROLLOUT_VERSION}",
                        help="results directory to analyse "
                             "(default: %(default)s)")
    parser.add_argument("--metric", default=None,
                        choices=sorted(METRICS) + [METRIC_ALL],
                        help="which rate to trend, or 'all' for one report per "
                             "metric (default: misaligned)")
    parser.add_argument("--overall", action="store_true",
                        help="trend the overall misalignment rate instead: "
                             "each act from the corpus built for it - "
                             "oversight and sandbox from --output-dir, "
                             "goal-guarding from --goalguard-dir - averaged "
                             "with equal weight. Charts go to charts/overall/")
    parser.add_argument("--goalguard-dir",
                        default="./eval_results_goalguard_r1",
                        help="the goal-guarding corpus --overall reads "
                             "(default: %(default)s)")
    parser.add_argument("--version-style", default="decimal",
                        choices=VERSION_STYLES,
                        help="how to order a version: 'decimal' reads 4.20 as "
                             "4.2, so before 4.3 - which is what the vendors "
                             "mean; 'component' reads it as 4 major 20 minor, "
                             "so after 4.6, the way a package manager reads a "
                             "semantic version (default: %(default)s)")
    parser.add_argument("--json-out", default=None,
                        help="where to write the JSON report (default: "
                             "family_trends_<metric>[_<grader>]_<timestamp>"
                             ".json inside --output-dir; no grader for a "
                             "metric read off the act keys)")
    parser.add_argument("--chart-dir", default=None,
                        help="where to write the PNG charts (default: "
                             "charts/<rollout>/ beside --output-dir, not "
                             "inside it), in a subdirectory per grader found "
                             "in the run files for a metric a grader's verdict "
                             "reaches. One per family plus one combined, "
                             "against version order and again against release "
                             "date; needs the 'charts' extra")
    parser.add_argument("--no-charts", action="store_true",
                        help="skip the charts. Every figure they plot is in the "
                             "table and the JSON either way")
    args = parser.parse_args()
    if args.overall and args.metric:
        parser.error("--overall is its own rate; drop --metric")

    for directory in ([args.output_dir, args.goalguard_dir] if args.overall
                      else [args.output_dir]):
        if not os.path.isdir(directory):
            print(f"No such directory: {redact_paths(directory)}")
            return 1
    if args.overall:
        return _report_overall(args)

    metric = args.metric or "misaligned"
    metrics = sorted(METRICS) if metric == METRIC_ALL else [metric]
    # One report per grader the run files hold for a metric a grader's verdict
    # reaches, as the research report does. A metric read off the act keys is
    # every grader's alike, so it gets ONE report over every episode - see
    # _GRADER_FREE. A directory with no run files, or none graded, gets the
    # one report it always did.
    graders = report_graders(args.output_dir)
    free = [m for m in metrics if not METRICS[m]["llm_dependent"]]
    judged = [m for m in metrics if METRICS[m]["llm_dependent"]]
    n_reports = len(free) + len(judged) * len(graders)
    if args.json_out and n_reports > 1:
        parser.error("--json-out names one file, and this run writes "
                     f"{n_reports} reports: one per grader for each metric "
                     "a grader's verdict reaches, and one for each that it "
                     "does not. Drop --json-out to get "
                     "family_trends_<metric>[_<grader>]_<timestamp>.json "
                     "for each, or name a single --metric.")

    # One stamp for the whole invocation rather than one per metric, so the
    # reports from a single run share a filename suffix and sort together
    # instead of being separated by however long the run took.
    stamp = time.strftime("%Y%m%dT%H%M%S")
    failed = 0
    for grader, its_metrics in [(_GRADER_FREE, free)] + [
            (g, judged) for g in graders]:
        if not its_metrics:
            continue
        # Loaded once per grader rather than once per metric: every metric
        # needs to know which episodes this grader has not read yet.
        episodes = (load_episodes(args.output_dir) if grader is _GRADER_FREE
                    else load_episodes(args.output_dir, grader=grader))
        for metric in its_metrics:
            if n_reports > 1:
                print(f"\n\n{'#' * 78}\n# grader: {grader or 'none'}\n"
                      f"# metric: {metric}\n{'#' * 78}")
            failed += _report_one_metric(args, metric, grader, episodes, stamp)
    return 1 if failed else 0


def _report_overall(args) -> int:
    """The overall rate end to end: table, charts and JSON, as
    _report_one_metric does for one corpus's rate."""
    report = build_overall_report(args.output_dir, args.goalguard_dir,
                                  args.version_style)
    if not report["overall_by_model"]:
        print("No model has all three acts measured across "
              f"{redact_paths(args.output_dir)} and "
              f"{redact_paths(args.goalguard_dir)}")
        return 1
    _print_report(report)
    _print_overall(report)
    if not args.no_charts:
        # Beside both corpora's own chart directories, named for neither.
        chart_dir = args.chart_dir or os.path.join(
            os.path.dirname(charting.default_chart_dir(args.output_dir)),
            "overall")
        written = (write_overall_charts(report, chart_dir)
                   + write_charts(report, chart_dir))
        if written:
            print(f"\n{len(written)} chart(s) written to "
                  f"{redact_paths(chart_dir)}:")
            for path in written:
                print(f"  {os.path.basename(path)}")
            report["charts"] = [redact_paths(p) for p in written]
    out = args.json_out or os.path.join(
        args.output_dir,
        f"family_trends_overall_{time.strftime('%Y%m%dT%H%M%S')}.json")
    with open(out, "w") as f:
        json.dump(report, f, indent=2)
    print(f"\nJSON written to {redact_paths(out)}")
    return 0


# The `grader` a metric no grader's verdict reaches is reported under: one
# report over every episode, its charts in the chart directory itself and its
# JSON named without a grader. Drawn once per grader instead, each copy left
# out the episodes that grader had not read, so one grader's misalignment
# trend silently covered fewer episodes than the corpus holds.
_GRADER_FREE = None


def _report_one_metric(args, metric: str, grader: str, episodes: list,
                       stamp: str) -> int:
    """
    One metric for one grader, end to end. Returns 0 on success, 1 on failure.

    Split out of main so `--metric all` runs the same path for every metric
    and every grader rather than a second implementation of it.
    """
    report = build_report(args.output_dir, metric, args.version_style,
                          grader, episodes)
    if not report["families"]:
        # A metric read from episodes finds nothing in a directory that holds
        # only summaries, and the goal-guarding rate finds nothing in a corpus
        # with no goal-guarding arm. That is a gap in what this corpus can
        # answer, not a failure of the run - and under `--metric all` it must
        # not take the metrics that DID compute down with it.
        if METRICS[metric].get("from_episodes"):
            print(f"Skipping --metric {metric}: it is derived per episode, and "
                  f"{redact_paths(args.output_dir)} holds no episode it "
                  f"applies to - no run files, or none that could take it.")
            return 0
        print(f"No family with two or more members in "
              f"{redact_paths(args.output_dir)}")
        return 1
    _print_report(report)

    if not args.no_charts:
        chart_dir = args.chart_dir or charting.default_chart_dir(
            args.output_dir)
        if grader is not _GRADER_FREE:
            chart_dir = charting.grader_chart_dir(chart_dir, grader)
        written = write_charts(report, chart_dir)
        if written:
            print(f"\n{len(written)} chart(s) written to "
                  f"{redact_paths(chart_dir)}:")
            for path in written:
                print(f"  {os.path.basename(path)}")
            report["charts"] = [redact_paths(p) for p in written]

    out = args.json_out or os.path.join(
        args.output_dir,
        # The metric is in the name for the same reason it is in the chart
        # names: two metrics of one corpus are two different reports, and a
        # directory of timestamped files gives no way to tell which is which
        # without opening them.
        f"family_trends_{metric}"
        + ("" if grader is _GRADER_FREE else f"_{grader.replace('/', '_')}")
        + f"_{stamp}.json")
    with open(out, "w") as f:
        json.dump(report, f, indent=2)
    print(f"\nJSON written to {redact_paths(out)}")
    return 0

# No `if __name__ == "__main__"` here. __main__.py is the entry point, and it
# says why: the package re-exports main(), so running THIS module with -m would
# execute it a second time and warn about it above every report.
