"""The command line: which mode was asked for, and what it writes.
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

from subversionbench.config import ROLLOUT_VERSION
from subversionbench.redaction import redact_paths

# Reached through the MODULES rather than bound by name, so the paths this
# reads and the functions it calls resolve at call time. Bound by name,
# --encode read a _PLAIN_PATH captured at import and a test redirecting it
# changed nothing - which is the failure test_project/test_init.py exists for,
# applied to a package's own internals.
from . import bundle, charts, comparison, console


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="python3 -m agentic_misalignment",
        description=("Correlate an external agentic-misalignment benchmark with "
                     "the rates measured here, on the overall level and on the "
                     "awareness-suppression gap the two benchmarks share."))
    parser.add_argument("--output-dir", default=f"./eval_results_{ROLLOUT_VERSION}",
                        help="results directory to read (default: %(default)s)")
    parser.add_argument("--json-out", default=None,
                        help="where to write the JSON report")
    parser.add_argument("--chart-dir", default=None,
                        help="where to write the chart (default: charts/ "
                             "inside --output-dir)")
    parser.add_argument("--no-charts", action="store_true",
                        help="skip the chart; every figure it draws is in the "
                             "printed output and the JSON either way")
    parser.add_argument("--decode", action="store_true",
                        help="write the table to agentic_misalignment.json to "
                             "edit it, then --encode to fold it back")
    parser.add_argument("--encode", action="store_true",
                        help="fold agentic_misalignment.json back into the "
                             "encrypted table")
    args = parser.parse_args()

    if args.decode and args.encode:
        parser.error("--decode and --encode are opposites; pick one")
    if args.decode:
        bundle._PLAIN_PATH.write_text(
            json.dumps(bundle.load_bundle(), indent=1, sort_keys=True) + "\n",
            encoding="utf-8")
        print(f"wrote {bundle._PLAIN_PATH.name} - gitignored, so it cannot be "
              f"committed by accident")
        return 0
    if args.encode:
        if not bundle._PLAIN_PATH.exists():
            print(f"{bundle._PLAIN_PATH.name} does not exist; run --decode first",
                  file=sys.stderr)
            return 2
        bundle._BUNDLE_PATH.write_text(
            bundle.encrypt(json.loads(bundle._PLAIN_PATH.read_text(encoding="utf-8"))),
            encoding="utf-8")
        print(f"folded {bundle._PLAIN_PATH.name} back into {bundle._BUNDLE_PATH.name}")
        return 0

    if not Path(args.output_dir).is_dir():
        print(f"no such results directory: {args.output_dir}", file=sys.stderr)
        return 2
    table = bundle.load_bundle()
    report = comparison.build_report(args.output_dir, table)
    if not report["n_pairs"]:
        print("no model in this corpus matches a row in the external table.",
              file=sys.stderr)
        return 1
    console.print_report(report)

    if not args.no_charts:
        chart_dir = args.chart_dir or os.path.join(args.output_dir, "charts")
        os.makedirs(chart_dir, exist_ok=True)
        chart = charts.write_chart(report, os.path.join(
            chart_dir, "agentic_misalignment_correlation.png"))
        if chart:
            print(f"\nChart written to {redact_paths(chart)}")
            report["chart"] = redact_paths(chart)
        scenario_charts = charts.write_scenario_charts(table, chart_dir)
        if scenario_charts:
            redacted = [redact_paths(p) for p in scenario_charts]
            print(f"\n{len(redacted)} scenario chart(s) written:")
            for p in redacted:
                print(f"  {p}")
            report["scenario_charts"] = redacted
        scenario_act_chart = charts.write_scenario_act_chart(report, os.path.join(
            chart_dir, "agentic_misalignment_scenario_act_correlation.png"))
        if scenario_act_chart:
            print(f"\nScenario/act chart written to "
                  f"{redact_paths(scenario_act_chart)}")
            report["scenario_act_chart"] = redact_paths(scenario_act_chart)

    path = args.json_out or str(Path(args.output_dir) / (
        f"agentic_misalignment_correlation_"
        f"{time.strftime('%Y%m%dT%H%M%S')}.json"))
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, default=str)
    print(f"\nJSON written to {path}")
    return 0
